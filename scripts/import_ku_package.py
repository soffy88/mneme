#!/usr/bin/env python3
"""
import_ku_package.py — AII 知识单元包幂等导入脚本

用法:
  python scripts/import_ku_package.py <json_file>          # 正式导入
  python scripts/import_ku_package.py <json_file> --dry-run  # 预演

JSON 格式 (AII 接口契约):
{
  "textbook": {"id", "subject", "grade", "edition", "book_name"},
  "clusters": [{"id", "name", "display_order", "description"}],
  "units":    [{"id", "cluster_id", "textbook_id", "name", "description",
                "prerequisites", "related_kus", "difficulty",
                "exam_frequency", "question_types", "ku_type",
                "curriculum_standard", "mastery_levels"}]
}
"""
from __future__ import annotations

import argparse
import json
import sys
import os

# ── DB 连接使用与后端相同的 psycopg2 同步驱动 ──────────────────
import psycopg2
import psycopg2.extras

DATABASE_URL_SYNC = os.environ.get(
    "DATABASE_URL_SYNC",
    "postgresql://postgres:postgres@localhost:5433/mneme",
)


def get_conn():
    return psycopg2.connect(DATABASE_URL_SYNC)


# ── 校验 ──────────────────────────────────────────────────────

def validate(pkg: dict) -> list[str]:
    errors: list[str] = []
    tb = pkg.get("textbook")
    if not tb or not tb.get("id"):
        errors.append("textbook.id 缺失")

    cluster_ids = {c["id"] for c in pkg.get("clusters", [])}
    textbook_id = (tb or {}).get("id", "")

    for u in pkg.get("units", []):
        if u.get("cluster_id") not in cluster_ids:
            errors.append(f"unit {u.get('id')}: cluster_id={u.get('cluster_id')} 不在 clusters 中")
        if u.get("textbook_id") != textbook_id:
            errors.append(f"unit {u.get('id')}: textbook_id={u.get('textbook_id')} 与 textbook.id 不匹配")
    return errors


# ── 幂等 upsert helpers ────────────────────────────────────────

def upsert_textbook(cur, tb: dict) -> str:
    cur.execute(
        """
        INSERT INTO textbooks (id, subject, grade, edition, book_name)
        VALUES (%(id)s, %(subject)s, %(grade)s, %(edition)s, %(book_name)s)
        ON CONFLICT (id) DO UPDATE SET
          subject   = EXCLUDED.subject,
          grade     = EXCLUDED.grade,
          edition   = EXCLUDED.edition,
          book_name = EXCLUDED.book_name
        """,
        tb,
    )
    return tb["id"]


def upsert_cluster(cur, textbook_id: str, c: dict) -> None:
    cur.execute(
        """
        INSERT INTO knowledge_clusters (id, textbook_id, name, display_order, description)
        VALUES (%(id)s, %(textbook_id)s, %(name)s, %(display_order)s, %(description)s)
        ON CONFLICT (id) DO UPDATE SET
          name          = EXCLUDED.name,
          display_order = EXCLUDED.display_order,
          description   = EXCLUDED.description
        """,
        {
            "id":            c["id"],
            "textbook_id":   textbook_id,
            "name":          c["name"],
            "display_order": c.get("display_order", 0),
            "description":   c.get("description"),
        },
    )


def upsert_unit(cur, u: dict) -> None:
    cur.execute(
        """
        INSERT INTO knowledge_units (
          id, textbook_id, cluster_id, name, description,
          prerequisites, related_kus, difficulty, exam_frequency,
          question_types, ku_type, curriculum_standard, mastery_levels
        ) VALUES (
          %(id)s, %(textbook_id)s, %(cluster_id)s, %(name)s, %(description)s,
          %(prerequisites)s, %(related_kus)s, %(difficulty)s, %(exam_frequency)s,
          %(question_types)s, %(ku_type)s, %(curriculum_standard)s, %(mastery_levels)s
        )
        ON CONFLICT (id) DO UPDATE SET
          textbook_id         = EXCLUDED.textbook_id,
          cluster_id          = EXCLUDED.cluster_id,
          name                = EXCLUDED.name,
          description         = EXCLUDED.description,
          prerequisites       = EXCLUDED.prerequisites,
          related_kus         = EXCLUDED.related_kus,
          difficulty          = EXCLUDED.difficulty,
          exam_frequency      = EXCLUDED.exam_frequency,
          question_types      = EXCLUDED.question_types,
          ku_type             = EXCLUDED.ku_type,
          curriculum_standard = EXCLUDED.curriculum_standard,
          mastery_levels      = EXCLUDED.mastery_levels
        """,
        {
            "id":                 u["id"],
            "textbook_id":        u["textbook_id"],
            "cluster_id":         u["cluster_id"],
            "name":               u["name"],
            "description":        u.get("description"),
            "prerequisites":      json.dumps(u.get("prerequisites", []), ensure_ascii=False),
            "related_kus":        json.dumps(u.get("related_kus", []), ensure_ascii=False),
            "difficulty":         u.get("difficulty", 0.5),
            "exam_frequency":     u.get("exam_frequency", "mid"),
            "question_types":     json.dumps(u.get("question_types", []), ensure_ascii=False),
            "ku_type":            u.get("ku_type", "concept"),
            "curriculum_standard": u.get("curriculum_standard"),
            "mastery_levels":     json.dumps(u.get("mastery_levels", []), ensure_ascii=False),
        },
    )


# ── main ─────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="AII 知识单元包导入")
    parser.add_argument("json_file", help="AII 输出的 JSON 包路径")
    parser.add_argument("--dry-run", action="store_true", help="预演，不写库")
    args = parser.parse_args()

    with open(args.json_file, encoding="utf-8") as f:
        pkg = json.load(f)

    # ── 校验 ──
    errors = validate(pkg)
    if errors:
        for e in errors:
            print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    tb       = pkg["textbook"]
    clusters = pkg["clusters"]
    units    = pkg["units"]

    print(f"[INFO] 教材: {tb['book_name']}  ({tb['subject']} {tb['grade']} {tb['edition']})")
    print(f"[INFO] clusters: {len(clusters)}, units: {len(units)}")

    if args.dry_run:
        print("[DRY-RUN] 预演通过，不写库。")
        # 打印前 3 个 unit 供检查
        for u in units[:3]:
            prereqs = u.get("prerequisites", [])
            print(f"  ku={u['id']}  cluster={u['cluster_id']}  prereqs={prereqs}")
        return

    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                # 1. textbook
                upsert_textbook(cur, tb)

                # 2. clusters（按 display_order 顺序）
                for c in sorted(clusters, key=lambda x: x.get("display_order", 0)):
                    upsert_cluster(cur, tb["id"], c)

                # 3. units
                for u in units:
                    upsert_unit(cur, u)

        print(f"[OK] 导入完成: {len(clusters)} 个 cluster, {len(units)} 个 KU")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
