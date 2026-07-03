"""RCT 实验分流(首个:教学引擎)。确定性分臂 + 安全默认。"""


import pytest
from oprim.experiment import assign_arm


def test_assign_arm_deterministic():
    a1 = assign_arm("student-123", "exp", ["A", "B"])
    a2 = assign_arm("student-123", "exp", ["A", "B"])
    assert a1 == a2 and a1 in ("A", "B")


def test_assign_arm_roughly_balanced():
    arms = [assign_arm(f"s{i}", "exp", ["A", "B"]) for i in range(1000)]
    a = arms.count("A")
    assert 400 < a < 600  # 50/50 ±10%


def test_assign_arm_respects_ratios():
    arms = [assign_arm(f"s{i}", "exp", ["A", "B"], [0.8, 0.2]) for i in range(1000)]
    a = arms.count("A")
    assert 720 < a < 880  # ~80%


def test_student_arm_control_when_experiment_off(monkeypatch):
    from services.experiment_service import student_arm, teaching_engine_on_for

    monkeypatch.delenv("EXPERIMENT_TEACHING_ENGINE", raising=False)
    monkeypatch.delenv("TEACHING_ENGINE_ENABLED", raising=False)
    # 实验关：所有人 control，教学引擎不开（现网零变化）
    for sid in ("a", "b", "c", "d"):
        assert student_arm(sid) == "control"
        assert teaching_engine_on_for(sid) is False


def test_student_arm_splits_when_experiment_on(monkeypatch):
    from services.experiment_service import student_arm

    monkeypatch.setenv("EXPERIMENT_TEACHING_ENGINE", "1")
    arms = {student_arm(f"stu-{i}") for i in range(200)}
    assert arms == {"worked_example", "control"}  # 两臂都出现


def test_global_flag_forces_engine_on(monkeypatch):
    from services.experiment_service import teaching_engine_on_for

    monkeypatch.setenv("TEACHING_ENGINE_ENABLED", "1")
    assert teaching_engine_on_for("anyone") is True


@pytest.mark.asyncio
async def test_experiment_metrics_shape():
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from sqlalchemy.pool import NullPool

    from obase.config import settings
    from services.experiment_service import experiment_metrics

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as db:
        m = await experiment_metrics(db, "teaching_engine_v1")
    await engine.dispose()
    assert "arms" in m and "worked_example" in m["arms"] and "control" in m["arms"]
    for arm in m["arms"].values():
        assert "delayed_retention" in arm and "n_students" in arm
