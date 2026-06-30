"""把非数学公共题库的"源前缀占位 KC 键"归并为干净的粗粒度 KC 层（实证决策）。

实证结论（见对话）：
- 细粒度自动匹配（KU/cluster）torch-free 不可靠（TF-IDF 平均相似度 0.12、明显错配），
  本会话无可用 LLM；细到 402 cluster 又把题库打碎到 <5 题/桶（topics 阈值失效）。
- 故采用与数学（~14 KC）同档的**粗粒度 KC 层**：跨源同题归并、去前缀、可读命名。
- 细到 KU 级掌握度需离线 LLM 语义匹配（generalize match_questions_to_ku），单列后续。

幂等：把每题 knowledge_points 的占位键重写为下方 canonical 键（已是 canonical 则跳过）。
"""
from __future__ import annotations

import asyncio
import json

import asyncpg

from obase.config import settings

# 旧占位键 → (canonical 键, 友好名)。跨源同主题合并到同一 KC（更多数据/更连贯掌握度）。
CANON: dict[str, tuple[str, str]] = {
    # 物理
    "cmmlu-physics-高中物理": ("PHYS-高中物理", "高中物理"),
    "ceval-physics-高中物理": ("PHYS-高中物理", "高中物理"),
    "gaokao-physics-高考物理选择": ("PHYS-高中物理", "高中物理"),
    "cmmlu-physics-概念物理": ("PHYS-概念物理", "概念物理"),
    "ceval-physics-初中物理": ("PHYS-初中物理", "初中物理"),
    "ceval-physics-大学物理": ("PHYS-大学物理", "大学物理"),
    # 语文
    "cmmlu-chinese-小学语文": ("CHN-小学语文", "小学语文"),
    "cmmlu-chinese-中国文学": ("CHN-文学", "中国文学"),
    "ceval-chinese-语言文字与文学": ("CHN-文学", "中国文学"),
    "cmmlu-chinese-古代汉语": ("CHN-古代汉语", "古代汉语"),
    "cmmlu-chinese-现代汉语": ("CHN-现代汉语", "现代汉语"),
    "gaokao-chinese-高考语文语用": ("CHN-高中语文", "高中语文·语用"),
    "ceval-chinese-高中语文": ("CHN-高中语文", "高中语文·语用"),
    # 英语
    "gaokao-english-高考英语单选": ("ENG-高中英语", "高中英语"),
}


async def run(dry_run: bool) -> None:
    conn = await asyncpg.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
    updated = skipped = 0
    try:
        rows = await conn.fetch(
            "select id, knowledge_points from wrong_questions "
            "where student_id is null and subject in ('physics','chinese','english')")
        for r in rows:
            kp = r["knowledge_points"]
            kp = json.loads(kp) if isinstance(kp, str) else dict(kp)
            old_keys = list(kp.keys())
            new_kp = {}
            changed = False
            for k in old_keys:
                if k in CANON:
                    ck, name = CANON[k]
                    new_kp[ck] = name
                    changed = changed or (ck != k)
                else:
                    new_kp[k] = kp[k]  # 已 canonical 或未知，原样
            if changed and not dry_run:
                await conn.execute(
                    "update wrong_questions set knowledge_points=$1::jsonb where id=$2",
                    json.dumps(new_kp, ensure_ascii=False), r["id"])
            updated += 1 if changed else 0
            skipped += 0 if changed else 1
    finally:
        await conn.close()
    print(f"完成 dry_run={dry_run}: 归并 {updated} 题，跳过 {skipped} 题")


def main() -> None:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    asyncio.run(run(p.parse_args().dry_run))


if __name__ == "__main__":
    main()
