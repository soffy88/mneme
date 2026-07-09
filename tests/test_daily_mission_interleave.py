"""daily_mission 交错红线：产出任务相邻 KC 不同（omodul.daily_mission_workflow）。无 DB。"""

from __future__ import annotations

from pathlib import Path

from omodul.daily_mission_workflow import (
    DailyMissionConfig,
    DailyMissionInput,
    daily_mission_workflow,
)


def _q(qid: str, kc: str) -> dict:
    return {"question_id": qid, "kc_id": kc, "difficulty": 0.5}


def test_daily_mission_adjacent_kc_differ(tmp_path: Path):
    """朴素按优先级拼接会得到 A A A B B；交错后相邻任务 KC 必须不同（红线）。"""
    inp = DailyMissionInput(
        user_id="stu-interleave-test",
        mission_date="2026-07-02",
        available_questions=[
            _q("q1", "KC-A"),
            _q("q2", "KC-A"),
            _q("q3", "KC-A"),
            _q("q4", "KC-B"),
            _q("q5", "KC-B"),
            _q("q6", "KC-B"),
        ],
        kc_mastery={"KC-A": 0.1, "KC-B": 0.9},  # A 优先级远高于 B → 朴素排序会连排 A
    )
    res = daily_mission_workflow(DailyMissionConfig(mission_count=5), inp, tmp_path)
    assert res["status"] == "ok"
    kcs = [m["ku_id"] for m in res["missions"]]
    assert len(kcs) == 5  # 可交错时数量不缩水
    assert set(kcs) == {"KC-A", "KC-B"}
    for a, b in zip(kcs, kcs[1:]):
        assert a != b  # 相邻 KC 不同（交错红线）


def test_daily_mission_single_kc_no_crash(tmp_path: Path):
    """候选只有 1 个 KC 时无法交错 → 原样返回，不崩溃。"""
    inp = DailyMissionInput(
        user_id="stu-interleave-test",
        mission_date="2026-07-02",
        available_questions=[_q("q1", "KC-A"), _q("q2", "KC-A")],
        kc_mastery={"KC-A": 0.5},
    )
    res = daily_mission_workflow(DailyMissionConfig(mission_count=2), inp, tmp_path)
    assert res["status"] == "ok"
    assert len(res["missions"]) == 2
