"""
认知状态存储基础设施
====================
obase/cognitive_store.py
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable, Dict, List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, insert

import uuid as _uuid

from obase.cognitive_types import KCState, new_state_from_prior, fsrs_new_card
from obase.prior_provider import PriorProvider
from services.models import KCMastery, InteractionEvent


@runtime_checkable
class BaseCognitiveStore(Protocol):
    """认知状态存储协议。"""

    async def get_or_create(
        self, student_id: UUID, kc_id: str, question_type: str = "solve"
    ) -> tuple[KCState, dict]:
        """获取或创建认知状态和 FSRS 卡片。"""
        ...

    async def get_all_states(self, student_id: UUID) -> Dict[str, tuple[KCState, dict]]:
        """获取学生所有知识点的认知状态。"""
        ...

    async def save(
        self, student_id: UUID, kc_id: str, state: KCState, card_dict: dict
    ) -> None:
        """保存更新后的状态。"""
        ...

    async def append_event(
        self, student_id: UUID, kc_id: str, event_data: dict
    ) -> Optional[UUID]:
        """追加交互事件（只增不改），返回事件 id（供 FIRe 等溯源）。"""
        ...

    async def get_verified_prerequisites(self, kc_id: str) -> List[str]:
        """kc_id 的 verified 前置边（FIRe M-H §4.8）：仅当该 KU 自身 verified
        且前置 KU 存在并 verified 时返回——未过校验门的 LLM 前置边不参与，
        防幻觉边扩散信用。非 KU 知识点返回 []。"""
        ...


class InMemoryStore:
    """内存版状态存储（用于测试）。"""

    def __init__(self):
        self._states: Dict[str, KCState] = {}
        self._cards: Dict[str, dict] = {}
        self._events: List[dict] = []
        # 测试可直接注入：kc_id → verified 前置 kc_id 列表
        self._verified_prereqs: Dict[str, List[str]] = {}

    def _key(self, student_id: UUID, kc_id: str) -> str:
        return f"{student_id}::{kc_id}"

    async def get_or_create(
        self, student_id: UUID, kc_id: str, question_type: str = "solve"
    ) -> tuple[KCState, dict]:
        k = self._key(student_id, kc_id)
        if k not in self._states:
            # 优先使用 PriorProvider，如果它已经预热 (例如在测试中或应用启动时)
            if PriorProvider._is_warmed:
                prior = await PriorProvider.get_prior(None, kc_id, question_type)
            else:
                # 兼容性 Fallback
                from data.guangdong_math_kc import get_bkt_prior

                prior = get_bkt_prior(kc_id)

            self._states[k] = new_state_from_prior(kc_id=kc_id, prior=prior)
            self._cards[k] = fsrs_new_card()
        return self._states[k], self._cards[k]

    async def get_all_states(self, student_id: UUID) -> Dict[str, tuple[KCState, dict]]:
        prefix = f"{student_id}::"
        return {
            k[len(prefix) :]: (self._states[k], self._cards[k])
            for k in self._states
            if k.startswith(prefix)
        }

    async def save(
        self, student_id: UUID, kc_id: str, state: KCState, card_dict: dict
    ) -> None:
        k = self._key(student_id, kc_id)
        self._states[k] = state
        self._cards[k] = card_dict

    async def append_event(
        self, student_id: UUID, kc_id: str, event_data: dict
    ) -> Optional[UUID]:
        event = event_data.copy()
        event["id"] = _uuid.uuid4()
        event["student_id"] = student_id
        event["knowledge_point"] = kc_id
        if "occurred_at" not in event:
            event["occurred_at"] = datetime.now(timezone.utc)
        self._events.append(event)
        return event["id"]

    async def get_verified_prerequisites(self, kc_id: str) -> List[str]:
        return list(self._verified_prereqs.get(kc_id, []))


class PgStore:
    """PostgreSQL 状态存储。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(
        self, student_id: UUID, kc_id: str, question_type: str = "solve"
    ) -> tuple[KCState, dict]:
        stmt = select(KCMastery).where(
            KCMastery.student_id == student_id, KCMastery.knowledge_point == kc_id
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()

        if row:
            return self._row_to_entry(row)
        else:
            prior = await PriorProvider.get_prior(self.session, kc_id, question_type)
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
            last_interaction_ts=row.last_interaction_at.timestamp()
            if row.last_interaction_at
            else None,
            n_attempts=row.n_attempts or 0,
            p_recognition=row.p_recognition,
            p_recognition_init=row.p_recognition_init or 0.20,
        )
        card = row.fsrs_card_json or fsrs_new_card()
        return state, card

    async def save(
        self, student_id: UUID, kc_id: str, state: KCState, card_dict: dict
    ) -> None:
        last_interaction_at = (
            datetime.fromtimestamp(state.last_interaction_ts, timezone.utc)
            if state.last_interaction_ts
            else datetime.now(timezone.utc)
        )
        stmt = (
            update(KCMastery)
            .where(
                KCMastery.student_id == student_id, KCMastery.knowledge_point == kc_id
            )
            .values(
                p_mastery=state.p_mastery,
                long_term_mastery=state.long_term_mastery,
                p_recognition=state.p_recognition,
                fsrs_card_json=card_dict,
                last_interaction_at=last_interaction_at,
                n_attempts=state.n_attempts,
                updated_at=datetime.now(timezone.utc),
            )
        )
        result = await self.session.execute(stmt)

        if result.rowcount == 0:
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
                n_attempts=state.n_attempts,
            )
            await self.session.execute(ins_stmt)

    async def append_event(
        self, student_id: UUID, kc_id: str, event_data: dict
    ) -> Optional[UUID]:
        ins_stmt = (
            insert(InteractionEvent)
            .values(
                student_id=student_id,
                knowledge_point=kc_id,
                question_id=event_data.get("question_id"),
                source=event_data.get("source"),
                is_correct=event_data.get("is_correct"),
                fsrs_rating=event_data.get("fsrs_rating"),
                time_spent_seconds=event_data.get("time_spent_seconds"),
                days_since_last=event_data.get("days_since_last"),
                is_interleaved=event_data.get("is_interleaved", False),
                item_difficulty=event_data.get("item_difficulty"),
                predicted_confidence=event_data.get("predicted_confidence"),
                predicted_r=event_data.get("predicted_r"),
                fire_meta=event_data.get("fire_meta"),
                occurred_at=event_data.get("occurred_at", datetime.now(timezone.utc)),
            )
            .returning(InteractionEvent.id)
        )
        result = await self.session.execute(ins_stmt)
        return result.scalar_one_or_none()

    async def get_verified_prerequisites(self, kc_id: str) -> List[str]:
        """kc_id 的 verified 前置边（M-H §4.8）：KU 自身与前置 KU 均须 verified。"""
        from services.models import KnowledgeUnit

        row = (
            await self.session.execute(
                select(KnowledgeUnit.prerequisites, KnowledgeUnit.verified).where(
                    KnowledgeUnit.id == kc_id
                )
            )
        ).one_or_none()
        if row is None or not row[1]:
            return []
        prereq_ids = [p for p in (row[0] or []) if isinstance(p, str)]
        if not prereq_ids:
            return []
        verified_ids = (
            (
                await self.session.execute(
                    select(KnowledgeUnit.id)
                    .where(KnowledgeUnit.id.in_(prereq_ids))
                    .where(KnowledgeUnit.verified.is_(True))
                )
            )
            .scalars()
            .all()
        )
        keep = set(verified_ids)
        return [p for p in prereq_ids if p in keep]
