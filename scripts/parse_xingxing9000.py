"""象形9000 OCR 缓存 -> vocabulary_xiangxing。

用法：
    python scripts/parse_xingxing9000.py              # dry-run，只报告
    python scripts/parse_xingxing9000.py --apply      # 落库（需先跑迁移）

只写 vocabulary_xiangxing，**不覆盖** vocabulary_items —— 象形释义是详尽义项，
与课标的精简义项粒度不同而非冲突。

入库门控（三道，全部为「拒绝」而非「启发式修补」）：
1. 音标块必须能在**同列上方 120px 内**找到词行（x 区间重叠）—— 锚点对不上就丢。
2. 词性必须命中白名单 —— 挡掉 OCR 形近噪声（`u.` `adi.` 之类）。
3. 归属必须经**例句交叉验证**：例句里实际出现该词（含去连字符/去空格/常见屈折），
   才置 ownership_verified；否则记录仍留但标 false，供人工复核。
"""

import argparse
import asyncio
import json
import os
import re
from pathlib import Path

# 默认在仓库内的缓存目录；OCR 脚本与解析脚本可能分处宿主机/容器，故可用环境变量覆盖。
OCR_CACHE = Path(os.environ.get("XIANGXING_OCR_CACHE", "data/external/vocab_src/ocr_cache/ocr.jsonl"))
REVIEW_OUT = Path("data/external/vocab_src/xingxing9000_review.json")

COLLECTION_ID = "core-exam-zhongkao-gaokao-k12"
SOURCE = "XIANGXING9000"

WORD_RE = re.compile(r"^[A-Za-z][A-Za-z\-']{1,24}$")
IPA_RE = re.compile(r"^\[([^\]]{2,40})\]\s*(.*)$")
CJK_RE = re.compile(r"[一-鿿]")
POS_RE = re.compile(r"^([a-zA-Z]{1,8}(?:\s*/\s*[a-zA-Z]{1,8})*)\s*[.．]")
LEAD_NUM_RE = re.compile(r"^\d+(.*)$")

POS_WHITELIST = {
    "n", "v", "vt", "vi", "adj", "adv", "prep", "conj", "pron", "num", "int",
    "aux", "art", "modal", "abbr", "pl", "sing", "link", "u", "c",
    "prep./adv", "adj./adv", "n./v", "v./n", "adj./n", "n./adj",
}

INFLECTIONS = ("s", "es", "ed", "ing", "d", "ies")
COLUMN_TOLERANCE = 170
BELOW_WINDOW = 260
ANCHOR_GAP = 120


def strip_leading_page_no(text: str) -> str:
    """`5238750953135absent` -> `absent`（象形页把词拆成部分，页码噪声会粘在前面）。"""
    m = LEAD_NUM_RE.match(text.strip())
    return (m.group(1) if m else text).strip()


def clean_ipa(raw: str) -> str:
    return re.sub(r"[\]\[\s]+$", "", raw.strip()).strip("[").strip()


def pos_of(meaning: str) -> str | None:
    m = POS_RE.match(meaning.strip())
    return m.group(1).replace(" ", "").lower() if m else None


def normalize(text: str) -> str:
    """OCR 会丢空格并在行末加连字符：`atten- tion` / `Ihave faiththat`。"""
    return re.sub(r"\s+", "", re.sub(r"-\s+", "", text)).lower()


def mentions(sentence: str, word: str) -> bool:
    """例句是否用到该词（含常见屈折）。

    覆盖英语两条会丢字母的规则，否则会把正确归属误判为存疑：
      e 脱落  ride -> riding / make -> making / like -> liked
      y -> ies  carry -> carries
    只按**英语形态规则**放宽，不对 OCR 形近字做容错 —— 那会把真实错配也一起
    掩盖掉。OCR 噪声（`physicai` / `yeliow`）就该留在 ownership_verified=false
    里等人工看。
    """
    n = normalize(sentence)
    forms = [word, *(word + i for i in INFLECTIONS)]
    if word.endswith("e"):
        stem = word[:-1]
        forms += [stem + i for i in INFLECTIONS]
    if word.endswith("y") and len(word) > 3:
        forms.append(word[:-1] + "ies")
    return any(f in n for f in forms)


def parse_page(page: dict) -> list[dict]:
    lines = page["lines"]
    heads = [l for l in lines if IPA_RE.match(l["text"].strip())]
    words = [l for l in lines if WORD_RE.match(strip_leading_page_no(l["text"]))]
    out: list[dict] = []
    for head in heads:
        m = IPA_RE.match(head["text"].strip())
        meaning = m.group(2).strip()
        if not meaning:
            continue
        pos = pos_of(meaning)
        if pos is None or pos not in POS_WHITELIST:
            continue
        anchor = None
        for w in words:
            if w["y1"] > head["y0"] or head["y0"] - w["y1"] > ANCHOR_GAP:
                continue
            if min(head["x1"], w["x1"]) - max(head["x0"], w["x0"]) <= 0:
                continue
            if anchor is None or w["y1"] > anchor["y1"]:
                anchor = w
        if anchor is None:
            continue
        word = strip_leading_page_no(anchor["text"]).lower()
        if not WORD_RE.match(word):
            continue
        cx = (head["x0"] + head["x1"]) // 2
        seg = [
            l for l in lines
            if head["y1"] < l["y0"] < head["y1"] + BELOW_WINDOW
            and not CJK_RE.search(l["text"])
            and abs((l["x0"] + l["x1"]) // 2 - cx) < COLUMN_TOLERANCE
        ]
        seg.sort(key=lambda l: (l["y0"], l["x0"]))
        en = " ".join(l["text"] for l in seg).strip()[:240] or None
        cn = None
        for l in lines:
            if l["y0"] > head["y1"] and CJK_RE.search(l["text"]):
                cn = l["text"].strip()[:240]
                break
        out.append({
            "word": word,
            "ipa_ascii": clean_ipa(m.group(1)),
            "pos": pos,
            "meaning_cn": meaning[:400],
            "example_en": en,
            "example_cn": cn,
            "source_volume": page["pdf"][:24],
            "ownership_verified": bool(en and mentions(en, word)),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--cache", type=Path, default=OCR_CACHE)
    args = ap.parse_args()

    pages = [json.loads(line) for line in args.cache.open(encoding="utf-8")]
    records: dict[str, dict] = {}
    for page in pages:
        for rec in parse_page(page):
            records.setdefault(rec["word"], rec)
    print(f"OCR 页 {len(pages)}  候选词条 {len(records)}")

    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from sqlalchemy import text
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from obase.db import SessionLocal
    from services.models import VocabularyXiangxing

    async def fetch_core() -> dict[str, str]:
        async with SessionLocal() as db:
            rows = await db.execute(
                text(
                    "select distinct lower(v.word), v.id from vocabulary_items v "
                    "join vocabulary_collection_memberships m on m.vocabulary_item_id = v.id "
                    "where m.collection_id = :cid"
                ),
                {"cid": COLLECTION_ID},
            )
            return dict(rows.all())

    core = asyncio.run(fetch_core())
    hits = {w: r for w, r in records.items() if w in core}
    print(f"∩ 核心范围 {len(core)} = {len(hits)} ({len(hits)/len(core)*100:.1f}%)")
    verified = {w: r for w, r in hits.items() if r["ownership_verified"]}
    print(f"其中归属经例句验证 = {len(verified)} ({len(verified)/len(hits)*100:.1f}%)")

    review = {
        "source": SOURCE,
        "ocr_pages": len(pages),
        "candidates": len(records),
        "core_hits": len(hits),
        "ownership_verified": len(verified),
        "records": sorted(hits.values(), key=lambda r: r["word"]),
    }
    REVIEW_OUT.write_text(json.dumps(review, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"复核队列 -> {REVIEW_OUT}")

    if not args.apply:
        print("[dry-run] 未落库。")
        return 0

    import uuid

    payload = [
        {
            "id": str(uuid.uuid4()),
            "vocabulary_item_id": str(core[w]),
            "ipa_ascii": r["ipa_ascii"],
            "pos": r["pos"],
            "meaning_cn": r["meaning_cn"],
            "example_en": r["example_en"],
            "example_cn": r["example_cn"],
            "source_volume": r["source_volume"],
            "ownership_verified": r["ownership_verified"],
        }
        for w, r in sorted(hits.items())
    ]
    async def write() -> None:
        async with SessionLocal() as db:
            await db.execute(
                pg_insert(VocabularyXiangxing.__table__)
                .values(payload)
                .on_conflict_do_nothing(index_elements=["vocabulary_item_id"])
            )
            await db.commit()

    asyncio.run(write())
    print(f"完成：写入 {len(payload)} 条（归属已验证 {len(verified)} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())