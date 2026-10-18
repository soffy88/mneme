import json
import os
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from services.models import KnowledgeUnit

DATA_DIR = "/tmp/cn-math-taxonomy/data"

async def import_cn_math_taxonomy(db: AsyncSession) -> dict:
    topics_path = os.path.join(DATA_DIR, "topics.json")
    deps_path = os.path.join(DATA_DIR, "dependencies.json")
    questions_path = os.path.join(DATA_DIR, "questions.json")

    if not os.path.exists(topics_path):
        raise FileNotFoundError(f"Topics file not found at {topics_path}")

    with open(topics_path, "r", encoding="utf-8") as f:
        topics = json.load(f)
    
    deps = []
    if os.path.exists(deps_path):
        with open(deps_path, "r", encoding="utf-8") as f:
            deps = json.load(f)

    questions = []
    if os.path.exists(questions_path):
        with open(questions_path, "r", encoding="utf-8") as f:
            questions = json.load(f)

    from collections import defaultdict
    hard_prereqs = defaultdict(list)
    soft_prereqs = defaultdict(list)

    for d in deps:
        tid = d.get("topicId")
        pid = d.get("prerequisiteId")
        strength = d.get("strength", "hard")
        if strength == "soft":
            soft_prereqs[tid].append(f"cnmath:{pid}")
        else:
            hard_prereqs[tid].append(f"cnmath:{pid}")

    q_map = defaultdict(list)
    for q in questions:
        q_map[q["topicId"]].append(q)

    imported_count = updated_count = 0

    for t in topics:
        tid = t["id"]
        ku_id = f"cnmath:{tid}"
        is_external = t.get("external", False)
        grade = t.get("grade")
        semester = t.get("semester")
        chapter = t.get("chapter")
        domain = t.get("domain")
        ttype = t.get("type")
        desc = t.get("description", "")
        mastery_criteria = t.get("mastery_criteria", [])
        diagnostic_question = t.get("diagnostic_question")
        standards = t.get("standards", [])

        qtypes = list(set(q.get("type") for q in q_map[tid])) if tid in q_map else []
        ku_type = "concept" if ttype == "conceptual" else ("procedural" if ttype == "procedural" else "application")

        rich_content = {
            "cnm_id": tid,
            "external": is_external,
            "grade": grade,
            "semester": semester,
            "chapter": chapter,
            "domain": domain,
            "type": ttype,
            "diagnostic_question": diagnostic_question,
            "questions": q_map[tid]
        }

        provenance = {
            "source": "cn-math-taxonomy",
            "license": "CC BY-NC 4.0",
            "needs_teacher_review": True,
            "github": "https://github.com/xiaoyang111222/cn-math-taxonomy"
        }

        # Check existing
        stmt = select(KnowledgeUnit).where(KnowledgeUnit.id == ku_id)
        result = await db.execute(stmt)
        existing = result.scalars().first()

        if existing:
            existing.textbook_id = "CN-MATH-2024"
            existing.cluster_id = domain or "数与代数"
            existing.name = t["name"]
            existing.description = desc
            existing.prerequisites = hard_prereqs[tid]
            existing.soft_prerequisites = soft_prereqs[tid]
            existing.question_types = qtypes
            existing.ku_type = ku_type
            existing.curriculum_standard = json.dumps(standards, ensure_ascii=False)
            existing.mastery_levels = mastery_criteria
            existing.exam_region_tags = ["全国中考", f"grade:{grade}"]
            existing.rich_content = rich_content
            existing.provenance = provenance
            existing.source_excerpt = desc
            existing.ai_generated = True
            existing.verified = False
            updated_count += 1
        else:
            ku = KnowledgeUnit(
                id=ku_id,
                textbook_id="CN-MATH-2024",
                cluster_id=domain or "数与代数",
                name=t["name"],
                description=desc,
                prerequisites=hard_prereqs[tid],
                soft_prerequisites=soft_prereqs[tid],
                related_kus=[],
                difficulty=0.5,
                exam_frequency="HIGH" if not is_external else "MEDIUM",
                question_types=qtypes,
                ku_type=ku_type,
                curriculum_standard=json.dumps(standards, ensure_ascii=False),
                mastery_levels=mastery_criteria,
                exam_region_tags=["全国中考", f"grade:{grade}"],
                rich_content=rich_content,
                provenance=provenance,
                source_excerpt=desc,
                ai_generated=True,
                verified=False
            )
            db.add(ku)
            imported_count += 1

    await db.commit()
    return {
        "status": "success",
        "imported": imported_count,
        "updated": updated_count,
        "total": len(topics)
    }
