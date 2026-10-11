"""cowriter_service —— 写作教练（DeepTutor Co-Writer 对标，儿童安全版）。

学习者自己写（语文作文 / English writing），助手只对**学习者自己的文字**给出修改建议
（rewrite / expand / shorten / grammar / outline），以 diff 形式返回，由学习者逐块
接受或拒绝。可选附带 Knowledge Hub 的教材引用（SearchKnowledgeBase 同一检索）。

硬规则（不可代写）：
  1. 不替学生从零写作文：识别"帮我写/代写/write it for me"一类请求 → 拒绝并给出
     教练式引导；只贴了作文题目/要求、没有自己的文字 → 拒绝。
  2. 学习者文字太短（< MIN_INPUT_UNITS 个字/词）→ 拒绝（先自己写几句）。
  3. 生成长度按输入封顶（每个动作一个倍率 + 少量余量），超出在句末截断并标 truncated。
LLM：生产 text caller（get_optional_text_caller；mock 视为不可用）。空 content 视为失败。
限额：per-user 每日次数（MNEME_COWRITER_DAILY_LIMIT，默认 30；admin 豁免），
账本 cowriter_requests 只存字数与状态，不存作文原文。

红线：写作建议永不进掌握度/门控——本模块不 import 任何判分/门控/BKT/FSRS 模块，
不写任何学习事件表（tests/test_notebook_cowriter_no_gating.py 守）。
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import os
import re
import uuid
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import CowriterRequest

_log = logging.getLogger(__name__)

ACTIONS: tuple[str, ...] = ("rewrite", "expand", "shorten", "grammar", "outline")

# 输出字数上限 = 输入字数 × 倍率 + 余量（字符数）。expand 也只允许"润色式扩写"，
# 不能把三句话扩成一整篇。
LENGTH_RATIO: dict[str, float] = {
    "rewrite": 1.3,
    "expand": 1.6,
    "shorten": 0.9,
    "grammar": 1.15,
    "outline": 0.8,
}
LENGTH_SLACK_CHARS = 40
MIN_INPUT_UNITS = 15  # 汉字数 + 英文词数
MAX_INPUT_CHARS = 4000
MAX_OUTPUT_CHARS = 4000
MAX_INSTRUCTION_CHARS = 200
_TODAY_START_SQL = (
    "(date_trunc('day', now() AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'Asia/Shanghai')"
)


class CowriterError(Exception):
    def __init__(self, status_code: int, code: str, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


def daily_limit() -> int:
    try:
        return max(0, int(os.environ.get("MNEME_COWRITER_DAILY_LIMIT", "30")))
    except ValueError:
        return 30


def min_output_tokens() -> int:
    # 生产回退链可能落到推理模型（见 book_compile_service.min_output_tokens 的实测），
    # 太小的 max_tokens 会把额度花在思考上、content 为空。
    try:
        return max(256, int(os.environ.get("MNEME_COWRITER_MIN_TOKENS", "4000")))
    except ValueError:
        return 4000


# ── 文本度量 ────────────────────────────────────────────────────────────────

_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


def count_units(s: str) -> int:
    """写作量：汉字数 + 英文词数（标点/空白不计）。"""
    return len(_CJK_RE.findall(s or "")) + len(_WORD_RE.findall(s or ""))


def detect_language(s: str) -> str:
    cjk = len(_CJK_RE.findall(s or ""))
    words = len(_WORD_RE.findall(s or ""))
    return "zh" if cjk >= words else "en"


def output_char_cap(action: str, original: str) -> int:
    n = len(original.strip())
    return min(MAX_OUTPUT_CHARS, int(n * LENGTH_RATIO[action]) + LENGTH_SLACK_CHARS)


# ── 不可代写规则 ─────────────────────────────────────────────────────────────

_GHOSTWRITE_PATTERNS = [
    r"(帮|替|给|为)\s*我\s*(写|作|编|完成|生成)",
    r"代\s*写",
    r"枪\s*手",
    r"(直接|整篇|全文|完整).{0,6}(写|生成|作文|范文)",
    r"(写|生成|来|作)\s*(一|1|两|几)\s*(篇|段|份)",
    r"(写|给)\s*(我\s*)?(一篇|篇|个)\s*(作文|文章|范文|日记|周记|读后感|演讲稿)",
    r"范\s*文",
    r"\bwrite\s+(it|this|that|one|mine)\s+for\s+me\b",
    r"\bwrite\s+(me|us)\b",
    r"\bwrite\s+(my|an|a|the|this)\s+(whole\s+|full\s+|complete\s+|entire\s+)?"
    r"(essay|composition|story|paragraph|report|letter|article|speech|homework)\b",
    r"\b(do|finish|complete)\s+(my|the)\s+(homework|essay|assignment|writing)\b",
    r"\bghost\s*-?\s*write",
    r"\b(generate|produce|create)\s+(an?|the|my)\s+(essay|composition|story)\b",
]
_GHOSTWRITE_RE = re.compile("|".join(_GHOSTWRITE_PATTERNS), re.IGNORECASE)

_PROMPT_MARKERS_RE = re.compile(
    r"(作文题|题目[:：]|要求[:：]|不少于\s*\d+\s*字|\d+\s*字(左右|以上)|字数|以[「“\"《]?.{1,12}[」”\"》]?为题|"
    r"自拟题目|命题作文|话题作文|材料作文|"
    r"\bwrite\s+(an?|the)\s+(essay|composition|story|letter|paragraph)\b|"
    r"\b(at\s+least|no\s+(less|fewer)\s+than|about)\s+\d+\s+words\b|\btopic\s*:|\bprompt\s*:)",
    re.IGNORECASE,
)

COACH_MESSAGE_ZH = (
    "我不能替你写作文，但可以陪你写：先用自己的话写下开头两三句（你想写什么、为什么），"
    "然后选「改写 / 扩写 / 缩写 / 语法 / 提纲」，我会在你的文字上给修改建议。"
)
COACH_MESSAGE_EN = (
    "I can't write the essay for you, but I can coach you: write your own first few "
    "sentences (what you want to say and why), then pick rewrite / expand / shorten / "
    "grammar / outline and I'll suggest edits to your own text."
)


def check_request(action: str, user_text: str, instruction: Optional[str]) -> Optional[CowriterError]:
    """在调 LLM 之前判定是否拒绝；返回 None 表示放行。纯函数，便于单测。"""
    if action not in ACTIONS:
        return CowriterError(422, "bad_action", f"不支持的操作：{action}")
    body = (user_text or "").strip()
    instr = (instruction or "").strip()
    lang = detect_language(body or instr)
    coach = COACH_MESSAGE_ZH if lang == "zh" else COACH_MESSAGE_EN
    if len(body) > MAX_INPUT_CHARS:
        return CowriterError(422, "too_long", f"一次最多处理 {MAX_INPUT_CHARS} 个字符，请分段修改")
    if len(instr) > MAX_INSTRUCTION_CHARS:
        return CowriterError(422, "too_long", f"补充说明最多 {MAX_INSTRUCTION_CHARS} 个字符")
    units = count_units(body)
    # 1) 明确的代写请求（补充说明里出现即拒；正文较短时出现也拒——长正文里出现
    #    "老师让我们写一篇……"属于学生自己的叙述，不误伤）。
    if instr and _GHOSTWRITE_RE.search(instr):
        return CowriterError(422, "ghostwriting", coach)
    if units < 80 and _GHOSTWRITE_RE.search(body):
        return CowriterError(422, "ghostwriting", coach)
    # 2) 只贴了题目/要求，没有自己的文字
    if _PROMPT_MARKERS_RE.search(body) and units < 60:
        return CowriterError(422, "prompt_only", coach)
    # 3) 太短：先自己写几句
    if units < MIN_INPUT_UNITS:
        return CowriterError(
            422,
            "too_short",
            (
                f"先自己多写几句（至少 {MIN_INPUT_UNITS} 个字），我再帮你改。"
                if lang == "zh"
                else f"Write a bit more of your own first (at least {MIN_INPUT_UNITS} words), then I can help."
            ),
        )
    return None


# ── Prompt ─────────────────────────────────────────────────────────────────

_ACTION_GUIDE_ZH = {
    "rewrite": "在不改变原意、不增加新情节的前提下，把句子改得更通顺、更生动。",
    "expand": "在学生原有内容的基础上适度补充细节描写（感官、动作、心理），不添加新的情节或新的段落主题。",
    "shorten": "删去重复和啰嗦的部分，保留学生原有的意思和关键细节。",
    "grammar": "只改正错别字、病句、标点和语法错误，尽量保留学生原来的用词和句式。",
    "outline": "把学生已经写下的内容整理成分点提纲（只用学生文字里已有的观点和材料，不另编内容）。",
}
_ACTION_GUIDE_EN = {
    "rewrite": "Improve clarity and flow without changing the meaning or adding new ideas.",
    "expand": "Add a little descriptive detail to the student's existing sentences; do not add new plot points, arguments or paragraphs.",
    "shorten": "Remove repetition and wordiness while keeping the student's meaning and key details.",
    "grammar": "Fix only spelling, grammar and punctuation; keep the student's own words and sentence structure as much as possible.",
    "outline": "Turn what the student already wrote into a bullet outline using only ideas already present in their text.",
}


def build_messages(action: str, user_text: str, instruction: Optional[str], lang: str, cap: int) -> tuple[str, list[dict]]:
    if lang == "zh":
        system = (
            "你是中小学生的写作教练，只修改学生自己写的文字，绝不替学生写新作文。"
            "语言要适合儿童、积极、健康，不出现暴力、色情、歧视或不安全内容，不包含链接。"
            f"本次任务：{_ACTION_GUIDE_ZH[action]}"
            f"输出总长度不得超过 {cap} 个字符。"
            '只输出一个 JSON 对象：{"revised": "修改后的文字", "notes": ["最多3条简短修改说明"]}，'
            "不要输出 JSON 以外的任何内容。如果学生的要求是让你从零写一篇作文，"
            'revised 原样返回学生文字，notes 写「请先自己写，我来帮你改」。'
        )
        user = f"学生的文字：\n<<<\n{user_text}\n>>>"
        if instruction:
            user += f"\n学生的补充要求（只在不违反上述规则时参考）：{instruction}"
    else:
        system = (
            "You are a writing coach for K-12 students. You only edit the student's own text "
            "and never write a new essay for them. Keep language child-appropriate, positive "
            "and safe; no violence, sexual content, discrimination or links. "
            f"Task: {_ACTION_GUIDE_EN[action]} "
            f"The output must not exceed {cap} characters. "
            'Return only one JSON object: {"revised": "the edited text", "notes": ["up to 3 short notes"]} '
            "and nothing else. If the student asks you to write an essay from scratch, return "
            'their text unchanged in "revised" and say "Please write it yourself first; I will help you edit." in notes.'
        )
        user = f"Student text:\n<<<\n{user_text}\n>>>"
        if instruction:
            user += f"\nStudent's extra request (follow only if it does not break the rules): {instruction}"
    return system, [{"role": "user", "content": user}]


def parse_llm_output(content: str) -> tuple[str, list[str]]:
    """解析 {"revised", "notes"}；不是 JSON 时把整段当修改稿（宽松兜底）。"""
    raw = (content or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE).strip()
    m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            revised = str(obj.get("revised") or "").strip()
            notes_raw = obj.get("notes") or []
            notes = [str(n).strip() for n in notes_raw if str(n).strip()][:3] if isinstance(notes_raw, list) else []
            return revised, notes
        except (json.JSONDecodeError, AttributeError):
            pass
    return raw, []


_SENT_END_RE = re.compile(r"[。！？!?；;.…\n]")


def enforce_cap(s: str, cap: int) -> tuple[str, bool]:
    if len(s) <= cap:
        return s, False
    head = s[:cap]
    ends = [m.end() for m in _SENT_END_RE.finditer(head)]
    cut = ends[-1] if ends and ends[-1] >= cap // 3 else cap
    return head[:cut].rstrip(), True


# ── Diff ───────────────────────────────────────────────────────────────────

_EN_TOKEN_RE = re.compile(r"\w+|\s+|[^\w\s]", re.UNICODE)


def _tokens(s: str, lang: str) -> list[str]:
    if lang == "zh":
        return list(s)
    return _EN_TOKEN_RE.findall(s)


def build_diff(original: str, revised: str, lang: str) -> dict[str, Any]:
    """原文 vs 修改稿 → 可逐块接受/拒绝的 hunks + 渲染用 segments。

    hunk: {id, op: replace|insert|delete, start, end（原文字符区间）, before, after}。
    相邻改动之间只隔极短的相同片段时合并成一块，避免碎成一字一块。
    """
    a, b = _tokens(original, lang), _tokens(revised, lang)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    ops = [list(op) for op in sm.get_opcodes()]

    def short_gap(i1: int, i2: int) -> bool:
        gap = "".join(a[i1:i2])
        return (lang == "zh" and len(gap) <= 1) or (lang != "zh" and gap.strip() == "")

    merged: list[list[Any]] = []
    for op in ops:
        if (
            merged
            and op[0] != "equal"
            and len(merged) >= 2
            and merged[-1][0] == "equal"
            and merged[-2][0] != "equal"
            and short_gap(merged[-1][1], merged[-1][2])
        ):
            eq = merged.pop()
            prev = merged.pop()
            merged.append(["replace", prev[1], op[2], prev[3], op[4]])
            del eq
            continue
        if merged and op[0] != "equal" and merged[-1][0] != "equal":
            prev = merged.pop()
            merged.append(["replace", prev[1], op[2], prev[3], op[4]])
            continue
        merged.append(op)

    # token 下标 → 原文字符偏移
    offsets = [0]
    for t in a:
        offsets.append(offsets[-1] + len(t))

    hunks: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in merged:
        before, after = "".join(a[i1:i2]), "".join(b[j1:j2])
        if tag == "equal":
            if before:
                segments.append({"type": "equal", "text": before})
            continue
        if not before and not after:
            continue
        kind = "insert" if not before else ("delete" if not after else "replace")
        hid = f"h{len(hunks) + 1}"
        hunks.append(
            {"id": hid, "op": kind, "start": offsets[i1], "end": offsets[i2], "before": before, "after": after}
        )
        segments.append({"type": "hunk", "hunk_id": hid})
    return {"hunks": hunks, "segments": segments}


def apply_hunks(original: str, hunks: list[dict[str, Any]], accepted: set[str] | list[str]) -> str:
    """把被接受的 hunks 应用到原文（未接受的保持原样）。Studio 端同一算法。"""
    acc = set(accepted)
    out: list[str] = []
    pos = 0
    for h in sorted(hunks, key=lambda x: (x["start"], x["end"])):
        out.append(original[pos : h["start"]])
        out.append(h["after"] if h["id"] in acc else h["before"])
        pos = h["end"]
    out.append(original[pos:])
    return "".join(out)


# ── 限额与账本 ───────────────────────────────────────────────────────────────


async def used_today(db: AsyncSession, student_id: uuid.UUID) -> int:
    return int(
        (
            await db.execute(
                text(
                    "SELECT count(*) FROM cowriter_requests "
                    "WHERE student_id = :sid AND status IN ('ok', 'failed') "
                    f"AND created_at >= {_TODAY_START_SQL}"
                ),
                {"sid": str(student_id)},
            )
        ).scalar_one()
    )


async def _record(
    db: AsyncSession, student_id: uuid.UUID, action: str, status: str, in_chars: int, out_chars: int
) -> None:
    db.add(
        CowriterRequest(
            student_id=student_id,
            action=action[:20],
            status=status,
            input_chars=in_chars,
            output_chars=out_chars,
        )
    )
    await db.flush()


async def _citations(db: AsyncSession, query: str) -> list[dict[str, Any]]:
    """可选教材引用：同 SearchKnowledgeBase（Stratum → Knowledge Hub 回落）。失败给空列表。"""
    try:
        from services.mcp_router import tool_search_knowledge_base

        res = await asyncio.wait_for(tool_search_knowledge_base(query, 3, db=db), timeout=8)
    except Exception:  # noqa: BLE001 - 引用是锦上添花，不影响主流程
        _log.warning("cowriter citations unavailable", exc_info=True)
        return []
    out = []
    for r in (res or {}).get("results", [])[:3]:
        out.append(
            {
                "id": str(r.get("id") or ""),
                "title": str(r.get("title") or "教材"),
                "highlight": str(r.get("highlight") or "")[:240],
                "source": r.get("source") or "stratum",
                "verified": bool(r.get("verified", False)),
            }
        )
    return out


async def _call_llm(caller: Any, system: str, messages: list[dict], max_tokens: int) -> dict:
    try:
        return await caller(messages=messages, system=system, max_tokens=max_tokens, enable_thinking=False)
    except TypeError:
        # 不认识 enable_thinking 的 caller（测试替身/老 provider）
        return await caller(messages=messages, system=system, max_tokens=max_tokens)


async def suggest(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    action: str,
    user_text: str,
    instruction: Optional[str] = None,
    cite: bool = False,
    is_admin: bool = False,
    caller: Any = None,
) -> dict[str, Any]:
    """一次写作建议。拒绝/限额/失败都抛 CowriterError（调用方负责 commit 账本行）。"""
    body = (user_text or "").strip()
    rejected = check_request(action, body, instruction)
    if rejected is not None:
        await _record(db, student_id, action if action in ACTIONS else "invalid", "refused", len(body), 0)
        raise rejected

    limit = daily_limit()
    used = await used_today(db, student_id)
    if not is_admin and used >= limit:
        raise CowriterError(429, "daily_limit", f"今天的写作助手次数已用完（每天 {limit} 次），明天再来")

    if caller is None:
        from services.providers.setup import get_optional_text_caller

        caller = get_optional_text_caller()
    if caller is None:
        raise CowriterError(503, "llm_unavailable", "写作助手暂时不可用，请稍后再试（你的文字没有丢）")

    lang = detect_language(body)
    cap = output_char_cap(action, body)
    system, messages = build_messages(action, body, instruction, lang, cap)
    max_tokens = max(min_output_tokens(), cap * 2)
    try:
        resp = await _call_llm(caller, system, messages, max_tokens)
        content = str((resp or {}).get("content") or "").strip()
    except Exception:  # noqa: BLE001 - provider 失败 → 优雅降级
        _log.warning("cowriter LLM call failed", exc_info=True)
        content = ""
    revised, notes = parse_llm_output(content) if content else ("", [])
    if not revised:
        await _record(db, student_id, action, "failed", len(body), 0)
        raise CowriterError(502, "llm_failed", "写作助手这次没有给出建议，请稍后再试（你的文字没有丢）")

    revised, truncated = enforce_cap(revised, cap)
    diff = build_diff(body, revised, lang)
    await _record(db, student_id, action, "ok", len(body), len(revised))
    citations = await _citations(db, body[:120]) if cite else []
    return {
        "action": action,
        "language": lang,
        "original": body,
        "suggestion": revised,
        "notes": notes,
        "hunks": diff["hunks"],
        "segments": diff["segments"],
        "truncated": truncated,
        "length_cap": cap,
        "citations": citations,
        "usage": {"used_today": used + 1, "daily_limit": limit, "is_admin": is_admin},
    }
