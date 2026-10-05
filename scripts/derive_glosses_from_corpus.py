"""CME-P1.12：给「有真实语境句、但没有中文释义」的词补一份**有出处**的派生释义。

## 为什么需要

MEANING_AUTHORITY 门禁（2026-10-04 加）实测拒收了 16/100 个词，全部因为
`meaning_cn` 为空且 `canonical_meaning` 装的是**纯音标**：
`[ˈdaɪət]`、`[ɪˈlektrɪk]`、`[kəˈmɪtmənt]`。规模：核心范围里
「有 NCE 真实句 + 无中文释义」= **461 词**（459 个 canonical 是纯音标）。
确定性路径已走不通（`derive_meaning_from_canonical` 实测可派生 = 0）。

## 为什么不写进 meaning_cn

那一列承载「教材词表原文」的可追溯性。写进去就再也分不清「教材原文」与
「模型从语料句推的」。故写入独立的 `vocabulary_derived_glosses`（alembic
d7e8f9a0b1c2），出处显式存 `source_kind`，读取方按 `derived_from_corpus` 档位返回。
与词根那侧的 `etymology_status` 三档是同一个解法。

## 可信度说明

例句**不是模型编的**：`retrieve_context` 从 `timed_sentences` 确定性抽取，
`source_sentence_id` 记下用了哪一句，可回溯。释义由既有
`oprim._vocab_gloss_generate` 生成（那个 oprim 的契约就是「例句由语料库确定性抽取」）。

## 不做什么

- **不写 `pos`**：87 个目标词已有策展版 `pos`（来自默写表），LLM 推断的 pos 更差。
  缺 pos 的走 `scripts/import_pos_from_dictation.py` 那条更好的路。
- **不覆盖任何已有释义**：只补空缺。
- 默认 dry-run，不加 `--apply` 不写库。

跑法：
  docker compose exec api python scripts/derive_glosses_from_corpus.py
  docker compose exec api python scripts/derive_glosses_from_corpus.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services  # noqa: E402,F401  (vendor sys.path shim)

CORE_COLLECTION = "core-exam-zhongkao-gaokao-k12"
# 只取单词：短语（`a bit of`）的释义由 vocabulary_collocations 覆盖，不走这条。
SINGLE_WORD_RE = "^[A-Za-z][A-Za-z-]*$"

_TARGET_SQL = """
SELECT v.id, v.word, v.pos
FROM vocabulary_items v
JOIN vocabulary_collection_memberships m
  ON m.vocabulary_item_id = v.id
WHERE m.collection_id = :c
  AND v.word ~ :single_word_re
  AND btrim(coalesce(v.meaning_cn, '')) = ''
  AND btrim(coalesce(v.example_sentence, '')) <> ''
  AND NOT EXISTS (
    SELECT 1 FROM vocabulary_derived_glosses g
    WHERE g.vocabulary_item_id = v.id
  )
ORDER BY v.id
"""

# 每批词数。oprim 的契约是「等长同序」，所以批大小固定、顺序稳定，
# 便于复跑比对；也避免一次塞几百个词导致输出被 max_tokens 截断。
BATCH_SIZE = 8


async def collect_targets(db) -> list[tuple[str, str, str | None]]:
    from sqlalchemy import text

    rows = (
        (
            await db.execute(
                text(_TARGET_SQL),
                {"c": CORE_COLLECTION, "single_word_re": SINGLE_WORD_RE},
            )
        )
        .all()
    )
    return [tuple(r) for r in rows]


async def run(limit: int, apply: bool) -> dict:
    from obase.db import SessionLocal
    from obase.provider_registry import ProviderRegistry
    from oprim._vocab_gloss_generate import generate_vocab_glosses
    from services.providers.setup import configure_llm_providers
    from services.vocab_context import retrieve_context
    from sqlalchemy import text

    configure_llm_providers()
    caller = ProviderRegistry.get().llm("default")
    model = getattr(caller, "model", None) or "unknown"

    written = 0
    skipped_no_context = 0
    degraded = 0
    call_errors = 0
    details: list[dict] = []

    async with SessionLocal() as db:
        targets = await collect_targets(db)
        if limit and limit < len(targets):
            targets = targets[:limit]
        print(f"目标词（有真实例句 + 无释义 + 无派生释义）= {len(targets)}")
        print(f"LLM 模型 = {model}")
        if not apply:
            print("[dry-run] 不写库")
        print()

        for start in range(0, len(targets), BATCH_SIZE):
            batch = targets[start : start + BATCH_SIZE]
            entries: list[dict] = []
            sent_ids: dict[str, str | None] = {}
            for vid, word, pos in batch:
                bundle = await retrieve_context(db, vid, limit=1)
                best = bundle.best
                if best is None:
                    skipped_no_context += 1
                    entries = []
                    break
                # 例句来自确定性抽取，**不是模型编的**
                entries.append({"word": word, "example_sentence": best.text})
                sent_ids[word] = best.sentence_id
            if not entries:
                continue

            # 逐批隔离：第一版没有这层，一次 timeout 就把整轮带走，
            # 已经写好的批次虽然 commit 过，但剩下的全丢（实测 written=0）。
            # 批级 try/except 是这里的正确粒度 —— 单批失败重跑代价小。
            try:
                glosses = await generate_vocab_glosses(entries, caller=caller)
            except Exception as exc:  # noqa: BLE001 — 要的是覆盖，不是中断
                call_errors += 1
                # 必须打 cause 链：`restore_llm` 会把底层异常包成
                # LLMOprimError("LLM call failed", cause=...)，只打类型名
                # 会把「超时」和「JSON 截断」显示成同一个东西（实测踩过）。
                chain = []
                cur: BaseException | None = exc
                while cur is not None:
                    chain.append(f"{type(cur).__name__}: {cur}")
                    cur = cur.__cause__
                print(
                    f"  [{start + 1}-{start + len(batch)}/{len(targets)}] "
                    f"LLM 调用失败，跳过本批 ← " + " | caused by ← ".join(chain[:4])
                )
                continue
            # 位置对齐必须在**每个**返回项上推进，包括要丢弃的 ——
            # 否则某个 gloss 缺 meaning_cn 后，后面全部错位（apply_gloss_batch 的教训）。
            idx = 0
            for vid, word, _pos in batch:
                if idx >= len(glosses):
                    break
                g = glosses[idx]
                idx += 1
                gloss = (g.get("meaning_cn") or "").strip()
                if not gloss:
                    degraded += 1
                    continue
                details.append({"word": word, "gloss": gloss})
                if apply:
                    await db.execute(
                        text(
                            """
                    INSERT INTO vocabulary_derived_glosses
                        (vocabulary_item_id, gloss, source_kind, source_sentence_id, model)
                    VALUES (:vid, :gloss, 'corpus_llm', :sid, :model)
                    ON CONFLICT (vocabulary_item_id) DO NOTHING
                    """
                        ),
                        {
                            "vid": vid,
                            "gloss": gloss,
                            "sid": sent_ids.get(word),
                            "model": model,
                        },
                    )
                    written += 1
            if apply:
                await db.commit()
            done = min(start + BATCH_SIZE, len(targets))
            print(f"  [{done}/{len(targets)}] 本批累计写入 {written}")

    summary = {
        "collection": CORE_COLLECTION,
        "targets": len(targets),
        "applied": apply,
        "written": written,
        "degraded_no_gloss": degraded,
        "skipped_no_context": skipped_no_context,
        "call_errors": call_errors,
    }
    print("\n=== 汇总 ===")
    for k, v in summary.items():
        print(f"  {k:<24} {v}")

    out = Path(__file__).resolve().parents[1] / "reports" / "vocab_memory_p0"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"derived_glosses_{'applied' if apply else 'dryrun'}.json"
    path.write_text(
        json.dumps({"summary": summary, "details": details}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n明细: {path}")
    if apply and details:
        print("\n抽样（人工判读用）:")
        for d in details[:10]:
            print(f"  {d['word']:<14} {d['gloss']}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="0 = 全量")
    parser.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    asyncio.run(run(args.limit, args.apply))


if __name__ == "__main__":
    main()