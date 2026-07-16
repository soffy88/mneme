"""qualitative_verifier — rubric-anchored LLM verification of a self-explanation.

SPEC §3 契约。纯逻辑 + 一次**注入**的 LLM 调用；**不 import 任何 provider SDK**——
模型经 `LLMCaller` Protocol 注入（obase.provider_registry 侧在服务层/装配层绑定；
W1 测试注入脚本化伪 caller，真 provider 绑定留 W2）。

内部五步（组合形态，D3.2 要求列出）：
  1. rubric 解析 + 权重校验（维度权重和须为 1.0，否则 ValueError）；
  2. prompt 构建（把各维 criterion + 学生原文组织成 messages）；
  3. 注入的 llm 调用（唯一外部依赖，经 Protocol 注入）；
  4. 裁决结构化解析（容错：畸形输出不崩，退化为“无一维锚定”）；
  5. evidence_spans 锚定 + **幻觉回验**：LLM 声称的每个 span 必满足
     ``explanation[start:end] == quote``，否则该锚定无效、该维判否。

整体 passed = **各维全过**（每维须“LLM 判过” ∧ “至少一个 span 通过回验”）；
score = 已过维度的权重和。任一维无法锚定 → 该维 False → 整体 False（§3“无法锚定→False”）。
"""

from __future__ import annotations

import json
from typing import Optional, Protocol

from mneme_core.oprim.models import (
    DimensionVerdict,
    EvidenceSpan,
    KpView,
    QualitativeVerdict,
    Rubric,
)

WEIGHT_TOLERANCE = 1e-6


class LLMCaller(Protocol):
    """注入式 LLM 调用契约。返回模型原始补全（期望为 JSON 文本）。

    W1 测试注入脚本化伪实现（固定 messages → 固定 JSON）；真 provider（可能异步）
    的绑定在装配层完成，本元素不感知 provider。
    """

    def __call__(self, *, messages: list[dict]) -> str: ...


def _build_messages(explanation: str, rubric: Rubric, kp: KpView) -> list[dict]:
    """构建判分 messages（步骤 2）。"""
    dims_desc = "\n".join(
        f"- {d.name}（权重 {d.weight}）：{d.criterion}" for d in rubric.dimensions
    )
    system = (
        "你是严格的学习判官。只依据学生自我解释的原文判断每个维度是否达标，"
        "并给出原文中的引证区间。严禁臆测原文中不存在的内容。"
    )
    user = (
        f"知识点：{kp.name}\n"
        f"评分维度：\n{dims_desc}\n\n"
        f"学生自我解释（原文）：\n{explanation}\n\n"
        "对每个维度输出严格 JSON，形如："
        '{"dimensions":[{"name":"<维度名>","passed":true,'
        '"spans":[{"start":<int>,"end":<int>,"quote":"<原文子串>"}]}]}。'
        "其中 start/end 是引文在原文中的字符区间，quote 必须精确等于原文该区间的子串。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _parse(raw: str) -> dict[str, dict]:
    """容错解析（步骤 4）：LLM 原始输出 → {维度名: {passed, spans}}。

    不可解析 / 结构异常 → 返回空 dict（不抛异常），下游据此判每维未锚定。
    """
    try:
        data = json.loads(raw)
        dims = data.get("dimensions", [])
    except (json.JSONDecodeError, AttributeError, TypeError):
        return {}
    if not isinstance(dims, list):
        return {}
    out: dict[str, dict] = {}
    for d in dims:
        if not isinstance(d, dict) or "name" not in d:
            continue
        spans = d.get("spans", [])
        out[str(d["name"])] = {
            "passed": bool(d.get("passed", False)),
            "spans": spans if isinstance(spans, list) else [],
        }
    return out


def _anchor_spans(
    explanation: str, raw_spans: list, dim_name: str
) -> Optional[list[EvidenceSpan]]:
    """锚定 + 幻觉回验（步骤 5）。

    对每个声称的 span 校验 ``0<=start<end<=len`` 且 ``explanation[start:end]==quote``。
    任一不符（含区间越界 / 引文与区间文本不一致）→ 返回 None（该维作废，防幻觉引用）。
    空 spans → None（passed 却无引证 = 无法锚定）。全部通过 → EvidenceSpan 列表。
    """
    if not raw_spans:
        return None
    n = len(explanation)
    anchored: list[EvidenceSpan] = []
    for s in raw_spans:
        if not isinstance(s, dict):
            return None
        try:
            start = int(s["start"])
            end = int(s["end"])
            quote = str(s["quote"])
        except (KeyError, TypeError, ValueError):
            return None
        if not (0 <= start < end <= n):
            return None
        if explanation[start:end] != quote:
            return None  # 幻觉引用：声称引文与原文区间不符
        anchored.append(
            EvidenceSpan(dimension=dim_name, start=start, end=end, quote=quote)
        )
    return anchored


def qualitative_verifier(
    explanation: str,
    *,
    rubric: Rubric,
    kp: KpView,
    llm: LLMCaller,
) -> QualitativeVerdict:
    """按 rubric 对学生自我解释做 LLM 判分 + evidence_spans 锚定（SPEC §3）。

    Args:
        explanation: 学生自我解释原文。
        rubric: 该 KC 的评分 rubric（各维 name/criterion/weight，权重和须为 1.0）。
        kp: 知识点视图（name/gate_type）。
        llm: 注入的 LLM 调用（Protocol；不 import provider SDK）。

    Returns:
        QualitativeVerdict：整体 passed（各维全过）、score（过维权重和）、逐维裁决、
        全部已回验的 evidence_spans。

    Raises:
        ValueError: rubric 无维度或权重和 ≠ 1.0。
    """
    # 步骤 1：rubric 权重校验
    total_w = sum(d.weight for d in rubric.dimensions)
    if not rubric.dimensions or abs(total_w - 1.0) > WEIGHT_TOLERANCE:
        raise ValueError(
            f"rubric 维度权重和必须为 1.0（{rubric.kc_id} 实际 {total_w}）"
        )

    # 步骤 2–3：构建 prompt 并调用注入的 LLM
    messages = _build_messages(explanation, rubric, kp)
    raw = llm(messages=messages)

    # 步骤 4：容错解析
    parsed = _parse(raw)

    # 步骤 5：逐维锚定 + 回验
    dim_verdicts: list[DimensionVerdict] = []
    all_spans: list[EvidenceSpan] = []
    score = 0.0
    for d in rubric.dimensions:
        entry = parsed.get(d.name)
        if entry is None or not entry["passed"]:
            dim_verdicts.append(
                DimensionVerdict(
                    name=d.name, passed=False, reason="LLM 判为未达标或缺该维"
                )
            )
            continue
        anchored = _anchor_spans(explanation, entry["spans"], d.name)
        if anchored is None:
            dim_verdicts.append(
                DimensionVerdict(
                    name=d.name,
                    passed=False,
                    reason="引证无法锚定 / 回验失败（防幻觉）",
                )
            )
            continue
        dim_verdicts.append(
            DimensionVerdict(name=d.name, passed=True, spans=tuple(anchored))
        )
        all_spans.extend(anchored)
        score += d.weight

    passed = all(dv.passed for dv in dim_verdicts)
    return QualitativeVerdict(
        kc_id=rubric.kc_id,
        passed=passed,
        score=round(score, 6),
        dimensions=tuple(dim_verdicts),
        evidence_spans=tuple(all_spans),
    )
