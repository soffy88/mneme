"""S1 判分准确率验收（阻断项，见 TASKS.md AB 段）。

根因：W1/W2a 只用 3 道构造桩题（test_dod_e2e.py）验收判分，真题库上线后 AA.10 核查出
实际判对率仅 10%。构造桩题 != 真实数据路径。

本测试跑的是从真实题库冻结抽样的 fixture（tests/fixtures/s1_grading_sample.json，
由 scripts/build_s1_grading_fixture.py 一次性生成，seed 固定可复现、不挑好题——
solve/fill 全量收录+choice 随机补足）。CI 内零 DB/LLM 依赖，只读 JSON。

fixture 重建：题库大改或 grade_math/answer_match 逻辑大改时手动重跑
`docker compose exec api python scripts/build_s1_grading_fixture.py`。
"""

from __future__ import annotations

import json
from pathlib import Path

from mneme_core.oprim.grade import answer_match

from services.math_grade import grade_math

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "s1_grading_sample.json"
FAILURES_PATH = Path(__file__).parent.parent / "outputs" / "s1_grading_failures.json"
MIN_N = 100
MIN_KC = 30
ACCURACY_THRESHOLD = 0.90


def _grade_entry(entry: dict) -> bool:
    if entry["qtype"] == "choice":
        return answer_match(
            entry["student_answer"], expected=entry["expected"], qtype="choice"
        ).is_correct
    return grade_math(entry["student_answer"], entry["expected"])


def test_real_bank_sample_grading_accuracy() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    entries = fixture["entries"]
    assert len(entries) >= MIN_N, (
        f"抽样量 {len(entries)} < {MIN_N}，需重跑 scripts/build_s1_grading_fixture.py"
    )
    assert len({e["kc_id"] for e in entries}) >= MIN_KC

    failures = []
    for entry in entries:
        if not _grade_entry(entry):
            failures.append(entry)

    accuracy = 1 - len(failures) / len(entries)

    FAILURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    FAILURES_PATH.write_text(
        json.dumps(
            {
                "total": len(entries),
                "failed": len(failures),
                "accuracy": round(accuracy, 4),
                "threshold": ACCURACY_THRESHOLD,
                "failures": failures,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    assert accuracy >= ACCURACY_THRESHOLD, (
        f"判分准确率 {accuracy:.1%} < {ACCURACY_THRESHOLD:.0%}；"
        f"失败样本见 {FAILURES_PATH}"
    )
