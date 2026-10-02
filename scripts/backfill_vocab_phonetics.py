"""P0.3b 从 CMUdict 回填 vocabulary_items.phonetic_arpabet（美式发音音标）。

数据源：CMUdict（cmusphinx/cmudict），许可明示「for any research or commercial
purpose is completely unrestricted」，使用需致谢 Carnegie Mellon University。
文件放 data/external/（.gitignore 已忽略该目录），不进版本库。

为什么存 ARPAbet 而不是 IPA：见 alembic a7b8c9d0e1f2 的 docstring —— 现有
phonetic_* 三列装的是教材词表的 IPA，混写会出现两套记音体系。本脚本只写
phonetic_arpabet，phonetic_uk / phonetic_generic 保持 NULL（CMUdict 只有北美
发音，编造英音是错的）。

英式拼写变体：核心范围是英式教材词表（aeroplane/colourful/maths…），CMUdict 是
北美库，这些词查不到。用一张**显式可审计**的映射表转成美式拼写再查，而不是
模糊匹配——模糊匹配会把「不同词」判成「同一个词」，给孩子看错发音。

只写 phonetic_arpabet IS NULL 的行，天然幂等；按 id 更新（word 不唯一）。

    docker compose exec api python scripts/backfill_vocab_phonetics.py
    docker compose exec api python scripts/backfill_vocab_phonetics.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services  # noqa: E402,F401  (vendor sys.path shim)
from obase.db import SessionLocal  # noqa: E402
from sqlalchemy import text  # noqa: E402

CORE_COLLECTION = "core-exam-zhongkao-gaokao-k12"

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DICT = _REPO_ROOT / "data" / "external" / "cmudict.dict"
CMUDICT_URL = "https://raw.githubusercontent.com/cmusphinx/cmudict/master/cmudict.dict"

# 英式→美式拼写变体：仅用于「让英式教材词能在北美 CMUdict 里查到发音」。
# 显式枚举，不做模糊匹配。取自核心范围实际缺失的 18 个单词中属于英式拼写的那部分。
BRITISH_TO_AMERICAN = {
    "aeroplane": "airplane",
    "colourful": "colorful",
    "kilogramme": "kilogram",
    "yoghurt": "yogurt",
    "speciality": "specialty",
    "realise": "realize",
    "recognise": "recognize",
    "organise": "organize",
    "apologise": "apologize",
    "theatre": "theater",
    "metre": "meter",
    "litre": "liter",
    "fibre": "fiber",
    "centre": "center",
    "favourite": "favorite",
    "colour": "color",
    "flavour": "flavor",
    "honour": "honor",
    "neighbour": "neighbor",
    "travelling": "traveling",
    "programme": "program",
    "practise": "practice",
    "storey": "story",
}


def load_cmudict(path: Path) -> dict[str, str]:
    """解析 CMUdict -> {lower_word: "ARPAbet"}。

    注意必须按**第一个**空格切分。写成 rsplit(' ', 1) 会把音标截到只剩最后一个
    音素、并把前面的音素并进「词」里，表现为「几乎全部查不到」（实测 0.1% 而不是
    81.7%）——静默且极具误导性，tests/test_vocab_phonetics.py 钉住了这一点。
    """
    out: dict[str, str] = {}
    with path.open(encoding="latin-1") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";;;"):
                continue
            parts = line.split(" ", 1)
            if len(parts) != 2:
                continue
            word, pron = parts[0].strip(), parts[1].strip()
            if not word or not pron:
                continue
            # 多发音取第一个：CMUdict 同一词通常只有一行；重复时保持确定性。
            out.setdefault(word.lower(), pron)
    return out


def lookup(word: str, cmudict: dict[str, str]) -> tuple[str | None, str]:
    """返回 (arpabet, 命中方式)。命中方式用于报告，便于审计英式变体用了多少。"""
    key = word.strip().lower()
    if not key:
        return None, "none"
    if key in cmudict:
        return cmudict[key], "direct"
    alt = BRITISH_TO_AMERICAN.get(key)
    if alt and alt in cmudict:
        return cmudict[alt], f"variant:{alt}"
    return None, "none"


_SUMMARY_SQL = text(
    """
    WITH target AS (
        SELECT v.id, v.word
        FROM vocabulary_items v
        JOIN vocabulary_collection_memberships m ON m.vocabulary_item_id = v.id
        WHERE m.collection_id = :collection
          AND coalesce(v.phonetic_arpabet, '') = ''
    )
    SELECT count(*) FROM target
    """
)


async def run(collection: str, dict_path: Path, apply: bool) -> None:
    if not dict_path.exists():
        print(f"缺少 CMUdict：{dict_path}")
        print(f"下载：curl -L -o {dict_path} {CMUDICT_URL}")
        return

    cmudict = load_cmudict(dict_path)
    print(f"CMUdict: {dict_path} · {len(cmudict)} 词条")

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT v.id, v.word FROM vocabulary_items v "
                    "JOIN vocabulary_collection_memberships m ON m.vocabulary_item_id = v.id "
                    "WHERE m.collection_id = :c AND coalesce(v.phonetic_arpabet,'') = ''"
                ),
                {"c": collection},
            )
        ).all()

        resolved: list[tuple[str, str, str]] = []  # (vid, arpabet, how)
        misses: list[str] = []
        for vid, word in rows:
            pron, how = lookup(word, cmudict)
            if pron:
                resolved.append((vid, pron, how))
            else:
                misses.append(word)

        total = len(rows)
        n_direct = sum(1 for r in resolved if r[2] == "direct")
        n_var = len(resolved) - n_direct
        print(f"目标范围 collection={collection}")
        print(f"  待补音标词数   = {total}")
        print(f"  命中           = {len(resolved)}  ({len(resolved)/total*100:.1f}%)")
        print(f"    直接命中     = {n_direct}")
        print(f"    英式变体命中 = {n_var}  ({', '.join(sorted({r[2].split(':',1)[1] for r in resolved if r[2] != 'direct'})) or '-'})")
        print(f"  未命中         = {len(misses)}")
        if misses:
            print(f"    未命中样例: {', '.join(misses[:15])}")

        # ARPAbet 音素最长也就 60 余字符；超长说明解析异常，宁可不写。
        resolved = [r for r in resolved if len(r[1]) <= 100]
        if not resolved:
            print("无可写入项，退出")
            return

        if not apply:
            print(f"\n[dry-run] 将更新 {len(resolved)} 行的 phonetic_arpabet。未落库。")
            for vid, pron, how in resolved[:5]:
                print(f"    [{how}] {pron}")
            return

        now = datetime.now(timezone.utc)
        n = 0
        for vid, pron, _how in resolved:
            await db.execute(
                text(
                    "UPDATE vocabulary_items SET phonetic_arpabet = :p, updated_at = :now "
                    "WHERE id = :vid AND coalesce(phonetic_arpabet, '') = ''"
                ),
                {"p": pron, "now": now, "vid": vid},
            )
            n += 1
            if n % 500 == 0:
                await db.commit()
                print(f"  …已更新 {n}/{len(resolved)}")
        await db.commit()

        done = (
            await db.execute(
                text(
                    "SELECT count(*) FROM vocabulary_items v "
                    "JOIN vocabulary_collection_memberships m ON m.vocabulary_item_id = v.id "
                    "WHERE m.collection_id = :c AND coalesce(v.phonetic_arpabet,'') <> ''"
                ),
                {"c": collection},
            )
        ).scalar()
        print(f"\n完成：本次更新 {n} 行；范围内已有音标 {done} 词")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    parser.add_argument("--collection", default=CORE_COLLECTION)
    parser.add_argument("--dict", type=Path, default=DEFAULT_DICT)
    args = parser.parse_args()
    asyncio.run(run(args.collection, args.dict, apply=args.apply))