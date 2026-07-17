"""Tests for oskill.quiz_generator — C2 (W2C)."""

from mneme_core.oprim.models import (
    BktPosterior,
    KnowledgePoint,
    KnowledgeType,
    LearningProgress,
    Module,
)
from mneme_core.oskill.quiz_generator import quiz_generator


def _kp(kc_id, difficulty=0.5, ktype=KnowledgeType.PROCEDURE):
    return KnowledgePoint(id=kc_id, name=kc_id, type=ktype, difficulty=difficulty)


def _progress(bkt=None, qual=None):
    return LearningProgress(
        student_id="s1",
        modules=[Module(id="m", name="m", order=0, knowledge_points=[])],
        bkt=bkt or {},
        qualitative_mastery=qual or {},
    )


def test_selects_up_to_size_ascending_by_default():
    cands = [_kp("c", 0.9), _kp("a", 0.1), _kp("b", 0.5)]
    result = quiz_generator(_progress(), cands, size=2)
    assert [kp.id for kp in result] == ["a", "b"]


def test_excludes_mastered_kc_by_default():
    mastered = BktPosterior(p_learned=0.99, sigma=0.01, n_obs=5)  # 远超阈值 → 过门
    unmastered = BktPosterior(p_learned=0.3, sigma=0.2, n_obs=3)
    progress = _progress(bkt={"mastered_kc": mastered, "weak_kc": unmastered})
    cands = [_kp("mastered_kc", 0.5), _kp("weak_kc", 0.5)]

    result = quiz_generator(progress, cands, size=10)
    assert [kp.id for kp in result] == ["weak_kc"]


def test_exclude_mastered_false_includes_everything():
    mastered = BktPosterior(p_learned=0.99, sigma=0.01, n_obs=5)
    progress = _progress(bkt={"mastered_kc": mastered})
    cands = [_kp("mastered_kc", 0.5), _kp("new_kc", 0.5)]

    result = quiz_generator(progress, cands, size=10, exclude_mastered=False)
    assert {kp.id for kp in result} == {"mastered_kc", "new_kc"}


def test_dedupes_candidates_by_id_keeping_first():
    cands = [_kp("a", 0.1), _kp("a", 0.9)]  # 同 id 不同 difficulty，保留首次出现
    result = quiz_generator(_progress(), cands, size=10)
    assert len(result) == 1
    assert result[0].difficulty == 0.1


def test_fewer_candidates_than_size_returns_all_no_padding():
    cands = [_kp("a"), _kp("b")]
    result = quiz_generator(_progress(), cands, size=10)
    assert len(result) == 2


def test_mixed_curve_passthrough():
    cands = [_kp("a", 0.1), _kp("b", 0.5), _kp("c", 0.9)]
    result = quiz_generator(_progress(), cands, size=3, difficulty_curve="mixed")
    assert [kp.id for kp in result] == ["a", "c", "b"]
