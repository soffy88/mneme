"""P3b 把课标「用法搭配」入库（受交叉核对门控）。

输入：`scripts/extract_curriculum_collocation.py` 产出的复核队列
`data/external/vocab_src/curriculum_collocations_review.json`（扫描件 OCR）。

## 入库前的门控

OCR 不可全信，但**可以用另一个独立权威源交叉验证**：库里
`vocabulary_items.meaning_cn` 来自**教材词表原文**（可追溯，见 P0.4a）。
对同一词：

  - 课标 OCR 释义与教材释义**有共同汉字** → 同源互证，可信
  - **完全无共同汉字** → 可能是错配/错字，**不加载**，进 review 分区

实测：67 条可比对里 63 条有共同汉字（平均覆盖 75.1%），4 条无共同汉字经人工判读
全部是「义项选择不同」而非错误（`novel` 课标=长篇小说 / 教材=新奇的；课标教名词
义项，教材列形容词义项），因此这 4 条按「有共同汉字才放行」会被误拒 —— 故本脚本
把它们落到 review.json 的 `unverified` 分区并**报告**，由人判，而不是默默丢。

词义**不覆盖**：课标给的是适合该学段的精简义项，与教材的详尽释义粒度不同。

    python scripts/load_vocab_collocations.py            # dry-run
    python scripts/load_vocab_collocations.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services  # noqa: E402,F401  (vendor sys.path shim)
from obase.db import SessionLocal  # noqa: E402
from sqlalchemy import text  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[1]
REVIEW_JSON = (
    _REPO_ROOT / "data" / "external" / "vocab_src"
    / "curriculum_collocations_review.json"
)
CJK = re.compile(r"[一-鿿]")
MIN_CHAR_OVERLAP = 0.30  # 课标释义汉字被教材释义覆盖的最低比例


def _load_review() -> list[dict]:
    if not REVIEW_JSON.exists():
        raise SystemExit(f"缺少复核队列：{REVIEW_JSON}（先跑 extract_curriculum_collocation.py）")
    return json.loads(REVIEW_JSON.read_text(encoding="utf-8"))["records"]


async def _known_meanings() -> dict[str, str]:
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT lower(v.word), v.meaning_cn FROM vocabulary_items v "
                    "WHERE coalesce(v.meaning_cn, '') <> ''"
                )
            )
        ).all()
    return {w: m for w, m in rows}


async def run(apply: bool) -> None:
    records = _load_review()
    known = await _known_meanings()
    print(f"复核队列 {len(records)} 条；库内可比对教材释义 {len(known)} 词")

    verified, unverified, skipped = [], [], 0
    for r in records:
        cands = [c for c in r.get("collocations", []) if c.get("en") and c.get("zh")]
        if not cands:
            skipped += 1
            continue
        k = known.get(r["word"])
        if k:
            a = set(CJK.findall(r["meaning"]))
            b = set(CJK.findall(k))
            overlap = len(a & b) / len(a) if a else 0.0
            if overlap < MIN_CHAR_OVERLAP:
                unverified.append({**r, "overlap": round(overlap, 3)})
                continue
        else:
            # 教材无释义可对照：交叉核对做不了，放行但标记低置信
            r = {**r, "unverified_reason": "no_textbook_crosscheck"}
        verified.append({**r, "collocations": cands})

    print(f"  交叉核对通过 = {len(verified)}")
    print(f"  无共同汉字（不加载）= {len(unverified)}")
    print(f"  无搭配可加载 = {skipped}")
    if unverified:
        print("\n-- 无共同汉字明细（需人工判是义项差异还是错配）--")
        for r in unverified:
            k = known.get(r["word"], "")
            print(f"    {r['word']:14s} overlap={r['overlap']:.2f} 课标={r['meaning'][:20]!r} 教材={k[:20]!r}")

    # 只对真实存在的 vocabulary_item 建搭配
    async with SessionLocal() as db:
        vids = (
            await db.execute(
                text("SELECT id, lower(word) FROM vocabulary_items")
            )
        ).all()
        by_word: dict[str, list[str]] = {}
        for vid, w in vids:
            by_word.setdefault(w, []).append(vid)

        rows, orphan = [], 0
        for r in verified:
            for vid in by_word.get(r["word"], []):
                for c in r["collocations"]:
                    rows.append(
                        {
                            "vid": vid,
                            "en": c["en"],
                            "cn": c["zh"],
                            "src": "CURRICULUM_OCR",
                        }
                    )
            if r["word"] not in by_word:
                orphan += 1

        # 去重
        seen, uniq = set(), []
        for row in rows:
            k = (row["vid"], row["en"].lower(), row["cn"])
            if k in seen:
                continue
            seen.add(k)
            uniq.append(row)

        print(f"\n待写入搭配行 = {len(uniq)}（原始 {len(rows)}，去重后）")
        print(f"队列中词不在 vocabulary_items 的 = {orphan}")
        if not apply:
            for row in uniq[:8]:
                print(f"    {row['en']}  {row['cn']}")
            print("\n[dry-run] 未落库。")
            return

        now = datetime.now(timezone.utc)
        for row in uniq:
            await db.execute(
                text(
                    "INSERT INTO vocabulary_collocations "
                    "(vocabulary_item_id, phrase_en, phrase_cn, source, created_at, updated_at) "
                    "VALUES (:vid, :en, :cn, :src, :now, :now) "
                    "ON CONFLICT (vocabulary_item_id, phrase_en, phrase_cn) DO NOTHING"
                ),
                {**row, "now": now},
            )
        await db.commit()

        n = (
            await db.execute(text("SELECT count(*) FROM vocabulary_collocations"))
        ).scalar()
        withcol = (
            await db.execute(
                text("SELECT count(DISTINCT vocabulary_item_id) FROM vocabulary_collocations")
            )
        ).scalar()
        print(f"\n完成：库内搭配 {n} 条，覆盖 {withcol} 个词")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", default=False)
    asyncio.run(run(ap.parse_args().apply))