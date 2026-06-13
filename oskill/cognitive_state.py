"""
认知状态协调器（StateStore 抽象 + 统一 KT/FSRS 更新）
=====================================================
3O 范式：oskill/cognitive_state.py

职责：
1. 定义 BaseCognitiveStore 协议（抽象存储）。
2. 实现 InMemoryStore（测试用）与 PgStore（生产用）。
3. 协调 oprim.bkt 与 oprim.fsrs_engine 完成统一更新。
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable, Dict, List
from uuid import UUID
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, insert

from oprim.types import KCState
from oprim.bkt import bkt_update, classify_error, new_state_from_prior
from oprim.fsrs_engine import (
    fsrs_retrievability, 
    fsrs_review, 
    fsrs_map_rating, 
    fsrs_new_card,
    fsrs_due_date
)
from data.guangdong_math_kc import get_bkt_prior
from services.models import KCMastery, InteractionEvent

# ── 存储协议 ──────────────────────────────────────────────────────────────────

@runtime_checkable
class BaseCognitiveStore(Protocol):
    """认知状态存储协议。支持 BKT 状态、FSRS 卡片以及事件追加。"""
    
    async def get_or_create(self, student_id: UUID, kc_id: str) -> tuple[KCState, dict]:
        """获取或创建认知状态和 FSRS 卡片。"""
        ...

    async def get_all_states(self, student_id: UUID) -> Dict[str, tuple[KCState, dict]]:
        """获取学生所有知识点的认知状态。"""
        ...

    async def save(self, student_id: UUID, kc_id: str, state: KCState, card_dict: dict) -> None:
        """保存更新后的状态。"""
        ...

    async def append_event(self, student_id: UUID, kc_id: str, event_data: dict) -> None:
        """追加交互事件（只增不改）。"""
        ...

# ── 内存存储（测试用） ─────────────────────────────────────────────────────────

class InMemoryStore:
    """内存版状态存储。"""
    def __init__(self):
        self._states: Dict[str, KCState] = {}
        self._cards: Dict[str, dict] = {}
        self._events: List[dict] = []

    def _key(self, student_id: UUID, kc_id: str) -> str:
        return f"{student_id}::{kc_id}"

    async def get_or_create(self, student_id: UUID, kc_id: str) -> tuple[KCState, dict]:
        k = self._key(student_id, kc_id)
        if k not in self._states:
            prior = get_bkt_prior(kc_id)
            self._states[k] = new_state_from_prior(kc_id=kc_id, prior=prior)
            self._cards[k] = fsrs_new_card()
        return self._states[k], self._cards[k]

    async def get_all_states(self, student_id: UUID) -> Dict[str, tuple[KCState, dict]]:
        prefix = f"{student_id}::"
        return {
            k[len(prefix):]: (self._states[k], self._cards[k])
            for k in self._states if k.startswith(prefix)
        }

    async def save(self, student_id: UUID, kc_id: str, state: KCState, card_dict: dict) -> None:
        k = self._key(student_id, kc_id)
        self._states[k] = state
        self._cards[k] = card_dict

    async def append_event(self, student_id: UUID, kc_id: str, event_data: dict) -> None:
        event = event_data.copy()
        event["student_id"] = student_id
        event["knowledge_point"] = kc_id
        if "occurred_at" not in event:
            event["occurred_at"] = datetime.now(timezone.utc)
        self._events.append(event)

# ── PgStore（生产用） ─────────────────────────────────────────────────────────

class PgStore:
    """PostgreSQL 状态存储。直接操作 kc_mastery 和 interaction_events 表。"""
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(self, student_id: UUID, kc_id: str) -> tuple[KCState, dict]:
        stmt = select(KCMastery).where(
            KCMastery.student_id == student_id,
            KCMastery.knowledge_point == kc_id
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()

        if row:
            return self._row_to_entry(row)
        else:
            prior = get_bkt_prior(kc_id)
            state = new_state_from_prior(kc_id=kc_id, prior=prior)
            card = fsrs_new_card()
            return state, card

    async def get_all_states(self, student_id: UUID) -> Dict[str, tuple[KCState, dict]]:
        stmt = select(KCMastery).where(KCMastery.student_id == student_id)
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        return {row.knowledge_point: self._row_to_entry(row) for row in rows}

    def _row_to_entry(self, row: KCMastery) -> tuple[KCState, dict]:
        state = KCState(
            kc_id=row.knowledge_point,
            p_init=row.p_init,
            p_transit=row.p_transit,
            p_guess=row.p_guess,
            p_slip=row.p_slip,
            p_mastery=row.p_mastery,
            long_term_mastery=row.long_term_mastery,
            last_interaction_ts=row.last_interaction_at.timestamp() if row.last_interaction_at else None,
            n_attempts=row.n_attempts or 0,
            p_recognition=row.p_recognition,
            p_recognition_init=row.p_recognition_init or 0.20
        )
        card = row.fsrs_card_json or fsrs_new_card()
        return state, card

    async def save(self, student_id: UUID, kc_id: str, state: KCState, card_dict: dict) -> None:
        # 尝试更新
        last_interaction_at = datetime.fromtimestamp(state.last_interaction_ts, timezone.utc) if state.last_interaction_ts else datetime.now(timezone.utc)
        stmt = update(KCMastery).where(
            KCMastery.student_id == student_id,
            KCMastery.knowledge_point == kc_id
        ).values(
            p_mastery=state.p_mastery,
            long_term_mastery=state.long_term_mastery,
            p_recognition=state.p_recognition,
            fsrs_card_json=card_dict,
            last_interaction_at=last_interaction_at,
            n_attempts=state.n_attempts,
            updated_at=datetime.now(timezone.utc)
        )
        result = await self.session.execute(stmt)
        
        if result.rowcount == 0:
            # 不存在则插入
            ins_stmt = insert(KCMastery).values(
                student_id=student_id,
                knowledge_point=kc_id,
                p_init=state.p_init,
                p_transit=state.p_transit,
                p_guess=state.p_guess,
                p_slip=state.p_slip,
                p_mastery=state.p_mastery,
                long_term_mastery=state.long_term_mastery,
                p_recognition=state.p_recognition,
                p_recognition_init=state.p_recognition_init,
                fsrs_card_json=card_dict,
                last_interaction_at=last_interaction_at,
                n_attempts=state.n_attempts
            )
            await self.session.execute(ins_stmt)

    async def append_event(self, student_id: UUID, kc_id: str, event_data: dict) -> None:
        ins_stmt = insert(InteractionEvent).values(
            student_id=student_id,
            knowledge_point=kc_id,
            question_id=event_data.get("question_id"),
            source=event_data.get("source"),
            is_correct=event_data.get("is_correct"),
            fsrs_rating=event_data.get("fsrs_rating"),
            time_spent_seconds=event_data.get("time_spent_seconds"),
            days_since_last=event_data.get("days_since_last"),
            is_interleaved=event_data.get("is_interleaved", False),
            occurred_at=event_data.get("occurred_at", datetime.now(timezone.utc))
        )
        await self.session.execute(ins_stmt)

# ── 统一更新逻辑 ──────────────────────────────────────────────────────────────

class CognitiveUpdateInput(BaseModel):
    state: KCState
    card_dict: dict
    is_correct: bool
    used_answer: bool = False
    struggled: bool = False
    effortless: bool = False
    is_interleaved: bool = False
    now: datetime | None = None

class CognitiveUpdateResult(BaseModel):
    state: KCState
    card_dict: dict
    error_type: str | None
    rating: str
    rating_val: int
    effective_mastery: float

def cognitive_update(*, input: CognitiveUpdateInput) -> CognitiveUpdateResult:
    """BKT + FSRS 统一更新算法（纯函数）。"""
    now = input.now or datetime.now(timezone.utc)
    
    # 1. 算 R (遗忘因子)
    R = fsrs_retrievability(card_dict=input.card_dict, now=now)
    
    # 2. BKT 更新 (forgetting-aware)
    bkt_update(state=input.state, is_correct=input.is_correct, retrievability=R)
    
    # 3. 错误分类
    error_type = None
    if not input.is_correct:
        error_type = classify_error(state=input.state)
        
    # 4. FSRS 更新
    rating = fsrs_map_rating(
        is_correct=input.is_correct, 
        used_answer=input.used_answer,
        struggled=input.struggled, 
        effortless=input.effortless
    )
    new_card = fsrs_review(card_dict=input.card_dict, rating=rating, now=now)
    
    # TODO: 5. Recognition 更新 (等 12.1 实现)
    
    input.state.last_interaction_ts = now.timestamp()
    
    eff = (input.state.long_term_mastery or input.state.current()) * R
    
    return CognitiveUpdateResult(
        state=input.state,
        card_dict=new_card,
        error_type=error_type,
        rating=rating.name,
        rating_val=rating.value,
        effective_mastery=eff
    )

async def process_interaction(
    store: BaseCognitiveStore,
    student_id: UUID,
    kc_id: str,
    is_correct: bool,
    *,
    question_id: UUID | None = None,
    source: str = "paper",
    used_answer: bool = False,
    struggled: bool = False,
    effortless: bool = False,
    is_interleaved: bool = False,
    time_spent_seconds: int | None = None,
    now: datetime | None = None,
) -> dict:
    """
    高层业务函数：从 store 取状态 -> 计算 -> 写回 store -> 追加事件。
    """
    now = now or datetime.now(timezone.utc)
    state, card_dict = await store.get_or_create(student_id, kc_id)
    
    update_input = CognitiveUpdateInput(
        state=state,
        card_dict=card_dict,
        is_correct=is_correct,
        used_answer=used_answer,
        struggled=struggled,
        effortless=effortless,
        is_interleaved=is_interleaved,
        now=now
    )
    
    result = cognitive_update(input=update_input)
    
    # 写回状态
    await store.save(student_id, kc_id, result.state, result.card_dict)
    
    # 追加事件
    days_since_last = None
    if state.last_interaction_ts:
        days_since_last = (now - datetime.fromtimestamp(state.last_interaction_ts, timezone.utc)).total_seconds() / 86400.0
        
    event_data = {
        "question_id": question_id,
        "source": source,
        "is_correct": is_correct,
        "fsrs_rating": result.rating_val,
        "time_spent_seconds": time_spent_seconds,
        "days_since_last": days_since_last,
        "is_interleaved": is_interleaved,
        "occurred_at": now
    }
    await store.append_event(student_id, kc_id, event_data)
    
    return {
        "kc_id": kc_id,
        "p_mastery": round(result.state.current(), 4),
        "long_term_mastery": round(result.state.long_term_mastery or result.state.current(), 4),
        "effective_mastery": round(result.effective_mastery, 4),
        "error_type": result.error_type,
        "rating": result.rating,
        "next_review_due": fsrs_due_date(card_dict=result.card_dict),
        "n_attempts": result.state.n_attempts,
    }

async def mastery_overview(store: BaseCognitiveStore, student_id: UUID, now: datetime | None = None):
    """获取所有已记录 KC 的掌握度总览。"""
    now = now or datetime.now(timezone.utc)
    states_map = await store.get_all_states(student_id)
    out = []
    for kc_id, (state, card) in states_map.items():
        R = fsrs_retrievability(card_dict=card, now=now)
        out.append({
            "kc_id": kc_id,
            "long_term_mastery": round(state.long_term_mastery or state.current(), 4),
            "effective_mastery": round(state.current() * R, 4),
            "n_attempts": state.n_attempts,
        })
    return sorted(out, key=lambda x: x["effective_mastery"])

async def review_queue(store: BaseCognitiveStore, student_id: UUID, now: datetime | None = None):
    """今日到期复习池：FSRS due <= now 的卡片。"""
    now = now or datetime.now(timezone.utc)
    states_map = await store.get_all_states(student_id)
    queue = []
    for kc_id, (state, card) in states_map.items():
        due_iso = fsrs_due_date(card_dict=card)
        if due_iso and datetime.fromisoformat(due_iso) <= now:
            queue.append({"kc_id": kc_id, "due": due_iso})
    return queue

__version__ = "0.2.1"
__manifest__ = {
    "version": __version__,
    "updated_at": "2026-06-13",
    "elements": [
        {"name": "BaseCognitiveStore", "layer": "oskill", "summary": "认知状态存储协议"},
        {"name": "InMemoryStore", "layer": "oskill", "summary": "内存版认知存储"},
        {"name": "PgStore", "layer": "oskill", "summary": "PostgreSQL 认知存储"},
        {"name": "cognitive_update", "layer": "oskill", "summary": "BKT+FSRS 统一更新算法"},
        {"name": "process_interaction", "layer": "oskill", "summary": "处理交互事件并持久化"},
        {"name": "mastery_overview", "layer": "oskill", "summary": "获取所有已记录 KC 的掌握度总览"},
        {"name": "review_queue", "layer": "oskill", "summary": "今日到期复习池"},
    ]
}
