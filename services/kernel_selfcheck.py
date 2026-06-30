"""3O 内核契约自检：防"内核仓静默回退"。

背景：oprim/oskill/omodul 是独立 git 仓，曾发生 omodul 被切回 main、丢掉
fsrs_parameters/conversation_history 等字段——pydantic 默默忽略多余 kwarg，
于是 去抖/个性化/苏格拉底续接 等功能静默失效、测试还过。

本模块声明 mneme 依赖的内核契约（字段/入参），缺失即可被 CI 测试 + 启动日志快速发现。
"""
from __future__ import annotations

import inspect


def check_kernel_contract() -> list[str]:
    """返回缺失的内核能力清单（空=契约完整）。不抛异常，便于启动期软告警。"""
    missing: list[str] = []

    def need_fields(label, model, fields):
        try:
            present = set(getattr(model, "model_fields", {}).keys())
            for f in fields:
                if f not in present:
                    missing.append(f"{label}.{f}")
        except Exception as e:  # noqa: BLE001
            missing.append(f"{label}: {e}")

    try:
        from omodul.cognitive import InteractionInput
        need_fields("omodul.InteractionInput", InteractionInput,
                    ("fsrs_parameters", "min_review_interval_hours"))
    except Exception as e:  # noqa: BLE001
        missing.append(f"import omodul.cognitive.InteractionInput: {e}")

    try:
        from oskill.cognitive_state import CognitiveUpdateInput
        need_fields("oskill.CognitiveUpdateInput", CognitiveUpdateInput,
                    ("fsrs_parameters", "min_review_interval_hours"))
    except Exception as e:  # noqa: BLE001
        missing.append(f"import oskill.cognitive_state.CognitiveUpdateInput: {e}")

    try:
        from omodul.socratic_session_workflow import SocraticInput
        need_fields("omodul.SocraticInput", SocraticInput, ("conversation_history",))
    except Exception as e:  # noqa: BLE001
        missing.append(f"import omodul.socratic_session_workflow.SocraticInput: {e}")

    try:
        from oprim.fsrs_engine import fsrs_retrievability, fsrs_review
        for fn in (fsrs_review, fsrs_retrievability):
            if "parameters" not in inspect.signature(fn).parameters:
                missing.append(f"oprim.fsrs_engine.{fn.__name__}.parameters")
    except Exception as e:  # noqa: BLE001
        missing.append(f"oprim.fsrs_engine: {e}")

    try:
        from oprim import due_compute  # noqa: F401
    except Exception as e:  # noqa: BLE001
        missing.append(f"oprim.due_compute: {e}")

    return missing
