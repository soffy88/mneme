"""P1 从英译汉 1600 默写版词表回填 vocabulary_items.pos（确定性，零 LLM）。

数据源：`(英译汉)1600词汇单词默写版.pdf`（gdrive `考研成人/英语词汇书`）。
版式为双栏，每格 `[*]word pos`，pos 可能是复合（`prep & ad`、`ad, prep & conj`）。
用 `pdftotext -layout` 保留栏位，按 2+ 空格切栏。

为什么先做这份：它是**人工编排的固定词表**，`pos` 是表里显式标注的字段，
不是从音标或释义推断出来的 —— 与 P0.4a 里被拒的「从词性标签推断」性质不同，
无幻觉风险。核心范围命中 1,120 词，能补 `pos` 缺口。

词性归一化：源表用中文教材缩写（`a`=形容词、`ad`=副词），与库里既有的
`n.`/`noun`/`vt.` 混用。统一映射成标准英文缩写，消除 `a`（形容词）与
冠词 art 的歧义：

    a -> adj    ad -> adv    其余保持（n/v/prep/conj/pron/num/aux/vt/vi/...）

只写 pos 为空的行，按 id 更新（word 不唯一），天然幂等。

    docker compose exec api python scripts/import_pos_from_dictation.py
    docker compose exec api python scripts/import_pos_from_dictation.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services  # noqa: E402,F401  (vendor sys.path shim)
from obase.db import SessionLocal  # noqa: E402
from sqlalchemy import text  # noqa: E402

CORE_COLLECTION = "core-exam-zhongkao-gaokao-k12"
_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PDF = (
    _REPO_ROOT / "data" / "external" / "vocab_src" / "(英译汉)1600词汇单词默写版.pdf"
)

# 源表使用的词性标记
POS_TOKENS = {
    "n", "v", "a", "ad", "adj", "adv", "prep", "conj", "pron", "det", "num",
    "art", "int", "aux", "modal", "abbr", "vt", "vi", "pl", "phr", "u", "c",
}
# 归一化到标准英文缩写
POS_NORMALISE = {"a": "adj", "ad": "adv"}

_CJK = re.compile(r"[一-鿿]")
_PAGE_NOISE = re.compile(r"^[\d\s\-—–·.]*$")
# 词本身允许：字母、空格、撇号、连字符、斜杠、点、圆括号（含逗号，如 bad (worse, worst)）
_WORD_OK = re.compile(r"^[A-Za-z][A-Za-z'\- ()/.,]*$")
# 尾部括号里的屈折变化标注：bad (worse, worst) -> bad
_PAREN_TAIL = re.compile(r"\s*\([^()]*\)\s*$")


def _norm_tok(raw: str) -> str:
    return raw.strip().strip(",&.").lower()


def parse_cells(raw: str) -> tuple[dict[str, str], list[str]]:
    """解析双栏文本 -> ({word: pos}, 未解析单元格)。纯函数，便于单测。

    做法：按 2+ 空格切栏 → 空格切 token → 从尾部摘掉词性标记。
    **不能**用尾部正则去匹配词性：`ability n` 会被贪婪吃掉 `ity n`（把单词
    的一部分当词性），这是第一版解析器的真实 bug，解析率只有 36/1600。
    `&` / `,` 作连接符时透明摘除，否则 `prep & ad` 会断成只认到 `ad`。
    """
    out: dict[str, str] = {}
    unparsed: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("\x0c"):
            continue
        for cell in re.split(r"\s{2,}", s):
            cell = cell.strip()
            if not cell or cell.startswith("\x0c"):
                continue
            if _CJK.search(cell) or _PAGE_NOISE.match(cell):
                continue  # 标题行 / 页码
            toks = cell.lstrip("*").split()
            pos: list[str] = []
            while toks and len(pos) < 5:
                raw_tok = toks[-1]
                n = _norm_tok(raw_tok)
                if n == "" and raw_tok in ("&", ","):
                    toks.pop()          # 连接符透明
                    continue
                if n in POS_TOKENS:
                    pos.insert(0, n)
                    toks.pop()
                    continue
                break
            if not pos or not toks:
                unparsed.append(cell)
                continue
            word = " ".join(toks).strip()
            # `*ad n` 这类：单词本身就是词性标记，摘完没有词了 → 正确拒绝
            if not _WORD_OK.match(word):
                unparsed.append(cell)
                continue
            pos_text = " & ".join(POS_NORMALISE.get(p, p) for p in pos)
            out[word.lower()] = pos_text
            # `bad (worse, worst) a` 里的括号是屈折变化标注，不属于词本身。
            # vocabulary_items.word 存的是裸词 `bad`，所以额外按词头索引一份，
            # 否则查表永远 miss。
            head = _PAREN_TAIL.sub("", word).strip()
            if head and head != word:
                out.setdefault(head.lower(), pos_text)
    return out, unparsed


def extract(pdf: Path) -> tuple[dict[str, str], list[str]]:
    """用 pymupdf 按阅读顺序抽文本。

    刻意**不用** `pdftotext -layout` 外部二进制：API 镜像里没有 poppler
    （`which pdftotext` 为空），而 pymupdf 已是 requirements 里的声明依赖。
    `sort=True` 对这份双栏词表能还原出与 -layout 等价的栏位对齐。
    """
    import pymupdf

    chunks: list[str] = []
    with pymupdf.open(pdf) as doc:
        for page in doc:
            chunks.append(page.get_text("text", sort=True))
    return parse_cells("\n".join(chunks))


async def run(collection: str, pdf: Path, apply: bool) -> None:
    if not pdf.exists():
        print(f"缺少词表 PDF：{pdf}")
        return
    table, unparsed = extract(pdf)
    print(f"词表解析：{len(table)} 条，未解析 {len(unparsed)} 个单元格")
    print(f"  未解析样例：{unparsed[:8]}")

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT v.id, lower(v.word) FROM vocabulary_items v "
                    "JOIN vocabulary_collection_memberships m ON m.vocabulary_item_id = v.id "
                    "WHERE m.collection_id = :c AND coalesce(v.pos, '') = ''"
                ),
                {"c": collection},
            )
        ).all()

        plans = [(vid, word, table[word]) for vid, word in rows if word in table]
        print(f"\n目标范围 collection={collection}")
        print(f"  尚缺 pos 词数 = {len(rows)}")
        print(f"  词表命中     = {len(plans)}")

        if not plans:
            print("无可写入项，退出")
            return
        if not apply:
            print(f"\n[dry-run] 将更新 {len(plans)} 行。未落库。")
            for _vid, word, pos in plans[:10]:
                print(f"    {word:16s} {pos}")
            return

        now = datetime.now(timezone.utc)
        for vid, _word, pos in plans:
            await db.execute(
                text(
                    "UPDATE vocabulary_items SET pos = :p, updated_at = :now "
                    "WHERE id = :vid AND coalesce(pos, '') = ''"
                ),
                {"p": pos, "now": now, "vid": vid},
            )
        await db.commit()

        done = (
            await db.execute(
                text(
                    "SELECT count(*) FROM vocabulary_items v "
                    "JOIN vocabulary_collection_memberships m ON m.vocabulary_item_id = v.id "
                    "WHERE m.collection_id = :c AND coalesce(v.pos,'') <> ''"
                ),
                {"c": collection},
            )
        ).scalar()
        print(f"\n完成：本次更新 {len(plans)} 行；范围内已有 pos {done} 词")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    parser.add_argument("--collection", default=CORE_COLLECTION)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    args = parser.parse_args()
    asyncio.run(run(args.collection, args.pdf, apply=args.apply))