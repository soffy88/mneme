"""scripts/import_pos_from_xingxing.py — 从《象形9000》回填 vocabulary_items.pos

与 `scripts/import_pos_from_dictation.py` 同一模式：**确定性、零 LLM、只填空值**。
理由和那份一样 —— 词性是教材里显式标注的字段，不是从音标或释义推断出来的。

## 为什么用这一份而不是词根词缀大全

先量过（2026-10-05，全部实测）：

- 《词根词缀大全》：可解析派生词 761 条 ∩ 核心中考高考 2761 词 = **56（2.0%）**。
  它是**派生词**书（`abduct/absorb/accelerate`），而中考核心以**基础词**为主，
  天然错位。→ 不值得为它写导入器。
- 《象形9000》：单是「第一册 下」就 **429/2761 = 15.5%**；全书 6 册 11 个半册。
  且它给的是「词性 + 中文释义 + 英文例句 + 中译」——正好是记忆引擎消费的形态。

**只取 pos，不取例句。** 例句看着更值钱，但落不进现有 schema：
`timed_sentences` 是**听力计时句**表（有 `start_ms`/`end_ms`），且
`services/vocab_context._nce_sentences` 用 `JOIN lessons`（**内连接**）取句——
`lesson_id` 为空的外部句子永远读不到。要用例句就得新建表并改 retriever，
而 retriever 是 P0 十道门禁的输入，资格验证期间不动它。详见 STATUS.md。

## 对齐规则为什么这么严

版式是「单词」独立成段，下一段是「音标 + 词性. + 释义」。所以词性行必须紧跟在
**一个干净的单词段**之后。实测踩到的坑：不加这个约束时，`R首AR nrfera`（OCR 把
`merchant` 毁成乱码）会被当成词条收进来 —— 词段是乱码时，「取上一段的第一个
token」会把定义句里的词当成单词。宁可漏，不可错位。

## 只填空值 + 幂等

`vocabulary_items.pos` 现在有 100+ 种历史脏格式（`n.` / `n` / `noun` /
`adj & n` / `形容词` …）。本脚本**只写 pos 为空的行**，按 id 更新，天然幂等，
不碰任何已有值。归一化沿用 `import_pos_from_dictation.py` 的约定：**不带点**。

    python scripts/import_pos_from_xingxing.py            # dry-run（默认）
    python scripts/import_pos_from_xingxing.py --apply
    python scripts/import_pos_from_xingxing.py --limit 50
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = _REPO_ROOT / "data" / "external" / "vocab_src" / "xingxing"

# 版式里出现过的词性标记。归一化只做一件事：**去掉尾点**（`n.` → `n`），
# 与 import_pos_from_dictation.py 已落库的约定一致。
_SOURCE_POS = (
    "n", "v", "vt", "vi", "adj", "adv", "prep", "conj", "pron", "num",
    "art", "aux", "int", "modal", "det", "pl", "abbr", "phr",
)
# 「音标（含 OCR 噪声）+ 词性. + 释义」这一段的开头。
# 音标用宽松的 `[...]` 或裸 token 吃掉 —— 象形9000 的音标 OCR 噪声很大
# （`[su:1 pri:m]`、`[m3：rtfQnt]`），这里**不解析**它，只用它来定位词性标记。
_ENTRY_RE = re.compile(
    r"^[\[\s]*(?:\[[^\]]{0,40}\]|[\w'ˈˌ:;,.()\- ]{0,30})?[\]\s]*"
    r"((?:" + "|".join(_SOURCE_POS) + r")\.)"
    r"\s*(.+)$",
    re.IGNORECASE,
)
# 单词段：必须是**完整**的干净单词，不含空格、不含数字、不含非 ASCII。
_WORD_LINE_RE = re.compile(r"^[A-Za-z][A-Za-z\-]{1,20}$")


def docx_paragraphs(path: Path) -> list[str]:
    """docx → 非空段落列表（保持顺序；对齐完全依赖这个顺序）。"""
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    out: list[str] = []
    for p in root.iter(ns + "p"):
        text = "".join(n.text or "" for n in p.iter(ns + "t")).strip()
        if text:
            out.append(text)
    return out


def pdf_paragraphs(path: Path) -> list[str]:
    """PDF → 非空「行」列表。

    图解/图册类 PDF 的版面不是段落而是行，所以这里按换行切。`parse_pos_entries`
    只要求「词性行紧跟在单词行之后」，对行/段是等价的 —— 这样 docx 与 PDF
    两条抽取路径能共用同一个纯函数，也就能互相校验。
    """
    import pymupdf

    out: list[str] = []
    with pymupdf.open(path) as doc:
        for page in doc:
            for line in page.get_text().split("\n"):
                line = line.strip()
                if line:
                    out.append(line)
    return out


def parse_pos_entries(lines: list[str]) -> list[tuple[str, str]]:
    """从版式行里取 ``(word, pos)``。

    纯函数，docx / PDF 共用。要求词性行的**上一行**完整匹配单词正则 ——
    见模块 docstring 里 `R首AR nrfera` 那个坑。
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for i, line in enumerate(lines):
        m = _ENTRY_RE.match(line)
        if not m:
            continue
        if i == 0:
            continue
        word = lines[i - 1].strip()
        if not _WORD_LINE_RE.match(word):
            continue
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((key, m.group(1).rstrip(".").lower()))
    return out


def collect_entries(paths: list[Path]) -> dict[str, str]:
    """多份文件 → ``{word: pos}``。同词以首次出现为准（册内顺序即优先级）。"""
    out: dict[str, str] = {}
    for path in paths:
        lines = docx_paragraphs(path) if path.suffix.lower() == ".docx" else pdf_paragraphs(path)
        for word, pos in parse_pos_entries(lines):
            out.setdefault(word, pos)
    return out


async def run(limit: int | None, apply: bool, paths: list[Path]) -> dict[str, Any]:
    from sqlalchemy import text

    from obase.db import SessionLocal

    entries = collect_entries(paths)
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    """
            SELECT DISTINCT ON (lower(btrim(v.word)))
                   v.id, lower(btrim(v.word)) AS word, coalesce(btrim(v.pos), '') AS pos
            FROM vocabulary_items v
            JOIN vocabulary_collection_memberships m
              ON m.vocabulary_item_id = v.id
            WHERE m.collection_id = 'core-exam-zhongkao-gaokao-k12'
              AND v.word ~ '^[A-Za-z][A-Za-z-]*$'
            ORDER BY lower(btrim(v.word)), v.id
            """
                )
            )
        ).all()

        gaps = [r for r in rows if not r.pos]
        plan = [(r.id, r.word, entries[r.word]) for r in gaps if r.word in entries]
        if limit:
            plan = plan[:limit]

        # 已有值与本源口径不同的词：只报告、绝不改写。
        conflicts: list[dict[str, str]] = []
        for r in rows:
            if not r.pos or r.word not in entries:
                continue
            if p_normalise(r.pos) != entries[r.word]:
                conflicts.append(
                    {"word": r.word, "existing": r.pos, "source": entries[r.word]}
                )
        conflicts = conflicts[:50]

        if apply:
            for vid, _word, pos in plan:
                await db.execute(
                    text("UPDATE vocabulary_items SET pos = :pos WHERE id = :vid"),
                    {"pos": pos, "vid": vid},
                )
            await db.commit()

    return {
        "summary": {
            "sources": [str(p) for p in paths],
            "parsed_entries": len(entries),
            "core_words": len(rows),
            "pos_gaps": len(gaps),
            "matched_gaps": len(plan),
            "gap_coverage_pct": round(100 * len(plan) / len(gaps), 1) if gaps else 0.0,
            "applied": apply,
            "conflicts_skipped": len(conflicts),
        },
        "conflicts": conflicts,
        "details": [{"word": w, "pos": p} for _i, w, p in plan],
    }


def p_normalise(raw: str) -> str:
    """把已有的 pos 值归一化到同一口径，**仅用于报告冲突**，不写库。"""
    parts = re.split(r"\s*[/&,]\s*|\s+", raw.strip().lower())
    out: list[str] = []
    for p in parts:
        p = p.rstrip(".").strip()
        p = {"a": "adj", "ad": "adv"}.get(p, p)
        if p in _SOURCE_POS and p not in out:
            out.append(p)
    return "&".join(sorted(out))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="源文件目录")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 个（0=全部）")
    parser.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    parser.add_argument(
        "--out",
        type=Path,
        default=_REPO_ROOT / "reports" / "vocab_memory_p0" / "pos_from_xingxing.json",
        help="报告输出路径",
    )
    args = parser.parse_args()

    paths = sorted(
        [p for p in args.dir.glob("*") if p.suffix.lower() in {".docx", ".pdf"}]
    )
    if not paths:
        print(f"目录内没有 docx/pdf：{args.dir}", file=sys.stderr)
        raise SystemExit(1)

    print("源文件：")
    for p in paths:
        print(f"  {p.name}  ({p.stat().st_size / 1024 / 1024:.1f} MiB)")
    print()

    report = asyncio.run(run(args.limit or None, args.apply, paths))
    s = report["summary"]
    print(f"解析出 (词, 词性)     {s['parsed_entries']}")
    print(f"核心词                {s['core_words']}")
    print(f"其中 pos 为空         {s['pos_gaps']}")
    print(f"可从本源填入          {s['matched_gaps']}  ({s['gap_coverage_pct']}% 的缺口)")
    print(f"与已有值口径冲突(跳过) {s['conflicts_skipped']}")
    print(f"{'已写库' if s['applied'] else '[dry-run] 不写库'}")

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
    if report["conflicts"]:
        print("\n冲突样例（已有值口径不同，未改动）:")
        for c in report["conflicts"][:8]:
            print(f"  {c['word']:14} 库={c['existing']!r} 源={c['source']!r}")


if __name__ == "__main__":
    main()