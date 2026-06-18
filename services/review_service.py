from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from oprim import due_compute
from oskill import variant_for_review, ReviewVariantInput
from omodul.due_recall_push import due_recall_push_workflow, DueRecallPushConfig, DueRecallPushInput
from services.models import KCMastery, WrongQuestion
from obase.provider_registry import ProviderRegistry
from obase.persistence.pool import PgPool
from obase.config import settings

async def get_pg_pool() -> PgPool:
    dsn = settings.DATABASE_URL.replace('+asyncpg', '')
    return await PgPool.get_or_create(dsn=dsn)

async def get_due_variants(db: AsyncSession, student_id: uuid.UUID) -> List[dict]:
    # 1. Fetch all mastery for student
    stmt = select(KCMastery).where(KCMastery.student_id == student_id)
    masteries = (await db.execute(stmt)).scalars().all()
    
    due_items = []
    now = datetime.now(timezone.utc)
    
    caller = ProviderRegistry.get().llm() if ProviderRegistry._instance else None
    
    for m in masteries:
        if not m.fsrs_card_json:
            continue
            
        # 2. Check if due
        is_due = due_compute(card_dict=m.fsrs_card_json, now=now)
        if is_due:
            # 3. Generate variant
            # Find an original question for context
            wq_stmt = select(WrongQuestion).where(
                WrongQuestion.student_id == student_id,
                WrongQuestion.knowledge_points.has_key(m.knowledge_point)
            ).limit(1)
            wq = (await db.execute(wq_stmt)).scalar_one_or_none()
            
            orig_q = wq.question_text if wq else "已知知识点为 " + m.knowledge_point
            orig_a = wq.correct_answer if wq else "无"
            
            try:
                variant = await variant_for_review(
                    ReviewVariantInput(
                        student_id=str(student_id),
                        kc_id=m.knowledge_point,
                        original_question=orig_q,
                        original_answer=orig_a
                    ),
                    caller=caller
                )
                
                due_items.append({
                    "kc_id": m.knowledge_point,
                    "variant_question": variant.question_text,
                    "variant_answer": variant.correct_answer,
                    "due_since": m.last_interaction_at.isoformat() if m.last_interaction_at else None,
                    "fsrs_interval": m.fsrs_card_json.get("stability", 0)
                })
            except Exception:
                continue # Skip if variant generation fails
                
    if due_items:
        # 4. Wrap with due_recall_push (omodul)
        # Note: omodul.due_recall_push_workflow might trigger actual push (e.g. Telegram)
        # Here we just use it for the "business transaction" recording if needed.
        pool = await get_pg_pool()
        await due_recall_push_workflow(
            config=DueRecallPushConfig(),
            input_data=DueRecallPushInput(
                batch_id=str(uuid.uuid4()),
                due_items=due_items
            ),
            pool=pool
        )
        
    return due_items
