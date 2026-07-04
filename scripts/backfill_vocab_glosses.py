"""U.19 英语习得型范式：回填 vocabulary_items 里 meaning_cn/pos 为空的行。

import_english_vocab_reading.py 首次导入时若无可用 LLM provider（如 GPU 被
占满），meaning_cn/pos 留空、词/例句/频率档已落库。GPU 空闲后跑本脚本只补
空字段，不重新跑词频/难度统计（那部分是确定性的，早就跑完了）。

跑法（容器内）：
  docker compose exec api python scripts/backfill_vocab_glosses.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services  # noqa: E402,F401  (vendor sys.path shim)
from oprim._vocab_gloss_generate import generate_vocab_glosses  # noqa: E402


async def run(batch_size: int) -> None:
    from obase.provider_registry import ProviderRegistry
    from services.providers.setup import configure_llm_providers

    configure_llm_providers()
    try:
        caller = ProviderRegistry.get().llm("default")
    except Exception as exc:
        print(f"无可用 LLM provider（{exc}），退出")
        return

    dsn = os.environ.get(
        "DATABASE_URL_SYNC", "postgresql://postgres:postgres@db:5432/mneme"
    )
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute(
        "SELECT word, example_sentence FROM vocabulary_items WHERE meaning_cn IS NULL"
    )
    rows = cur.fetchall()
    print(f"待回填 {len(rows)} 个词")

    n_filled = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        entries = [{"word": w, "example_sentence": ex or w} for w, ex in batch]
        try:
            glosses = await generate_vocab_glosses(entries, caller=caller)
        except Exception as exc:
            print(f"  ⚠️ 批次 {i}-{i + len(batch)} 失败（{exc}），跳过")
            continue
        for g in glosses:
            if g.get("meaning_cn") is None:
                continue
            pos = (g.get("pos") or "")[:20] or None
            try:
                cur.execute(
                    "UPDATE vocabulary_items SET pos = %s, meaning_cn = %s "
                    "WHERE word = %s AND meaning_cn IS NULL",
                    (pos, g.get("meaning_cn"), g["word"]),
                )
                n_filled += cur.rowcount
            except Exception as exc:
                print(f"  ⚠️ {g['word']} 写入失败（{exc}），跳过")
                conn.rollback()
                continue
        conn.commit()
        print(f"  已处理 {i + len(batch)}/{len(rows)}，累计回填 {n_filled}")

    cur.close()
    conn.close()
    print(f"完成：回填 {n_filled}/{len(rows)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=20)
    args = parser.parse_args()
    asyncio.run(run(args.batch_size))
