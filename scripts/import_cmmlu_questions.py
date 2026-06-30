"""从 CMMLU（svjack/cmmlu 合并版 parquet）增厚物理/语文公共题库（item 10 题量扩充）。

CMMLU 是中文 67 学科 MCQ 评测集（question + A/B/C/D + answer + task）。本脚本下载
parquet，挑选与 中学语文/物理 相关的 task 导入 wrong_questions(student_id=NULL)。
英语 CMMLU 无对应 task（中文基准），英语仍由 gaokao 提供。

  python scripts/import_cmmlu_questions.py [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import tempfile
import urllib.request

import asyncpg
import pandas as pd

from obase.config import settings

_PARQUET_URL = "https://huggingface.co/api/datasets/svjack/cmmlu/parquet/default/train/0.parquet"

# target_code → [(cmmlu_task, 簇名)]；只取 K12 语文/物理 相关，剔除史/政/医等非学科
TASK_MAP: dict[str, list[tuple[str, str]]] = {
    "physics": [
        ("high_school_physics", "高中物理"),
        ("conceptual_physics", "概念物理"),
    ],
    "chinese": [
        ("elementary_chinese", "小学语文"),
        ("chinese_literature", "中国文学"),
        ("ancient_chinese", "古代汉语"),
        ("modern_chinese", "现代汉语"),
    ],
}
_ANS_RE = re.compile(r"[A-D]")


def load_df() -> pd.DataFrame:
    url = _PARQUET_URL
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tf:
        path = tf.name
    print(f"下载 CMMLU parquet…")
    urllib.request.urlretrieve(url, path)
    return pd.read_parquet(path)


async def run(dry_run: bool) -> None:
    df = load_df()
    tasks_wanted = {t for cfgs in TASK_MAP.values() for t, _ in cfgs}
    df = df[df["task"].isin(tasks_wanted)]
    cluster_of = {t: c for cfgs in TASK_MAP.values() for t, c in cfgs}
    code_of = {t: code for code, cfgs in TASK_MAP.items() for t, _ in cfgs}

    conn = await asyncpg.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
    stats = {"ok": 0, "skip": 0, "bad": 0}
    try:
        for _, row in df.iterrows():
            ans = str(row.get("answer", "")).strip().upper()
            q = str(row.get("question", "")).strip()
            if not _ANS_RE.fullmatch(ans) or len(q) < 5:
                stats["bad"] += 1
                continue
            task = row["task"]
            code, cluster = code_of[task], cluster_of[task]
            kp_key = f"cmmlu-{code}-{cluster}"
            qtext = q + "\n" + "\n".join(f"{k}. {row.get(k, '')}" for k in ("A", "B", "C", "D"))
            cid = f"cmmlu-{task}-{row.get('id')}"
            if dry_run:
                stats["ok"] += 1
                if stats["ok"] <= 3:
                    print(f"  [{code}·{cluster}] {qtext[:55].replace(chr(10),' ')}… → {ans}")
                continue
            if await conn.fetchval(
                "select 1 from wrong_questions where student_id is null "
                "and profiler_analysis->>'cmmlu_id' = $1", cid):
                stats["skip"] += 1
                continue
            kp = json.dumps({kp_key: cluster}, ensure_ascii=False)
            prof = json.dumps({"source": "cmmlu", "cmmlu_id": cid, "cluster": cluster}, ensure_ascii=False)
            await conn.execute(
                """INSERT INTO wrong_questions
                       (id, paper_id, student_id, subject, question_text,
                        student_answer, correct_answer, knowledge_points,
                        profiler_analysis, needs_image)
                   VALUES (gen_random_uuid(), NULL, NULL, $1, $2,
                           NULL, $3, $4::jsonb, $5::jsonb, false)""",
                code, qtext, ans, kp, prof)
            stats["ok"] += 1
    finally:
        await conn.close()
    print(f"\n完成 dry_run={dry_run}: 导入={stats['ok']} 跳过={stats['skip']} 无效={stats['bad']}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    asyncio.run(run(p.parse_args().dry_run))


if __name__ == "__main__":
    sys.exit(main())
