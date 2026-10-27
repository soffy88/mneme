"""Tutor 回答溯源标签 + 超纲拒答门 + 资料防注入。

Exam Cram Coach 方法论的 Mneme 干净实现（方法可学，代码自己写）：
- 每段回答带三档标签：MATERIAL（来自学生资料，须带来源引用）、
  SUPPLEMENT（AI 补充背景，可能与老师讲法不同）、GENERATED（资料中
  无此答案，模型自编）。
- 检索不到任何支撑材料时返回定型拒答结果（类型化 dict，绝不用
  HTTP 状态码 hack，更不现场编答案）。
- 学生上传 / 摄入的资料一律视为数据而非指令：围栏 + 启发式扫描，
  检出只标记、不执行、不隐藏（向学生明示一句已忽略）。

本模块是纯函数，无 DB、无网络、无 LLM 调用，可脱服务直测。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence


class ProvenanceLabel(str, Enum):
    """回答段落的来源档位。"""

    MATERIAL = "material"
    SUPPLEMENT = "supplement"
    GENERATED = "generated"


LABEL_MARK = {
    ProvenanceLabel.MATERIAL: "🟢",
    ProvenanceLabel.SUPPLEMENT: "🟡",
    ProvenanceLabel.GENERATED: "⚠️",
}

LABEL_NAME = {
    ProvenanceLabel.MATERIAL: "来自资料",
    ProvenanceLabel.SUPPLEMENT: "AI 补充",
    ProvenanceLabel.GENERATED: "AI 自编答案",
}


@dataclass(frozen=True)
class SourceRef:
    """一条来源引用：KU id / 题 id / 讲义文件页码三者至少其一。

    kind 取值：ku（知识点）、question（题库题）、material（讲义/文件）、
    textbook（教材册）。
    """

    kind: str
    ref: str
    page: Optional[int] = None

    def render(self) -> str:
        if self.page is not None:
            return f"{self.kind}:{self.ref} p.{self.page}"
        return f"{self.kind}:{self.ref}"


@dataclass
class TaggedSegment:
    """一段回答 + 它的来源档位。label 为 None 表示未标注（门禁不通过）。"""

    text: str
    label: Optional[ProvenanceLabel] = None
    sources: list[SourceRef] = field(default_factory=list)

    def render(self) -> str:
        if self.label is None:
            return self.text
        mark = LABEL_MARK[self.label]
        if self.label is ProvenanceLabel.MATERIAL and self.sources:
            cites = "、".join(s.render() for s in self.sources)
            return f"{mark} {self.text}（来源：{cites}）"
        return f"{mark} {self.text}"


def render_reply(segments: Sequence[TaggedSegment]) -> str:
    """把带标签的段落拼成最终回复文本（段与段之间空行分隔）。"""
    return "\n\n".join(s.render() for s in segments if s.text.strip())


def certify_reply(segments: Sequence[TaggedSegment]) -> dict:
    """门禁：每段都必须带标签，否则视为未完成、不得交付。

    返回 {"passed": bool, "unlabeled": [段序号...], "labels": [...]}。
    空回复同样不通过（无内容可交付）。
    """
    unlabeled = [i for i, s in enumerate(segments) if s.label is None or not s.text.strip()]
    labels = [s.label.value if s.label is not None else None for s in segments]
    return {
        "passed": not unlabeled and len(segments) > 0,
        "unlabeled": unlabeled,
        "labels": labels,
    }


# ---------------------------------------------------------------- 拒答门


def _short(query: str, limit: int = 60) -> str:
    q = " ".join(str(query or "").split())
    return q if len(q) <= limit else q[:limit] + "…"


def build_refusal(query: str, related: Sequence[SourceRef] = ()) -> dict:
    """定型拒答结果：明说资料里没有，并推荐已覆盖的相关内容。

    类型化 dict，不用 HTTP 状态码表达业务拒答；related 为空时不伪造推荐。
    """
    rel = [s.render() for s in related]
    return {
        "refused": True,
        "reason": f"资料里没有与「{_short(query)}」直接相关的内容，无法按资料作答。",
        "related": rel,
        "hint": "可以先看上面列出的相关内容，或换一个资料里讲过的问法。" if rel else "可以换一个资料里讲过的问法，或先学已覆盖的相关内容。",
    }


@dataclass
class RetrievalEvidence:
    """一次问答检索到的支撑材料：三类命中任一存在即有支撑。"""

    ku_hits: list[str] = field(default_factory=list)
    question_hits: list[str] = field(default_factory=list)
    material_hits: list[SourceRef] = field(default_factory=list)

    def has_support(self) -> bool:
        return bool(self.ku_hits or self.question_hits or self.material_hits)

    def as_related(self) -> list[SourceRef]:
        refs = [SourceRef(kind="ku", ref=k) for k in self.ku_hits[:5]]
        refs += [SourceRef(kind="question", ref=q) for q in self.question_hits[:5]]
        refs += list(self.material_hits[:5])
        return refs


def gate_retrieval(evidence: RetrievalEvidence, query: str) -> Optional[dict]:
    """拒答门：无任何支撑材料时返回定型拒答，否则返回 None（放行）。

    注意：放行只表示“有材料可讲”，不表示回答本身已标注——回答仍须
    经过 certify_reply 门禁。
    """
    if evidence.has_support():
        return None
    return build_refusal(query, [])


# ---------------------------------------------------------------- 防注入


MATERIAL_OPEN = "<<<MATERIAL"
MATERIAL_CLOSE = "MATERIAL>>>"

# 转向语句启发式：命中即标记，绝不执行。刻意只列“对 AI 下指令”的句式，
# 不列学科内容词，避免把正常讲义误伤。
_STEERING_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ignore_previous", re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE)),
    ("disregard_previous", re.compile(r"disregard\s+(all\s+)?(previous|prior|above)\b", re.IGNORECASE)),
    ("you_are_now", re.compile(r"you\s+are\s+now\b", re.IGNORECASE)),
    ("system_prompt", re.compile(r"system\s*prompt", re.IGNORECASE)),
    ("jailbreak", re.compile(r"jailbreak", re.IGNORECASE)),
    ("do_not_tell", re.compile(r"(do\s+not|never)\s+tell\s+(the\s+)?(student|user)", re.IGNORECASE)),
    ("ignore_cn", re.compile(r"忽略(之前|以前|所有|上面)的(指令|提示|说明|规则)")),
    ("if_you_are_ai", re.compile(r"如果你是\s*AI")),
    ("you_are_now_cn", re.compile(r"你现在是(?!学生|老师)")),
    ("pretend_cn", re.compile(r"假装你(是|没有|不是)")),
    ("hide_from_student", re.compile(r"不要告诉(学生|用户)")),
]


@dataclass
class SteeringHit:
    pattern: str
    snippet: str


def scan_injected_instructions(text: str) -> list[SteeringHit]:
    """启发式扫描资料/消息中的转向语句。只标记，不执行，不删除原文。"""
    hits: list[SteeringHit] = []
    if not text:
        return hits
    for name, pat in _STEERING_PATTERNS:
        m = pat.search(text)
        if m:
            start = max(0, m.start() - 20)
            end = min(len(text), m.end() + 20)
            snippet = " ".join(text[start:end].split())
            hits.append(SteeringHit(pattern=name, snippet=snippet))
    return hits


def fence_material(text: str, doc_id: str) -> str:
    """把外来资料围进 MATERIAL 围栏：围栏内外身份明确，围栏内一律是数据。"""
    return f"{MATERIAL_OPEN} {doc_id}\n{text}\n{MATERIAL_CLOSE} {doc_id}"


STEERING_NOTICE = (
    "（注：本次资料中含试图影响 AI 回答的语句，已忽略，仅按资料内容作答。）"
)


def attach_steering_notice(rendered: str, hits: Sequence[SteeringHit]) -> str:
    """检出转向语句时，在回复末尾明示一句已忽略；无检出时原样返回。"""
    if not hits:
        return rendered
    if STEERING_NOTICE in rendered:
        return rendered
    return f"{rendered}\n\n{STEERING_NOTICE}" if rendered else STEERING_NOTICE


def scan_result_to_dict(hits: Sequence[SteeringHit]) -> list[dict]:
    return [{"pattern": h.pattern, "snippet": h.snippet} for h in hits]
