"""从 C-Eval（ceval/ceval-exam）导入非数学学科选择题到公共题库（item 10 数据接线）。

C-Eval 是中文学科评测集，MCQ 格式（question + A/B/C/D + answer 字母）。
本脚本拉取物理/语文相关 config 的 dev+val 切分（含答案），写入 wrong_questions
(student_id=NULL) 作为公共题库题。选择题 → judge_answer 可确定性判分。

  python scripts/import_ceval_questions.py            # 真导入
  python scripts/import_ceval_questions.py --dry-run  # 只预览

注意：subject 列存英文代码（与前端 listPracticeTopics(subject) 查询一致：'physics'/'chinese'）。
knowledge_points 用粗粒度占位键 ceval-{code}-{cluster}（每簇≥5题，满足 topics 的 min_count）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.parse
import urllib.request

import asyncpg

from obase.config import settings

# target_code → [(ceval_config, 簇名)]
SUBJECTS: dict[str, list[tuple[str, str]]] = {
    "physics": [
        ("high_school_physics", "高中物理"),
        ("middle_school_physics", "初中物理"),
        ("college_physics", "大学物理"),
    ],
    "chinese": [
        ("high_school_chinese", "高中语文"),
        ("chinese_language_and_literature", "语言文字与文学"),
    ],
}
SPLITS = ("dev", "val")  # 含答案（test 答案在 C-Eval 中隐藏）
_BASE = "https://datasets-server.huggingface.co/rows"


def fetch_rows(config: str, split: str) -> list[dict]:
    """拉取一个 (config, split) 的全部行（C-Eval 单科 <100 行，一次取够）。"""
    qs = urllib.parse.urlencode(
        {"dataset": "ceval/ceval-exam", "config": config, "split": split,
         "offset": 0, "length": 100}
    )
    with urllib.request.urlopen(f"{_BASE}?{qs}", timeout=30) as resp:
        data = json.loads(resp.read())
    return [r["row"] for r in data.get("rows", [])]


def to_question(row: dict) -> tuple[str, str] | None:
    """C-Eval 行 → (question_text 含选项, correct_answer 字母)。无有效答案则 None。"""
    ans = (row.get("answer") or "").strip().upper()
    if ans not in ("A", "B", "C", "D"):
        return None
    q = (row.get("question") or "").strip()
    opts = "\n".join(f"{k}. {row.get(k, '')}" for k in ("A", "B", "C", "D"))
    return (f"{q}\n{opts}", ans)


async def run(dry_run: bool) -> None:
    conn = await asyncpg.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
    stats = {"ok": 0, "skip": 0, "bad": 0}
    try:
        for code, configs in SUBJECTS.items():
            for config, cluster in configs:
                kp_key = f"ceval-{code}-{cluster}"
                kp = json.dumps({kp_key: cluster}, ensure_ascii=False)
                for split in SPLITS:
                    try:
                        rows = fetch_rows(config, split)
                    except Exception as e:
                        print(f"  ⚠ 拉取失败 {config}/{split}: {e}")
                        continue
                    for row in rows:
                        parsed = to_question(row)
                        if not parsed:
                            stats["bad"] += 1
                            continue
                        qtext, ans = parsed
                        ceval_id = f"{config}-{split}-{row.get('id')}"
                        if dry_run:
                            stats["ok"] += 1
                            if stats["ok"] <= 3:
                                print(f"  [{code}·{cluster}] {qtext[:60]}… → {ans}")
                            continue
                        exists = await conn.fetchval(
                            "select 1 from wrong_questions where student_id is null "
                            "and profiler_analysis->>'ceval_id' = $1", ceval_id)
                        if exists:
                            stats["skip"] += 1
                            continue
                        prof = json.dumps(
                            {"source": "ceval", "ceval_id": ceval_id, "cluster": cluster,
                             "explanation": row.get("explanation", "")},
                            ensure_ascii=False)
                        await conn.execute(
                            """INSERT INTO wrong_questions
                                   (id, paper_id, student_id, subject, question_text,
                                    student_answer, correct_answer, knowledge_points,
                                    profiler_analysis, needs_image)
                               VALUES (gen_random_uuid(), NULL, NULL, $1, $2,
                                       NULL, $3, $4::jsonb, $5::jsonb, false)""",
                            code, qtext, ans, kp, prof)
                        stats["ok"] += 1
                    print(f"  {config}/{split}: 累计 ok={stats['ok']} skip={stats['skip']}")
    finally:
        await conn.close()
    print(f"\n完成 dry_run={dry_run}: 导入={stats['ok']} 跳过={stats['skip']} 无效={stats['bad']}")
    if not dry_run:
        print("下一步（可选）: python scripts/match_questions_to_ku.py 把占位 KC 映射到真实 KU")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    asyncio.run(run(args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
