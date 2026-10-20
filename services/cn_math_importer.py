"""cn-math-taxonomy → knowledge_units 导入器（幂等 upsert）。

数据：``data/cn_math_taxonomy``（上游 https://github.com/xiaoyang111222/cn-math-taxonomy ，
CC BY-NC 4.0，原样快照，版本见同目录 UPSTREAM.json）。一—九年级 531 个知识点
（小学 216 + 初中 315）→ KU ``cnmath:<topicId>``：
  - dependencies（topicId 依赖 prerequisiteId）→ ``prerequisites``（hard）/ ``soft_prerequisites``（soft）
  - questions → ``rich_content.questions``（先修诊断题库，见 services/prereq_diagnosis_service）
  - cn-curriculum-standards → ``curriculum_standard``（课标条目 id + 置信度 + 条文）
  - id-aliases（上游已删除的 18 个 cnm_ext_* 外部节点）→ 库里若还有旧行，只打
    ``rich_content.deprecated=True`` + ``alias_targets``，**不删除**（可能有学生作答引用）。

注意：这是写库操作。对生产库运行前需确认（会改变 cnmath:* KU 的 hard 先修 → 影响
P4 推荐/fringe 解锁判定）。
"""

import json
import os
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import KnowledgeUnit

DATA_DIR = os.getenv("CN_MATH_DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cn_math_taxonomy"))
KU_PREFIX = "cnmath:"
UPSTREAM_URL = "https://github.com/xiaoyang111222/cn-math-taxonomy"


def _read_json(name: str, default: Any) -> Any:
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _region_tags(grade: Any) -> list[str]:
    stage = "全国中考" if isinstance(grade, int) and grade >= 7 else "小学"
    return [stage, f"grade:{grade}"]


async def import_cn_math_taxonomy(db: AsyncSession) -> dict:
    topics_path = os.path.join(DATA_DIR, "topics.json")
    if not os.path.exists(topics_path):
        raise FileNotFoundError(f"Topics file not found at {topics_path}")

    topics = _read_json("topics.json", [])
    deps = _read_json("dependencies.json", [])
    questions = _read_json("questions.json", [])
    standards = {s["id"]: s for s in _read_json("cn-curriculum-standards.json", {}).get("items", [])}
    aliases = _read_json("id-aliases.json", {}).get("aliases", {})
    upstream = _read_json("UPSTREAM.json", {})

    hard_prereqs: dict[str, list[str]] = defaultdict(list)
    soft_prereqs: dict[str, list[str]] = defaultdict(list)
    for d in deps:
        tid = d.get("topicId")
        pid = d.get("prerequisiteId")
        target = soft_prereqs if d.get("strength", "hard") == "soft" else hard_prereqs
        if f"{KU_PREFIX}{pid}" not in target[tid]:
            target[tid].append(f"{KU_PREFIX}{pid}")

    q_map: dict[str, list[dict]] = defaultdict(list)
    for q in questions:
        q_map[q["topicId"]].append(q)

    provenance = {
        "source": "cn-math-taxonomy",
        "license": "CC BY-NC 4.0",
        "needs_teacher_review": True,
        "github": UPSTREAM_URL,
        "commit": upstream.get("commit"),
    }

    imported_count = updated_count = deprecated_count = 0

    for order, t in enumerate(topics):
        tid = t["id"]
        ku_id = f"{KU_PREFIX}{tid}"
        is_external = t.get("external", False)
        grade = t.get("grade")
        domain = t.get("domain")
        ttype = t.get("type")
        desc = t.get("description", "")
        mastery_criteria = t.get("mastery_criteria", [])
        std_refs = [
            {**s, "text": standards.get(s.get("id"), {}).get("text")} for s in t.get("standards", [])
        ]
        qtypes = sorted({str(q.get("type")) for q in q_map[tid]}) if tid in q_map else []
        ku_type = "concept" if ttype == "conceptual" else ("procedural" if ttype == "procedural" else "application")

        rich_content = {
            "cnm_id": tid,
            "order": order,  # 上游 topics 顺序：先修诊断同级出题次序依赖它
            "external": is_external,
            "grade": grade,
            "semester": t.get("semester"),
            "chapter": t.get("chapter"),
            "domain": domain,
            "type": ttype,
            "diagnostic_question": t.get("diagnostic_question"),
            "questions": q_map[tid],
        }
        fields = dict(
            textbook_id="CN-MATH-2024",
            cluster_id=domain or "数与代数",
            name=t["name"],
            description=desc,
            prerequisites=hard_prereqs[tid],
            soft_prerequisites=soft_prereqs[tid],
            question_types=qtypes,
            ku_type=ku_type,
            curriculum_standard=json.dumps(std_refs, ensure_ascii=False),
            mastery_levels=mastery_criteria,
            exam_region_tags=_region_tags(grade),
            rich_content=rich_content,
            provenance=provenance,
            source_excerpt=desc,
            ai_generated=True,
            verified=False,
        )

        result = await db.execute(select(KnowledgeUnit).where(KnowledgeUnit.id == ku_id))
        existing = result.scalars().first()
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            updated_count += 1
        else:
            db.add(KnowledgeUnit(
                id=ku_id,
                related_kus=[],
                difficulty=0.5,
                exam_frequency="HIGH" if not is_external else "MEDIUM",
                **fields,
            ))
            imported_count += 1

    # 上游已删除的旧外部节点：库里有就标废弃并指向替代知识点（不删行）
    for old_id, spec in aliases.items():
        result = await db.execute(select(KnowledgeUnit).where(KnowledgeUnit.id == f"{KU_PREFIX}{old_id}"))
        row = result.scalars().first()
        if row is None:
            continue
        rc = dict(row.rich_content or {})
        rc["deprecated"] = True
        rc["alias_targets"] = [f"{KU_PREFIX}{x}" for x in spec.get("targets", [])]
        row.rich_content = rc
        deprecated_count += 1

    await db.commit()
    return {
        "status": "success",
        "imported": imported_count,
        "updated": updated_count,
        "deprecated": deprecated_count,
        "total": len(topics),
    }
