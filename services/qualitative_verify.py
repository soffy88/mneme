"""qualitative_verify — Layer4 编排：用真 LLM 跑 qualitative_verifier oskill 出裁决。

W2b 定性 verifier 接线。studio 学生提交"概念解释"(open 题) → 本服务按该 KC 的 rubric
用真 Qwen 判定各维度是否达标（含 evidence_spans 反幻觉锚定，见 oskill）→ QualitativeVerdict。
落库（gate.evidence + gate.qualitative_mastery + clear pending）由调用方走 tool_report_result。

3O 分层：
- qualitative_verifier 是 **oskill**（mneme-core，纯逻辑、同步、LLMCaller 也同步）。
- 本模块是 **服务层**编排：取 rubric/kp、构造真 LLM 适配器、在线程里跑同步 oskill。
- **graceful**：LLM 未配 / 无 rubric / rubric 非法 / LLM 调用失败 → 返回 None（不 raise），
  调用方据此退回 needs_qualitative（交外部 assess），学生提交永不因 verifier 崩。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from mneme_core.oprim.models import KpView, QualitativeVerdict, Rubric
from mneme_core.oskill.qualitative_verifier import qualitative_verifier

from services import gate_store
from services.providers.qwenvl_caller import QwenTextCaller

logger = logging.getLogger(__name__)


def _api_key() -> Optional[str]:
    # 与 _llm_generate_question 同源的 key（DASHSCOPE_API_KEY 生产已配、出题实测可用）；
    # 兼容 QWEN_API_KEY 命名。
    return os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY")


def _repair_spans(raw: str, explanation: str) -> str:
    """把 LLM 返回里每个 span 的 start/end 用 quote 在原文里 find 重算（关键修正）。

    实测真 LLM（含中文）**引文 quote 精确、但 start/end 字符偏移几乎必错**（模型不会按
    Python 码点计数），导致 oskill 的 `explanation[start:end]==quote` 回验全数失败、每维判否。
    这里以**可验证的 quote 文本**为锚：`explanation.find(quote)` 得到确定偏移，改写 start/end。
    - quote 非原文子串（真幻觉）→ find 返回 -1 → 丢弃该 span（该维随之无锚定 → 判否），
      反幻觉红线不削弱；且 oskill 仍会独立再回验一次（双保险）。
    - 解析失败 → 原样返回（oskill 的 _parse 容错为空）。
    """
    try:
        data = json.loads(raw)
        dims = data.get("dimensions", [])
    except (json.JSONDecodeError, AttributeError, TypeError):
        return raw
    if not isinstance(dims, list):
        return raw
    for d in dims:
        if not isinstance(d, dict):
            continue
        fixed = []
        for s in d.get("spans", []) or []:
            if not isinstance(s, dict) or "quote" not in s:
                continue
            quote = str(s["quote"])
            idx = explanation.find(quote)
            if idx < 0 or not quote:
                continue  # 幻觉引文：原文找不到 → 丢弃
            fixed.append({"start": idx, "end": idx + len(quote), "quote": quote})
        d["spans"] = fixed
    return json.dumps(data, ensure_ascii=False)


class _SyncQwenAdapter:
    """异步 QwenTextCaller → oskill 要的同步 LLMCaller：__call__(*, messages) -> str。

    在 asyncio.to_thread 的 worker 线程里被调用（该线程无运行中的 event loop），故用
    asyncio.run 起临时 loop 执行异步 HTTP。QwenTextCaller 每次自建 httpx client、无跨
    loop 共享资源，线程内新建 loop 安全。返回前用 _repair_spans 按 quote 重算偏移。
    """

    def __init__(self, caller: QwenTextCaller, explanation: str) -> None:
        self._caller = caller
        self._explanation = explanation

    def __call__(self, *, messages: list[dict]) -> str:
        out = asyncio.run(
            self._caller(
                messages=messages,
                max_tokens=1024,
                response_format="json",
                enable_thinking=False,  # 判分无需思维链：~50s → ~2s，同模型不降质
            )
        )
        return _repair_spans(str(out.get("content", "")), self._explanation)


def _kc_name(kc_id: str) -> str:
    """KC 展示名（喂给 verifier 的 prompt 上下文）；查不到回落 kc_id。"""
    try:
        from data.guangdong_math_kc import get_kc

        kc = get_kc(kc_id)
        name = getattr(kc, "name", None) if kc else None
        return str(name) if name else kc_id
    except Exception:
        return kc_id


async def run_qualitative_verifier(
    db: AsyncSession,
    *,
    kc_id: str,
    explanation: str,
    caller: Optional[QwenTextCaller] = None,
) -> Optional[QualitativeVerdict]:
    """跑真 verifier 得 QualitativeVerdict；不可用（无 key/rubric/rubric 非法/LLM 失败）→ None。

    caller 可注入（测试用假 caller）；缺省用真 Qwen（DASHSCOPE_API_KEY）。
    注意：rubric 在 async 上下文里先取好，oskill 在线程内运行且不碰 db（AsyncSession 非线程安全）。
    """
    if caller is None:
        key = _api_key()
        if not key:
            return None
        caller = QwenTextCaller(
            api_key=key, model=os.environ.get("QWEN_MODEL", "qwen-plus")
        )

    rubric_dict = await gate_store.get_rubric(db, kc_id)
    if not rubric_dict:
        return None
    try:
        rubric = Rubric.from_dict(rubric_dict)
    except Exception as e:  # 维度缺失 / 权重和≠1.0 等
        logger.warning("qualitative rubric 非法 kc=%s: %s", kc_id, e)
        return None

    kp = KpView(kc_id=kc_id, name=_kc_name(kc_id), gate_type="qualitative")
    adapter = _SyncQwenAdapter(caller, explanation)
    try:
        verdict = await asyncio.to_thread(
            qualitative_verifier, explanation, rubric=rubric, kp=kp, llm=adapter
        )
    except Exception as e:  # LLM 失败 / JSON 解析失败等 → 退回外部 assess
        logger.warning("qualitative_verifier 运行失败 kc=%s: %s", kc_id, e)
        return None
    return verdict
