"""L3 能力估计(Rasch θ)：自适应定位/ZPD 的心脏。纯函数，确定性。"""

from oprim.ability import estimate_ability, next_item_difficulty


def test_empty_returns_prior_median():
    r = estimate_ability([])
    assert r["theta"] == 0.5 and r["n"] == 0 and r["se"] is None


def test_all_correct_on_hard_items_gives_high_ability():
    # 难题全对 → 高能力
    r = estimate_ability([(0.8, True), (0.85, True), (0.9, True)])
    assert r["theta"] >= 0.8


def test_all_wrong_on_easy_items_gives_low_ability():
    r = estimate_ability([(0.2, False), (0.15, False), (0.1, False)])
    assert r["theta"] <= 0.2


def test_mixed_responses_land_in_middle():
    # 中等难度对错各半 → θ 居中
    r = estimate_ability([(0.5, True), (0.5, False), (0.55, True), (0.45, False)])
    assert 0.35 <= r["theta"] <= 0.65


def test_more_evidence_shrinks_se():
    few = estimate_ability([(0.5, True), (0.5, False)])
    many = estimate_ability([(0.5, True), (0.5, False)] * 10)
    assert few["se"] is not None and many["se"] is not None
    assert many["se"] < few["se"]  # 证据越多 SE 越小


def test_monotonic_ability():
    # 逐步答对更多难题，θ 单调不降
    base = estimate_ability([(0.6, False), (0.6, False)])["theta"]
    up = estimate_ability([(0.6, True), (0.6, True)])["theta"]
    assert up > base


def test_next_item_targets_theta():
    assert next_item_difficulty(0.7) == 0.7
    assert next_item_difficulty(1.5) == 1.0  # clamp
