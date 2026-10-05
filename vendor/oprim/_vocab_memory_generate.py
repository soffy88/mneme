"""oprim._vocab_memory_generate — 词汇记忆节点批量生成（单次 LLM 调用）

单次 LLM 调用批量生成 MemoryNode 的**联想层**：核心画面 / 语义核心 / 记忆场景 /
家族词 / 声音钩子 / 拼写钩子 / 主动回忆问 / 图片 prompt。

刻意**不生成**的东西（见 MNEME_CORE3000_MEMORY_ENGINE_P0_SPEC.md §1.3）：

- **词源 / etymology**：LLM 产出的词源是首要幻觉面。本仓已有分档体系
  `vocabulary_affixes.etymology_status`（reference_confirmed / mnemonic_association /
  disputed），词源一律由调用方从那里读。**契约里没有这个字段 = 不可能编造**，
  比事后跑一个 `ETYMOLOGY_CONFIRMED` 门禁强得多。
- **搭配 / 词根**：同理，读 `vocabulary_collocations` / `vocabulary_affixes`。
- **例句**：调用方给的是从 `timed_sentences` 确定性抽取的真实句。LLM 只读不改，
  输出里的任何句子都不是事实来源。

LLM 输出解析失败、字段缺失或契约违规时，**该词整体退化为 None**，绝不返回半成品
——半成品会被下游质量门当成可用记忆，反而比没有更坏。
"""

from __future__ import annotations

from typing import Any

# 契约里刻意没有 etymology / collocations / root / example。见模块 docstring。
_REQUIRED_KEYS = (
    "word",
    "core_image",
    "semantic_core",
    "scene",
    "recall_question",
    "answer",
    "image_prompt",
)

_SYSTEM = """你是中学英语单词记忆卡的编创者，服务 12-18 岁学生。

对每个单词，产出一个「记得住」的记忆节点。铁律：

1. **核心画面**：一个具体、可视、有动作的场面（10-30 字）。不是抽象解释，
   不是定义复述，不是环保新闻式空泛比喻。例：`abandon` → 「船长松开缆绳弃船」。
2. **语义核心**：image 是同一画面的中文表述；meaning 是「放手类」这类
   **上位概念**（6-15 字），不是词典释义抄写；logic 是 3 步因果链，用 → 连接。
3. **记忆场景**：把画面放进一个更长的故事场景（15-40 字）。
4. **家族词**：**只能**从该单词的「库内同族候选」清单里挑，最多 3 个，并给中文义。
   - 清单非空：只允许输出清单里的词，**不得**自行添加清单外的词。
   - 清单为空（`[]`）：说明这个词（多为专有名词或缩写，如 Canada / CD）**本来就没有
     同族词**。此时 `family` 必须输出 `[]`。交空数组是正确答案，编一个词才是错的。
5. **易混词**：**只能**从该单词的「库内形近易混候选」清单里挑，**最多 2 个**，
   并给出「一秒区分」的判断方法。
   - 清单非空：只允许输出清单里的词。若清单里没有真正值得区分的，输出 `[]` 即可 ——
     **宁可空，也不要硬凑**（收一条不混淆的对照规则只是占位）。
   - 清单为空：`confusables` 输出 `[]`。
   - 若输入给出「学习者自报混淆词」，**必须**把它排在第一位，并让区分方法直接针对它。
6. **声音钩子**：用中文谐音或音节联想把这个词的发音挂到画面上（≤20 字）。
7. **拼写钩子**：按词根/前缀/词缀或词形拆解帮记拼写（≤25 字）。
   不得凭空编造词根——只说你有把握的部分。
8. **主动回忆问**：一个问句（以？结尾），问画面或动作，**严禁包含目标单词本身**。
9. **answer**：**就是目标单词本身**，照抄输入里给出的英文单词（原形，一个词，不加
   句号、不加解释、不写中文）。它是学生作答时要回忆的那个词 —— 不是对回忆问的
   文字回答。例如单词 `abandon` → answer 就是 `abandon`。
10. **图片 prompt**：英文，20 词以内，`cartoon educational style, clear action,
   vocabulary learning illustration` 风格描述画面主体与动作。

严禁：编造词源、编造例句、输出目标词以外的英文句子、**编造库内不存在的家族词**、
**编造清单外的易混词**。
只输出 JSON 数组，与输入一一对应、顺序不变、长度相同：
[{"word": "...", "core_image": "...", "semantic_core": {"image": "...",
  "meaning": "...", "logic": "..."}, "scene": "...", "family": [{"word": "...",
  "meaning_cn": "..."}], "confusables": [{"word": "...", "distinguish_cn": "..."}],
  "sound_hook": "...", "spelling_hook": "...",
  "recall_question": "...", "answer": "...", "image_prompt": "..."}]"""


def _render_family_candidates(candidates: Any) -> str:
    """把库内同族候选渲染成 prompt 里的一行。

    **空清单要显式说「本来就没有」**，不能渲染成「无」——模型看到「无」会去猜，
    而空清单的正确答案就是交空数组。这个区别是 FAMILY_TRACEABLE 的成败所在。
    """
    items = [c for c in (candidates or []) if isinstance(c, dict) and c.get("word")]
    if not items:
        return "[]（该词无库内同族词，family 请输出空数组）"
    return "[" + ", ".join(
        f"{c['word']}（{(c.get('meaning_cn') or '无释义').strip()}）" for c in items
    ) + "]"


def _render_confusable_candidates(candidates: Any) -> str:
    """渲染形近易混候选。空清单同样要**显式说明**（同 family：空 = 无需硬凑）。"""
    items = [c for c in (candidates or []) if isinstance(c, dict) and c.get("word")]
    if not items:
        return "[]（库内无形近词，confusables 请输出空数组）"
    return "[" + ", ".join(
        f"{c['word']}（{(c.get('meaning_cn') or '无释义').strip()}）" for c in items
    ) + "]"


def _valid(d: Any) -> bool:
    """一个 dict 是否满足契约。任一必填字段缺失/空/类型错即整体作废。"""
    if not isinstance(d, dict):
        return False
    for k in _REQUIRED_KEYS:
        v = d.get(k)
        if k == "semantic_core":
            if not isinstance(v, dict) or not all(
                isinstance(v.get(sub), str) and v.get(sub, "").strip()
                for sub in ("image", "meaning", "logic")
            ):
                return False
        elif not isinstance(v, str) or not v.strip():
            return False
    fam = d.get("family", [])
    if not isinstance(fam, list):
        return False
    for item in fam:
        if not isinstance(item, dict) or not isinstance(item.get("word"), str):
            return False
    return True


async def generate_memory_nodes(
    entries: list[dict],
    *,
    caller: Any,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 16384,
) -> list[dict]:
    """批量生成记忆节点。

    Parameters
    ----------
    entries : list[dict]
        每项 ``{"word": str, "pos": str|None, "meaning_cn": str|None,
        "context": str|None, "affix_hint": str|None,
        "family_candidates": list[dict]|None}``。
        ``context`` 是调用方从语料库确定性抽取的**真实句**；``affix_hint`` 是
        调用方从 ``vocabulary_affixes`` 读到的既有分解（可能为空）。

        ``family_candidates`` 是调用方用**确定性算法**（词干前缀 ∪ 同词根）算出的
        库内真实同族词（见 ``services.vocab_context.family_candidates``）。给了它，
        模型就不必凭「英语里真实存在」去猜 —— 那正是 100 词试跑里
        FAMILY_TRACEABLE 唯一拒收来源。**空列表是合法输入**（专有名词/缩写）。
    caller : Any
        LLM 调用者（注入）。
    model : str
        模型名。
    max_tokens : int
        输出上限。

    Returns
    -------
    list[dict]
        与 ``entries`` **等长同序**。契约违规或缺项的那一项为 ``None``
        （调用方据此跳过该词，不假装生成成功）。
    """
    import json

    from oprim.llm import llm_complete

    listing = "\n".join(
        "{i}. 单词: {w}\n   词性: {p}\n   释义: {m}\n   真实语境句: {c}\n   已知词根拆解: {a}\n   库内同族候选: {f}\n   库内形近易混候选: {x}\n   学习者自报混淆词: {lc}".format(
            i=i + 1,
            w=e.get("word"),
            p=e.get("pos") or "未标注",
            m=e.get("meaning_cn") or "未标注",
            c=e.get("context") or "无（请勿编造例句，只做画面联想）",
            a=e.get("affix_hint") or "无（请勿编造词根）",
            f=_render_family_candidates(e.get("family_candidates")),
            x=_render_confusable_candidates(e.get("confusable_candidates")),
            lc=(e.get("learner_confused_with") or "无（学习者未提出混淆点）"),
        )
        for i, e in enumerate(entries)
    )
    resp = await llm_complete(
        [{"role": "user", "content": listing}],
        caller=caller,
        system=_SYSTEM,
        model=model,
        max_tokens=max_tokens,
    )

    raw = resp.text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    # 「为什么没解析出来」必须能说清。推理模型被 max_tokens 截断时，HTTP 是 200、
    # 正文是**半截 JSON**（实测 Agents-A1 在 8192 下就断在字符串中间）。若只报
    # 「契约未过」，会被误判成 prompt/模型质量问题，而真正的原因是预算不足。
    truncated = str(getattr(resp, "stop_reason", "") or "").lower() == "length"

    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            data = []
    except json.JSONDecodeError as exc:
        data = []
        parse_error = str(exc)
    else:
        parse_error = None

    by_word = {d.get("word"): d for d in data if isinstance(d, dict)}

    out: list[dict | None] = []
    for e in entries:
        d = by_word.get(e.get("word"))
        ok = d is not None and _valid(d)
        if ok:
            out.append(d)
        else:
            # 附上诊断信息；None 的语义仍是「本词跳过」，这里只增加可观测性
            out.append(
                {
                    "__failed__": True,
                    "word": e.get("word"),
                    "reason": (
                        "truncated_by_max_tokens" if truncated
                        else ("json_parse_error: " + (parse_error or "")[:80] if parse_error
                              else "missing_or_invalid_fields")
                    ),
                    "stop_reason": getattr(resp, "stop_reason", None),
                    "raw_len": len(raw),
                }
            )
    return out


__all__ = ["generate_memory_nodes"]