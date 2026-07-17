"""services.qualitative_verify — 定性 verifier 接线（真 LLM 编排）单测。

用**注入的假 caller** + monkeypatch 的 rubric，全程不碰真 Qwen、不碰 DB：
- 验证 async→sync 适配器 + oskill 在线程内跑通、evidence 锚定生效；
- 验证 graceful：无 rubric / rubric 非法 / LLM 失败 → None（调用方退回 needs_qualitative）。
"""

from __future__ import annotations

import json

import pytest

from services import qualitative_verify

EXPLANATION = "函数是两个非空数集间每个x唯一对应一个y的对应关系"
RUBRIC = {
    "kc_id": "test-kc-q",
    "author": "t",
    "dimensions": [{"name": "对应关系", "criterion": "说明唯一对应", "weight": 1.0}],
}


class FakeCaller:
    """假 QwenTextCaller：异步、返回 {'content': <预置 JSON>}。"""

    def __init__(self, content: str) -> None:
        self._content = content

    async def __call__(self, *, messages, **kw):
        return {"content": self._content}


def _pass_json() -> str:
    return json.dumps(
        {
            "dimensions": [
                {
                    "name": "对应关系",
                    "passed": True,
                    "spans": [
                        {"start": 0, "end": len(EXPLANATION), "quote": EXPLANATION}
                    ],
                }
            ]
        }
    )


@pytest.fixture
def _rubric(monkeypatch):
    async def fake_get_rubric(db, kc_id):
        return RUBRIC

    monkeypatch.setattr(qualitative_verify.gate_store, "get_rubric", fake_get_rubric)


@pytest.mark.asyncio
async def test_verifier_pass(_rubric):
    v = await qualitative_verify.run_qualitative_verifier(
        None,
        kc_id="test-kc-q",
        explanation=EXPLANATION,
        caller=FakeCaller(_pass_json()),
    )
    assert v is not None
    assert v.passed is True
    assert v.score == 1.0
    assert len(v.evidence_spans) == 1


@pytest.mark.asyncio
async def test_verifier_hallucinated_span_fails(_rubric):
    # 声称的 quote 与原文区间不符 → 锚定失败 → 该维 False → 整体 False（防幻觉红线）
    bad = json.dumps(
        {
            "dimensions": [
                {
                    "name": "对应关系",
                    "passed": True,
                    "spans": [{"start": 0, "end": 5, "quote": "完全不同的引文"}],
                }
            ]
        }
    )
    v = await qualitative_verify.run_qualitative_verifier(
        None, kc_id="test-kc-q", explanation=EXPLANATION, caller=FakeCaller(bad)
    )
    assert v is not None
    assert v.passed is False


@pytest.mark.asyncio
async def test_verifier_no_rubric_returns_none(monkeypatch):
    async def no_rubric(db, kc_id):
        return None

    monkeypatch.setattr(qualitative_verify.gate_store, "get_rubric", no_rubric)
    v = await qualitative_verify.run_qualitative_verifier(
        None, kc_id="x", explanation="e", caller=FakeCaller("{}")
    )
    assert v is None


@pytest.mark.asyncio
async def test_verifier_bad_rubric_weights_returns_none(monkeypatch):
    # 权重和≠1.0 → oskill raise ValueError → 服务层 graceful 返回 None
    bad_rubric = {
        "kc_id": "test-kc-q",
        "author": "t",
        "dimensions": [{"name": "d", "criterion": "c", "weight": 0.5}],
    }

    async def fake(db, kc_id):
        return bad_rubric

    monkeypatch.setattr(qualitative_verify.gate_store, "get_rubric", fake)
    v = await qualitative_verify.run_qualitative_verifier(
        None,
        kc_id="test-kc-q",
        explanation=EXPLANATION,
        caller=FakeCaller(_pass_json()),
    )
    assert v is None


@pytest.mark.asyncio
async def test_verifier_llm_error_returns_none(_rubric):
    class Boom:
        async def __call__(self, *, messages, **kw):
            raise RuntimeError("llm down")

    v = await qualitative_verify.run_qualitative_verifier(
        None, kc_id="test-kc-q", explanation=EXPLANATION, caller=Boom()
    )
    assert v is None
