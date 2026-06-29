"""统一 KU 命名（数据地基）。

现状：知识体系(knowledge_units)与题库(wrong_questions.knowledge_points key)是多套来源、
命名/粒度不一致：题库里 cmm-math-*（粗）与 renjiao 描述式 key 有 1.5 万+ 题，但这些 KU
不在 knowledge_units 里 → 掌握度/错题/lesson 引用到"不存在的 KU"，名字也只能显示原始 key。

做法（安全·幂等·不改题、不删旧 KU）：把每个"有题但不在 knowledge_units"的 KU key，
注册为正式 knowledge_unit，统一挂到一个"真题题库"textbook 下，按年级分 cluster。
结果：每个有练习题的 KU 都成为系统一等公民（命名统一到 knowledge_units 空间）。

跑法：cd mneme && .venv/bin/python scripts/unify_ku_naming.py [--subject math]
"""
from __future__ import annotations

import asyncio
import re
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from obase.config import settings

GRADE_NAME = {1: "一年级", 2: "二年级", 3: "三年级", 4: "四年级", 5: "五年级", 6: "六年级",
              7: "初一", 8: "初二", 9: "初三", 10: "高一", 11: "高二", 12: "高三"}


def parse(key: str) -> tuple[int, str]:
    gm = re.search(r"[gG](\d+)", key)
    grade = int(gm.group(1)) if gm else 0
    name = re.sub(r"^cmm-[a-z]+-g\d+-", "", key)
    name = re.sub(r"^renjiao-[a-z]+-g\d+-[a-z0-9]+-ku-", "", name)
    name = re.sub(r"^RENJIAO-G\d+-[A-Z]+-[A-Z0-9]+-ku-", "", name)
    if name == key:
        name = key.split("-")[-1]
    return grade, name.strip("-") or key


async def main(subject: str) -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    tb_id = f"qbank-{subject}"
    async with engine.begin() as c:
        await c.execute(text(
            "insert into textbooks (id, subject, grade, edition, book_name) "
            "values (:id, :s, '全部', '题库', :bn) on conflict (id) do nothing"
        ), {"id": tb_id, "s": subject, "bn": f"真题题库·{subject}"})

        rows = (await c.execute(text(
            """
            select distinct key from wrong_questions, jsonb_object_keys(knowledge_points) key
            where student_id is null and subject = :s
              and not exists (select 1 from knowledge_units ku where ku.id = key)
            """
        ), {"s": subject})).fetchall()
        keys = [r[0] for r in rows]

        for g in sorted({parse(k)[0] for k in keys}):
            await c.execute(text(
                "insert into knowledge_clusters (id, textbook_id, name, display_order, description) "
                "values (:id, :tb, :name, :ord, '题库主题') on conflict (id) do nothing"
            ), {"id": f"{tb_id}-g{g}", "tb": tb_id,
                "name": f"{GRADE_NAME.get(g, '其它')}·真题", "ord": g})

        for k in keys:
            g, name = parse(k)
            await c.execute(text(
                """
                insert into knowledge_units
                  (id, textbook_id, cluster_id, name, description, prerequisites, related_kus,
                   difficulty, exam_frequency, question_types, ku_type, mastery_levels)
                values (:id, :tb, :cid, :name, '', '[]'::jsonb, '[]'::jsonb,
                   0.5, 'mid', '[]'::jsonb, 'method', '[]'::jsonb)
                on conflict (id) do nothing
                """
            ), {"id": k, "tb": tb_id, "cid": f"{tb_id}-g{g}", "name": name[:120]})

        print(f"回填：{len(keys)} 个孤立 KU 注册到 '{tb_id}'")

    async with engine.connect() as c:
        r = await c.execute(text(
            """
            with keys as (select distinct key from wrong_questions, jsonb_object_keys(knowledge_points) key
                          where student_id is null and subject = :s)
            select count(*), count(*) filter (where exists(select 1 from knowledge_units ku where ku.id = keys.key))
            from keys
            """
        ), {"s": subject})
        total, matched = r.fetchone()
        print(f"统一后：题库 {total} 个 key，knowledge_units 命中 {matched}（{round(matched / max(total, 1) * 100)}%）")
    await engine.dispose()


if __name__ == "__main__":
    subj = "math"
    if "--subject" in sys.argv:
        subj = sys.argv[sys.argv.index("--subject") + 1]
    asyncio.run(main(subj))
