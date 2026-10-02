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


def apply_gloss_batch(cur, batch, glosses) -> int:
    """把一批 gloss 写回 vocabulary_items，返回实际写入行数。

    batch: [(id, word, example_sentence), ...]
    glosses: generate_vocab_glosses 的返回，与 batch 等长同序。

    抽出成独立函数是为了能对着假 cursor 做回归测试——本函数历史上出过两个
    静默写错数据的 bug（按 word 更新、无上下文也猜），都需要单测钉住。
    """
    n_filled = 0
    idx = 0
    for g in glosses:
        # 位置对齐必须在**每个**返回项上推进，包括要丢弃的——否则一旦某个 gloss
        # 缺 meaning_cn，后面全部错位，会把释义写到别的词上。
        if idx >= len(batch):
            print("  ⚠️ 返回项多于输入，停止本批")
            break
        row_id, row_word, _ex = batch[idx]
        idx += 1
        if row_word != g.get("word"):
            print(f"  ⚠️ 顺序/词不匹配（期望 {row_word}，得到 {g.get('word')}），跳过")
            continue
        if g.get("meaning_cn") is None:
            continue
        pos = (g.get("pos") or "")[:20] or None
        # 按 id 定位，绝不按 word：word 在本表**不唯一**（24,681 行 /
        # 24,441 个不同词，240 个词重复）。按 word 更新会把一个义项的释义覆盖到
        # 同名其它行，且先命中的无上下文行会挤掉后命中有上下文的好结果。
        cur.execute(
            "UPDATE vocabulary_items SET pos = %s, meaning_cn = %s "
            "WHERE id = %s AND meaning_cn IS NULL",
            (pos, g.get("meaning_cn"), row_id),
        )
        n_filled += cur.rowcount
    return n_filled


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
    # 只处理「有真实例句」的词。
    # 早期版本用 `ex or w` 把词本身当例句，等于零上下文交给 LLM 猜义项——
    # 那正是 oprim._vocab_gloss_generate 契约明令禁止的（"例句由调用方从语料库
    # 确定性抽取，不是 LLM 编的"），多义词会被猜错（bank=河岸/银行）。
    # 现在无例句一律不猜，例句由 scripts/extract_vocab_examples.py 先行补齐。
    cur.execute(
        "SELECT id, word, example_sentence FROM vocabulary_items "
        "WHERE meaning_cn IS NULL "
        "  AND example_sentence IS NOT NULL AND example_sentence <> ''"
    )
    rows = cur.fetchall()
    cur.execute(
        "SELECT count(*) FROM vocabulary_items "
        "WHERE meaning_cn IS NULL "
        "  AND (example_sentence IS NULL OR example_sentence = '')"
    )
    n_no_ctx = cur.fetchone()[0]
    print(f"待回填 {len(rows)} 个词（有例句）")
    print(f"跳过 {n_no_ctx} 个词（无例句，无上下文不猜义项）")

    n_filled = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        entries = [{"word": w, "example_sentence": ex} for _id, w, ex in batch]
        try:
            glosses = await generate_vocab_glosses(entries, caller=caller)
        except Exception as exc:
            print(f"  ⚠️ 批次 {i}-{i + len(batch)} 失败（{exc}），跳过")
            continue
        try:
            n_filled += apply_gloss_batch(cur, batch, glosses)
        except Exception as exc:
            print(f"  ⚠️ 批次 {i}-{i + len(batch)} 写入失败（{exc}），回滚该批")
            conn.rollback()
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
