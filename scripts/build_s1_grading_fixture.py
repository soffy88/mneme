"""S1 判分准确率验收：从真实题库冻结抽样 fixture（一次性生成，非 CI 内跑）。

根因（见 TASKS.md AB 段）：W1/W2a 只用 3 道构造桩题验收判分（tests/test_dod_e2e.py），
真题库上线后 AA.10 核查出实际判对率仅 10%。构造桩题 != 真实数据路径。

本脚本只在需要重建 fixture 时手动跑一次（题库有大改动、grade_math 逻辑大改时）：

    docker compose exec api python scripts/build_s1_grading_fixture.py

抽样口径与 tool_request_question 的 serve 过滤（AA.9/AA.10 修 B）完全一致：
高一、非图形、g10-a KC、且"可确定性判分"（选择题字母，或短且无解析标记的 solve/fill）。
choice 题正确答案就是字母本身，不需要 LLM。solve/fill 题库只存一种写法（LaTeX 解析体的
最终答案），没有"同一题另一种写法"可互测——照抄 AA.10 的验证方法：LLM 生成一个学生会写的
朴素写法答案，写死进 fixture（一次性人工触发，CI 跑测试时零 LLM 依赖，纯读 JSON）。

抽样策略：全部 solve/fill 合格题（数量小，是 AA.10 修的高风险类别，全收）+ 随机补足到
choice 题凑够 N（seed 固定，可复现；不挑好题——按 id 排序后用 Random(SEED) 抽，不手选）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import asyncpg

from obase.config import settings
from services.mcp_router import _choice_prompt, _infer_qtype
from services.providers.qwenvl_caller import QwenTextCaller

SEED = 20260717  # 固定种子（生成日期即可，只要固定不变、可复现）
TARGET_N = 120
OUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "fixtures"
    / "s1_grading_sample.json"
)

_ELIGIBLE_SQL = """
    SELECT id, question_text, correct_answer, knowledge_points, profiler_analysis
    FROM wrong_questions
    WHERE needs_image = false
      AND question_text NOT LIKE '%<ImageHere>%'
      AND profiler_analysis->>'grade' = '高一'
      AND (
        correct_answer ~ '^[A-D、,]{1,3}$'
        OR (
          length(correct_answer) <= 40
          AND correct_answer !~ '解析|见解析|【解|证明'
          AND correct_answer !~ '[(（][1１２3３]'
        )
      )
      AND EXISTS (
        SELECT 1 FROM jsonb_object_keys(knowledge_points) k
        WHERE k LIKE 'renjiao-math-g10-a-%'
      )
    ORDER BY id
"""

_STUDENT_ANSWER_PROMPT = (
    "这是一道高一数学题的标准答案（可能带 LaTeX 排版）：\n{expected}\n\n"
    "题干：\n{prompt}\n\n"
    "请给出这道题「正确」的最终作答——只要学生会在作答框里填的最终结果，不要解题过程，"
    "不要用 LaTeX 命令（不要 \\frac \\sqrt \\pi 等反斜杠写法），改用学生日常键盘书写习惯"
    "（如 1/2、sqrt(2)、pi、x^2、a>=1、A={{1,2,3}}）。只输出最终答案本身，不要任何解释文字。"
)


def _g10a_kc(knowledge_points: dict) -> str:
    for k in knowledge_points:
        if k.startswith("renjiao-math-g10-a-"):
            return k
    raise ValueError("no g10-a kc in knowledge_points")


async def _gen_student_answer(
    caller: QwenTextCaller, prompt: str, expected: str
) -> str:
    out = await caller(
        messages=[
            {
                "role": "user",
                "content": _STUDENT_ANSWER_PROMPT.format(
                    expected=expected, prompt=prompt
                ),
            }
        ],
        max_tokens=200,
        enable_thinking=False,
    )
    return out["content"].strip()


async def run() -> None:
    import os

    conn = await asyncpg.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
    try:
        rows = await conn.fetch(_ELIGIBLE_SQL)
    finally:
        await conn.close()

    print(f"eligible rows: {len(rows)}")

    solve_rows: list[asyncpg.Record] = []
    choice_rows: list[asyncpg.Record] = []
    for r in rows:
        qtype = _infer_qtype(str(r["correct_answer"]))
        (solve_rows if qtype == "solve" else choice_rows).append(r)

    import random

    rng = random.Random(SEED)
    n_choice = max(0, TARGET_N - len(solve_rows))
    sampled_choice = rng.sample(choice_rows, k=min(n_choice, len(choice_rows)))
    sample = solve_rows + sampled_choice
    print(
        f"sampled: {len(sample)} (solve/fill={len(solve_rows)}, choice={len(sampled_choice)})"
    )

    caller = QwenTextCaller(
        api_key=os.environ["DASHSCOPE_API_KEY"],
        model=os.environ.get("QWEN_MODEL", "qwen-plus"),
    )

    fixture = []
    skipped = 0
    for r in sample:
        kp = r["knowledge_points"]
        kp = json.loads(kp) if isinstance(kp, str) else kp
        try:
            kc_id = _g10a_kc(kp)
        except ValueError:
            skipped += 1
            continue
        expected = str(r["correct_answer"])
        qtype = _infer_qtype(expected)
        profiler = r["profiler_analysis"]
        profiler = json.loads(profiler) if isinstance(profiler, str) else profiler
        prompt = _choice_prompt(str(r["question_text"]), qtype, profiler)

        if qtype == "choice":
            student_answer = expected  # 字母答案本身即"学生会写的正确作答"，无需 LLM
        else:
            try:
                student_answer = await _gen_student_answer(caller, prompt, expected)
            except Exception as e:  # noqa: BLE001 — 单题失败不阻断整批
                print(f"  LLM failed for {r['id']}: {e}")
                skipped += 1
                continue

        fixture.append(
            {
                "id": str(r["id"]),
                "kc_id": kc_id,
                "qtype": qtype,
                "expected": expected,
                "student_answer": student_answer,
            }
        )

    print(f"fixture entries: {len(fixture)} (skipped: {skipped})")
    print(f"distinct KCs: {len({e['kc_id'] for e in fixture})}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(
            {"seed": SEED, "source_query": _ELIGIBLE_SQL, "entries": fixture},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    asyncio.run(run())
