"""scripts/import_dict_from_coca20k.py — 从 EchoType 的 coca20000 词表回填 pos 与词典释义

数据源：EchoType（MIT）`public/wordbooks/coca20000.json`，已存到
`data/external/vocab_src/coca20000_echo_type.json`（`.gitignore` 排除）。
17,631 条，每条 ``{"word": "<词>", "sentence": "<词性.><多义中文释义>"}``。

## 实测（2026-10-05，为什么值得做）

与核心合集 `core-exam-zhongkao-gaokao-k12`（2,761 词）**重合 93.3%（2,575）**：

| 用途 | 收益 |
|---|---|
| `pos` 缺口 987 | **+855（86.6%）** —— 对比《象形9000》的 +209 |
| `meaning_cn` 空且**完全无可用释义**的 314 词 | **+285** |

## ⚠️ 这个文件**没有词频信息**

文件名里的 `coca20000` 只说明**词表来自 COCA**，不代表保留了 rank。实测
17,631 条是**严格字母序**（`words == sorted(words)` 为 True）：`aback`=1、
`abandon`=2、`ability`=18、`water`=17178、`zulu`=17631。

所以**不要**用它做 spec §四 的频率等级 —— `water`（最常用词之一）会被标成低频。
这正是当初否决 `frequency_band` 时说的「实测无区分度」，换个文件名就又踩一遍。

## 只填「当前完全没有可用释义」的词，不覆盖已有的

776 个 `meaning_cn` 为空的词里，**461 已落到 `derived_from_corpus`**（模型从真实
语料句派生）、1 个 legacy，只有 **314 真正 unusable**。词典释义质量高于单句派生，
但覆盖那 461 个会**改变学生看到的答案**，属于要人决策的事。

本脚本只写那 314 个（其中 COCA 覆盖 285）。已写进
`vocabulary_dictionary_glosses`（独立表，alembic `b3e9d1f5a7c2`）而不是
`vocabulary_derived_glosses` —— 后者 CHECK 锁死 `source_kind='corpus_llm'`，
且溯源串被硬编码成「从真实语料句派生」，对词典来源那句话是假的。

`pos` 那边没有这个纠结：只写 `pos` 为空的行，不碰已有的 100+ 种历史脏值。

    python scripts/import_dict_from_coca20k.py             # dry-run（默认）
    python scripts/import_dict_from_coca20k.py --apply
    python scripts/import_dict_from_coca20k.py --pos-only
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
DEFAULT_SRC = _REPO_ROOT / "data" / "external" / "vocab_src" / "coca20000_echo_type.json"
COLLECTION = "core-exam-zhongkao-gaokao-k12"
SOURCE_TAG = "ECHOTYPE_COCA20000"

# 词性标签。顺序**无关**（用 findall），但集合要和 `services/vocab_senses.canon_pos`
# 认的那套对齐，否则写进去的 pos 下游认不出来。
_POS = r"(?:n|v|vt|vi|adj|adv|prep|conj|pron|num|art|aux|int)"
# 一个义项段：`n.放任，放纵…`。要求标签后**紧跟汉字**，避免把 `a.m.` 之类当词性。
_SENSE_SEG = re.compile(rf"(?:^|(?<=[\u4e00-\u9fff]))({_POS})\.\s*(?=[\u4e00-\u9fff])")
_LEAD_POS = re.compile(rf"^\s*({_POS})\.\s*(?=[\u4e00-\u9fff])")
MAX_GLOSS = 200


def split_senses(field: str | None) -> list[tuple[str, str]]:
    """把 ``vt.放弃，抛弃…n.放任，放纵…`` 拆成 ``[("vt", "放弃，抛弃…"), ("n", "放任…")]``。

    纯函数。源文件的义项之间**没有空格**（`…终止n.放任…`），所以靠「汉字后紧跟
    词性标签」来切 —— 只认紧跟在汉字后的标签，前面没汉字的（行首）单独用
    ``_LEAD_POS`` 处理，避免把 `a.m.`、`U.S.` 之类误判成词性。

    返回**全部**义项，不是首个 —— 只取首个是我们已知的坑
    （`blind`→百叶窗、`wet`→雨天，20 词人工审查抓出来的）。
    """
    raw = (field or "").strip()
    if not raw:
        return []
    lead = _LEAD_POS.match(raw)
    offset = 0
    if lead:
        offset = lead.end()
    out: list[tuple[str, str]] = []
    pos = lead.group(1) if lead else None
    for m in _SENSE_SEG.finditer(raw, offset):
        if pos and m.start() > offset:
            out.append((pos, raw[offset : m.start()].strip("，,、；; ")))
        pos = m.group(1)
        offset = m.end()
    if pos and offset < len(raw):
        out.append((pos, raw[offset:].strip("，,、；; ")))
    return [(p, g) for p, g in out if g.strip()]


def primary_pos(senses: list[tuple[str, str]]) -> str | None:
    """取第一个义项的词性。词表本身已按义项顺序排列，第一条即主义项。"""
    return senses[0][0] if senses else None


def join_gloss(senses: list[tuple[str, str]]) -> str | None:
    """把全部义项合成一行，写进 `vocabulary_dictionary_glosses.gloss`。

    **带词性标签**并用换行分隔 —— `services.vocab_senses.parse_senses` 就是按行
    解析、每行可带行首词性标签的，写成它认的形状才能被义项选择用到。
    上限 200 字：超了截断并记进报告（截断会丢义项，所以必须可见）。
    """
    if not senses:
        return None
    text = "\n".join(f"{p}. {g}" for p, g in senses)
    return text if len(text) <= MAX_GLOSS else None


async def run(
    apply: bool, pos_only: bool, limit: int | None, src: Path
) -> dict[str, Any]:
    from sqlalchemy import text

    from obase.db import SessionLocal

    entries: list[dict[str, Any]] = []
    data = json.loads(src.read_text(encoding="utf-8"))
    for idx, row in enumerate(data):
        word = (row.get("word") or "").strip().lower()
        if not word:
            continue
        senses = split_senses(row.get("sentence"))
        entries.append(
            {
                "word": word,
                "line_no": idx + 1,
                "pos": primary_pos(senses),
                "gloss": join_gloss(senses),
            }
        )

    src_by_word = {e["word"]: e for e in entries}
    pos_plan: list[tuple[str, str, str]] = []
    gloss_plan: list[dict[str, str]] = []
    gloss_skipped_overlong = 0

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    """
            SELECT DISTINCT ON (lower(btrim(v.word)))
                   v.id, lower(btrim(v.word)) AS word,
                   btrim(coalesce(v.pos, '')) AS pos,
                   btrim(coalesce(v.meaning_cn, '')) AS mc,
                   btrim(coalesce(v.canonical_meaning, '')) AS cm,
                   g.gloss AS dg
            FROM vocabulary_items v
            JOIN vocabulary_collection_memberships m ON m.vocabulary_item_id = v.id
            LEFT JOIN vocabulary_derived_glosses g ON g.vocabulary_item_id = v.id
            WHERE m.collection_id = :coll AND v.word ~ '^[A-Za-z][A-Za-z-]*$'
            ORDER BY lower(btrim(v.word)), v.id
            """
                ),
                {"coll": COLLECTION},
            )
        ).all()

        from services.vocab_meaning import classify_meaning_source

        for r in rows:
            e = src_by_word.get(r.word)
            if not e:
                continue
            # pos：只填空值，绝不碰已有的历史脏值
            if not r.pos and e["pos"]:
                pos_plan.append((r.id, r.word, e["pos"]))
            if pos_only or not e["gloss"]:
                continue
            verdict = classify_meaning_source(
                meaning_cn=r.mc, canonical_meaning=r.cm, derived_gloss=r.dg
            )
            # 只写**当前完全拿不到释义**的词。覆盖已有的会改变学生看到的答案。
            if not verdict.usable:
                gloss_plan.append(
                    {
                        "vocabulary_item_id": r.id,
                        "word": r.word,
                        "gloss": e["gloss"],
                        "source_ref": str(e["line_no"]),
                    }
                )

    if limit:
        pos_plan = pos_plan[:limit]
        gloss_plan = gloss_plan[:limit]

    pos_written = gloss_written = 0
    if apply:
        async with SessionLocal() as db:
            for vid, _w, pos in pos_plan:
                res = await db.execute(
                    text("UPDATE vocabulary_items SET pos = :p WHERE id = :v"),
                    {"p": pos, "v": vid},
                )
                pos_written += res.rowcount or 0
            for g in gloss_plan:
                res = await db.execute(
                    text(
                        """
                    INSERT INTO vocabulary_dictionary_glosses
                        (vocabulary_item_id, gloss, source, source_ref)
                    VALUES (:v, :g, :src, :ref)
                    ON CONFLICT (vocabulary_item_id) DO NOTHING
                    """
                    ),
                    {
                        "v": g["vocabulary_item_id"],
                        "g": g["gloss"],
                        "src": SOURCE_TAG,
                        "ref": g["source_ref"],
                    },
                )
                gloss_written += res.rowcount or 0
            await db.commit()

    over = [e["word"] for e in entries if e["gloss"] is None and e["pos"]]
    gloss_skipped_overlong = len(over)
    return {
        "summary": {
            "source": src.name,
            "source_entries": len(entries),
            "core_words": len(rows),
            "pos_plan": len(pos_plan),
            "gloss_plan": len(gloss_plan),
            "gloss_skipped_overlong": gloss_skipped_overlong,
            "applied": apply,
            "pos_written": pos_written,
            "gloss_written": gloss_written,
        },
        "pos_plan": [{"word": w, "pos": p} for _v, w, p in pos_plan],
        "gloss_plan": gloss_plan,
        "gloss_overlong_sample": over[:15],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pos-only", action="store_true", help="只填 pos，不写词典释义")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    ap.add_argument(
        "--out",
        type=Path,
        default=_REPO_ROOT / "reports" / "vocab_memory_p0" / "dict_from_coca20k.json",
    )
    args = ap.parse_args()

    if not args.src.exists():
        print(f"源文件不存在：{args.src}", file=sys.stderr)
        raise SystemExit(1)
    print(f"源：{args.src.name}（{args.src.stat().st_size / 1024 / 1024:.1f} MiB）\n")

    rep = asyncio.run(run(args.apply, args.pos_only, args.limit or None, args.src))
    s = rep["summary"]
    print(f"源条目            {s['source_entries']}")
    print(f"核心词            {s['core_words']}")
    print(f"可填 pos 空位     {s['pos_plan']}")
    print(f"可填词典释义      {s['gloss_plan']}  （只填当前完全无可用释义的词）")
    print(f"释义超长被拒      {s['gloss_skipped_overlong']}")
    if s["applied"]:
        print(f"已写库            pos {s['pos_written']} 行 / 词典释义 {s['gloss_written']} 行")
    else:
        print("[dry-run] 不写库")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {"generated_at": datetime.now(timezone.utc).isoformat(), **rep},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"明细: {args.out}")
    print("\npos 抽样:", ", ".join(f"{r['word']}={r['pos']}" for r in rep["pos_plan"][:8]))
    for g in rep["gloss_plan"][:3]:
        print(f"\n{g['word']} (line {g['source_ref']}):\n{g['gloss'][:150]}")


if __name__ == "__main__":
    main()