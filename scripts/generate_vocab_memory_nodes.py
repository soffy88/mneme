"""P0 试跑：核心范围 100 词记忆节点生成（MNEME_CORE3000_MEMORY_ENGINE_P0_SPEC.md §3）

从核心范围**单词**全集（实测 2,761 个）随机抽 N 个，跑完整链路：
Context Retriever → LLM → Quality Verifier → 装配。

默认 dry-run：不加 `--apply` 不写库，只打印每个词的门禁结果并把完整报告写到
`reports/vocab_memory_p0/`，供人工判读后再决定是否落库。

刻意**不写** KCMastery：掌握度只经 SubmitAnswer 写路径产生（AGENTS.md 红线），
试跑阶段造一批假卡片会污染到期队列。

跑法：
  docker compose exec api python scripts/generate_vocab_memory_nodes.py --limit 100
  docker compose exec api python scripts/generate_vocab_memory_nodes.py --limit 100 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services  # noqa: E402,F401  (vendor sys.path shim)

CORE_COLLECTION = "core-exam-zhongkao-gaokao-k12"
# 只取单词。多词短语（`a bit of` / `according to`）的「记忆画面」价值低，
# 且多数已被 vocabulary_collocations 覆盖 —— 口径见 spec §2.3。
SINGLE_WORD_RE = "^[A-Za-z][A-Za-z-]*$"
REPORT_DIR = Path(__file__).resolve().parents[1] / "reports" / "vocab_memory_p0"

_TARGET_SQL = """
SELECT v.id, v.word, v.pos
FROM vocabulary_items v
JOIN vocabulary_collection_memberships m ON m.vocabulary_item_id = v.id
WHERE m.collection_id = :c
  AND v.word ~ :single_word_re
"""

# 试跑范围（2026-10-03 人决策）：CORE_EXAM_VOCAB ∩ **有真实教材/NCE 例句**。
# 即只取 A/B 级（有语境），不取 C 级（无语境）—— 本轮要验的是「有真实语境时
# 生成质量如何」，而不是「没有语境时能不能编」。无语境那条降级路径由单测覆盖。
# 过滤放在 SQL 里而不是取回后再筛：2,066 行 vs 2,761 行，省掉 700 次无谓的
# retrieve_context 往返（每行一次查询）。
_TARGET_SQL_REQUIRE_CONTEXT = """
SELECT v.id, v.word, v.pos
FROM vocabulary_items v
JOIN vocabulary_collection_memberships m ON m.vocabulary_item_id = v.id
WHERE m.collection_id = :c
  AND v.word ~ :single_word_re
  AND EXISTS (
    SELECT 1
    FROM sentence_vocabulary_occurrences o
    JOIN timed_sentences ts ON ts.id = o.sentence_id
    WHERE o.vocabulary_item_id = v.id
      AND ts.english_text IS NOT NULL
      AND btrim(ts.english_text) <> ''
  )
"""


def pick_targets(
    rows: list[tuple[str, str, str | None]],
    limit: int,
    seed: int,
    only: set[str] | None = None,
) -> list[tuple[str, str, str | None]]:
    """`only` 非空时只保留这些词（人工审查用）。大小写不敏感。"""
    if only:
        want = {w.strip().lower() for w in only}
        return [r for r in rows if r[1].strip().lower() in want]
    """确定性抽样：固定 seed 同参数复跑同一批词，报告才可比对。"""
    pool = sorted(rows, key=lambda r: r[0])
    # limit<=0 = 全量审计（输入侧统计要的是总体成色，不是抽样）
    if limit <= 0 or limit >= len(pool):
        return pool
    rng = random.Random(seed)
    return sorted(rng.sample(pool, limit), key=lambda r: r[0])


async def run(limit: int, seed: int, apply: bool, audit_only: bool = False,
              require_context: bool = False, words: str | None = None) -> dict:
    from obase.db import SessionLocal
    from sqlalchemy import text

    from services.mcp_router import tool_generate_memory_node

    async with SessionLocal() as db:
        sql = _TARGET_SQL_REQUIRE_CONTEXT if require_context else _TARGET_SQL
        rows = (
            (
                await db.execute(
                    text(sql),
                    {"c": CORE_COLLECTION, "single_word_re": SINGLE_WORD_RE},
                )
            )
            .all()
        )
        pool = [tuple(r) for r in rows]
        targets = pick_targets(
            pool, limit, seed, {w for w in words.split(",") if w.strip()} if words else None
        )

        print(f"核心范围单词总数 = {len(pool)}" + ("（已限定：有真实 NCE 例句）" if require_context else ""))
        print(f"本轮试跑         = {len(targets)}（seed={seed}）")
        if not apply:
            print("[dry-run] 不写库。报告仍会写到 " + str(REPORT_DIR))
        print()

        if audit_only:
            return await _audit(db, pool, targets, seed, apply)

        reports: list[dict] = []
        gate_counter: Counter[str] = Counter()
        skipped = 0
        errored = 0

        for i, (vid, word, pos) in enumerate(targets, start=1):
            # 每个词独立隔离：模型超时/网络抖动/契约异常都只记进报告，不许中断整轮。
            # 第一版没有这层 —— 100 词跑到第 38 个时一次 timeout 就把整轮带走了，
            # 前面 37 个已生成的结果全丢。试跑的价值恰恰在于「跑完 100 个」的分布，
            # 中途崩掉等于什么都没测到。
            try:
                result = await tool_generate_memory_node(db, vid, persist=apply)
            except Exception as exc:  # noqa: BLE001 — 试跑要的是分布，不是中断
                errored += 1
                reports.append(
                    {
                        "vocabulary_item_id": vid,
                        "word": word,
                        "generated": False,
                        "error": f"{type(exc).__name__}: {exc}"[:300],
                    }
                )
                print(f"[{i}/{len(targets)}] {word:<16} 调用失败：{type(exc).__name__}")
                continue
            node = result.get("node")
            if node is None:
                skipped += 1
                reports.append(
                    {
                        "vocabulary_item_id": vid,
                        "word": word,
                        "generated": False,
                        "reason": result.get("reason"),
                    }
                )
                print(f"[{i}/{len(targets)}] {word:<16} 契约未过，跳过")
                continue

            rep = result["report"]
            ctx = result["memory_input"]["context"]
            for g in rep["gates"]:
                if not g["passed"]:
                    gate_counter[g["gate"]] += 1
            entry = {
                "vocabulary_item_id": vid,
                "word": word,
                "pos": pos,
                "generated": True,
                "tier": result["row"]["tier"],
                "context_tier": ctx["tier"],
                "verified": rep["verified"],
                "degraded": rep["degraded"],
                "quality_score": rep["quality_score"],
                "failed_gates": rep["failed_gates"],
                "core_image": result["row"]["core_image"],
                "semantic_core": result["row"]["semantic_core"],
                "scene": result["row"]["scene"],
                "family_network": result["row"]["family_network"],
                "sound_hook": result["row"]["sound_hook"],
                "spelling_hook": result["row"]["spelling_hook"],
                "recall_question": result["row"]["recall_question"],
                "answer": result["row"]["answer"],
                "image_prompt": result["row"]["image_prompt"],
                "animation_candidate": result["row"]["animation_candidate"],
                "context_evidence": result["row"]["context_evidence"],
                "input_meaning": result["memory_input"]["meaning"],
                "input_context": (result["memory_input"]["context_flat"]),
                "input_affix_chain": (result["memory_input"]["affix"] or {}).get("chain"),
            }
            reports.append(entry)
            flag = "OK " if rep["verified"] else ("降级" if rep["degraded"] else "拒收")
            print(
                f"[{i}/{len(targets)}] {word:<16} tier={entry['tier']} "
                f"ctx=t{entry['context_tier']} q={rep['quality_score']:.2f} {flag}"
                + (f"  未过={rep['failed_gates']}" if rep["failed_gates"] else "")
            )

        if apply:
            await db.commit()


    verified = sum(1 for r in reports if r.get("verified"))
    degraded = sum(1 for r in reports if r.get("degraded"))
    with_context = sum(1 for r in reports if r.get("context_tier", 5) < 5)
    summary = {
        "collection": CORE_COLLECTION,
        "pool_single_words": len(pool),
        "trial_size": len(targets),
        "seed": seed,
        "applied": apply,
        "generated": sum(1 for r in reports if r.get("generated")),
        "skipped_contract": skipped,
        "call_errors": errored,
        "verified": verified,
        "degraded_no_context": degraded,
        "with_context": with_context,
        "image_prompt_coverage": round(
            sum(1 for r in reports if r.get("image_prompt")) / max(1, len(targets)), 4
        ),
        "failed_gate_counts": dict(gate_counter.most_common()),
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "applied" if apply else "dryrun"
    path = REPORT_DIR / f"trial_{len(targets)}_seed{seed}_{suffix}.json"
    path.write_text(
        json.dumps({"summary": summary, "reports": reports}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n=== 试跑汇总 ===")
    for k, v in summary.items():
        print(f"  {k:<24} {v}")
    print(f"\n完整报告: {path}")
    return summary


async def _audit(db, pool, targets, seed, apply) -> dict:
    """只跑**输入侧**：Context Retriever + 分层 + 既有素材覆盖。不调 LLM。

    存在的理由：生成质量依赖模型，而模型可能限流/下线（2026-10-03 实测 Veya 配额
    耗尽、Qwen key 为空）。输入侧是纯确定性的，不该被模型的可用性绑住 ——
    「扩到 3000 之前先知道输入侧成色」这件事今天就能回答。
    """
    from sqlalchemy import text

    from services.vocab_context import assign_tier, retrieve_context

    print("=== 输入侧审计（不调 LLM）===")
    tiers: Counter[str] = Counter()
    ctx_tiers: Counter[int] = Counter()
    detail: list[dict] = []
    for vid, word, _pos in targets:
        bundle = await retrieve_context(db, vid, limit=3)
        tier = await assign_tier(db, vid, has_context=bundle.has_context)
        tiers[tier] += 1
        ctx_tiers[bundle.tier] += 1
        detail.append(
            {
                "vocabulary_item_id": vid,
                "word": word,
                "tier": tier,
                "context_tier": bundle.tier,
                "sentences": len(bundle.sentences),
                "best": (bundle.best.text if bundle.best else None),
            }
        )

    ids = [t[0] for t in targets]
    # 用 `= ANY(:ids)` 而不是 `unnest(:ids::text[])`：asyncpg 的参数风格下
    # `::` 会被 SQLAlchemy 当成转义，报 "syntax error at or near ':'"。
    material = (
        await db.execute(
            text(
                """
        SELECT
          (SELECT count(*) FROM vocabulary_affixes
            WHERE vocabulary_item_id = ANY(:ids)) AS affix,
          (SELECT count(*) FROM vocabulary_xiangxing
            WHERE vocabulary_item_id = ANY(:ids)) AS xiangxing,
          (SELECT count(DISTINCT vocabulary_item_id) FROM vocabulary_collocations
            WHERE vocabulary_item_id = ANY(:ids)) AS colloc
        """
            ),
            {"ids": ids},
        )
    ).first()

    n = len(targets)
    has_ctx = sum(1 for d in detail if d["context_tier"] < 5)
    summary = {
        "mode": "audit_only",
        "pool_single_words": len(pool),
        "audit_size": n,
        "seed": seed,
        "tier_distribution": dict(tiers),
        "context_tier_distribution": {str(k): v for k, v in sorted(ctx_tiers.items())},
        "context_coverage": round(has_ctx / max(1, n), 4),
        "mean_sentences_per_word": round(
            sum(d["sentences"] for d in detail) / max(1, n), 3
        ),
        "has_affix": int(material.affix or 0),
        "has_xiangxing": int(material.xiangxing or 0),
        "has_collocations": int(material.colloc or 0),
        "llm_called": False,
    }
    for k, v in summary.items():
        print(f"  {k:<28} {v}")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"audit_{n}_seed{seed}.json"
    path.write_text(
        json.dumps({"summary": summary, "detail": detail}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n完整报告: {path}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20261003)
    parser.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    parser.add_argument(
        "--words",
        default=None,
        help="逗号分隔的指定词（人工审查用），给定后忽略 --limit/seed 抽样",
    )
    parser.add_argument(
        "--require-context",
        action="store_true",
        help="只取有真实教材/NCE 例句的词（A/B 级），本轮验的是有语境时的生成质量",
    )
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="只跑输入侧（Context Retriever + 分层），不调 LLM",
    )
    args = parser.parse_args()
    # -u：长跑必须实时看到进度。第一版没加，整轮 4KB 输出全压在缓冲区里，
    # 进程被杀时进度与部分结果一起丢（100 词试跑就是这么丢的）。
    sys.stdout.reconfigure(line_buffering=True)
    asyncio.run(
        run(
            args.limit,
            args.seed,
            args.apply,
            args.audit_only,
            args.require_context,
            args.words,
        )
    )


if __name__ == "__main__":
    main()