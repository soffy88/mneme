"""services/vocab_memory.py — 记忆节点的**质量门禁**、装配与 FSRS 复习阶梯

MNEME_CORE3000_MEMORY_ENGINE_P0_SPEC.md §5 / §6 的实现。三件事，都是确定性的：

1. :func:`verify_memory_node` —— 9 条质量门禁。**这是本文件存在的主要理由**：
   LLM 生成的记忆内容是要给 12-18 岁学生背的，一个错字就是错的，所以门禁一律
   「拒绝」而不是「启发式清洗」（与 OCR 管线同一纪律，见 STATUS 2026-10-02 P3）。
2. :func:`build_memory_node` —— 把 LLM 输出 + 已验证语境 + 既有事实层装配成落库行。
3. :func:`render_review_ladder` —— 复习阶梯。**每词 1 张卡、1 个 KC**，阶梯是同一张
   卡内的分阶段揭示，不是 4 张卡（2026-10-03 人决策）。

两条贯穿全文件的纪律：

- **不生成词源**。词源/词根/搭配全部读既有表（`vocabulary_affixes` 带三档可信度）。
  门禁 ``NOT_DISPUTED_SOURCE`` 挡的是「把 disputed 当词源展示」，不是重新判定词源。
- **降级要留痕**。无语境（tier 5）记 ``DEGRADED_NO_CONTEXT``，``verified=False``，
  **绝不记 PASS** —— 假绿会让「教材优先」这条产品承诺静默消失。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

# 门禁名。顺序即报告里的顺序，故意把「拒绝性」的门禁排前面。
GATE_HAS_ONE_CORE_IMAGE = "HAS_ONE_CORE_IMAGE"
GATE_HAS_RECALL_HOOK = "HAS_RECALL_HOOK"
GATE_ANSWER_MATCHES_WORD = "ANSWER_MATCHES_WORD"
GATE_NO_ANSWER_LEAK = "NO_ANSWER_LEAK"
GATE_NO_ECHO_OF_EVIDENCE = "NO_ECHO_OF_EVIDENCE"
GATE_HAS_CONTEXT = "HAS_CONTEXT"
GATE_FAMILY_TRACEABLE = "FAMILY_TRACEABLE"
GATE_NO_FALSE_ROOT = "NO_FALSE_ROOT"
GATE_NOT_DISPUTED_SOURCE = "NOT_DISPUTED_SOURCE"

ALL_GATES: tuple[str, ...] = (
    GATE_HAS_ONE_CORE_IMAGE,
    GATE_HAS_RECALL_HOOK,
    GATE_ANSWER_MATCHES_WORD,
    GATE_NO_ANSWER_LEAK,
    GATE_NO_ECHO_OF_EVIDENCE,
    GATE_HAS_CONTEXT,
    GATE_FAMILY_TRACEABLE,
    GATE_NO_FALSE_ROOT,
    GATE_NOT_DISPUTED_SOURCE,
)

# 核心画面太短撑不起记忆，太长学生读不完。
#
# 下限**曾是 8**，被 100 词真实试跑打掉：4/4 个 HAS_ONE_CORE_IMAGE 拒收全是
# **7 个汉字的好画面**——`real`→「火烧假花露真蕊」、`each`→「老师逐个发糖果」、
# `stand`→「脚生根顶住狂风」、`wet`→「拧湿毛巾水滴答」。也就是门槛刚好卡在模型
# 那种「凝练七字」的记忆风格上，把 40% 的拒收变成误杀（10 次拒收里 4 次）。
# 5 字仍是有效画面（「拉窗帘」），下限定 5；上限 60 不变（再长就是整段叙文）。
CORE_IMAGE_MIN_LEN = 5
CORE_IMAGE_MAX_LEN = 60

_DEGRADED_NO_CONTEXT = "DEGRADED_NO_CONTEXT"


def _norm(text: str | None) -> str:
    """归一化：NFKC + 小写 + 折叠空白 + 去掉所有非字母数字。

    用于「回答是否等于目标词」「回忆问是否泄漏目标词」这类比较。学生端可能打
    ``Abandon`` / ``abandon.`` / ``abandon ``，不该因此判错。
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[^0-9a-z一-鿿]+", "", t)


def _tokens(text: str | None) -> set[str]:
    """英文按空白/标点切词；中文整串（中文没有空格可切）。"""
    if not text:
        return set()
    return {t for t in re.split(r"[^0-9a-zA-Z一-鿿']+", text) if t}


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"gate": self.name, "passed": self.passed, "detail": self.detail}


@dataclass
class QualityReport:
    word: str
    gates: list[GateResult]

    @property
    def passed_count(self) -> int:
        return sum(1 for g in self.gates if g.passed)

    @property
    def degraded(self) -> bool:
        return any(not g.passed and g.detail == _DEGRADED_NO_CONTEXT for g in self.gates)

    @property
    def score(self) -> float:
        return round(self.passed_count / len(self.gates), 4) if self.gates else 0.0

    @property
    def failed_gates(self) -> list[str]:
        return [g.name for g in self.gates if not g.passed]

    def to_payload(self) -> dict[str, Any]:
        return {
            "word": self.word,
            "quality_score": self.score,
            "gates_passed": self.passed_count,
            "gates_total": len(self.gates),
            "failed_gates": self.failed_gates,
            # verified 要求全过。无语境降级时 HAS_CONTEXT 也不过，故 tier C 词
            # 不会成为 verified —— 这是刻意的：无语境记忆卡不等于验证过的记忆卡。
            "verified": self.passed_count == len(self.gates),
            "degraded": self.degraded,
            "gates": [g.to_payload() for g in self.gates],
        }


def verify_memory_node(
    node: dict[str, Any],
    *,
    memory_input: dict[str, Any],
    family_resolved: list[dict[str, Any]] | None = None,
) -> QualityReport:
    """跑 9 条门禁。纯函数、无 IO，可完整单测。

    Parameters
    ----------
    node : dict
        LLM 产出的记忆节点（尚未装配）。
    memory_input : dict
        :func:`services.vocab_context.load_memory_input` 的返回，提供词、语境、
        既有词根分档等事实。
    family_resolved : list[dict] | None
        :func:`services.vocab_context.resolve_family` 的返回（只含库内真实词）。
        ``None`` 表示还没解析 —— 此时 FAMILY_TRACEABLE 判不过，因为**未验证即不可信**。
    """
    word = str(memory_input.get("word") or "")
    word_norm = _norm(word)
    gates: list[GateResult] = []

    # 1. HAS_ONE_CORE_IMAGE
    core_image = (node.get("core_image") or "").strip()
    if not core_image:
        gates.append(GateResult(GATE_HAS_ONE_CORE_IMAGE, False, "core_image 为空"))
    elif not (CORE_IMAGE_MIN_LEN <= len(core_image) <= CORE_IMAGE_MAX_LEN):
        gates.append(
            GateResult(
                GATE_HAS_ONE_CORE_IMAGE,
                False,
                f"core_image 长度 {len(core_image)} 不在 "
                f"[{CORE_IMAGE_MIN_LEN}, {CORE_IMAGE_MAX_LEN}]",
            )
        )
    else:
        gates.append(GateResult(GATE_HAS_ONE_CORE_IMAGE, True))

    # 2. HAS_RECALL_HOOK
    q = (node.get("recall_question") or "").strip()
    if not q:
        gates.append(GateResult(GATE_HAS_RECALL_HOOK, False, "recall_question 为空"))
    elif not q.endswith(("？", "?")):
        gates.append(GateResult(GATE_HAS_RECALL_HOOK, False, "recall_question 不是问句"))
    else:
        gates.append(GateResult(GATE_HAS_RECALL_HOOK, True))

    # 3. ANSWER_MATCHES_WORD
    answer_norm = _norm(node.get("answer"))
    if not answer_norm:
        gates.append(GateResult(GATE_ANSWER_MATCHES_WORD, False, "answer 为空"))
    elif answer_norm != word_norm:
        gates.append(
            GateResult(
                GATE_ANSWER_MATCHES_WORD,
                False,
                f"answer={node.get('answer')!r} != word={word!r}",
            )
        )
    else:
        gates.append(GateResult(GATE_ANSWER_MATCHES_WORD, True))

    # 4. NO_ANSWER_LEAK —— 回忆问里出现目标词，主动回忆就废了。
    #    原 spec 未列这条，但它会让整张卡退化成「填空题里印着答案」。
    if q and word_norm:
        leaked = [t for t in _tokens(q) if _norm(t) and _norm(t) == word_norm]
        # 多词短语按整串比；单词按 token 比，避免 "a bit of" 命中 "of"。
        if word_norm in _norm(q) and (" " in word.strip() or not _tokens(word)):
            leaked = [word]
        if leaked:
            gates.append(
                GateResult(GATE_NO_ANSWER_LEAK, False, f"recall_question 泄漏目标词 {leaked}")
            )
        else:
            gates.append(GateResult(GATE_NO_ANSWER_LEAK, True))
    else:
        gates.append(GateResult(GATE_NO_ANSWER_LEAK, False, "无法判定（缺问句或缺词）"))

    # 5. NO_ECHO_OF_EVIDENCE —— 核心画面不能是真实句的复制，否则「记忆」= 抄课文。
    ctx = memory_input.get("context") or {}
    evidence_texts = [
        (s.get("text") or "").strip() for s in (ctx.get("sentences") or [])
    ]
    evidence_texts.append((memory_input.get("context_flat") or "").strip())
    core_norm = _norm(core_image)
    if core_norm and any(core_norm and core_norm == _norm(t) for t in evidence_texts if t):
        gates.append(
            GateResult(GATE_NO_ECHO_OF_EVIDENCE, False, "core_image 是语境句的复制")
        )
    else:
        gates.append(GateResult(GATE_NO_ECHO_OF_EVIDENCE, True))

    # 6. HAS_CONTEXT —— 无语境时记 DEGRADED，**不记 PASS**。
    if ctx.get("tier", 5) < 5 and ctx.get("sentences"):
        gates.append(GateResult(GATE_HAS_CONTEXT, True, f"tier={ctx.get('tier')}"))
    else:
        gates.append(GateResult(GATE_HAS_CONTEXT, False, _DEGRADED_NO_CONTEXT))

    # 7. FAMILY_TRACEABLE —— 未解析即不可信。
    raw_family = node.get("family") or []
    if family_resolved is None:
        gates.append(GateResult(GATE_FAMILY_TRACEABLE, False, "family 尚未解析为库内真实词"))
    elif not raw_family:
        gates.append(GateResult(GATE_FAMILY_TRACEABLE, True, "无 family 成员"))
    elif not family_resolved:
        gates.append(
            GateResult(GATE_FAMILY_TRACEABLE, False, "family 成员全部查不到（非真实词）")
        )
    else:
        gates.append(
            GateResult(
                GATE_FAMILY_TRACEABLE,
                True,
                f"{len(family_resolved)}/{len(raw_family)} 可追溯",
            )
        )

    # 8. NO_FALSE_ROOT —— 生成的拼写钩子若与存储分解矛盾则丢弃生成值。
    #    P0 的 memory node 不落 root_logic 列，所以这一步实际是「不许生成值污染
    #    既有 379 条分档数据」。
    affix = memory_input.get("affix") or {}
    root_logic = (node.get("spelling_hook") or "").strip()
    if not root_logic:
        gates.append(GateResult(GATE_NO_FALSE_ROOT, True, "无生成词根叙述"))
    else:
        conflict = _root_conflicts(root_logic, affix)
        if conflict:
            gates.append(GateResult(GATE_NO_FALSE_ROOT, False, f"与存储分解矛盾: {conflict}"))
        else:
            gates.append(GateResult(GATE_NO_FALSE_ROOT, True))

    # 9. NOT_DISPUTED_SOURCE —— disputed（与参考表冲突）不得进记忆卡展示面。
    if not affix:
        gates.append(GateResult(GATE_NOT_DISPUTED_SOURCE, True, "无词根数据"))
    elif affix.get("etymology_status") == "disputed":
        gates.append(
            GateResult(GATE_NOT_DISPUTED_SOURCE, False, "词根档位为 disputed，不得展示")
        )
    else:
        gates.append(GateResult(GATE_NOT_DISPUTED_SOURCE, True))

    return QualityReport(word=word, gates=gates)


# 生成文本里出现这些「拆解记号」时，才去核对是否与存储分解矛盾 —— 否则普通
# 句子（「想象一只拒绝帮助的猫」）不该被当词根叙述审。
_MORPHEME_MARKERS = ("词根", "前缀", "后缀", "拆解", "=-", "＝", "- ", "·")


def _root_conflicts(spelling_hook: str, affix: dict[str, Any]) -> str | None:
    """生成的拼写钩子是否与存储的前缀/词根/后缀矛盾。返回矛盾描述或 None。

    只在拼写钩子**明确在讲拆解**时才判矛盾，且只判「存储里有的段位被生成否定」
    这一个方向 —— 生成内容漏掉某段位不算矛盾（那只是讲得少），但把存储里
    `pre-` 说成「没有前缀」是直接教错。
    """
    if not any(m in spelling_hook for m in _MORPHEME_MARKERS):
        return None
    lowered = spelling_hook.lower()
    for seg_name, seg in (
        ("前缀", affix.get("prefix")),
        ("词根", affix.get("root")),
        ("后缀", affix.get("suffix")),
    ):
        if not seg:
            continue
        for phrase in (f"没有{seg_name}", f"无{seg_name}", f"不含{seg_name}"):
            if phrase in lowered or phrase in spelling_hook:
                return f"称「{phrase}」但库内有 {seg_name}={seg}"
    return None


# ---------------------------------------------------------------------------
# 装配
# ---------------------------------------------------------------------------

# 只有 A 级（语境 + 记忆锚点）进动画候选。理由见 spec §2.4：B 级连词根/象形锚点
# 都没有，画面是凭空的，动画只会把凭空的画面做得更可信。
ANIMATION_TIERS = frozenset({"A"})


def build_memory_node(
    node: dict[str, Any],
    *,
    memory_input: dict[str, Any],
    report: QualityReport,
    family_resolved: list[dict[str, Any]] | None,
    generation_model: str | None,
    generation_version: str = "p0",
) -> dict[str, Any]:
    """装配落库行。**不做启发式修补**：门禁不过就带 verified=False 落库，
    保留现场供人工复核，而不是悄悄把不合格内容修成合格的。"""
    ctx = memory_input.get("context") or {}
    tier = memory_input.get("tier") or "C"
    evidence = [
        {
            "sentence_id": s.get("sentence_id"),
            "text": s.get("text"),
            "lesson": s.get("lesson"),
            "source": s.get("source"),
        }
        for s in (ctx.get("sentences") or [])
    ]
    payload = report.to_payload()
    animation_candidate = tier in ANIMATION_TIERS and bool(node.get("image_prompt"))
    return {
        "vocabulary_item_id": memory_input["vocabulary_id"],
        "tier": tier,
        "core_image": (node.get("core_image") or "").strip(),
        "semantic_core": node.get("semantic_core") or {},
        "scene": (node.get("scene") or "").strip() or None,
        "family_network": family_resolved or [],
        "sound_hook": (node.get("sound_hook") or "").strip() or None,
        "spelling_hook": (node.get("spelling_hook") or "").strip() or None,
        "recall_question": (node.get("recall_question") or "").strip(),
        "answer": (node.get("answer") or "").strip(),
        "image_prompt": (node.get("image_prompt") or "").strip() or None,
        "animation_candidate": animation_candidate,
        "animation_scene": (node.get("scene") or "").strip()
        if animation_candidate
        else None,
        "context_tier": int(ctx.get("tier") or 5),
        "context_evidence": evidence,
        "context_absence_reason": None if evidence else ctx.get("degradation_reason"),
        "generation_model": generation_model,
        "generation_version": generation_version,
        "quality_score": payload["quality_score"],
        "verified": payload["verified"],
    }


# ---------------------------------------------------------------------------
# FSRS 复习阶梯（spec §6）
# ---------------------------------------------------------------------------

STAGE_LEARNING = "learning"
STAGE_REVIEW_EARLY = "review_early"
STAGE_REVIEW_MID = "review_mid"
STAGE_REVIEW_LATE = "review_late"

# 每阶段默认露到第几层。首次（learning）= 全展开：2026-10-03 人决策「第一次最重要，
# 目标是完全理解，所以首次不做下拉折叠」。
STAGE_MAX_LAYER: dict[str, int] = {
    STAGE_LEARNING: 4,
    STAGE_REVIEW_EARLY: 3,
    STAGE_REVIEW_MID: 3,
    STAGE_REVIEW_LATE: 2,
}

# 层序：1 画面 → 2 语义 → 3 词根/词源 + 搭配 → 4 真实语境句。
# 注意层 3 的内容**不在** MemoryNode 里（单源红线），渲染时由调用方从既有表取，
# 这里只声明「这一层存在，由 facts 提供」。
LAYER_ORDER = ("core_image", "semantic_core", "word_origin", "context_sentence")


# py-fsrs 的 State 枚举值。**不能假设 state 是字符串** —— 实测线上
# `kc_mastery.fsrs_card_json` 存的是 `{"state": 1, "step": 0, ...}`，
# 即 int。第一版 resolve_stage 按 `"learning"/"review"` 字符串写，且读了
# `card["reps"]` —— 而 py-fsrs 的 Card **根本没有 reps 字段**
# （字段只有 card_id/state/step/stability/difficulty/due/last_review）。
# 那种写法只对自己编的 fixture 成立，接到真卡上就是 AttributeError。
_FRSRS_STATE_LEARNING = 1
_FRSRS_STATE_REVIEW = 2
_FRSRS_STATE_RELEARNING = 3

# py-fsrs 不存复习次数，只能用**已排定的间隔**当重复次数的代理：间隔随成功次数单调
# 增长。阈值取 FSRS 常用量级（天）。这是代理不是真计数，故写在这里而不是散落。
_EARLY_INTERVAL_DAYS = 3.0
_MID_INTERVAL_DAYS = 21.0


def _as_card_dict(card: Any) -> dict[str, Any]:
    """把 fsrs_card_json 规整成 dict。列是 JSONB，但历史行/导入数据可能是字符串。"""
    if card is None:
        return {}
    if isinstance(card, dict):
        return card
    if isinstance(card, str):
        import json

        try:
            parsed = json.loads(card)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _interval_days(card: dict[str, Any]) -> float | None:
    """已排定的复习间隔（天）。取不到就返回 None（不猜）。"""
    import datetime as _dt

    due = card.get("due")
    last = card.get("last_review")
    if not isinstance(due, str) or not isinstance(last, str):
        return None
    try:
        due_dt = _dt.datetime.fromisoformat(due)
        last_dt = _dt.datetime.fromisoformat(last)
    except ValueError:
        return None
    if due_dt.tzinfo is None:
        due_dt = due_dt.replace(tzinfo=_dt.timezone.utc)
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=_dt.timezone.utc)
    return (due_dt - last_dt).total_seconds() / 86400.0


def resolve_stage(card: Any) -> str:
    """由 FSRS 卡片状态判定阶梯阶段。纯函数、可单测。

    ``card`` 是 KCMastery.fsrs_card_json（dict 或 JSON 字符串）。无卡片 → ``learning``。

    - ``state`` 1/3（Learning / Relearning）→ ``learning``：**全展开**。Relearning
      也归这里，因为「忘了重新学」的场景同样需要完整理解，不该折叠。
    - ``state`` 2（Review）→ 按已排定间隔分早/中/晚（见上面的阈值与原因）。
    """
    c = _as_card_dict(card)
    if not c:
        return STAGE_LEARNING
    raw_state = c.get("state")
    # 容错：int（py-fsrs 原生）或字符串（其它 provider / 手写数据）
    if isinstance(raw_state, bool):  # bool 是 int 的子类，挡掉
        return STAGE_LEARNING
    if isinstance(raw_state, int):
        state = raw_state
    elif isinstance(raw_state, str):
        s = raw_state.strip().lower()
        if s in ("1", "learning", "relearning"):
            state = _FRSRS_STATE_LEARNING
        elif s in ("2", "review"):
            state = _FRSRS_STATE_REVIEW
        elif s in ("3", "relearning"):
            state = _FRSRS_STATE_RELEARNING
        else:
            return STAGE_LEARNING
    else:
        return STAGE_LEARNING

    if state in (_FRSRS_STATE_LEARNING, _FRSRS_STATE_RELEARNING):
        return STAGE_LEARNING

    days = _interval_days(c)
    if days is None:
        return STAGE_REVIEW_EARLY
    if days < _EARLY_INTERVAL_DAYS:
        return STAGE_REVIEW_EARLY
    if days < _MID_INTERVAL_DAYS:
        return STAGE_REVIEW_MID
    return STAGE_REVIEW_LATE


def render_review_ladder(
    node: dict[str, Any],
    *,
    stage: str | None = None,
    card: dict[str, Any] | None = None,
    expanded: int = 0,
    facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """渲染一张卡的复习阶梯。

    Parameters
    ----------
    node : dict
        落库的 memory node 行。
    stage : str | None
        显式阶段；不给则由 ``card`` 推。
    card : dict | None
        KCMastery.fsrs_card_json。
    expanded : int
        「再看一层」的次数。**只影响露出多少，不改变 FSRS 调度状态** —— 想深挖的
        学生可以每次多看一层，但复习间隔仍由引擎决定。
    facts : dict | None
        既有事实层（``word_origin`` 取自 vocabulary_affixes，``collocations`` 取自
        vocabulary_collocations）。由调用方从既有表读，不存在本函数里。

    Returns
    -------
    dict
        ``{"stage", "layers": [...], "hidden_layers": [...], "kc", "all_shown"}``
    """
    st = stage or resolve_stage(card)
    base = STAGE_MAX_LAYER.get(st, STAGE_MAX_LAYER[STAGE_LEARNING])
    visible = min(len(LAYER_ORDER), max(1, base + max(0, expanded)))
    facts = facts or {}
    origin = facts.get("word_origin")

    payloads: dict[str, Any] = {
        "core_image": {"core_image": node.get("core_image")},
        "semantic_core": {
            "semantic_core": node.get("semantic_core"),
            "scene": node.get("scene"),
            "recall_question": node.get("recall_question"),
        },
        # disputed 档位不进展示面（与 vocab_affixes.should_display 同规则）。
        "word_origin": {
            "word_origin": None if origin is None or not origin.get("should_display", True) else origin,
            "collocations": facts.get("collocations") or [],
        },
        "context_sentence": {"context_evidence": node.get("context_evidence") or []},
    }

    layers = [
        {"layer": i + 1, "key": key, "content": payloads[key]}
        for i, key in enumerate(LAYER_ORDER)
    ]
    return {
        "stage": st,
        "kc": vocab_kc(node["vocabulary_item_id"]),
        "layers": layers[:visible],
        "hidden_layers": [ly["key"] for ly in layers[visible:]],
        "hidden_count": max(0, len(layers) - visible),
        "all_shown": visible >= len(layers),
    }


def vocab_kc(vocabulary_item_id: str) -> str:
    """词汇 KC 命名。唯一来源，与 services/vocab_service._kp 同约定。"""
    return f"vocab-{vocabulary_item_id}"


__all__ = [
    "ALL_GATES",
    "GATE_ANSWER_MATCHES_WORD",
    "GATE_FAMILY_TRACEABLE",
    "GATE_HAS_CONTEXT",
    "GATE_HAS_ONE_CORE_IMAGE",
    "GATE_HAS_RECALL_HOOK",
    "GATE_NOT_DISPUTED_SOURCE",
    "GATE_NO_ANSWER_LEAK",
    "GATE_NO_ECHO_OF_EVIDENCE",
    "GATE_NO_FALSE_ROOT",
    "STAGE_LEARNING",
    "STAGE_REVIEW_EARLY",
    "STAGE_REVIEW_LATE",
    "STAGE_REVIEW_MID",
    "GateResult",
    "QualityReport",
    "verify_memory_node",
    "build_memory_node",
    "render_review_ladder",
    "resolve_stage",
    "vocab_kc",
]