#!/usr/bin/env python3
"""
export_ku_package.py — 把库内知识单元导出为可复现的 JSON 包（import_ku_package.py 的逆操作）

动机（审计 2026-07-03）：12,573 个 KU（含"讲透" rich_content）此前只存在于 DB，
一次性脚本生成、无 seed/迁移固化 → 容器重建即清零且不可复现。
本脚本把 DB 内容导出为 **git/备份可追踪的资产包**，与 import_ku_package.py 完整往复
（含 rich_content/provenance/verified 等全部内容字段），从此内容是可复现资产而非易失状态。

用法:
  python scripts/export_ku_package.py --out data/ku_packages            # 每教材一个 JSON
  python scripts/export_ku_package.py --out data/ku_packages --textbook RENJIAO-G10-MATH-BX1
  python scripts/export_ku_package.py --stdout --textbook <id>          # 单包打到 stdout

复现流程:  export → 提交 data/ku_packages/*.json 进 git → 新库 import_ku_package.py 逐包回放
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# 注意：psycopg2 只在真正连库时（main/export_textbook）惰性 import，
# 使纯函数 build_package 无需数据库驱动即可被测试/复用。

DATABASE_URL_SYNC = os.environ.get(
    "DATABASE_URL_SYNC",
    "postgresql://postgres:postgres@localhost:5433/mneme",
)

# 内容字段全集：与 import 往复的权威列表（新增列时两处同步）
UNIT_FIELDS = [
    "id",
    "textbook_id",
    "cluster_id",
    "name",
    "description",
    "prerequisites",
    "related_kus",
    "difficulty",
    "exam_frequency",
    "question_types",
    "ku_type",
    "curriculum_standard",
    "mastery_levels",
    "rich_content",
    "provenance",
    "source_excerpt",
    "ai_generated",
    "verified",
]


def build_package(tb: dict, clusters: list[dict], units: list[dict]) -> dict:
    """纯函数：库行 → 包 dict。无 DB 依赖，便于离线往复测试。"""
    return {
        "textbook": {
            "id": tb["id"],
            "subject": tb.get("subject"),
            "grade": tb.get("grade"),
            "edition": tb.get("edition"),
            "book_name": tb.get("book_name"),
        },
        "clusters": [
            {
                "id": c["id"],
                "name": c["name"],
                "display_order": c.get("display_order", 0),
                "description": c.get("description"),
            }
            for c in sorted(
                clusters, key=lambda c: (c.get("display_order", 0), c["id"])
            )
        ],
        "units": [
            {k: u.get(k) for k in UNIT_FIELDS}
            for u in sorted(units, key=lambda u: u["id"])
        ],
    }


def _fetch(cur, sql: str, args: tuple) -> list[dict]:
    cur.execute(sql, args)
    return [dict(r) for r in cur.fetchall()]


def export_textbook(cur, textbook_id: str) -> dict | None:
    tbs = _fetch(
        cur,
        "SELECT id, subject, grade, edition, book_name FROM textbooks WHERE id=%s",
        (textbook_id,),
    )
    if not tbs:
        return None
    clusters = _fetch(
        cur,
        "SELECT id, name, display_order, description FROM knowledge_clusters WHERE textbook_id=%s",
        (textbook_id,),
    )
    units = _fetch(
        cur,
        f"SELECT {', '.join(UNIT_FIELDS)} FROM knowledge_units WHERE textbook_id=%s",
        (textbook_id,),
    )
    return build_package(tbs[0], clusters, units)


def main() -> None:
    ap = argparse.ArgumentParser(description="导出 KU 为可复现 JSON 包")
    ap.add_argument("--out", help="输出目录（每教材一个 <id>.json）")
    ap.add_argument(
        "--stdout", action="store_true", help="打到标准输出（需配 --textbook）"
    )
    ap.add_argument("--textbook", help="只导出指定教材 id；缺省导出全部有 KU 的教材")
    args = ap.parse_args()

    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(DATABASE_URL_SYNC)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if args.textbook:
        ids = [args.textbook]
    else:
        cur.execute("SELECT DISTINCT textbook_id FROM knowledge_units ORDER BY 1")
        ids = [r["textbook_id"] for r in cur.fetchall()]

    if not ids:
        print("[export] 库内无 KU（0 行）——无内容可导出。", file=sys.stderr)
        return

    if args.stdout:
        if len(ids) != 1:
            sys.exit("--stdout 需配单一 --textbook")
        print(json.dumps(export_textbook(cur, ids[0]), ensure_ascii=False, indent=2))
        return

    if not args.out:
        sys.exit("需 --out 目录 或 --stdout")
    os.makedirs(args.out, exist_ok=True)
    total = 0
    for tid in ids:
        pkg = export_textbook(cur, tid)
        if not pkg:
            continue
        path = os.path.join(args.out, f"{tid}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(pkg, f, ensure_ascii=False, indent=2)
        n = len(pkg["units"])
        total += n
        print(f"  {tid}: {n} KU -> {path}")
    print(f"[export] {len(ids)} 教材 / {total} KU 导出完成 -> {args.out}")


if __name__ == "__main__":
    main()
