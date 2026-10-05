"""scripts/import_collocations_from_k12.py — 从中考教辅 PDF 回填 vocabulary_collocations

数据源：gdrive `K12教育/初中` 下 21 个《每天一篇故事，21天搞定中考英语1600词》PDF
（每个 87–92 KB，合计 2.3 MB；已下载到 `data/external/k12_src/`，`.gitignore` 排除）。

## 为什么是这批而不是词表

同批资料里，**词表部分几乎无用**、**词组部分是真机会**（2026-10-05 实测）：

- `pos` 只能填 **+29 词**（占 987 缺口的 2.9%）—— 中考 1600 词表与我们已有的
  高度重叠，另有 100 个与已有值口径冲突会跳过。对比《象形9000》docx 的 +209。
- **多词条目 233 条**（去重后），而 `vocabulary_collocations` **只有 66 行**。
  这些词组会经 `render_review_ladder` 的 `word_origin` 层**直接渲染给学生**
  （spec §五「📌实用搭配 3–5 个」），是当前最薄的一层。

## 确定性、零 LLM

中文释义与英文词组在版面上是**两列等长**（先 N 行英文、再 N 行中文、顺序对应），
所以配对是纯版面操作，不需要模型。同 `import_pos_from_dictation.py` /
`import_pos_from_xingxing.py` 模式：默认 dry-run、`--apply` 才写、
`ON CONFLICT DO NOTHING` 天然幂等。

## 中心词（挂到哪个 vocabulary_item）

既有 66 行的惯例是「**教的那个词**」：`traffic accident`/`by accident` → `accident`
（末词）、`alarm clock` → `alarm`（首词）、`an astronaut` → `astronaut`。

所以这里按**内容词**判定，顺序是「末个内容词 → 首个内容词」，命中即止；
两者都查不到就**丢弃并记进报告** —— 宁可少收，也不把搭配挂到虚词上
（`at last` 的中心词是 `at`，那不是能教搭配的词）。

    python scripts/import_collocations_from_k12.py             # dry-run（默认）
    python scripts/import_collocations_from_k12.py --apply
    python scripts/import_collocations_from_k12.py --limit 50
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = _REPO_ROOT / "data" / "external" / "k12_src"

COLLECTION = "core-exam-zhongkao-gaokao-k12"
SOURCE_TAG = "ZHONGKAO1600_PDF"

_ZH = re.compile(r"[\u4e00-\u9fff]")
_EN = re.compile(r"^[A-Za-z][A-Za-z'’\s\.\-]*[A-Za-z.]$")
# 词表行的形态：`new adj.` / `whether conj.` —— 带词性标记的**不是**搭配
_POS_MARKER = re.compile(r"\b(adj|adv|vt|vi|prep|conj|pron|num|art|n|v)\.")
# 版面噪声：`/v. 电话` —— OCR 把词性挪到了同一格
_SLASH = re.compile(r"/")

# 占位符：`speak to sb.` / `wait a moment` 里的 sb./sth. 不是词
_PLACEHOLDER = re.compile(r"^(sb|sth|somebody|something|it|one|ones)\.?$", re.I)
# 功能词：不能当搭配的中心词
STOPWORDS = frozenset(
    """a an the this that these those and or but so of to in on at by for with from into
    onto over under again further is are was were be been being am do does did doing have
    has had having will would shall should can could may might must i you he she it we they
    me him her us them my your his its our their there here what which who whom whose when
    where why how not no nor only own same than too very s t don now""".split()
)

MAX_TOKENS = 8
MAX_ZH = 40


def extract_pairs(path: Path) -> list[tuple[str, str]]:
    """一个 PDF → ``[(en, zh)]``。

    版面是「先 N 行纯英文、再 N 行含中文、顺序一一对应」。所以做法是：扫到一个
    英文行块，向下吃掉紧邻的中文行块，**两者行数相等才配对** —— 行数不等说明
    版面串了，宁可整块丢掉。
    """
    import pymupdf

    raw = "\n".join(p.get_text() for p in pymupdf.open(path))
    lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        if _EN.match(lines[i]) and not _ZH.search(lines[i]):
            j = i
            while j < len(lines) and _EN.match(lines[j]) and not _ZH.search(lines[j]):
                j += 1
            en_block = lines[i:j]
            k = j
            while k < len(lines) and _ZH.search(lines[k]):
                k += 1
            zh_block = lines[j:k]
            if zh_block and len(en_block) == len(zh_block):
                out.extend((" ".join(a.split()), b) for a, b in zip(en_block, zh_block))
            i = k if k > j else j + 1
        else:
            i += 1
    return out


def usable_phrase(en: str, zh: str) -> str | None:
    """这一条能不能当搭配用；不能则返回 ``None``。

    纯函数，四条排除规则各有实测理由：

    1. **带词性标记** —— `new adj.` 是词表行，不是搭配。
    2. **含 ``/``** —— `/v. 电话` 是 OCR 把词性挪进同一格。
    3. **≥2 个词首大写** —— `A Young Officer and an Old Soldier` 是**故事标题**；
       而 `an astronaut` 只有首词大写、`a bank account` 全小写，都不会被误杀。
       代价：真含专名词的搭配（`New York`）会被丢，已在 docstring 记录。
    4. **单词 / 超长 / 中文过长** —— 不是搭配或不可用。
    """
    if not en or not zh or _SLASH.search(en) or _POS_MARKER.search(en):
        return None
    # 含 `...` 的是**语法句型**不是搭配：`not only...but also...`、`one of...`。
    # 实测它们确实混在同一批版面里。
    if "..." in en:
        return None
    # 版面把页码/项目符号漏进了中文格：`.送礼`、`.去海滩`、`.首先`。
    # 去掉**首尾**的点与空白；中间的 `......` 是原文的省略号，保留。
    zh = zh.strip().strip(".").strip()
    if not zh or len(zh) > MAX_ZH:
        return None
    tokens = en.split()
    if len(tokens) < 2 or len(tokens) > MAX_TOKENS:
        return None
    if sum(1 for t in tokens if t[:1].isupper()) >= 2:
        return None
    return en


def content_tokens(phrase: str) -> list[str]:
    """去掉功能词与占位符，剩下的才是可能当中心词的 token（保持原序）。"""
    out = []
    for tok in phrase.split():
        bare = tok.strip(".,;:!?'\"()").lower()
        if not bare or bare in STOPWORDS or _PLACEHOLDER.match(bare):
            continue
        out.append(bare)
    return out


def pick_head(phrase: str, vocab: dict[str, str]) -> str | None:
    """这条搭配该挂在哪个词上；查不到返回 ``None``（调用方丢弃并记录）。

    顺序「末个内容词 → 首个内容词」是照既有 66 行的惯例来的
    （`traffic accident`→`accident`，`alarm clock`→`alarm`）。
    """
    toks = content_tokens(phrase)
    if not toks:
        return None
    for cand in (toks[-1], toks[0]):
        if cand in vocab:
            return vocab[cand]
    return None


async def run(limit: int | None, apply: bool, files: list[Path]) -> dict[str, Any]:
    from sqlalchemy import text

    from obase.db import SessionLocal

    async with SessionLocal() as _db:
        rows = (
            await _db.execute(
            text(
                """
            SELECT DISTINCT ON (lower(btrim(v.word)))
                   v.id, lower(btrim(v.word)) AS word
            FROM vocabulary_items v
            JOIN vocabulary_collection_memberships m ON m.vocabulary_item_id = v.id
            WHERE m.collection_id = :coll AND v.word ~ '^[A-Za-z][A-Za-z-]*$'
            ORDER BY lower(btrim(v.word)), v.id
            """
            ),
                {"coll": COLLECTION},
            )
        ).all()
    vocab = {r.word: r.id for r in rows}

    details: list[dict[str, Any]] = []
    unlinked: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    skipped = 0
    for path in files:
        for en, zh in extract_pairs(path):
            phrase = usable_phrase(en, zh)
            if phrase is None:
                skipped += 1
                continue
            vid = pick_head(phrase, vocab)
            if vid is None:
                unlinked.append({"phrase_en": phrase, "phrase_cn": zh})
                continue
            key = (vid, phrase, zh)
            if key in seen:
                continue
            seen.add(key)
            details.append(
                {"vocabulary_item_id": vid, "phrase_en": phrase, "phrase_cn": zh}
            )

    if limit:
        details = details[:limit]

    applied = 0
    if apply and details:
        async with SessionLocal() as db:
            for d in details:
                res = await db.execute(
                    text(
                        """
                    INSERT INTO vocabulary_collocations
                        (vocabulary_item_id, phrase_en, phrase_cn, source, confidence)
                    VALUES (:vid, :en, :zh, :src, NULL)
                    ON CONFLICT (vocabulary_item_id, phrase_en, phrase_cn) DO NOTHING
                    """
                    ),
                    {
                        "vid": d["vocabulary_item_id"],
                        "en": d["phrase_en"],
                        "zh": d["phrase_cn"],
                        "src": SOURCE_TAG,
                    },
                )
                applied += res.rowcount or 0
            await db.commit()

    return {
        "summary": {
            "sources": [p.name for p in files],
            "core_vocab": len(vocab),
            "kept": len(details),
            "unlinked_no_head_word": len(unlinked),
            "skipped_not_a_phrase": skipped,
            "applied": apply,
            "rows_inserted": applied,
        },
        "details": details,
        "unlinked": unlinked,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="源 PDF 目录")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 条（0=全部）")
    parser.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    parser.add_argument(
        "--out",
        type=Path,
        default=_REPO_ROOT / "reports" / "vocab_memory_p0" / "collocations_from_k12.json",
        help="报告输出路径",
    )
    args = parser.parse_args()

    files = sorted(Path(args.dir).glob("*.pdf"))
    if not files:
        print(f"目录内没有 PDF：{args.dir}", file=sys.stderr)
        raise SystemExit(1)
    print(f"源文件 {len(files)} 个（{sum(p.stat().st_size for p in files) / 1024 / 1024:.1f} MiB）\n")

    report = asyncio.run(run(args.limit or None, args.apply, files))
    s = report["summary"]
    print(f"核心词表            {s['core_vocab']}")
    print(f"可入库的搭配        {s['kept']}")
    print(f"查不到中心词(丢弃)  {s['unlinked_no_head_word']}")
    print(f"不是搭配(词表行等)  {s['skipped_not_a_phrase']}")
    if s["applied"]:
        print(f"已写库              {s['rows_inserted']} 行（其余为 ON CONFLICT 跳过）")
    else:
        print("[dry-run] 不写库")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {"generated_at": datetime.now(timezone.utc).isoformat(), **report},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"明细: {args.out}")
    if report["unlinked"]:
        print("\n查不到中心词的样例（丢弃，不硬挂）:")
        for u in report["unlinked"][:8]:
            print(f"  {u['phrase_en'][:34]:36} {u['phrase_cn'][:22]}")


if __name__ == "__main__":
    main()