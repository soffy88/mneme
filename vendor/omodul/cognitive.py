"""
认知持久化业务事务
==================
omodul/cognitive.py
"""

from __future__ import annotations
import os
from datetime import datetime, timezone
from typing import ClassVar, Optional, Any
from pathlib import Path
from uuid import UUID
from pydantic import BaseModel, Field

from omodul.base import BaseConfig, build_fingerprint, standard_return
from oskill.cognitive_state import cognitive_update, CognitiveUpdateInput
from oskill.fire_propagate import FirePrereq, fire_propagate
from obase.cognitive_store import BaseCognitiveStore
from oprim.fsrs_engine import fsrs_due_date, fsrs_retrievability
from oprim.due_compute import due_compute


def _fire_enabled_default() -> bool:
    """FIRe-lite 开关（M-H §4.8）。exp4 仿真未达接线门槛（压缩 4.7~6.0% < 10%，
    对抗世界保留率损失 4.8pp > 2pp），故**默认关**：FIRE_ENABLED=1 才开。"""
    return os.environ.get("FIRE_ENABLED", "0") == "1"


class InteractionConfig(BaseConfig):
    _omodul_name = "process_interaction_workflow"
    _omodul_version = "0.1.0"
    _fingerprint_fields = set()
    _enabled_pillars = {"decision_trail"}

    # FIRe-lite 前置信用回写（M-H §4.8）
    fire_enabled: bool = Field(default_factory=_fire_enabled_default)
    fire_kappa0: float = 0.5  # κ_p = κ0 · P(L)_p
    fire_tau: float = 0.3  # κ_p < τ 不回写


class InteractionInput(BaseModel):
    student_id: UUID
    kc_id: str
    is_correct: bool
    question_type: str = "solve"
    question_id: Optional[UUID] = None
    source: str = "paper"
    used_answer: bool = False
    struggled: bool = False
    effortless: bool = False
    is_interleaved: bool = False
    time_spent_seconds: Optional[int] = None
    difficulty: Optional[float] = None  # 题目难度 b∈[0,1]（IRT）；None 时不改变行为
    predicted_confidence: Optional[float] = (
        None  # JOL：作答前自评把握 ∈[0,1]（仅记录，不入算法）
    )
    predicted_r: Optional[float] = (
        None  # 保留探针：作答时 FSRS 预测可提取性 R（仅记录，不入算法）
    )
    now: Optional[datetime] = None
    min_review_interval_hours: float = (
        0.0  # 集中练习去抖阈值，透传 cognitive_update；默认 0 不改变行为
    )
    fsrs_parameters: tuple | None = None  # 个性化 FSRS 权重；None → 全局默认


class InteractionFindings(BaseModel):
    kc_id: str
    p_mastery: float
    long_term_mastery: float
    effective_mastery: float
    error_type: Optional[str]
    rating: str
    next_review_due: Optional[str]
    n_attempts: int


async def _fire_credit_writeback(
    config: InteractionConfig,
    input_data: InteractionInput,
    store: BaseCognitiveStore,
    now: datetime,
    trigger_event_id: Optional[UUID],
) -> list[dict]:
    """FIRe-lite（M-H §4.8）：对触发 KC 的 verified 前置只顺延 due 并追加
    source="fire_credit" 事件（只增不改）。前置的 BKT 状态与卡片 D/S/R 不动；
    从未练过（无卡）的前置跳过。返回已回写的信用列表（供 decision_trail）。"""
    prereq_ids = await store.get_verified_prerequisites(input_data.kc_id)
    if not prereq_ids:
        return []

    states = await store.get_all_states(input_data.student_id)
    prereqs: list[FirePrereq] = []
    for pid in prereq_ids:
        if pid == input_data.kc_id:
            continue  # 自环防御
        entry = states.get(pid)
        if entry is None:
            continue  # 前置从未练过 → 无调度可顺延
        state_p, card_p = entry
        prereqs.append(
            FirePrereq(kc_id=pid, p_mastery=state_p.current(), card_dict=card_p)
        )
    if not prereqs:
        return []

    outcomes = fire_propagate(
        trigger_kc_id=input_data.kc_id,
        prereqs=prereqs,
        now=now,
        kappa0=config.fire_kappa0,
        tau=config.fire_tau,
    )

    applied: list[dict] = []
    for oc in outcomes:
        if oc.new_due is None:
            continue
        state_p, card_p = states[oc.kc_id]
        new_card = {**card_p, "due": oc.new_due}  # 仅顺延 due，D/S/R 逐位不动
        await store.save(input_data.student_id, oc.kc_id, state_p, new_card)
        credit = {
            "trigger_kc_id": input_data.kc_id,
            "trigger_event_id": str(trigger_event_id) if trigger_event_id else None,
            "kappa": oc.kappa,
            "due_before": oc.due_before,
            "due_after": oc.new_due,
        }
        await store.append_event(
            input_data.student_id,
            oc.kc_id,
            {
                "question_id": input_data.question_id,
                "source": "fire_credit",
                "is_correct": True,  # 记账事件：触发交互答对（隐式检索成功）
                "fsrs_rating": None,
                "occurred_at": now,
                "fire_meta": credit,
            },
        )
        applied.append({"kc_id": oc.kc_id, **credit})
    return applied


async def process_interaction_workflow(
    config: InteractionConfig,
    input_data: InteractionInput,
    store: BaseCognitiveStore,
    output_dir: Optional[Path] = None,
) -> dict:
    """处理一次认知交互并落库。

    DoD 1.3/1.4: 落 kc_mastery + 追加 interaction_events（只增不改），严守更新顺序红线。
    支持按照题型扩展。
    """
    now = input_data.now or datetime.now(timezone.utc)

    # 1. 获取当前状态 (传题型以获取正确的先验)
    state, card_dict = await store.get_or_create(
        input_data.student_id, input_data.kc_id, input_data.question_type
    )

    # 2. 调用认知更新算法 (oskill)
    update_input = CognitiveUpdateInput(
        state=state,
        card_dict=card_dict,
        is_correct=input_data.is_correct,
        used_answer=input_data.used_answer,
        struggled=input_data.struggled,
        effortless=input_data.effortless,
        is_interleaved=input_data.is_interleaved,
        difficulty=input_data.difficulty,
        min_review_interval_hours=input_data.min_review_interval_hours,
        fsrs_parameters=input_data.fsrs_parameters,
        now=now,
    )
    result = cognitive_update(input=update_input)

    # 3. 落库：更新 kc_mastery
    await store.save(
        input_data.student_id, input_data.kc_id, result.state, result.card_dict
    )

    # 4. 落库：追加 interaction_events
    days_since_last = None
    if state.last_interaction_ts:
        days_since_last = (
            now - datetime.fromtimestamp(state.last_interaction_ts, timezone.utc)
        ).total_seconds() / 86400.0

    event_data = {
        "question_id": input_data.question_id,
        "source": input_data.source,
        "is_correct": input_data.is_correct,
        "fsrs_rating": result.rating_val,
        "time_spent_seconds": input_data.time_spent_seconds,
        "days_since_last": days_since_last,
        "is_interleaved": input_data.is_interleaved,
        "item_difficulty": input_data.difficulty,
        "predicted_confidence": input_data.predicted_confidence,
        "predicted_r": input_data.predicted_r,
        "occurred_at": now,
    }
    trigger_event_id = await store.append_event(
        input_data.student_id, input_data.kc_id, event_data
    )

    # 4b. FIRe-lite 前置信用回写（M-H §4.8）：主更新链完成落库之后的独立后续步骤。
    #     触发条件：答对 + 真实检索（过 20h 去抖，schedule_advanced）+ 非 fire_credit
    #     自身产生（不级联；probe 是真实检索，可触发）。仅顺延 verified 前置的 due，
    #     不改 D/S/R、不动 BKT。
    fire_credits: list[dict] = []
    if (
        config.fire_enabled
        and input_data.is_correct
        and input_data.source != "fire_credit"
        and result.schedule_advanced
    ):
        fire_credits = await _fire_credit_writeback(
            config, input_data, store, now, trigger_event_id
        )

    # 5. 组装结果
    findings = InteractionFindings(
        kc_id=input_data.kc_id,
        p_mastery=round(result.state.current(), 4),
        long_term_mastery=round(
            result.state.long_term_mastery or result.state.current(), 4
        ),
        effective_mastery=round(result.effective_mastery, 4),
        error_type=result.error_type,
        rating=result.rating,
        next_review_due=fsrs_due_date(card_dict=result.card_dict),
        n_attempts=result.state.n_attempts,
    )

    trail = [
        {
            "step": "get_state",
            "kc_id": input_data.kc_id,
            "question_type": input_data.question_type,
        },
        {"step": "cognitive_update", "result": findings.model_dump()},
        {"step": "save_state"},
        {"step": "append_event"},
    ]
    if fire_credits:
        trail.append({"step": "fire_credit", "credits": fire_credits})

    return standard_return(
        findings=findings,
        status="completed",
        trail=trail if "decision_trail" in config._enabled_pillars else None,
    )


async def mastery_overview_workflow(
    store: BaseCognitiveStore, student_id: UUID, now: Optional[datetime] = None
):
    """获取掌握度总览（业务逻辑）。"""
    now = now or datetime.now(timezone.utc)
    states_map = await store.get_all_states(student_id)
    out = []
    for kc_id, (state, card) in states_map.items():
        R = fsrs_retrievability(card_dict=card, now=now)
        long_term = state.long_term_mastery or state.current()
        out.append(
            {
                "kc_id": kc_id,
                "long_term_mastery": round(long_term, 4),
                # 红线：effective = long_term × R（与 process 路径同口径，非 current()×R）
                "effective_mastery": round(long_term * R, 4),
                "n_attempts": state.n_attempts,
            }
        )
    return sorted(out, key=lambda x: x["effective_mastery"])


async def review_queue_workflow(
    store: BaseCognitiveStore, student_id: UUID, now: Optional[datetime] = None
):
    """今日到期复习池（业务逻辑）。"""
    now = now or datetime.now(timezone.utc)
    states_map = await store.get_all_states(student_id)
    queue = []
    for kc_id, (state, card) in states_map.items():
        # 单源到期判定（item 13）：统一用 due_compute，避免与其它路径语义分叉。
        if due_compute(card_dict=card, now=now):
            queue.append({"kc_id": kc_id, "due": fsrs_due_date(card_dict=card)})
    return queue
