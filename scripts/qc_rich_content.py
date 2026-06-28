"""KU "讲透"内容质检门（rich_content 完整性 / 反幻觉 / 反截断）。

LLM 生成的讲解可能：解析失败、拒答、被截断、LaTeX 不配对、内容过薄。
本脚本扫描 knowledge_units.rich_content，按类别报告问题 KU，
可作内容上线前的质量门（发现 FAIL 时退出码 1）。

用法：
    python scripts/qc_rich_content.py                 # 全量
    python scripts/qc_rich_content.py --subject math  # 限学科
    python scripts/qc_rich_content.py --limit 20      # 抽样
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from obase.config import settings  # noqa: E402
from services.models import KnowledgeUnit, Textbook  # noqa: E402

# 拒答信号（具体短语，避免误伤"职工无法完成销售指标"这类正常内容）
_REFUSAL = ("作为一个ai", "作为ai模型", "as an ai", "i cannot", "i'm sorry",
            "无法生成", "无法为您", "抱歉，我无法", "对不起，我无法")
# 每个 ku_type 的"核心内容键"——至少一个非空才算有实质内容
_CORE_KEYS = ("definition", "formula", "steps", "intuition", "core", "law", "motivation")


def _iter_strings(value):
    """递归取出 rich_content 里所有字符串。"""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _iter_strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _iter_strings(v)


def check_one(ku_type: str, rc) -> list[str]:
    """返回该 KU 的问题列表（空=通过）。"""
    problems: list[str] = []
    if not isinstance(rc, dict) or not rc:
        return ["rich_content 为空或非对象"]
    # 1. 生成失败标记
    for bad in ("_error", "_raw", "_skipped"):
        if bad in rc:
            problems.append(f"生成失败标记 {bad}")
    if problems:
        return problems  # 失败标记优先，不再细查

    texts = list(_iter_strings(rc))
    blob = "\n".join(texts).lower()
    # 2. 拒答
    for marker in _REFUSAL:
        if marker in blob:
            problems.append(f"疑似拒答: '{marker}'")
            break
    # 3. LaTeX $ 不配对
    if blob.count("$") % 2 != 0:
        problems.append("LaTeX $ 数量为奇数（疑似不配对/截断）")
    # 4. 内容过薄：无任何核心键的非空值
    has_core = any(
        rc.get(k) and (rc[k] if isinstance(rc[k], str) else any(rc[k]))
        for k in _CORE_KEYS if k in rc
    )
    if not has_core and not any(k in rc for k in _CORE_KEYS):
        # 该类型本就无核心键（如 physical_model 用 motivation）——放宽：只要总文本够长
        if len("".join(texts)) < 40:
            problems.append("内容过薄（<40 字且无核心键）")
    elif not has_core:
        problems.append("核心键全空（definition/formula/steps/intuition…）")
    return problems


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.connect() as conn:
        stmt = select(KnowledgeUnit.id, KnowledgeUnit.ku_type, KnowledgeUnit.rich_content)
        if args.subject:
            stmt = stmt.join(Textbook, KnowledgeUnit.textbook_id == Textbook.id).where(Textbook.subject == args.subject)
        if args.limit:
            stmt = stmt.limit(args.limit)
        rows = (await conn.execute(stmt)).all()
    await engine.dispose()

    total = len(rows)
    enriched = [r for r in rows if r.rich_content is not None]
    flagged: list[tuple[str, list[str]]] = []
    for kid, ku_type, rc in enriched:
        probs = check_one(ku_type, rc)
        if probs:
            flagged.append((kid, probs))

    print(f"扫描 {total} 个 KU，其中 {len(enriched)} 个已生成 rich_content，{total - len(enriched)} 个未生成。")
    print(f"质检：{len(enriched) - len(flagged)} 通过 / {len(flagged)} 有问题。")
    for kid, probs in flagged[:50]:
        print(f"  ✗ {kid}: {'; '.join(probs)}")
    if len(flagged) > 50:
        print(f"  …还有 {len(flagged) - 50} 个（截断显示）")

    sys.exit(1 if flagged else 0)


if __name__ == "__main__":
    asyncio.run(main())
