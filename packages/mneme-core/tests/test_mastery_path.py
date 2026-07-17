"""Tests for omodul.mastery_path — S2."""

from mneme_core.omodul.mastery_path import (
    MasteryPathConfig,
    MasteryPathInput,
    mastery_path,
)
from mneme_core.oprim.models import (
    BktPosterior,
    KnowledgePoint,
    KnowledgeType,
    LearningProgress,
    Module,
    ReviewTask,
)


def _progress(kps, bkt=None, review_queue=None):
    mod = Module(id="m1", name="Module 1", order=0, knowledge_points=kps)
    return LearningProgress(
        student_id="s1",
        modules=[mod],
        bkt=bkt or {},
        review_queue=review_queue or [],
    )


def test_signature_is_config_input_output_dir_to_dict():
    """三件套标准签名：(config, input_data, output_dir) -> dict。"""
    kp = KnowledgePoint(id="k1", name="K1", type=KnowledgeType.MEMORY)
    r = mastery_path(
        MasteryPathConfig(), MasteryPathInput(_progress([kp]), now=0.0), None
    )
    assert isinstance(r, dict)


def test_completed_findings_shape():
    kp = KnowledgePoint(id="k1", name="K1", type=KnowledgeType.MEMORY)
    review = ReviewTask(knowledge_point_id="k1", due_at=0.0, priority=1)
    progress = _progress(
        [kp],
        bkt={"k1": BktPosterior(p_learned=0.5, sigma=0.1, n_obs=1)},
        review_queue=[review],
    )
    r = mastery_path(MasteryPathConfig(), MasteryPathInput(progress, now=100.0), None)

    assert r["status"] == "completed"
    assert r["error"] is None
    assert r["findings"]["total_kps"] == 1
    assert r["findings"]["pending_review_count"] == 1
    assert r["findings"]["next"]["action"] == "review"


def test_decision_trail_has_no_raw_student_id():
    """决策轨迹（decision_trail）不得含真实 student_id（CLAUDE.md 指纹/轨迹禁 PII 红线）。"""
    kp = KnowledgePoint(id="k1", name="K1", type=KnowledgeType.MEMORY)
    progress = _progress([kp])
    r = mastery_path(MasteryPathConfig(), MasteryPathInput(progress, now=0.0), None)
    assert "s1" not in str(r["decision_trail"])


def test_never_raises_returns_failed_status():
    """失败不 raise：传入会在 map_summary 内部炸的 progress，仍拿到 status=failed。"""
    bad_progress = object()  # 没有 .modules，map_summary 内部访问会抛 AttributeError
    r = mastery_path(MasteryPathConfig(), MasteryPathInput(bad_progress, now=0.0), None)
    assert r["status"] == "failed"
    assert r["findings"] is None
    assert r["error"]["type"] == "AttributeError"


def test_idempotent_no_fingerprint_needed():
    """advance = 纯派生查询：同输入永远同输出，天然幂等，故不启用 fingerprint。"""
    kp = KnowledgePoint(id="k1", name="K1", type=KnowledgeType.MEMORY)
    progress = _progress([kp])
    r1 = mastery_path(MasteryPathConfig(), MasteryPathInput(progress, now=50.0), None)
    r2 = mastery_path(MasteryPathConfig(), MasteryPathInput(progress, now=50.0), None)
    assert r1["findings"] == r2["findings"]
    assert r1["fingerprint"] is None
    assert r2["fingerprint"] is None


def test_enabled_pillars_declares_decision_trail_only():
    assert MasteryPathConfig._enabled_pillars == frozenset({"decision_trail"})
    assert "fingerprint" not in MasteryPathConfig._enabled_pillars
    assert len(MasteryPathConfig._enabled_pillars) >= 1  # §5.1 判定标准 6：至少 1 项


def test_no_compute_fingerprint_for_exposed():
    """未启用 fingerprint 支柱 → 不暴露 compute_fingerprint_for（§5.5 仅启用时 MUST）。"""
    import mneme_core.omodul.mastery_path as mod

    assert not hasattr(mod, "compute_fingerprint_for")
