"""实证验证 harness：用真实 interaction_events 量化 KT/FSRS 的预测力（护城河实证）。

深度核查曾指"AUC 0.77 失实、实证虚"。本服务把累积的真实作答重放一遍内核模型，
逐次在**作答前**预测 P(答对)，与真实结果比，算 ROC-AUC / log-loss / 校准——
把"声称的个性化精度"变成"可复现的数字"。随用量增长定期跑，监控护城河是否真生效。

口径：重放计算纯只读（不改学习状态）。对每张 (student,kc) 卡片：用默认先验起 KCState，
按时间序对每次作答先 bkt_predict_correct（含 FSRS 可提取性 R 衰减），记录 (pred, 真值)，
再 bkt_update + fsrs_review 推进状态。AUC>0.5 即优于随机；接近 0.77 才算护城河兑现。
唯一写操作：全体评估末尾落一行 evaluation_runs 供历史查询（T.1）。
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from collections.abc import Callable, Iterable
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from obase.cognitive_types import new_state_from_prior
from oprim import bkt_predict_correct, bkt_update
from oprim.fsrs_engine import fsrs_new_card, fsrs_retrievability, fsrs_review
from services.models import EvaluationRun, InteractionEvent, InteractionSource
from services.shadow_evaluation import (
    ShadowEvaluationError,
    ShadowPrediction,
    validate_shadow_window,
)

try:
    from fsrs import Rating
except Exception:  # pragma: no cover
    Rating = None  # type: ignore

# 默认先验（无 KC 专属先验时）；AUC 衡量区分度，对先验选择较稳健。
_PRIOR = {"p_init": 0.3, "p_transit": 0.2, "p_guess": 0.2, "p_slip": 0.1}
_EPS = 1e-6


@dataclass(frozen=True, slots=True)
class ShadowReplayEvent:
    """Minimal event input for a deterministic kernel shadow replay."""

    event_id: UUID | None
    student_id: UUID | None
    knowledge_point: str
    occurred_at: datetime
    received_at: datetime | None
    is_correct: bool
    fsrs_rating: int | None
    item_difficulty: float | None


@dataclass(frozen=True, slots=True)
class ShadowPredictorEvent:
    """Current event view exposed to a candidate predictor (no actual result)."""

    event_id: UUID | None
    student_id: UUID | None
    knowledge_point: str
    occurred_at: datetime
    received_at: datetime | None
    fsrs_rating: int | None
    item_difficulty: float | None


CandidatePredictor = Callable[
    [tuple[ShadowReplayEvent, ...], ShadowPredictorEvent], float
]


def _group_shadow_replay_events(
    events: Iterable[ShadowReplayEvent],
    *,
    train_start: datetime,
    train_end: datetime,
    eval_start: datetime,
    eval_end: datetime,
    as_of: datetime,
) -> dict[tuple[UUID | None, str], list[ShadowReplayEvent]]:
    validate_shadow_window(
        train_start=train_start,
        train_end=train_end,
        eval_start=eval_start,
        eval_end=eval_end,
        as_of=as_of,
    )
    grouped: dict[tuple[UUID | None, str], list[ShadowReplayEvent]] = defaultdict(
        list
    )
    for event in events:
        if event.occurred_at.tzinfo is None or event.occurred_at.utcoffset() is None:
            raise ShadowEvaluationError("occurred_at must be timezone-aware")
        if event.received_at is not None:
            if (
                event.received_at.tzinfo is None
                or event.received_at.utcoffset() is None
            ):
                raise ShadowEvaluationError("received_at must be timezone-aware")
        in_train = train_start <= event.occurred_at < train_end
        in_eval = eval_start <= event.occurred_at < eval_end
        if not (in_train or in_eval):
            continue
        if event.occurred_at > as_of or (
            event.received_at is not None and event.received_at > as_of
        ):
            raise ShadowEvaluationError(
                "future occurred_at/received_at is not allowed by as_of"
            )
        grouped[(event.student_id, event.knowledge_point)].append(event)
    return grouped


def kernel_shadow_predictions(
    events: Iterable[ShadowReplayEvent],
    *,
    model_id: str,
    train_start: datetime,
    train_end: datetime,
    eval_start: datetime,
    eval_end: datetime,
    as_of: datetime,
) -> list[ShadowPrediction]:
    """Replay BKT+FSRS and emit only causal predictions in the eval window.

    Training-window events initialize each ``student × KC`` card.  Events in
    the gap between train and eval windows are deliberately ignored; each
    evaluation event is predicted before its own result updates the card.
    This function is pure and never mutates the database.
    """

    grouped = _group_shadow_replay_events(
        events,
        train_start=train_start,
        train_end=train_end,
        eval_start=eval_start,
        eval_end=eval_end,
        as_of=as_of,
    )

    predictions: list[ShadowPrediction] = []
    for (student_id, knowledge_point), sequence in grouped.items():
        sequence.sort(key=lambda item: (item.occurred_at, str(item.event_id or "")))
        state = new_state_from_prior(
            kc_id=f"shadow-{student_id or 'anonymous'}-{knowledge_point}",
            prior=dict(_PRIOR),
        )
        card = fsrs_new_card()
        for event in sequence:
            retrievability = fsrs_retrievability(
                card_dict=card, now=event.occurred_at
            )
            probability = min(
                1.0 - _EPS,
                max(
                    _EPS,
                    float(
                        bkt_predict_correct(
                            state=state,
                            retrievability=retrievability,
                            difficulty=event.item_difficulty,
                        )
                    ),
                ),
            )
            if eval_start <= event.occurred_at < eval_end:
                predictions.append(
                    ShadowPrediction(
                        model_id=model_id,
                        occurred_at=event.occurred_at,
                        probability=probability,
                        actual=event.is_correct,
                        student_id=student_id,
                        kc_id=knowledge_point,
                        received_at=event.received_at,
                        event_id=event.event_id,
                    )
                )
            bkt_update(
                state=state,
                is_correct=event.is_correct,
                retrievability=retrievability,
                difficulty=event.item_difficulty,
            )
            if Rating is not None and event.fsrs_rating is not None:
                try:
                    card = fsrs_review(
                        card_dict=card,
                        rating=Rating(int(event.fsrs_rating)),
                        now=event.occurred_at,
                    )
                except Exception:
                    pass
    predictions.sort(
        key=lambda item: (
            item.occurred_at,
            str(item.student_id or ""),
            item.kc_id or "",
            str(item.event_id or ""),
        )
    )
    return predictions


def candidate_shadow_predictions(
    events: Iterable[ShadowReplayEvent],
    *,
    model_id: str,
    predictor: CandidatePredictor,
    train_start: datetime,
    train_end: datetime,
    eval_start: datetime,
    eval_end: datetime,
    as_of: datetime,
) -> list[ShadowPrediction]:
    """Run a candidate predictor without exposing the current answer.

    The predictor receives an immutable tuple of already observed events and a
    current-event view that intentionally omits ``is_correct``.  Training and
    prior evaluation outcomes are available as history; the current outcome is
    appended only after the candidate prediction is returned.  This is the
    adapter contract for a future DKT/Hybrid KT challenger, not a model claim.
    """

    grouped = _group_shadow_replay_events(
        events,
        train_start=train_start,
        train_end=train_end,
        eval_start=eval_start,
        eval_end=eval_end,
        as_of=as_of,
    )
    predictions: list[ShadowPrediction] = []
    for (student_id, knowledge_point), sequence in grouped.items():
        sequence.sort(key=lambda item: (item.occurred_at, str(item.event_id or "")))
        history: list[ShadowReplayEvent] = []
        for event in sequence:
            current = ShadowPredictorEvent(
                event_id=event.event_id,
                student_id=event.student_id,
                knowledge_point=event.knowledge_point,
                occurred_at=event.occurred_at,
                received_at=event.received_at,
                fsrs_rating=event.fsrs_rating,
                item_difficulty=event.item_difficulty,
            )
            if eval_start <= event.occurred_at < eval_end:
                predictions.append(
                    ShadowPrediction(
                        model_id=model_id,
                        occurred_at=event.occurred_at,
                        probability=float(predictor(tuple(history), current)),
                        actual=event.is_correct,
                        student_id=student_id,
                        kc_id=knowledge_point,
                        received_at=event.received_at,
                        event_id=event.event_id,
                    )
                )
            history.append(event)
    predictions.sort(
        key=lambda item: (
            item.occurred_at,
            str(item.student_id or ""),
            item.kc_id or "",
            str(item.event_id or ""),
        )
    )
    return predictions


async def reconstruct_kernel_shadow_predictions(
    db: AsyncSession,
    *,
    model_id: str,
    train_start: datetime,
    train_end: datetime,
    eval_start: datetime,
    eval_end: datetime,
    as_of: datetime,
    student_id: UUID | None = None,
) -> list[ShadowPrediction]:
    """Read the event store and feed the pure kernel shadow replay.

    This is intentionally a read-only adapter.  It excludes FIRe accounting
    events and selects only the declared train/eval windows; the comparator or
    caller remains responsible for persisting a report if that is ever wanted.
    """

    window_filter = or_(
        and_(
            InteractionEvent.occurred_at >= train_start,
            InteractionEvent.occurred_at < train_end,
        ),
        and_(
            InteractionEvent.occurred_at >= eval_start,
            InteractionEvent.occurred_at < eval_end,
        ),
    )
    stmt = (
        select(
            InteractionEvent.id,
            InteractionEvent.student_id,
            InteractionEvent.knowledge_point,
            InteractionEvent.occurred_at,
            InteractionEvent.received_at,
            InteractionEvent.is_correct,
            InteractionEvent.fsrs_rating,
            InteractionEvent.item_difficulty,
        )
        .where(
            InteractionEvent.source != InteractionSource.fire_credit,
            InteractionEvent.knowledge_point.is_not(None),
            window_filter,
        )
        .order_by(InteractionEvent.occurred_at, InteractionEvent.id)
    )
    if student_id is not None:
        stmt = stmt.where(InteractionEvent.student_id == student_id)
    rows = (await db.execute(stmt)).all()
    events = [
        ShadowReplayEvent(
            event_id=event_id,
            student_id=row_student_id,
            knowledge_point=knowledge_point,
            occurred_at=occurred_at,
            received_at=received_at,
            is_correct=bool(is_correct),
            fsrs_rating=fsrs_rating,
            item_difficulty=item_difficulty,
        )
        for (
            event_id,
            row_student_id,
            knowledge_point,
            occurred_at,
            received_at,
            is_correct,
            fsrs_rating,
            item_difficulty,
        ) in rows
    ]
    return kernel_shadow_predictions(
        events,
        model_id=model_id,
        train_start=train_start,
        train_end=train_end,
        eval_start=eval_start,
        eval_end=eval_end,
        as_of=as_of,
    )


async def reconstruct_eval_logs(
    db: AsyncSession, student_id=None
) -> dict[tuple, list[tuple]]:
    """(student,kc) 卡片 → [(occurred_at, is_correct, fsrs_rating, item_difficulty), ...]（时间升序，≥2 次作答）。"""
    stmt = select(
        InteractionEvent.student_id,
        InteractionEvent.knowledge_point,
        InteractionEvent.occurred_at,
        InteractionEvent.is_correct,
        InteractionEvent.fsrs_rating,
        InteractionEvent.item_difficulty,
    ).where(
        # fire_credit（M-H §4.8）是调度记账事件、非真实作答，不进模型评估重放
        InteractionEvent.source != InteractionSource.fire_credit
    )
    if student_id is not None:
        stmt = stmt.where(InteractionEvent.student_id == student_id)
    rows = (await db.execute(stmt)).all()
    by_card: dict[tuple, list] = defaultdict(list)
    for sid, kc, ts, correct, rating, diff in rows:
        if kc is None:
            continue
        by_card[(sid, kc)].append((ts, bool(correct), rating, diff))
    out: dict[tuple, list[tuple]] = {}
    for card, seq in by_card.items():
        if len(seq) >= 2:
            seq.sort(key=lambda x: x[0])
            out[card] = seq
    return out


def compute_predictions(seqs) -> tuple[list[float], list[int]]:
    """重放内核模型，返回 (作答前预测概率, 真实是否答对)。"""
    preds: list[float] = []
    actuals: list[int] = []
    for seq in seqs:
        state = new_state_from_prior(kc_id="eval", prior=dict(_PRIOR))
        card = fsrs_new_card()
        for ts, correct, rating, diff in seq:
            r = fsrs_retrievability(card_dict=card, now=ts)
            p = bkt_predict_correct(state=state, retrievability=r, difficulty=diff)
            preds.append(min(1.0 - _EPS, max(_EPS, float(p))))
            actuals.append(1 if correct else 0)
            bkt_update(
                state=state, is_correct=correct, retrievability=r, difficulty=diff
            )
            if Rating is not None and rating is not None:
                try:
                    card = fsrs_review(
                        card_dict=card, rating=Rating(int(rating)), now=ts
                    )
                except Exception:
                    pass
    return preds, actuals


def predictive_metrics(seqs) -> dict:
    """AUC / log-loss / 基准正确率 / 样本量。两类不全则 AUC=None。"""
    preds, actuals = compute_predictions(seqs)
    n = len(preds)
    if n == 0:
        return {
            "n": 0,
            "auc": None,
            "logloss": None,
            "base_rate": None,
            "n_cards": len(seqs),
        }
    pos = sum(actuals)
    logloss = (
        -sum(
            y * math.log(p) + (1 - y) * math.log(1 - p) for p, y in zip(preds, actuals)
        )
        / n
    )
    auc = None
    if 0 < pos < n:
        from sklearn.metrics import roc_auc_score

        auc = float(roc_auc_score(actuals, preds))
    return {
        "n": n,
        "n_cards": len(seqs),
        "auc": auc,
        "logloss": round(logloss, 6),
        "base_rate": round(pos / n, 4),
    }


async def evaluate_model(db: AsyncSession, student_id=None) -> dict:
    """对（全体或某学生的）真实作答评估内核预测力。

    全体评估（student_id=None，即周任务口径）末尾把结果落一行 evaluation_runs
    （单独 commit，不影响只读重放）；样本不足跑不出 AUC 也落行记 n_events，
    便于看"真实数据积累进度"。评估计算本身仍是纯只读重放。
    """
    cards = await reconstruct_eval_logs(db, student_id=student_id)
    m = predictive_metrics(list(cards.values()))
    if m["auc"] is not None:
        m["verdict"] = (
            "护城河兑现(≈目标0.77)"
            if m["auc"] >= 0.75
            else "优于随机但未达目标"
            if m["auc"] >= 0.55
            else "接近随机(模型未体现预测力)"
        )
    if student_id is None:
        m["run_id"] = await _persist_run(db, cards, m)
    return m


async def _persist_run(
    db: AsyncSession, cards: dict[tuple, list[tuple]], m: dict
) -> str:
    """全体评估结果落一行 evaluation_runs（历史供 /v1/moat/evaluation-history 查询）。"""
    all_ts = [ts for seq in cards.values() for ts, *_ in seq]
    run_id = uuid.uuid4()
    db.add(
        EvaluationRun(
            id=run_id,
            window_start=min(all_ts) if all_ts else None,
            window_end=max(all_ts) if all_ts else None,
            n_events=m["n"],
            n_students=len({sid for sid, _ in cards}),
            auc=m["auc"],
            log_loss=m["logloss"],
            meta={
                "verdict": m.get("verdict"),
                "base_rate": m.get("base_rate"),
                "n_cards": m.get("n_cards"),
            },
        )
    )
    await db.commit()
    # 注：commit 后不读 ORM 对象属性——obase.db.SessionLocal 用默认 expire_on_commit=True，
    # 隐式惰性刷新在 AsyncSession 下不支持，会炸 MissingGreenlet（同 quiz_service 教训）。
    return str(run_id)
