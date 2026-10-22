"""幂等导入脚本：将 ChinaTextbookStudyFree v1.2.0 的四科教材、大纲/章节、知识点(KU)、题目、课文、故事导入到 Mneme 生产库。
打上 source='ctsf-v1.2.0' 标记。
"""
from __future__ import annotations

import sys
import json
import glob
import uuid
import hashlib
from pathlib import Path

sys.path.insert(0, '/app')

from sqlalchemy import select, text
from obase.db import SessionLocal
from services.models import (
    Textbook, KnowledgeCluster, QuestionRecord, ReadingPassage
)
from services.ku_ingest_service import store_curriculum_ku

CTSF_SRC = Path('upstream')
DATA_DIR = CTSF_SRC / 'data'
DATA_SOURCE_DIR = CTSF_SRC / 'data-source'

def sanitize(obj):
    if isinstance(obj, str):
        return obj.replace('\u0000', '')
    elif isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize(v) for v in obj]
    return obj

async def import_ctsf_data():
    print("=== 开始幂等导入 CTSF v1.2.0 数据到 Mneme 生产库 ===")
    async with SessionLocal() as db:
        print("清理旧的 CTSF 数据...")
        await db.execute(text("DELETE FROM reading_passages WHERE source_url LIKE 'ctsf%'"))
        await db.execute(text("DELETE FROM question_records WHERE source = 'ctsf-v1.2.0'"))
        await db.execute(text("DELETE FROM knowledge_units WHERE id LIKE 'ctsf-%'"))
        await db.execute(text("DELETE FROM knowledge_clusters WHERE id LIKE 'ctsf-%'"))
        await db.execute(text("DELETE FROM textbooks WHERE id LIKE 'ctsf-%'"))
        await db.commit()

        outlines_files = glob.glob(str(CTSF_SRC / 'output' / '**' / 'outlines' / '*.json'), recursive=True)
        if not outlines_files:
            outlines_files = glob.glob(str(DATA_DIR / '**' / 'outline.json'), recursive=True)
        print(f"找到大纲文件共 {len(outlines_files)} 个")

        textbooks_imported = 0
        kus_imported = 0
        questions_imported = 0
        passages_imported = 0
        stories_imported = 0

        for f_path in outlines_files:
            try:
                data = json.load(open(f_path, 'r', encoding='utf-8'))
            except Exception:
                continue

            textbook_title = sanitize(data.get('textbook', data.get('title', '未知教材')))
            subject = 'math'
            if 'chinese' in f_path:
                subject = 'chinese'
            elif 'english' in f_path:
                subject = 'english'
            elif 'science' in f_path or 'physics' in f_path:
                subject = 'science'

            h_str = hashlib.sha256(f_path.encode()).hexdigest()[:12]
            textbook_id = f"ctsf-{subject}-{h_str}"
            
            tb = (await db.execute(select(Textbook).where(Textbook.id == textbook_id))).scalar_one_or_none()
            if not tb:
                tb = Textbook(
                    id=textbook_id,
                    book_name=textbook_title,
                    subject=subject,
                    grade="all",
                    edition="人教/统编/PEP/教科",
                )
                db.add(tb)
                textbooks_imported += 1
                await db.flush()
            
            cluster_id = f"{textbook_id}-cluster"
            cluster = (await db.execute(select(KnowledgeCluster).where(KnowledgeCluster.id == cluster_id))).scalar_one_or_none()
            if not cluster:
                db.add(KnowledgeCluster(id=cluster_id, textbook_id=textbook_id, name=f"{textbook_title}知识簇"))
                await db.flush()

            units = data.get('units', data.get('chapters', []))
            for u_idx, unit in enumerate(units):
                kps = unit.get('knowledge_points', unit.get('sections', []))
                for kp_idx, kp in enumerate(kps):
                    kp_name = kp.get('name', kp.get('title', f'知识点{kp_idx+1}'))
                    kp_desc = kp.get('description', kp.get('content', kp_name))
                    if len(kp_desc) < 8:
                        kp_desc = kp_desc + " (ctsf-v1.2.0 基础知识点描述)"
                    ku_id = f"{textbook_id}-u{u_idx+1}-kp{kp_idx+1}"
                    ku_data = sanitize({
                        "id": ku_id,
                        "name": kp_name,
                        "description": kp_desc,
                        "difficulty": float(kp.get('difficulty', 0.5)) / 5.0 if kp.get('difficulty', 0.5) > 1 else float(kp.get('difficulty', 0.5)),
                        "prerequisites": [],
                        "provenance": {"source": "ctsf-v1.2.0", "file": f_path},
                        "textbook_id": textbook_id,
                        "cluster_id": cluster_id
                    })
                    res = await store_curriculum_ku(db, ku_data, extract_model="ctsf-import")
                    if res["status"] == "stored":
                        kus_imported += 1

            await db.commit()

        quiz_files = glob.glob(str(CTSF_SRC / 'output' / '**' / 'quizzes' / '*.json'), recursive=True)
        print(f"找到题库文件共 {len(quiz_files)} 个")
        for f_path in quiz_files:
            try:
                data = json.load(open(f_path, 'r', encoding='utf-8'))
            except Exception:
                continue

            for q_group_key in ['unit_test', 'exam', 'questions', 'exercises']:
                q_group = data.get(q_group_key, data if isinstance(data, list) else None)
                if not q_group:
                    continue
                q_list = q_group.get('questions', []) if isinstance(q_group, dict) else (q_group if isinstance(q_group, list) else [])
                if not isinstance(q_list, list):
                    continue
                for q_idx, q_item in enumerate(q_list):
                    if not isinstance(q_item, dict):
                        continue
                    q_text = sanitize(q_item.get('question', q_item.get('title', '')))
                    if not q_text:
                        continue
                    q_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, f"ctsf-q-{f_path}-{q_group_key}-{q_idx}")
                    existing_q = (await db.execute(select(QuestionRecord).where(QuestionRecord.id == q_uuid))).scalar_one_or_none()
                    if not existing_q:
                        qr = QuestionRecord(
                            id=q_uuid,
                            student_id=uuid.UUID('00000000-0000-0000-0000-000000000000'),
                            question_text=q_text,
                            correct_answer=sanitize(str(q_item.get('answer', q_item.get('correct', '')))),
                            subject="math",
                            source="ctsf-v1.2.0",
                            meta=sanitize({
                                "options": q_item.get('options', []),
                                "explanation": q_item.get('explanation', ''),
                                "difficulty": q_item.get('difficulty', 2),
                                "question_type": q_item.get('type', 'choice')
                            })
                        )
                        db.add(qr)
                        questions_imported += 1
            await db.commit()

        passage_files = glob.glob(str(DATA_SOURCE_DIR / 'passages' / '**' / '*.json'), recursive=True)
        print(f"找到 passages JSON 共 {len(passage_files)} 个")
        for f_path in passage_files:
            try:
                data = json.load(open(f_path, 'r', encoding='utf-8'))
            except Exception:
                continue
            passages = data.get('passages', data.get('items', [data] if isinstance(data, dict) else []))
            for p_idx, p in enumerate(passages):
                if not isinstance(p, dict):
                    continue
                title = sanitize(p.get('title', '未知课文'))
                body = sanitize("\n".join(p.get('sentences', p.get('content', []))))
                if not body:
                    body = sanitize(p.get('text', '暂无内容'))
                h_p = hashlib.sha256(f_path.encode()).hexdigest()[:8]
                p_id = f"ctsf-p-{h_p}-{p_idx}"
                existing_p = (await db.execute(select(ReadingPassage).where(ReadingPassage.id == p_id))).scalar_one_or_none()
                if not existing_p:
                    rp = ReadingPassage(
                        id=p_id,
                        title=title,
                        body_text=body,
                        subject=sanitize(data.get('subject', 'chinese')),
                        word_count=len(body),
                        readability_score=0.8,
                        difficulty_band=2,
                        source_url="ctsf-v1.2.0"
                    )
                    db.add(rp)
                    passages_imported += 1
            await db.commit()

        story_files = glob.glob(str(DATA_SOURCE_DIR / 'stories' / '**' / '*.json'), recursive=True)
        print(f"找到 stories JSON 共 {len(story_files)} 个")
        for f_path in story_files:
            try:
                data = json.load(open(f_path, 'r', encoding='utf-8'))
            except Exception:
                continue
            stories = data.get('stories', data.get('items', [data] if isinstance(data, dict) else []))
            for s_idx, s in enumerate(stories):
                if not isinstance(s, dict):
                    continue
                title = sanitize(s.get('title', '未知故事'))
                body = sanitize("\n".join(s.get('sentences', s.get('content', []))))
                if not body:
                    body = sanitize(s.get('text', '暂无内容'))
                h_s = hashlib.sha256(f_path.encode()).hexdigest()[:8]
                s_id = f"ctsf-s-{h_s}-{s_idx}"
                existing_s = (await db.execute(select(ReadingPassage).where(ReadingPassage.id == s_id))).scalar_one_or_none()
                if not existing_s:
                    rs = ReadingPassage(
                        id=s_id,
                        title=title,
                        body_text=body,
                        subject=sanitize(data.get('subject', 'chinese')),
                        word_count=len(body),
                        readability_score=0.8,
                        difficulty_band=2,
                        source_url="ctsf-v1.2.0-story"
                    )
                    db.add(rs)
                    stories_imported += 1

                for q_idx, q_item in enumerate(s.get('questions', [])):
                    if not isinstance(q_item, dict):
                        continue
                    q_text = sanitize(q_item.get('question', ''))
                    if not q_text:
                        continue
                    q_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, f"ctsf-story-file-{f_path}-{s_idx}-{q_idx}")
                    existing_q = (await db.execute(select(QuestionRecord).where(QuestionRecord.id == q_uuid))).scalar_one_or_none()
                    if not existing_q:
                        qr = QuestionRecord(
                            id=q_uuid,
                            student_id=uuid.UUID('00000000-0000-0000-0000-000000000000'),
                            question_text=q_text,
                            correct_answer=sanitize(str(q_item.get('answer', ''))),
                            subject="chinese",
                            source="ctsf-v1.2.0",
                            meta=sanitize({
                                "options": q_item.get('options', []),
                                "explanation": q_item.get('explanation', ''),
                            })
                        )
                        db.add(qr)
                        questions_imported += 1
            await db.commit()

        print("=== 导入统计报告 ===")
        print(f"教材新增: {textbooks_imported}")
        print(f"知识点(KU)新增: {kus_imported}")
        print(f"题目新增: {questions_imported}")
        print(f"课文新增: {passages_imported}")
        print(f"故事新增: {stories_imported}")

if __name__ == '__main__':
    import asyncio
    asyncio.run(import_ctsf_data())
