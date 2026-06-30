"""从 GAOKAO-Bench（AsakusaRinne/gaokao_bench）导入高考选择题到公共题库（item 10 数据接线）。

补 C-Eval 没有的英语，并增厚物理/语文。这些 MCQ config 的题面已内嵌选项、answer 为单字母。
写入 wrong_questions(student_id=NULL)，subject 存英文代码（与前端 listPracticeTopics 一致）。

  python scripts/import_gaokao_questions.py [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import urllib.parse
import urllib.request

import asyncpg

from obase.config import settings

# target_code → [(gaokao_config, 簇名)]
SUBJECTS: dict[str, list[tuple[str, str]]] = {
    "english": [("2010-2013_English_MCQs", "高考英语单选")],
    "physics": [("2010-2022_Physics_MCQs", "高考物理选择")],
    "chinese": [("2010-2022_Chinese_Lang_and_Usage_MCQs", "高考语文语用")],
}
_BASE = "https://datasets-server.huggingface.co/rows"
_ANS_RE = re.compile(r"[A-D]{1,2}")


def fetch_all(config: str) -> list[dict]:
    """分页拉取 gaokao_bench 某 config 的 dev 切分全部行。"""
    out: list[dict] = []
    offset = 0
    while True:
        qs = urllib.parse.urlencode(
            {"dataset": "AsakusaRinne/gaokao_bench", "config": config,
             "split": "dev", "offset": offset, "length": 100})
        with urllib.request.urlopen(f"{_BASE}?{qs}", timeout=30) as resp:
            data = json.loads(resp.read())
        rows = [r["row"] for r in data.get("rows", [])]
        out.extend(rows)
        total = data.get("num_rows_total", len(out))
        offset += len(rows)
        if not rows or offset >= total:
            break
    return out


async def run(dry_run: bool) -> None:
    conn = await asyncpg.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
    stats = {"ok": 0, "skip": 0, "bad": 0}
    try:
        for code, configs in SUBJECTS.items():
            for config, cluster in configs:
                kp_key = f"gaokao-{code}-{cluster}"
                kp = json.dumps({kp_key: cluster}, ensure_ascii=False)
                try:
                    rows = fetch_all(config)
                except Exception as e:
                    print(f"  ⚠ 拉取失败 {config}: {e}")
                    continue
                for row in rows:
                    ans = (row.get("answer") or "").strip().upper()
                    qtext = (row.get("question") or "").strip()
                    if not _ANS_RE.fullmatch(ans) or len(qtext) < 5:
                        stats["bad"] += 1
                        continue
                    gid = f"{config}-{row.get('index')}"
                    if dry_run:
                        stats["ok"] += 1
                        if stats["ok"] <= 3:
                            print(f"  [{code}·{cluster}] {qtext[:55].replace(chr(10),' ')}… → {ans}")
                        continue
                    if await conn.fetchval(
                        "select 1 from wrong_questions where student_id is null "
                        "and profiler_analysis->>'gaokao_id' = $1", gid):
                        stats["skip"] += 1
                        continue
                    prof = json.dumps(
                        {"source": "gaokao_bench", "gaokao_id": gid, "cluster": cluster,
                         "analysis": row.get("analysis", ""), "year": row.get("year")},
                        ensure_ascii=False)
                    await conn.execute(
                        """INSERT INTO wrong_questions
                               (id, paper_id, student_id, subject, question_text,
                                student_answer, correct_answer, knowledge_points,
                                profiler_analysis, needs_image)
                           VALUES (gen_random_uuid(), NULL, NULL, $1, $2,
                                   NULL, $3, $4::jsonb, $5::jsonb, false)""",
                        code, qtext, ans, kp, prof)
                    stats["ok"] += 1
                print(f"  {config}: 累计 ok={stats['ok']} skip={stats['skip']} bad={stats['bad']}")
    finally:
        await conn.close()
    print(f"\n完成 dry_run={dry_run}: 导入={stats['ok']} 跳过={stats['skip']} 无效={stats['bad']}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    asyncio.run(run(p.parse_args().dry_run))


if __name__ == "__main__":
    sys.exit(main())
