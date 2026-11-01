"""物理真值模型 + 不变量检查 + 计算题纪律（纯函数 + 库上测试）。

方法来源 Atlas of Physics 只学方法、干净重写；本文件不含对方代码、
文本或题目。模型参数值、检查项、题项均为自写。
"""

from __future__ import annotations

import math
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from services.models import (
    KnowledgeCluster,
    KnowledgeUnit,
    PhysicsModel,
    PhysicsPracticeItem,
    Textbook,
    User,
    UserRole,
)
from services.physics_models import (
    PHYSICS_MODEL_REGISTRY,
    ImpossibleStateError,
    PhysicsTruthModel,
    TaggedNumber,
    NumberKind,
    register_physics_models,
    run_invariant_checks,
    verify_physics_model,
)
from services.physics_practice import build_practice_item, verify_practice_item
from services.teaching_figure import MODEL_REGISTRY

KU_ID = "phys-test-ku"
TB_ID = "phys-test-textbook"
CLUSTER_ID = "phys-test-cluster"


def _tn(value, unit, kind, note):
    return {"value": value, "unit": unit, "kind": kind, "note": note}


def _bi(zh, en):
    return {"zh": zh, "en": en}


def _projectile_params():
    return {
        "v0": _tn(12, "m/s", "source_fact", "题目给定：水平初速度 12 米每秒"),
        "height": _tn(20, "m", "source_fact", "题目给定：抛出高度 20 米"),
        "g": _tn(9.8, "m/s²", "source_fact", "取重力加速度 9.8 米每二次方秒"),
    }


def _pendulum_params():
    return {
        "length": _tn(0.8, "m", "source_fact", "题目给定：摆长 0.8 米"),
        "amplitude_deg": _tn(6, "deg", "source_fact", "题目给定：摆角 6 度"),
        "g": _tn(9.8, "m/s²", "source_fact", "取重力加速度 9.8 米每二次方秒"),
    }


def _projectile_spec(spec_id="phys-proj", ku_id=KU_ID):
    return {
        "id": spec_id,
        "ku_id": ku_id,
        "title": _bi("平抛出去的小球，落地前水平飞了多远？", "How far does a projected ball fly?"),
        "lead": _bi("先预测射程，再改初速度看变化。", "Predict the range, then change the speed."),
        "caveat": _bi(
            "忽略空气阻力与风；只计重力作用，落地后停住。",
            "Air resistance and wind are ignored; gravity only; the ball rests after landing.",
        ),
        "language": "zh",
        "model_ref": {
            "model": "projectile_motion",
            "parameters": _projectile_params(),
            "expected": [
                {
                    "name": "reset",
                    "actions": [],
                    "expected": {
                        "x": _tn(0, "m", "calculation", "复位态水平位移为 0"),
                        "y": _tn(20, "m", "calculation", "复位态高度为抛出高度"),
                        "phase": "in_flight",
                    },
                },
                {
                    "name": "landing",
                    "actions": [{"kind": "set_time", "t": 3.0}],
                    "expected": {
                        "x": _tn(
                            24.243661069253058, "m", "calculation", "落地时水平位移＝射程"
                        ),
                        "y": _tn(0, "m", "calculation", "落地时高度为 0"),
                        "phase": "landed",
                    },
                },
            ],
        },
    }


def _pendulum_spec(spec_id="phys-pend", ku_id=KU_ID):
    return {
        "id": spec_id,
        "ku_id": ku_id,
        "title": _bi("摆长 0.8 米的单摆，周期是多少？", "What is the period of this pendulum?"),
        "lead": _bi("先预测周期，再改摆长看变化。", "Predict the period, then change the length."),
        "caveat": _bi(
            "忽略空气阻力与摆线质量；小角度近似，大角度修正不计。",
            "Air resistance and mass of the string are ignored; small angles only, "
            "large-angle correction omitted.",
        ),
        "language": "zh",
        "model_ref": {
            "model": "pendulum_small_angle",
            "parameters": _pendulum_params(),
            "expected": [
                {
                    "name": "reset",
                    "actions": [],
                    "expected": {
                        "angle": _tn(
                            0.10471975511965978, "rad", "calculation", "复位态摆角＝初摆角"
                        ),
                        "period": _tn(
                            1.7951958020513104, "s", "calculation", "周期＝2π√(L/g)"
                        ),
                    },
                },
                {
                    "name": "half_period",
                    "actions": [{"kind": "set_time", "t": 0.8975979010256552}],
                    "expected": {
                        "angle": _tn(
                            -0.10471975511965978,
                            "rad",
                            "calculation",
                            "半周期后摆角反向",
                        ),
                        "period": _tn(
                            1.7951958020513104, "s", "calculation", "周期不变"
                        ),
                    },
                },
            ],
        },
    }


def _bound(model_name, params):
    model = PHYSICS_MODEL_REGISTRY[model_name]
    bound, issues, _clamped = model.bind_parameters(params)
    assert issues == []
    return model, bound


# ── 纯核：模型 ────────────────────────────────────────────────────────────


def test_projectile_derive_values():
    model, bound = _bound("projectile_motion", _projectile_params())
    state = model.initial_state(bound)
    derived = model.derive(state)
    assert derived["x"].value == 0.0
    assert derived["y"].value == 20.0
    assert derived["vx"].value == 12.0
    assert derived["phase"] == "in_flight"
    assert derived["flight_time"].value == pytest.approx(math.sqrt(2 * 20 / 9.8))
    assert derived["range"].value == pytest.approx(12 * math.sqrt(2 * 20 / 9.8))


def test_projectile_step_and_landing_pin():
    model, bound = _bound("projectile_motion", _projectile_params())
    state = model.initial_state(bound)
    state = model.step(state, 1.0)
    derived = model.derive(state)
    assert derived["x"].value == pytest.approx(12.0)
    assert derived["y"].value == pytest.approx(20 - 0.5 * 9.8)
    assert derived["vy"].value == pytest.approx(-9.8)
    landed = model.apply_action(state, {"kind": "set_time", "t": 60.0})
    assert model.derive(landed)["phase"] == "landed"
    assert model.derive(landed)["y"].value == pytest.approx(0.0, abs=1e-9)


def test_projectile_rejects_impossible_states():
    model = PHYSICS_MODEL_REGISTRY["projectile_motion"]
    bad = dict(_projectile_params())
    bad["v0"] = _tn(0, "m/s", "source_fact", "零初速度")
    bound, _issues, _c = model.bind_parameters(bad)
    with pytest.raises(ImpossibleStateError):
        model.initial_state(bound)
    _model, bound = _bound("projectile_motion", _projectile_params())
    state = model.initial_state(bound)
    with pytest.raises(ImpossibleStateError):
        model.apply_action(state, {"kind": "set_time", "t": -1})
    with pytest.raises(ImpossibleStateError):
        model.apply_action(state, {"kind": "teleport"})


def test_pendulum_derive_and_rejects_large_angles():
    model, bound = _bound("pendulum_small_angle", _pendulum_params())
    state = model.initial_state(bound)
    derived = model.derive(state)
    assert derived["angle"].value == pytest.approx(math.radians(6))
    assert derived["period"].value == pytest.approx(2 * math.pi * math.sqrt(0.8 / 9.8))
    assert derived["speed"].value == 0.0
    bad = dict(_pendulum_params())
    bad["amplitude_deg"] = _tn(15, "deg", "source_fact", "超出小角度范围")
    bound2, _issues, _c = model.bind_parameters(bad)
    with pytest.raises(ImpossibleStateError):
        model.initial_state(bound2)


def test_invariant_checks_all_pass_for_reference_models():
    for name, params in (
        ("projectile_motion", _projectile_params()),
        ("pendulum_small_angle", _pendulum_params()),
    ):
        model, bound = _bound(name, params)
        checks = run_invariant_checks(model, bound)
        assert checks, name
        failed = [c for c in checks if not c.passed]
        assert failed == [], [(c.name, c.detail) for c in failed]


def test_invariant_checks_catch_wrong_recomputation():
    class BrokenModel(PhysicsTruthModel):
        name = "stub_broken"
        parameters = ()

        def initial_state(self, config):
            return {"t": 0.0}

        def apply_action(self, state, action):
            return dict(state)

        def derive(self, state):
            return {
                "x": TaggedNumber(
                    1.0, "m", NumberKind.CALCULATION, "stub readout"
                )
            }

        def recompute(self, readout, bound, actions=()):
            return 999.0

    model = BrokenModel()
    checks = run_invariant_checks(model, {})
    assert checks
    assert any(not c.passed for c in checks)
    assert any("x" in c.name for c in checks if not c.passed)


def test_physics_models_registered_into_teaching_figure_registry():
    register_physics_models()
    assert "projectile_motion" in MODEL_REGISTRY
    assert "pendulum_small_angle" in MODEL_REGISTRY


# ── 纯核：模型规格门禁 ────────────────────────────────────────────────────


def test_verify_physics_model_passes():
    result = verify_physics_model(_projectile_spec(), known_ku_ids={KU_ID})
    assert result.passed, [(i.field, i.code, i.message) for i in result.issues]
    assert all(result.gates.values())
    result = verify_physics_model(_pendulum_spec(), known_ku_ids={KU_ID})
    assert result.passed, [(i.field, i.code, i.message) for i in result.issues]


def test_verify_physics_model_rejects_verified_field():
    spec = _projectile_spec()
    spec["verified"] = True
    result = verify_physics_model(spec, known_ku_ids={KU_ID})
    assert not result.passed
    assert result.gates["p1"] is False


def test_verify_physics_model_anchor_fail_closed():
    spec = _projectile_spec()
    result = verify_physics_model(spec, known_ku_ids=None)
    assert not result.passed
    assert result.gates["p2"] is False
    result = verify_physics_model(spec, known_ku_ids={"other-ku"})
    assert not result.passed
    assert result.gates["p2"] is False


def test_verify_physics_model_caveat_must_name_ignored_terms():
    spec = _projectile_spec()
    spec["caveat"] = _bi(
        "忽略空气阻力；只计重力作用。",
        "Air resistance is ignored; gravity only.",
    )
    result = verify_physics_model(spec, known_ku_ids={KU_ID})
    assert not result.passed
    assert result.gates["p4"] is False
    assert any(i.code == "ignored_term_missing" for i in result.issues)


def test_verify_physics_model_rejects_untagged_numbers():
    spec = _projectile_spec()
    spec["stray_number"] = 5
    result = verify_physics_model(spec, known_ku_ids={KU_ID})
    assert not result.passed
    assert result.gates["p6"] is False


def test_verify_physics_model_rejects_unknown_model_and_bad_params():
    spec = _projectile_spec()
    spec["model_ref"]["model"] = "no_such_model"
    result = verify_physics_model(spec, known_ku_ids={KU_ID})
    assert not result.passed
    assert result.gates["p3"] is False
    spec = _pendulum_spec()
    spec["model_ref"]["parameters"]["amplitude_deg"] = _tn(
        15, "deg", "source_fact", "超出小角度范围"
    )
    result = verify_physics_model(spec, known_ku_ids={KU_ID})
    assert not result.passed
    assert result.gates["p3"] is False


def test_verify_physics_model_requires_reset_and_transition():
    spec = _projectile_spec()
    spec["model_ref"]["expected"] = spec["model_ref"]["expected"][:1]
    result = verify_physics_model(spec, known_ku_ids={KU_ID})
    assert not result.passed
    assert result.gates["p3"] is False


# ── 纯核：计算题纪律 ──────────────────────────────────────────────────────


def _numeric_item(item_id="phys-prac-range"):
    return build_practice_item(
        item_id=item_id,
        model_name="projectile_motion",
        parameters=_projectile_params(),
        stem=_bi(
            "小球以 {v0} 的水平初速度从 {height} 高处平抛，射程是多少米？",
            "A ball is projected horizontally at {v0} from {height}. What is the range?",
        ),
        answer_readout="range",
        tolerance=0.01,
        assumptions=_bi(
            "忽略空气阻力与风，只计重力。",
            "Air resistance and wind are ignored; gravity only.",
        ),
        language="zh",
    )


def _choice_item(item_id="phys-prac-range-mcq"):
    keyed = 24.243661069253058
    return build_practice_item(
        item_id=item_id,
        model_name="projectile_motion",
        parameters=_projectile_params(),
        stem=_bi(
            "小球以 {v0} 的水平初速度从 {height} 高处平抛，射程最接近哪一项？",
            "A ball is projected horizontally at {v0} from {height}. Which range is closest?",
        ),
        answer_readout="range",
        tolerance=0.01,
        assumptions=_bi(
            "忽略空气阻力与风，只计重力。",
            "Air resistance and wind are ignored; gravity only.",
        ),
        language="zh",
        kind="choice",
        choices=[
            _tn(20.0, "m", "calculation", "干扰项"),
            _tn(keyed, "m", "calculation", "模型算出的射程"),
            _tn(28.0, "m", "calculation", "干扰项"),
            _tn(30.0, "m", "calculation", "干扰项"),
        ],
        answer_index=1,
    )


def test_build_practice_item_computes_answer():
    item = _numeric_item()
    assert item["answer"]["readout"] == "range"
    assert item["answer"]["value"]["value"] == pytest.approx(24.243661069253058)
    assert item["answer"]["value"]["unit"] == "m"
    result = verify_practice_item(item)
    assert result.passed, [(i.field, i.code, i.message) for i in result.issues]


def test_verify_choice_item_passes():
    result = verify_practice_item(_choice_item())
    assert result.passed, [(i.field, i.code, i.message) for i in result.issues]


def test_build_practice_item_rejects_unknown_readout():
    with pytest.raises(ValueError, match="no numeric readout"):
        build_practice_item(
            item_id="phys-prac-bad",
            model_name="projectile_motion",
            parameters=_projectile_params(),
            stem=_bi("题干", "Stem"),
            answer_readout="nope",
            tolerance=0.01,
            assumptions=_bi("忽略空气阻力与风。", "Air resistance and wind ignored."),
        )


def test_verify_practice_rejects_tampered_answer():
    item = _numeric_item()
    item["answer"]["value"]["value"] = 25.0
    result = verify_practice_item(item)
    assert not result.passed
    assert result.gates["q3"] is False


def test_verify_practice_rejects_wrong_unit():
    item = _numeric_item()
    item["answer"]["value"]["unit"] = "km"
    result = verify_practice_item(item)
    assert not result.passed
    assert result.gates["q2"] is False


def test_verify_practice_rejects_undeclared_placeholder():
    item = _numeric_item()
    item["stem"] = _bi("质量为 {mass} 的小球平抛，射程是多少？", "A {mass} ball is projected. Range?")
    result = verify_practice_item(item)
    assert not result.passed
    assert result.gates["q4"] is False


def test_verify_practice_rejects_missing_ignored_term():
    item = _numeric_item()
    item["assumptions"] = _bi(
        "忽略空气阻力，只计重力。", "Air resistance is ignored; gravity only."
    )
    result = verify_practice_item(item)
    assert not result.passed
    assert result.gates["q5"] is False


def test_verify_practice_rejects_close_distractor():
    item = _choice_item()
    item["choices"][2] = _tn(24.3, "m", "calculation", "离真值太近的干扰项")
    result = verify_practice_item(item)
    assert not result.passed
    assert result.gates["q6"] is False


def test_verify_practice_rejects_keyed_mismatch():
    item = _choice_item()
    item["choices"][1] = _tn(22.0, "m", "calculation", "被调包的 keyed 选项")
    result = verify_practice_item(item)
    assert not result.passed
    assert result.gates["q6"] is False


# ── 迁移（容器内由 alembic API 实测；本测试只在 mneme_test 上跑）────────


@pytest.mark.asyncio
async def test_migration_upgrades_to_single_head():
    """迁移链单头 + 本迁移 upgrade/downgrade 真跑（克隆库，跑完即删）。

    既有状态如实记录：共享 mneme_test 的版本行漂移在他分支 revision，
    全链从空库 upgrade 在既有 word-atlas 迁移处已断——均为本迁移之外
    的既有状态，本次不越界修。克隆 mneme_test 为一次性库，删掉固件
    自建的表后 stamp 到父 revision，再走真实 alembic CLI。
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    import asyncpg
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy.engine.url import make_url

    base_url = os.environ["DATABASE_URL"]
    url = make_url(base_url)
    assert url.database == "mneme_test", "迁移测试只许以 mneme_test 为基"
    scratch = "mneme_test_phys"
    dsn = (
        f"postgresql://{url.username}:{url.password}"
        f"@{url.host}:{url.port}/postgres"
    )
    repo_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(repo_root / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    assert tuple(script.get_heads()) == ("phy1a2b3c4d5e",)
    assert script.get_revision("phy1a2b3c4d5e").down_revision == "wnb1a2b3c4d5e"
    assert script.get_revision("tfg1a2b3c4d5e").down_revision == "f9a1b2c3d4e5"
    assert script.get_revision("all1a2b3c4d5e").down_revision == "tfg1a2b3c4d5e"
    assert script.get_revision("wnb1a2b3c4d5e").down_revision == "all1a2b3c4d5e"

    def _alembic(*args):
        env = dict(os.environ)
        # str(URL) 会把密码打码成 ***：显式不过滤，子进程才拿得到真密码。
        # alembic 必须连一次性克隆库 scratch，而非 mneme_test 本身。
        env["DATABASE_URL"] = url.set(database=scratch).render_as_string(
            hide_password=False
        )
        env["PYTHONPATH"] = str(repo_root)
        proc = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=repo_root, env=env, capture_output=True, text=True, timeout=180,
        )
        assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]

    maint = await asyncpg.connect(dsn)
    try:
        await maint.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = 'mneme_test' AND pid <> pg_backend_pid()"
        )
        await maint.execute(f'DROP DATABASE IF EXISTS "{scratch}"')
        await maint.execute(
            f'CREATE DATABASE "{scratch}" TEMPLATE "mneme_test"'
        )
    finally:
        await maint.close()
    try:
        conn = await asyncpg.connect(dsn.rsplit("/", 1)[0] + f"/{scratch}")
        try:
            await conn.execute("DROP TABLE IF EXISTS physics_models CASCADE")
            await conn.execute("DROP TABLE IF EXISTS physics_practice_items CASCADE")
            await conn.execute("DROP TABLE IF EXISTS teaching_figure_specs CASCADE")
            await conn.execute("DROP TABLE IF EXISTS video_lesson_specs CASCADE")
            await conn.execute("DROP TABLE IF EXISTS dictation_specs CASCADE")
            await conn.execute("DROP TABLE IF EXISTS dictation_attempts CASCADE")
            await conn.execute("DROP TABLE IF EXISTS shadowing_specs CASCADE")
            await conn.execute("DROP TABLE IF EXISTS shadowing_attempts CASCADE")
            await conn.execute("DROP TABLE IF EXISTS graded_audio_specs CASCADE")
            await conn.execute("DROP TABLE IF EXISTS mock_exam_specs CASCADE")
            await conn.execute("DROP TABLE IF EXISTS mock_exam_attempts CASCADE")
            await conn.execute("DROP TABLE IF EXISTS study_tasks CASCADE")
            await conn.execute("DROP TABLE IF EXISTS exam_sheets CASCADE")
            await conn.execute("DROP TABLE IF EXISTS exam_sheet_results CASCADE")
            await conn.execute("DROP TABLE IF EXISTS animated_explanation_specs CASCADE")
            await conn.execute("DELETE FROM alembic_version")
            # stamp 到 tfg 的父 revision：upgrade head 须真跑 tfg/all/wnb/phy
            # 四迁移，downgrade 回 tfg 时 teaching_figure_specs 才在位。
            await conn.execute(
                "INSERT INTO alembic_version VALUES ('f9a1b2c3d4e5')"
            )
        finally:
            await conn.close()
        _alembic("upgrade", "head")
        conn = await asyncpg.connect(dsn.rsplit("/", 1)[0] + f"/{scratch}")
        try:
            version = await conn.fetchval(
                "SELECT version_num FROM alembic_version"
            )
            has_models = await conn.fetchval(
                "SELECT to_regclass('public.physics_models')"
            )
            has_items = await conn.fetchval(
                "SELECT to_regclass('public.physics_practice_items')"
            )
            has_index = await conn.fetchval(
                "SELECT indexname FROM pg_indexes WHERE "
                "indexname = 'ix_physics_practice_items_model_id'"
            )
        finally:
            await conn.close()
        assert version == "phy1a2b3c4d5e"
        assert has_models == "physics_models"
        assert has_items == "physics_practice_items"
        assert has_index == "ix_physics_practice_items_model_id"
        _alembic("downgrade", "tfg1a2b3c4d5e")
        conn = await asyncpg.connect(dsn.rsplit("/", 1)[0] + f"/{scratch}")
        try:
            version = await conn.fetchval(
                "SELECT version_num FROM alembic_version"
            )
            has_models = await conn.fetchval(
                "SELECT to_regclass('public.physics_models')"
            )
            has_items = await conn.fetchval(
                "SELECT to_regclass('public.physics_practice_items')"
            )
            has_figures = await conn.fetchval(
                "SELECT to_regclass('public.teaching_figure_specs')"
            )
        finally:
            await conn.close()
        assert version == "tfg1a2b3c4d5e"
        assert has_models is None
        assert has_items is None
        assert has_figures == "teaching_figure_specs"
    finally:
        maint = await asyncpg.connect(dsn)
        try:
            await maint.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{scratch}'"
            )
            await maint.execute(f'DROP DATABASE IF EXISTS "{scratch}"')
        finally:
            await maint.close()


# ── 路由（库上） ──────────────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
async def _ensure_physics_tables():
    """mneme_test 尚未应用本迁移，固件按迁移同源 DDL 自建表
    （IF NOT EXISTS），仅测试库；生产部署仍以 alembic upgrade head 为准。"""
    import os

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS physics_models ("
                "id VARCHAR(100) NOT NULL, "
                "ku_id VARCHAR(100), "
                "spec JSONB NOT NULL, "
                "verified BOOLEAN NOT NULL DEFAULT false, "
                "author_id UUID NOT NULL REFERENCES users(id), "
                "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                "PRIMARY KEY (id))"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_physics_models_ku_id "
                "ON physics_models (ku_id)"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS physics_practice_items ("
                "id VARCHAR(100) NOT NULL, "
                "model_id VARCHAR(100) NOT NULL, "
                "spec JSONB NOT NULL, "
                "verified BOOLEAN NOT NULL DEFAULT false, "
                "author_id UUID NOT NULL REFERENCES users(id), "
                "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                "PRIMARY KEY (id))"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_physics_practice_items_model_id "
                "ON physics_practice_items (model_id)"
            )
        )
    await engine.dispose()
    yield


@pytest.fixture
async def _seed():
    """种入物理教材 + cluster + KU + 学生用户；teardown 只清自己种的 id。"""
    from obase.db import SessionLocal

    user_id = uuid.uuid4()
    async with SessionLocal() as db:
        if (await db.get(Textbook, TB_ID)) is None:
            db.add(Textbook(id=TB_ID, subject="physics", grade="九年级",
                            edition="2017修订", book_name="测试物理教材"))
            await db.flush()
        if (await db.get(KnowledgeCluster, CLUSTER_ID)) is None:
            db.add(KnowledgeCluster(id=CLUSTER_ID, textbook_id=TB_ID,
                                    name="测试簇", display_order=1))
            await db.flush()
        if (await db.get(KnowledgeUnit, KU_ID)) is None:
            db.add(KnowledgeUnit(id=KU_ID, textbook_id=TB_ID, cluster_id=CLUSTER_ID,
                                 name="测试物理知识点", description="夹具",
                                 difficulty=0.5, exam_frequency="mid",
                                 ku_type="concept", verified=False))
        db.add(User(id=user_id, phone=f"150{str(uuid.uuid4())[:8]}",
                    role=UserRole.student))
        await db.commit()
    yield user_id
    async with SessionLocal() as db:
        await db.execute(delete(PhysicsPracticeItem).where(
            PhysicsPracticeItem.spec["model"].astext == "projectile_motion"))
        await db.execute(delete(PhysicsModel).where(PhysicsModel.ku_id == KU_ID))
        await db.execute(delete(KnowledgeUnit).where(KnowledgeUnit.id == KU_ID))
        await db.execute(delete(KnowledgeCluster).where(
            KnowledgeCluster.id == CLUSTER_ID))
        await db.execute(delete(Textbook).where(Textbook.id == TB_ID))
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()


@pytest.fixture
async def _client():
    from services.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


def _as_admin(monkeypatch, module, admin=True):
    monkeypatch.setattr(f"services.routers.{module}.is_admin", lambda u: admin)


@pytest.mark.asyncio
async def test_create_model_requires_admin(_client, _seed, bypass_auth, monkeypatch):
    _as_admin(monkeypatch, "physics_models", False)
    resp = await _client.post(
        "/v1/physics-models",
        json={"spec": _projectile_spec(), "student_id": str(_seed)},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_model_422_lists_gates(_client, _seed, bypass_auth, monkeypatch):
    _as_admin(monkeypatch, "physics_models", True)
    spec = _projectile_spec()
    spec["caveat"] = _bi("忽略空气阻力。", "Air resistance ignored.")
    resp = await _client.post(
        "/v1/physics-models",
        json={"spec": spec, "student_id": str(_seed)},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["gates"]["p4"] is False


@pytest.mark.asyncio
async def test_model_create_verify_list_flow(_client, _seed, bypass_auth, monkeypatch):
    _as_admin(monkeypatch, "physics_models", True)
    resp = await _client.post(
        "/v1/physics-models",
        json={"spec": _projectile_spec(), "student_id": str(_seed)},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["verified"] is False
    dup = await _client.post(
        "/v1/physics-models",
        json={"spec": _projectile_spec(), "student_id": str(_seed)},
    )
    assert dup.status_code == 409
    _as_admin(monkeypatch, "physics_models", False)
    hidden = await _client.get(
        "/v1/physics-models", params={"student_id": str(_seed)}
    )
    assert hidden.status_code == 200
    assert hidden.json()["total"] == 0
    gone = await _client.get(
        "/v1/physics-models/phys-proj", params={"student_id": str(_seed)}
    )
    assert gone.status_code == 404
    _as_admin(monkeypatch, "physics_models", True)
    verified = await _client.post(
        "/v1/physics-models/phys-proj/verify",
        json={"student_id": str(_seed)},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["verified"] is True
    _as_admin(monkeypatch, "physics_models", False)
    visible = await _client.get(
        "/v1/physics-models", params={"student_id": str(_seed)}
    )
    assert visible.json()["total"] == 1
    assert visible.json()["items"][0]["provenance"]["label"] == "material"


@pytest.mark.asyncio
async def test_model_checks_endpoint_reruns_invariants(
    _client, _seed, bypass_auth, monkeypatch
):
    _as_admin(monkeypatch, "physics_models", True)
    await _client.post(
        "/v1/physics-models",
        json={"spec": _pendulum_spec(), "student_id": str(_seed)},
    )
    await _client.post(
        "/v1/physics-models/phys-pend/verify",
        json={"student_id": str(_seed)},
    )
    _as_admin(monkeypatch, "physics_models", False)
    resp = await _client.post(
        "/v1/physics-models/phys-pend/checks",
        json={"student_id": str(_seed)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["passed"] is True
    assert len(body["checks"]) >= 20
    assert all(c["passed"] for c in body["checks"])


@pytest.mark.asyncio
async def test_practice_create_verify_flow(_client, _seed, bypass_auth, monkeypatch):
    _as_admin(monkeypatch, "physics_practice", True)
    resp = await _client.post(
        "/v1/physics-practice",
        json={"spec": _numeric_item(), "student_id": str(_seed)},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["verified"] is False
    assert resp.json()["model_id"] == "projectile_motion"
    verified = await _client.post(
        "/v1/physics-practice/phys-prac-range/verify",
        json={"student_id": str(_seed)},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["verified"] is True
    _as_admin(monkeypatch, "physics_practice", False)
    visible = await _client.get(
        "/v1/physics-practice", params={"student_id": str(_seed)}
    )
    assert visible.json()["total"] == 1


@pytest.mark.asyncio
async def test_practice_create_rejects_tampered_answer(
    _client, _seed, bypass_auth, monkeypatch
):
    _as_admin(monkeypatch, "physics_practice", True)
    item = _numeric_item()
    item["answer"]["value"]["value"] = 25.0
    resp = await _client.post(
        "/v1/physics-practice",
        json={"spec": item, "student_id": str(_seed)},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["gates"]["q3"] is False


@pytest.mark.asyncio
async def test_mcp_get_physics_model_verified_only(
    _client, _seed, bypass_auth, monkeypatch
):
    _as_admin(monkeypatch, "physics_models", True)
    await _client.post(
        "/v1/physics-models",
        json={"spec": _projectile_spec(), "student_id": str(_seed)},
    )
    body = {"student_id": str(_seed), "model_id": "phys-proj"}
    before = await _client.post("/mcp/GetPhysicsModel", json=body)
    assert before.status_code == 200
    assert before.json()["error"] == "physics model not found"
    await _client.post(
        "/v1/physics-models/phys-proj/verify",
        json={"student_id": str(_seed)},
    )
    after = await _client.post("/mcp/GetPhysicsModel", json=body)
    assert after.status_code == 200
    assert after.json()["model_id"] == "phys-proj"
    assert after.json()["spec"]["model_ref"]["model"] == "projectile_motion"
