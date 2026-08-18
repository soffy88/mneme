"""
services/seed_question_bank.py — 种子题库 + rubric 导入（幂等）
"""
from __future__ import annotations

import json
import os
import uuid

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import WrongQuestion


async def seed_seed_questions(db: AsyncSession) -> int:
    """将 seed_questions.json 导入 wrong_questions 表（student_id=NULL 表示系统种子题）。"""
    sq_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'data', 'seed_questions.json')
    if not os.path.exists(sq_path):
        return 0

    with open(sq_path) as f:
        all_qs: dict[str, list[dict]] = json.load(f)

    rows = []
    for kc_id, qs in all_qs.items():
        for q in qs:
            knowledge_points = {kc_id: 1.0}
            question_text = q['question_text']
            correct_answer = q['correct_answer']
            qtype = q['question_type']
            difficulty = q.get('difficulty', 0.5)

            lines = [question_text]
            if q.get('options'):
                lines.append('')
                lines.extend(q['options'])
            full_text = '\n'.join(lines)

            rows.append({
                'student_id': None,
                'subject': 'math',
                'question_text': full_text,
                'correct_answer': correct_answer,
                'knowledge_points': knowledge_points,
                'needs_image': False,
                'item_difficulty': difficulty,
                'profiler_analysis': {
                    'question_type': qtype,
                    'kc_id': kc_id,
                    'source': 'seed',
                },
            })

    if not rows:
        return 0

    # 批量插入（幂等：跳过已存在的，用 question_text + correct_answer 作为去重依据）
    inserted = 0
    for row in rows:
        # 检查是否已存在
        existing = await db.execute(
            text("SELECT 1 FROM wrong_questions WHERE question_text = :qt AND correct_answer = :ca AND student_id IS NULL"),
            {'qt': row['question_text'], 'ca': row['correct_answer']},
        )
        if existing.first():
            continue
        row['id'] = uuid.uuid4()
        stmt = pg_insert(WrongQuestion).values(**row)
        await db.execute(stmt)
        inserted += 1

    return inserted


async def seed_rubrics(db: AsyncSession) -> int:
    """将 seed_rubrics.json 导入 gate.rubric 和 gate.qualitative_intent。"""
    rb_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'data', 'seed_rubrics.json')
    if not os.path.exists(rb_path):
        return 0

    with open(rb_path) as f:
        rubrics: list[dict] = json.load(f)

    count = 0
    for r in rubrics:
        kc_id = r['kc_id']
        dimensions = r['dimensions']
        author = r.get('author', 'system')

        # 检查 rubric 是否已存在
        existing = await db.execute(
            text("SELECT 1 FROM gate.rubric WHERE kc_id = :kc"),
            {'kc': kc_id},
        )
        if existing.first():
            continue

        # 插入 rubric
        await db.execute(
            text("""
                INSERT INTO gate.rubric (kc_id, dimensions, author)
                VALUES (:kc, :dims, :author)
            """),
            {'kc': kc_id, 'dims': json.dumps(dimensions), 'author': author},
        )

        # 确保 qualitative_intent 也有记录（M1 设计：意图与判据分离）
        intent_exists = await db.execute(
            text("SELECT 1 FROM gate.qualitative_intent WHERE kc_id = :kc"),
            {'kc': kc_id},
        )
        if not intent_exists.first():
            # reason/author 均 NOT NULL（gate schema）：意图登记必须说明为什么
            # 该 KC 走定性门，不能只写 kc_id。
            await db.execute(
                text("""
                    INSERT INTO gate.qualitative_intent (kc_id, reason, author)
                    VALUES (:kc, :reason, :author)
                """),
                {
                    'kc': kc_id,
                    'reason': f"种子 rubric 导入：{r.get('kc_name', kc_id)} 为定性考查知识点",
                    'author': author,
                },
            )

        count += 1

    return count


async def seed_all(db: AsyncSession) -> dict[str, int]:
    """运行所有种子导入，返回各步骤计数。"""
    result = {}

    q_count = await seed_seed_questions(db)
    result['seed_questions'] = q_count

    r_count = await seed_rubrics(db)
    result['seed_rubrics'] = r_count

    await db.commit()
    return result