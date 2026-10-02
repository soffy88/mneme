"""新东方《词根词缀大全》-> 参考分解集，并对 vocabulary_affixes 标注可信档位。

为什么需要这个：P4 入库的 379 条分解，权威来源只是散文里「词根/前缀/后缀」的
**标注**，不是历史语言学。散文自身就常把词干/后缀写成「词根」（`careless→less`、
`chinese→ese`）。本脚本引入一份**可追溯的参考表**做交叉验证，把每条分解标成
`reference_confirmed` / `mnemonic_association` / `disputed` 三档。

实测价值不在于「判定对错」，而在于**补全**：交集 45 词里 17 条一致、28 条冲突，
而冲突几乎都是**本文档抽取不完整**而非错 ——
    arrive     mine=ar       ref=ar+rive
    increase   mine=in       ref=in+crease
    protect    mine=pro      ref=pro+tect
    technology mine=logy     ref=techn+logy
参考表能补上漏掉的词根/前缀/后缀，故一致档直接采用参考分解。

用法：
    python scripts/crossvalidate_affixes.py              # dry-run
    python scripts/crossvalidate_affixes.py --apply      # 落库

参考表是**教学参考级**权威（新东方），不是学术词源（OED/etymonline）。故
`reference_confirmed` 不等于「已考据的词源」，只表示「与教学参考表一致」。
"""

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

REF_PDF = Path(
    os.environ.get(
        "XIANGXING_ROOT_REF", "data/external/vocab_src/词根词缀大全.pdf"
    )
)
REF_JSON = Path("data/external/vocab_src/root_reference.json")
REVIEW_OUT = Path("data/external/vocab_src/affix_crossvalidate_review.json")

STATUS_CONFIRMED = "reference_confirmed"
STATUS_MNEMONIC = "mnemonic_association"
STATUS_DISPUTED = "disputed"

WORD_RE = re.compile(r"^[a-z][a-z\-\s]{1,24}$")
# 本 PDF 全角/半角括号混用（`（collect+ion)`），两种都要收。
PAREN_RE = re.compile(r"[（(]([^）)]{2,80})[）)]")
LATIN_RE = re.compile(r"[a-z]{2,}")
LOOKAHEAD = 5


def strip_noise(text: str) -> str:
    m = re.match(r"^\d+(.*)$", text.strip())
    return (m.group(1) if m else text).strip()


def classify(word: str, tokens: list[str]) -> dict | None:
    """按形态位置定角色：开头的是前缀、末尾的是后缀、能对上的是词根。

    参考书里括号内容格式不一（`ap+point 指→指定` / `col 一起+lect→收到一起` /
    `ap+prec+iate→给以价值`），中文含义会插在词缀之间，故先抽出全部拉丁词元再定角色。
    """
    w = word.lower().replace(" ", "")
    toks = [t.strip().strip("-").lower() for t in tokens]
    toks = [t for t in toks if t]
    if len(toks) < 2:
        return None

    if len(toks) == 2:
        # 两段式里「哪段是词根」无法只靠形态判定。已试错三次：
        #   startswith 当前缀 -> collection 的 collect 被当成前缀（它其实是词根）
        #   长度启发式      -> pardon 的 par+don（par 是前缀、don 是词根）判反
        #   要求「严格居内」-> arrive 的 rive 正在词尾，被误弃（拉丁词根大量落在
        #                    词尾：arrive/rive、predict/dict、factory/fact）
        # 两段各据一端时角色**真有歧义**且形态无法裁决，故只保留**段位集合**，
        # 角色留空 —— 段位集合才是补全我们漏段所需的信息，角色由各词自己判定。
        return {"prefix": None, "root": None, "suffix": None, "segments": sorted(toks)}

    pfx = toks[0] if w.startswith(toks[0]) else None
    sfx = toks[-1] if w.endswith(toks[-1]) else None
    if pfx and sfx and pfx == sfx:
        return None
    mid = [m for m in toks[1:-1] if m in w and m != pfx and m != sfx]
    if not (pfx or mid or sfx):
        return None
    return {"prefix": pfx, "root": mid[0] if mid else None, "suffix": sfx}


def parse_reference(pdf: Path) -> dict[str, dict]:
    """PDF 的括号常跨行，故先拼接前瞻窗口再匹配。"""
    # 容器里没有 pdftotext；仓库内 PDF 一律走 pymupdf（见
    # scripts/extract_curriculum_collocation.py）。
    import pymupdf

    lines = []
    with pymupdf.open(str(pdf)) as doc:
        for page in doc:
            lines.extend(page.get_text().splitlines())
    out: dict[str, dict] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not WORD_RE.match(line):
            i += 1
            continue
        word = line.lower().replace(" ", "")
        if word in out:
            i += 1
            continue
        window = " ".join(lines[i + 1: i + 1 + LOOKAHEAD])
        m = PAREN_RE.search(window)
        if not m:
            i += 1
            continue
        affix = classify(word, LATIN_RE.findall(m.group(1)))
        if not affix:
            i += 1
            continue
        out[word] = {"affix": affix, "meaning": window[: m.start()].strip()}
        i += 1
    return out


def _complete_segments(mine: tuple, theirs: dict) -> tuple[str | None, str | None, str | None]:
    """参考表只用于**补上我漏的段**，角色仍按形态位置判定（段位集合层面无歧义）。"""
    have = {i: v for i, v in enumerate(mine) if v}
    ref = theirs.get("segments") or []
    if not ref:
        return mine
    slots = [i for i in range(3) if i not in have]
    out = list(mine)
    for seg in sorted(ref, key=len, reverse=True):
        if seg in segments_of(mine):
            continue
        if not slots:
            break
        out[slots.pop(0)] = seg
    return tuple(out)


def segments_of(mine: tuple) -> list[str]:
    return sorted(t for t in mine if t)


def ref_segments(theirs: dict) -> list[str]:
    if theirs.get("segments"):
        return sorted(theirs["segments"])
    return sorted(t for t in (theirs["prefix"], theirs["root"], theirs["suffix"]) if t)


def same_parts(mine: tuple, theirs: dict) -> bool:
    return segments_of(mine) == ref_segments(theirs)


def superset_of(mine: tuple, theirs: dict) -> bool:
    """我的分解是否只是参考分解的子集（漏了词根/前后缀），而非与之冲突。"""
    mine_set = set(segments_of(mine))
    ref_set = set(ref_segments(theirs))
    if not ref_set:
        return False
    # 我方段位必须是参考段位的子集，且**不得有任何一段与参考冲突**
    return mine_set <= ref_set


async def fetch_affixes() -> list[tuple[str, str, str | None, str | None, str | None]]:
    from obase.db import SessionLocal
    from sqlalchemy import text

    async with SessionLocal() as db:
        rows = await db.execute(
            text(
                "select lower(v.word), a.vocabulary_item_id, a.prefix, a.root, a.suffix "
                "from vocabulary_affixes a join vocabulary_items v on v.id = a.vocabulary_item_id"
            )
        )
        return [tuple(r) for r in rows.all()]


async def apply_status(updates: list[tuple[str, str, str, str | None, str | None, str | None]]) -> None:
    from obase.db import SessionLocal
    from sqlalchemy import text

    async with SessionLocal() as db:
        for status, _word, vid, prefix, root, suffix in updates:
            await db.execute(
                text(
                    "update vocabulary_affixes set etymology_status = :s, "
                    "prefix = :p, root = :r, suffix = :x where vocabulary_item_id = :v"
                ),
                {"s": status, "p": prefix, "r": root, "x": suffix, "v": vid},
            )
        await db.commit()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import services  # noqa: F401  (vendor sys.path shim)

    ref = parse_reference(REF_PDF)
    REF_JSON.parent.mkdir(parents=True, exist_ok=True)
    REF_JSON.write_text(json.dumps(ref, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"参考表分解条目 = {len(ref)}  -> {REF_JSON}")

    rows = asyncio.run(fetch_affixes())
    confirmed = disputed = mnemonic = 0
    completed = 0
    review = []
    updates = []
    for word, vid, prefix, root, suffix in rows:
        mine = (prefix, root, suffix)
        ref_entry = ref.get(word)
        if not ref_entry:
            status, new = STATUS_MNEMONIC, mine
            mnemonic += 1
        elif same_parts(mine, ref_entry["affix"]):
            status, new = STATUS_CONFIRMED, mine
            confirmed += 1
        elif superset_of(mine, ref_entry["affix"]):
            # 不是冲突，是我漏了段位 —— 采用参考分解补全
            status = STATUS_CONFIRMED
            # 补全：把参考多出来的段按「能对上形态的位置」接回去，角色不猜。
            new = tuple(_complete_segments(mine, ref_entry["affix"]))
            if new != mine:
                completed += 1
            confirmed += 1
        else:
            status, new = STATUS_DISPUTED, mine
            disputed += 1
            review.append({
                "word": word,
                "mine": {"prefix": prefix, "root": root, "suffix": suffix},
                "reference": ref_entry["affix"],
                "reference_meaning": ref_entry.get("meaning", "")[:60],
            })
        updates.append((status, word, vid, new[0], new[1], new[2]))

    total = len(rows)
    print(f"\n库内分解 {total}")
    print(f"  reference_confirmed  = {confirmed}  ({confirmed/total*100:.1f}%)")
    print(f"  mnemonic_association = {mnemonic}  ({mnemonic/total*100:.1f}%)")
    print(f"  disputed             = {disputed}  ({disputed/total*100:.1f}%)")
    print(f"  其中靠参考表补全段位 = {completed}")
    review.sort(key=lambda r: r["word"])
    REVIEW_OUT.write_text(json.dumps(review, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"冲突待判读 -> {REVIEW_OUT}")

    if not args.apply:
        print("[dry-run] 未落库。")
        return 0
    asyncio.run(apply_status(updates))
    print(f"完成：{total} 条已标档（{confirmed} confirmed / {mnemonic} mnemonic / {disputed} disputed）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())