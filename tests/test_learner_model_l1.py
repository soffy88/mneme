"""L1 统一学习者模型（单一真相源）：权威阈值 + 掌握色 + 学习阶段状态机 + ZPD 带。纯函数。"""

from services import learner_model as lm


def test_canonical_thresholds():
    assert lm.GATE == 0.6 and lm.MASTERED == 0.7
    assert lm.GREEN == 0.75 and lm.YELLOW == 0.40


def test_mastery_color_single_source():
    assert lm.mastery_color(None) == "unknown"
    assert lm.mastery_color(0.8) == "green"
    assert lm.mastery_color(0.5) == "yellow"
    assert lm.mastery_color(0.2) == "red"


def test_get_stage_state_machine():
    assert lm.get_stage(None) == "worked_example"
    assert lm.get_stage(None, prereqs_ok=False) == "locked"
    assert lm.get_stage(0.3) == "completion"
    assert lm.get_stage(0.65) == "retrieval"
    assert lm.get_stage(0.9) == "consolidation"


def test_zpd_band_targets_desirable_difficulty():
    band = lm.get_zpd_band(0.5)
    assert band["difficulty_min"] <= 0.5 <= band["difficulty_max"]
    assert band["target_success"] == [0.70, 0.85]


def test_fringe_uses_gate_threshold():
    assert lm.fringe(None, ["A"], {"A": 0.65}) == "learnable"
    assert lm.fringe(None, ["A"], {"A": 0.5}) == "locked"


def test_call_sites_migrated_to_single_source():
    """守卫：main.py 掌握色/fringe 委托 learner_model；daily_plan 用 GATE。

    2026-07-04 审计发现的漂移（各自硬编码 0.5/0.4/0.6，未从 learner_model 导入，
    容易和权威阈值悄悄脱节）已修复，这里补守卫防止再犯。
    """
    main_src = open("services/main.py", encoding="utf-8").read()
    assert "from services.learner_model import mastery_color" in main_src
    assert "from services.learner_model import fringe" in main_src
    assert "_MASTERED" in main_src
    dp_src = open("services/daily_plan_service.py", encoding="utf-8").read()
    assert "GATE as MASTERY_THRESHOLD" in dp_src

    cog_src = open("services/cognitive_service.py", encoding="utf-8").read()
    assert "from services.learner_model import GATE" in cog_src
    assert "KCMastery.p_mastery < 0.5" not in cog_src
    assert "mastery_threshold: float = 0.6" not in cog_src

    vocab_src = open("services/vocab_service.py", encoding="utf-8").read()
    assert "from services.learner_model import GATE" in vocab_src
    assert "gate: float = 0.6" not in vocab_src

    socratic_src = open("services/socratic_service.py", encoding="utf-8").read()
    assert "from services.learner_model import YELLOW" in socratic_src
    assert "< 0.4 else" not in socratic_src
