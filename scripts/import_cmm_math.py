#!/usr/bin/env python3
"""
CMM-Math 全量导入脚本（无 LLM 标注）。

直接入库题目，knowledge_points 留占位 key（供 match_questions_to_ku.py 后续匹配替换）。
匹配 → 真实人教版 KU 由 match_questions_to_ku.py 完成。

用法:
  # 全量（宿主机 python，直连 DB port 5433）
  python3 scripts/import_cmm_math.py --input cmm_math_train.jsonl

  # 或在容器内（--network host）
  docker run --rm --network host \\
    -v ~/projects/mneme/scripts:/app/scripts \\
    -v ~/projects/mneme/cmm_math_train.jsonl:/data/cmm_math_train.jsonl \\
    -e DATABASE_URL=postgresql://postgres:postgres@localhost:5433/mneme \\
    mneme-api:latest python /app/scripts/import_cmm_math.py --input /data/cmm_math_train.jsonl

参数:
  --input   JSONL 文件路径（默认 cmm_math_train.jsonl）
  --dry-run 只打印前5条，不写DB
  --limit N 只导入前N条（测试用）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    import asyncpg
except ImportError:
    sys.exit("缺少 asyncpg：pip install asyncpg")


LEVEL_TO_GRADE: dict[str, str] = {
    "一年级": "G1", "二年级": "G2", "三年级": "G3",
    "四年级": "G4", "五年级": "G5", "六年级": "G6",
    "七年级": "G7", "八年级": "G8", "九年级": "G9",
    "高一": "G10", "高二": "G11", "高三": "G12",
}

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5433/mneme"
).replace("postgresql+asyncpg://", "postgresql://")


def _slug(text: str) -> str:
    text = re.sub(r"[^\w一-鿿]+", "-", text.strip())
    return text[:40].strip("-").lower()


async def question_exists(conn: asyncpg.Connection, cmm_id: str) -> bool:
    row = await conn.fetchrow(
        "SELECT id FROM wrong_questions WHERE profiler_analysis->>'cmm_id' = $1 LIMIT 1",
        cmm_id,
    )
    return row is not None


# item 10：学科参数化（默认数学，向后兼容）。其他学科传 --subject/--subject-code。
#   _SUBJECT       入 wrong_questions.subject 列的值（须与查询端一致）
#   _SUBJECT_CODE  KP 占位键/来源标识前缀（cmm-{code}-{grade}-*，供 match 脚本提取年级）
_SUBJECT = "数学"
_SUBJECT_CODE = "math"


async def insert_question(conn: asyncpg.Connection, ex: dict[str, Any]) -> None:
    level   = ex.get("level", "")
    grade   = LEVEL_TO_GRADE.get(level, "G1")
    subject = ex.get("subject", _SUBJECT)
    cmm_id  = str(ex.get("id", ""))
    images  = ex.get("image") or []
    if isinstance(images, str):
        images = [images] if images else []

    # 占位 knowledge_points key，格式 cmm-{code}-{grade_lower}-* 以供 match 脚本提取年级
    kp_key = f"cmm-{_SUBJECT_CODE}-{grade.lower()}-{_slug(subject)}"
    knowledge_points = {kp_key: "待匹配"}

    profiler: dict[str, Any] = {
        "source":          f"cmm-{_SUBJECT_CODE}",
        "cmm_id":          cmm_id,
        "grade":           level,          # 中文年级（一年级…高三）
        "grade_code":      grade,          # G1…G12
        "subject_branch":  subject,
        "options":         ex.get("options") or "",
        "steps":           ex.get("analysis") or "",
        "has_image":       bool(images),
        "image_filenames": images,
    }

    await conn.execute(
        """INSERT INTO wrong_questions
               (id, paper_id, student_id, subject, question_text,
                student_answer, correct_answer, knowledge_points, profiler_analysis)
           VALUES (gen_random_uuid(), NULL, NULL, $5, $1,
                   NULL, $2, $3::jsonb, $4::jsonb)
        """,
        ex.get("question", ""),
        ex.get("answer", ""),
        json.dumps(knowledge_points, ensure_ascii=False),
        json.dumps(profiler, ensure_ascii=False),
        _SUBJECT,
    )


async def run(samples: list[dict[str, Any]], dry_run: bool) -> None:
    total = len(samples)
    print(f"待导入: {total} 条  dry_run={dry_run}")

    if dry_run:
        for ex in samples[:5]:
            print(f"  [{ex.get('level','')}·{ex.get('subject','')}] "
                  f"{str(ex.get('question',''))[:80]}…")
        print("（dry-run 结束）")
        return

    conn  = await asyncpg.connect(DB_URL)
    t0    = time.time()
    stats: dict[str, int] = defaultdict(int)

    BATCH = 200
    for start in range(0, total, BATCH):
        batch = samples[start:start + BATCH]
        for ex in batch:
            cmm_id = str(ex.get("id", ""))
            level  = ex.get("level", "")
            grade  = LEVEL_TO_GRADE.get(level, "G1")
            try:
                if await question_exists(conn, cmm_id):
                    stats["skip"] += 1
                    continue
                await insert_question(conn, ex)
                stats["ok"] += 1
            except Exception as e:
                stats["fail"] += 1
                print(f"  ❌ {cmm_id}: {e}")

        elapsed = time.time() - t0
        done    = start + len(batch)
        rate    = done / max(elapsed, 0.1)
        eta     = (total - done) / max(rate, 0.1)
        print(f"  [{done:5d}/{total}] ok={stats['ok']} skip={stats['skip']} "
              f"fail={stats['fail']}  {rate:.0f}条/s  ETA {eta:.0f}s")

    await conn.close()

    elapsed = time.time() - t0
    print(f"""
{'='*55}
  CMM-Math 导入完成
{'='*55}
  总条数   : {total}
  导入成功 : {stats['ok']}
  已存在跳过: {stats['skip']}
  失败     : {stats['fail']}
  耗时     : {elapsed:.1f}s  ({elapsed/60:.1f}min)
  速率     : {total/max(elapsed,0.1):.0f} 条/s

  下一步: python scripts/match_questions_to_ku.py --concurrency 4
{'='*55}""")

    if stats["fail"]:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",   default="cmm_math_train.jsonl")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit",   type=int, default=None)
    parser.add_argument("--subject", default="数学",
                        help="入 wrong_questions.subject 列的值（须与练习查询端一致）")
    parser.add_argument("--subject-code", default="math",
                        help="KP 占位键/来源前缀：cmm-{code}-{grade}-*")
    args = parser.parse_args()

    global _SUBJECT, _SUBJECT_CODE
    _SUBJECT, _SUBJECT_CODE = args.subject, args.subject_code

    path = Path(args.input)
    if not path.exists():
        sys.exit(f"找不到文件: {path}")

    samples: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    samples.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    if args.limit:
        samples = samples[: args.limit]

    print(f"读取 {len(samples)} 条（文件: {path}）")
    asyncio.run(run(samples, args.dry_run))


if __name__ == "__main__":
    main()
