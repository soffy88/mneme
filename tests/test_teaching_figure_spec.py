"""教学图规格合同 + 真值模型 + 验证门 + 路由（纯函数 + 库上测试）。

方法来源 teachable-figures 只学方法、干净重写；本文件不含对方代码。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from services.models import (
    KnowledgeCluster,
    KnowledgeUnit,
    TeachingFigureSpec,
    Textbook,
    User,
    UserRole,
)
from services.teaching_figure import (
    MODEL_REGISTRY,
    ImpossibleStateError,
    NumberKind,
    TaggedNumber,
    TruthModel,
    expected_distribution,
    find_untagged_numbers,
    seeded_sample,
    spec_provenance,
    verify_figure,
)

KU_ID = "tf-test-ku"
TB_ID = "tf-test-textbook"
CLUSTER_ID = "tf-test-cluster"


def _tn(value, unit, kind, note):
    return {"value": value, "unit": unit, "kind": kind, "note": note}


def _bi(zh, en):
    return {"zh": zh, "en": en}


def _ratio_spec(spec_id="fig-tf-ratio", ku_id=KU_ID):
    return {
        "id": spec_id,
        "ku_id": ku_id,
        "title": _bi("主动轮变大，从动轮怎么转？", "What happens when the driver grows?"),
        "lead": _bi("先预测，再转一圈输入，看输出计数。", "Predict first, then turn the input once."),
        "predict": {
            "zh": ["从动轮转得更快", "从动轮转得更慢", "两轮转速永远相同"],
            "en": ["The driven gear turns faster", "The driven gear turns more slowly",
                   "Both gears always turn at the same speed"],
            "answer_index": 1,
        },
        "misconception": _bi("多一个齿轮输出就更慢", "Every extra gear makes the output slower"),
        "config": {},
        "insight": _bi("从动轮齿数越多，转一圈输出所需输入越多。",
                       "More driven teeth require more input rotation per output turn."),
        "caveat": _bi("理想外啮合齿轮，忽略间隙与摩擦；类比只讲齿数比，不涉及材料强度。",
                      "Ideal external gears; backlash and friction omitted; "
                      "the analogy covers ratio only."),
        "frame": _bi("当从动轮有 ___ 齿时，输入转 1 圈，输出转 ___ 圈。",
                     "When the driven gear has ___ teeth, one input turn produces ___ output turns."),
        "language": "zh",
        "renderer_hint": "svg-2d",
        "model_ref": {
            "model": "proportional_output",
            "parameters": {
                "driver_teeth": _tn(12, "teeth", "source_fact", "题目给定：主动轮 12 齿"),
                "driven_teeth": _tn(24, "teeth", "source_fact", "题目给定：从动轮 24 齿"),
                "reverses_direction": True,
            },
            "expected": [
                {"name": "reset", "actions": [],
                 "expected": {
                     "output_turns": _tn(0, "turn", "calculation", "复位态输出为 0"),
                     "ratio": _tn(0.5, "1", "calculation", "比值＝12/24"),
                 }},
                {"name": "one-turn", "actions": [{"kind": "turn", "turns": 1}],
                 "expected": {
                     "output_turns": _tn(-0.5, "turn", "calculation", "输入 1 圈反向输出半圈"),
                     "ratio": _tn(0.5, "1", "calculation", "比值不变"),
                 }},
            ],
        },
        "design_note": {
            "meaningful_try": _bi("转满 1 圈输入并读出输出计数", "Complete one input turn and read the counter"),
            "explanation_points": [
                _bi("输出圈数由齿数比决定", "Output turns follow the tooth ratio"),
                _bi("外啮合改变方向，不改变速比大小", "Meshing reverses direction, not magnitude"),
            ],
            "transfer_case": _bi("从动轮改为 36 齿，预测输出", "Predict the output with 36 driven teeth"),
        },
    }


def _quadratic_spec(spec_id="fig-tf-quadratic", ku_id=KU_ID):
    spec = _ratio_spec(spec_id=spec_id, ku_id=ku_id)
    spec["title"] = _bi("边长翻倍，面积变几倍？", "When the side doubles, what happens to the area?")
    spec["predict"] = {
        "zh": ["面积变 2 倍", "面积变 4 倍", "面积不变"],
        "en": ["The area doubles", "The area quadruples", "The area stays the same"],
        "answer_index": 1,
    }
    spec["misconception"] = _bi("边长翻倍面积也翻倍", "Doubling the side doubles the area")
    spec["model_ref"] = {
        "model": "quadratic_growth",
        "parameters": {
            "coefficient": _tn(1, "1", "calculation", "正方形面积＝边长²，系数 1"),
            "size_limit": _tn(10, "cm", "illustrative", "为教学所选的边长上限 10 厘米"),
        },
        "expected": [
            {"name": "reset", "actions": [],
             "expected": {
                 "size": _tn(0, "cm", "calculation", "复位态边长为 0"),
                 "area": _tn(0, "cm²", "calculation", "复位态面积为 0"),
             }},
            {"name": "double", "actions": [{"kind": "set_size", "size": 4}],
             "expected": {
                 "size": _tn(4, "cm", "calculation", "边长 4 厘米"),
                 "area": _tn(16, "cm²", "calculation", "面积＝1×4²"),
             }},
        ],
    }
    return spec


def _codes(result):
    return [i.code for i in result.issues]


# ── 纯函数：正例 ──────────────────────────────────────────────────────────


def test_valid_ratio_spec_passes_all_gates():
    result = verify_figure(_ratio_spec(), known_ku_ids={KU_ID})
    assert result.passed, [vars(i) for i in result.issues]
    assert all(result.gates.values())


def test_valid_quadratic_spec_passes_all_gates():
    result = verify_figure(_quadratic_spec(), known_ku_ids={KU_ID})
    assert result.passed, [vars(i) for i in result.issues]
    assert all(result.gates.values())


# ── 纯函数：schema 与锚点 ─────────────────────────────────────────────────


def test_bad_id_rejected():
    spec = _ratio_spec(spec_id="Bad ID!")
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert not result.passed
    assert "bad_id" in _codes(result)


def test_missing_required_field():
    spec = _ratio_spec()
    del spec["insight"]
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert not result.passed
    assert "missing_field" in _codes(result)


def test_verified_key_inside_spec_rejected():
    spec = _ratio_spec()
    spec["verified"] = True
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert not result.passed
    assert "verified_field_forbidden" in _codes(result)


def test_duplicate_id_rejected():
    result = verify_figure(
        _ratio_spec(), known_ku_ids={KU_ID}, existing_ids={"fig-tf-ratio"}
    )
    assert not result.passed
    assert "duplicate_id" in _codes(result)


def test_ku_not_found():
    result = verify_figure(_ratio_spec(), known_ku_ids={"other-ku"})
    assert not result.passed
    assert "ku_not_found" in _codes(result)


def test_ku_unchecked_fails_closed():
    result = verify_figure(_ratio_spec(), known_ku_ids=None)
    assert not result.passed
    assert "ku_existence_unchecked" in _codes(result)


# ── 纯函数：预测与误解 ────────────────────────────────────────────────────


def test_predict_option_counts():
    spec = _ratio_spec()
    spec["predict"]["zh"] = ["只有一项"]
    spec["predict"]["en"] = ["Only one"]
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "bad_option_count" in _codes(result)

    spec = _ratio_spec()
    spec["predict"]["zh"].append("第四项")
    spec["predict"]["zh"].append("第五项")
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "bad_option_count" in _codes(result)

    spec = _ratio_spec()
    spec["predict"]["answer_index"] = 5
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "answer_index_out_of_range" in _codes(result)


def test_misconception_equal_to_best_answer_rejected():
    spec = _ratio_spec()
    spec["misconception"] = _bi("从动轮转得更慢", "The driven gear turns more slowly")
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert not result.passed
    assert "misconception_equals_answer" in _codes(result)


def test_caveat_too_short():
    spec = _ratio_spec()
    spec["caveat"] = _bi("理想情况", "Ideal")
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "caveat_too_short" in _codes(result)


# ── 纯函数：数字三标签 ────────────────────────────────────────────────────


def test_untagged_number_in_config_rejected():
    spec = _ratio_spec()
    spec["config"] = {"teeth": 12}
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "untagged_number" in _codes(result)


def test_malformed_tagged_number_rejected():
    spec = _ratio_spec()
    spec["config"] = {"teeth": {"value": 12, "unit": "teeth", "kind": "guess", "note": "x"}}
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "untagged_number" in _codes(result)


def test_calculation_without_note_rejected():
    spec = _ratio_spec()
    spec["config"] = {"k": {"value": 2, "unit": "1", "kind": "calculation", "note": ""}}
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "untagged_number" in _codes(result)


def test_find_untagged_numbers_skips_structural_keys():
    assert find_untagged_numbers({"answer_index": 1, "seed": 7, "tolerance": 0.1}) == []
    assert find_untagged_numbers({"actions": [{"turns": 5}]}) == []
    assert find_untagged_numbers({"x": 1}) == ["$.x: untagged number 1"]


# ── 纯函数：语言与渲染提示 ────────────────────────────────────────────────


def test_missing_en_copy_rejected():
    spec = _ratio_spec()
    spec["title"] = {"zh": "标题"}
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "missing_language" in _codes(result)
    assert result.gates["g10"] is False


def test_bad_language_rejected():
    spec = _ratio_spec()
    spec["language"] = "fr"
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "bad_language" in _codes(result)


def test_bad_renderer_hint_rejected():
    spec = _ratio_spec()
    spec["renderer_hint"] = "hologram"
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "bad_renderer_hint" in _codes(result)
    assert result.gates["g9"] is False


# ── 纯函数：模型绑定与期望 ────────────────────────────────────────────────


def test_unknown_model_rejected():
    spec = _ratio_spec()
    spec["model_ref"]["model"] = "no-such-model"
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "unknown_model" in _codes(result)


def test_missing_and_wrong_kind_parameter():
    spec = _ratio_spec()
    del spec["model_ref"]["parameters"]["driven_teeth"]
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "bind_failed" in _codes(result)

    spec = _ratio_spec()
    spec["model_ref"]["parameters"]["driver_teeth"] = _tn(
        12, "teeth", "illustrative", "档位错"
    )
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "bind_failed" in _codes(result)


def test_expectation_mismatch_rejected():
    spec = _ratio_spec()
    spec["model_ref"]["expected"][1]["expected"]["output_turns"] = _tn(
        0.5, "turn", "calculation", "符号错了"
    )
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "expectation_mismatch" in _codes(result)


def test_expectations_require_reset_and_transition():
    spec = _ratio_spec()
    spec["model_ref"]["expected"] = spec["model_ref"]["expected"][:1]
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "expected_too_few" in _codes(result)
    assert "no_transition_case" in _codes(result)

    spec = _ratio_spec()
    spec["model_ref"]["expected"] = [spec["model_ref"]["expected"][1]]
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "no_reset_case" in _codes(result)


# ── 纯函数：模型行为（clamp / 拒绝 / 复位 / 视图分离）────────────────────


def test_ratio_model_clamps_turns():
    model = MODEL_REGISTRY["proportional_output"]
    bound, issues, _ = model.bind_parameters(
        {
            "driver_teeth": _tn(12, "teeth", "source_fact", "题"),
            "driven_teeth": _tn(24, "teeth", "source_fact", "题"),
            "reverses_direction": True,
        }
    )
    assert issues == []
    state = model.initial_state(bound)
    state = model.apply_action(state, {"kind": "turn", "turns": 1000})
    assert state["input_turns"] == 100.0
    assert model.derive(state)["output_turns"].value == -50.0


def test_quadratic_model_rejects_negative_size():
    model = MODEL_REGISTRY["quadratic_growth"]
    bound, _, _ = model.bind_parameters(
        {
            "coefficient": _tn(1, "1", "calculation", "正方形"),
            "size_limit": _tn(10, "cm", "illustrative", "示意上限"),
        }
    )
    state = model.initial_state(bound)
    with pytest.raises(ImpossibleStateError):
        model.apply_action(state, {"kind": "set_size", "size": -1})


def test_zero_coefficient_rejected_by_gate():
    spec = _quadratic_spec()
    spec["model_ref"]["parameters"]["coefficient"] = _tn(
        0, "1", "calculation", "系数为零不可能"
    )
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert not result.passed
    assert "model_rejected" in _codes(result)


def test_view_state_overlap_rejected():
    spec = _ratio_spec()
    spec["view"] = {"input_turns": 3}
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "view_state_leak" in _codes(result)


class _DriftingModel(TruthModel):
    name = "drifting"
    parameters = ()

    def __init__(self):
        self.calls = 0

    def initial_state(self, config):
        return {}

    def apply_action(self, state, action):
        return dict(state)

    def derive(self, state):
        self.calls += 1
        return {
            "x": TaggedNumber(
                float(self.calls), "1", NumberKind.CALCULATION, "每次调用都变"
            )
        }


def test_nondeterministic_model_fails_reset_gate(monkeypatch):
    monkeypatch.setitem(MODEL_REGISTRY, "drifting", _DriftingModel())
    spec = _ratio_spec()
    spec["model_ref"] = {
        "model": "drifting",
        "parameters": {},
        "expected": [
            {"name": "reset", "actions": [],
             "expected": {"x": _tn(1, "1", "calculation", "第一次派生")}},
            {"name": "t", "actions": [{"kind": "noop"}],
             "expected": {"x": _tn(2, "1", "calculation", "第二次派生")}},
        ],
    }
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "reset_not_restored" in _codes(result)


class _MutatingModel(TruthModel):
    name = "mutating"
    parameters = ()

    def initial_state(self, config):
        return {"x": 0.0}

    def apply_action(self, state, action):
        state["x"] = 1.0
        return state

    def derive(self, state):
        return {
            "x": TaggedNumber(state["x"], "1", NumberKind.CALCULATION, "状态值")
        }


def test_mutating_apply_action_detected(monkeypatch):
    monkeypatch.setitem(MODEL_REGISTRY, "mutating", _MutatingModel())
    spec = _ratio_spec()
    spec["model_ref"] = {
        "model": "mutating",
        "parameters": {},
        "expected": [
            {"name": "reset", "actions": [],
             "expected": {"x": _tn(0, "1", "calculation", "初态")}},
            {"name": "t", "actions": [{"kind": "go"}],
             "expected": {"x": _tn(1, "1", "calculation", "动作后")}},
        ],
    }
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "state_mutated" in _codes(result)


# ── 纯函数：随机性口径与来源标注 ─────────────────────────────────────────


def test_seeded_sample_reproducible_and_separated():
    weights = [1.0, 3.0]
    assert expected_distribution(weights) == [0.25, 0.75]
    first = seeded_sample(7, weights, 50)
    second = seeded_sample(7, weights, 50)
    assert first == second
    assert len(first) == 50
    assert set(first) <= {0, 1}
    with pytest.raises(ImpossibleStateError):
        expected_distribution([1.0, -1.0])
    with pytest.raises(ImpossibleStateError):
        expected_distribution([0.0, 0.0])


class _CoinModel(TruthModel):
    name = "coin"
    parameters = ()
    stochastic = True

    def initial_state(self, config):
        return {"flips": 0}

    def apply_action(self, state, action):
        return dict(state)

    def derive(self, state):
        return {
            "flips": TaggedNumber(
                float(state["flips"]), "1", NumberKind.CALCULATION, "翻转次数"
            )
        }

    def sample(self, seed, n):
        flips = seeded_sample(seed, [0.5, 0.5], n)
        return {
            "expected": {"heads": 0.5, "tails": 0.5},
            "sampled": {"heads": flips.count(0), "tails": flips.count(1)},
        }


def test_stochastic_model_gate(monkeypatch):
    monkeypatch.setitem(MODEL_REGISTRY, "coin", _CoinModel())
    spec = _ratio_spec()
    spec["model_ref"] = {
        "model": "coin",
        "parameters": {},
        "expected": [
            {"name": "reset", "actions": [],
             "expected": {"flips": _tn(0, "1", "calculation", "初态")}},
            {"name": "t", "actions": [{"kind": "noop"}],
             "expected": {"flips": _tn(0, "1", "calculation", "动作不改计数")}},
        ],
    }
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert result.passed, [vars(i) for i in result.issues]


class _StochasticNoSampleModel(_CoinModel):
    name = "coin-nosample"

    def sample(self, seed, n):
        raise NotImplementedError


def test_stochastic_without_sample_fails(monkeypatch):
    monkeypatch.setitem(MODEL_REGISTRY, "coin-nosample", _StochasticNoSampleModel())
    spec = _ratio_spec()
    spec["model_ref"] = {
        "model": "coin-nosample",
        "parameters": {},
        "expected": [
            {"name": "reset", "actions": [],
             "expected": {"flips": _tn(0, "1", "calculation", "初态")}},
            {"name": "t", "actions": [{"kind": "noop"}],
             "expected": {"flips": _tn(0, "1", "calculation", "动作不改计数")}},
        ],
    }
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "stochastic_no_sample" in _codes(result)


def test_spec_provenance_labels():
    spec = _quadratic_spec()
    prov = spec_provenance(spec, textbook_id=TB_ID)
    assert prov["label"] == "material"
    assert {"kind": "ku", "ref": KU_ID, "page": None} in prov["sources"]
    assert {"kind": "textbook", "ref": TB_ID, "page": None} in prov["sources"]
    assert "model_ref.parameters.size_limit" in prov["illustrative"]
    assert prov["number_kinds"]["model_ref.parameters.coefficient"] == "calculation"


def test_design_note_rules():
    spec = _ratio_spec()
    del spec["design_note"]
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert result.passed  # 缺失只记 note，不判分
    assert any("design_note" in n for n in result.notes)

    spec = _ratio_spec()
    spec["design_note"]["explanation_points"] = [spec["design_note"]["explanation_points"][0]]
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "bad_points" in _codes(result)


def test_figure_refs_key_shape():
    spec = _ratio_spec()
    spec["figure_refs"] = [{"object_key": "figures/doc1/p3_0.png"}]
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert result.passed

    spec = _ratio_spec()
    spec["figure_refs"] = [{"object_key": "https://example.com/x.png"}]
    result = verify_figure(spec, known_ku_ids={KU_ID})
    assert "bad_object_key" in _codes(result)


# ── 迁移（容器内由 alembic API 实测；本测试只在 mneme_test 上跑）────────


@pytest.mark.asyncio
async def test_migration_upgrades_to_single_head():
    """迁移链单头 + 本迁移 upgrade/downgrade 真跑（克隆库，跑完即删）。

    两点如实记录：① 共享 mneme_test 的版本行现指 prq1a2b3c4d5（其它
    分支迁移留下的版本行，本分支链内无此 revision），且全链从空库
    upgrade 在既有 word-atlas 迁移处已断（建 FSRS 卡表时 vocab_units
    不存在）——均为本迁移之外的既有状态，本次不越界修。② 故本测试克隆
    mneme_test（同一台测试 postgres）为一次性库，删掉固件自建的表后
    stamp 到父 revision，再走真实 alembic CLI upgrade head（只跑本迁移）
    与 downgrade 回父 revision；绝不碰生产库。
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    import asyncpg
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy.engine.url import make_url

    # conftest 已用 db_guard 把 DATABASE_URL 钉到 mneme_test，直接读它。
    base_url = os.environ["DATABASE_URL"]
    url = make_url(base_url)
    assert url.database == "mneme_test", "迁移测试只许以 mneme_test 为基"
    scratch = "mneme_test_tf"
    dsn = (
        f"postgresql://{url.username}:{url.password}"
        f"@{url.host}:{url.port}/postgres"
    )
    repo_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(repo_root / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    # 链已延长：单头现为 wrong-notebook 迁移（down_revision 已改为 all-grafts head）。
    assert tuple(script.get_heads()) == ("wnb1a2b3c4d5e",)
    assert script.get_revision("tfg1a2b3c4d5e").down_revision == "f9a1b2c3d4e5"
    assert script.get_revision("all1a2b3c4d5e").down_revision == "tfg1a2b3c4d5e"
    assert script.get_revision("wnb1a2b3c4d5e").down_revision == "all1a2b3c4d5e"

    def _alembic(*args):
        env = dict(os.environ)
        # str(URL) 会把密码打码成 ***：显式不过滤，子进程才拿得到真密码。
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
            # 克隆带上了固件自建的表：先删掉，upgrade 才能真建它。
            # 本分支新增的 9 张表同样由固件自建，一并删掉。
            await conn.execute(
                "DROP TABLE IF EXISTS teaching_figure_specs CASCADE"
            )
            for _table in (
                "video_lesson_specs",
                "dictation_specs",
                "dictation_attempts",
                "shadowing_specs",
                "shadowing_attempts",
                "graded_audio_specs",
                "mock_exam_specs",
                "mock_exam_attempts",
                "study_tasks",
            ):
                await conn.execute(f"DROP TABLE IF EXISTS {_table} CASCADE")
            # 克隆同样带上了 wrong-notebook 固件自建的表：先删掉，
            # upgrade head（全链）才能真建它们。
            await conn.execute("DROP TABLE IF EXISTS exam_sheet_results CASCADE")
            await conn.execute("DROP TABLE IF EXISTS exam_sheets CASCADE")
            await conn.execute(
                "DROP TABLE IF EXISTS animated_explanation_specs CASCADE"
            )
            # alembic stamp 会先解析当前版本行（prq1a2b3c4d5，链内无此
            # revision，直接拒）；只在一次性克隆库内直写版本行到父 revision。
            await conn.execute("DELETE FROM alembic_version")
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
            has_table = await conn.fetchval(
                "SELECT to_regclass('public.teaching_figure_specs')"
            )
            has_index = await conn.fetchval(
                "SELECT indexname FROM pg_indexes WHERE "
                "indexname = 'ix_teaching_figure_specs_ku_id'"
            )
        finally:
            await conn.close()
        assert version == "wnb1a2b3c4d5e"
        assert has_table == "teaching_figure_specs"
        assert has_index == "ix_teaching_figure_specs_ku_id"
        _alembic("downgrade", "f9a1b2c3d4e5")
        conn = await asyncpg.connect(dsn.rsplit("/", 1)[0] + f"/{scratch}")
        try:
            version = await conn.fetchval(
                "SELECT version_num FROM alembic_version"
            )
            has_table = await conn.fetchval(
                "SELECT to_regclass('public.teaching_figure_specs')"
            )
        finally:
            await conn.close()
        assert version == "f9a1b2c3d4e5"
        assert has_table is None
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


@pytest.fixture(scope="session", autouse=True)
async def _ensure_specs_table():
    """mneme_test 尚未应用本迁移（版本行漂移在他分支 revision），固件按
    迁移同源 DDL 自建表（IF NOT EXISTS），仅测试库；生产部署仍以
    alembic upgrade head 为准，见 test_migration_upgrades_to_single_head。"""
    import os

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    # conftest 已用 db_guard 把 DATABASE_URL 钉到 mneme_test，直接读它。
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS teaching_figure_specs ("
                "id VARCHAR(100) NOT NULL, "
                "ku_id VARCHAR(100) NOT NULL, "
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
                "CREATE INDEX IF NOT EXISTS ix_teaching_figure_specs_ku_id "
                "ON teaching_figure_specs (ku_id)"
            )
        )
    await engine.dispose()
    yield


# ── 路由（库上） ──────────────────────────────────────────────────────────


@pytest.fixture
async def _seed():
    """种入教材 + cluster + KU + 学生用户；teardown 只清自己种的 id。"""
    from obase.db import SessionLocal

    user_id = uuid.uuid4()
    async with SessionLocal() as db:
        # FK 只是 DB 层（ORM 无 relationship），flush 顺序不保证：逐级 flush。
        if (await db.get(Textbook, TB_ID)) is None:
            db.add(Textbook(id=TB_ID, subject="math", grade="初二",
                            edition="2017修订", book_name="测试教材"))
            await db.flush()
        if (await db.get(KnowledgeCluster, CLUSTER_ID)) is None:
            db.add(KnowledgeCluster(id=CLUSTER_ID, textbook_id=TB_ID,
                                    name="测试簇", display_order=1))
            await db.flush()
        if (await db.get(KnowledgeUnit, KU_ID)) is None:
            db.add(KnowledgeUnit(id=KU_ID, textbook_id=TB_ID, cluster_id=CLUSTER_ID,
                                 name="测试知识点", description="夹具",
                                 difficulty=0.5, exam_frequency="mid",
                                 ku_type="concept", verified=False))
        db.add(User(id=user_id, phone=f"150{str(uuid.uuid4())[:8]}",
                    role=UserRole.student))
        await db.commit()
    yield user_id
    async with SessionLocal() as db:
        await db.execute(delete(TeachingFigureSpec).where(
            TeachingFigureSpec.ku_id == KU_ID))
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


def _as_admin(monkeypatch, admin=True):
    monkeypatch.setattr(
        "services.routers.teaching_figures.is_admin", lambda u: admin
    )


@pytest.mark.asyncio
async def test_create_requires_admin(_client, _seed, bypass_auth, monkeypatch):
    _as_admin(monkeypatch, False)
    resp = await _client.post(
        "/v1/teaching-figures",
        json={"spec": _ratio_spec(), "student_id": str(_seed)},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_valid_stores_unverified_false(
    _client, _seed, bypass_auth, monkeypatch
):
    _as_admin(monkeypatch, True)
    resp = await _client.post(
        "/v1/teaching-figures",
        json={"spec": _ratio_spec(), "student_id": str(_seed)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == "fig-tf-ratio"
    assert body["verified"] is False
    assert body["provenance"]["label"] == "material"
    # 学生看不到未验证的规格（切回非 admin 身份再查）
    _as_admin(monkeypatch, False)
    resp = await _client.get(
        "/v1/teaching-figures/fig-tf-ratio", params={"student_id": str(_seed)}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_invalid_spec_422_and_no_row(
    _client, _seed, bypass_auth, monkeypatch
):
    _as_admin(monkeypatch, True)
    spec = _ratio_spec()
    spec["ku_id"] = "no-such-ku"
    resp = await _client.post(
        "/v1/teaching-figures",
        json={"spec": spec, "student_id": str(_seed)},
    )
    assert resp.status_code == 422
    assert "ku_not_found" in str(resp.json())

    spec = _ratio_spec()
    spec["verified"] = True
    resp = await _client.post(
        "/v1/teaching-figures",
        json={"spec": spec, "student_id": str(_seed)},
    )
    assert resp.status_code == 422
    assert "verified_field_forbidden" in str(resp.json())


@pytest.mark.asyncio
async def test_create_duplicate_409(_client, _seed, bypass_auth, monkeypatch):
    _as_admin(monkeypatch, True)
    payload = {"spec": _ratio_spec(), "student_id": str(_seed)}
    assert (await _client.post("/v1/teaching-figures", json=payload)).status_code == 200
    resp = await _client.post("/v1/teaching-figures", json=payload)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_verify_flow(_client, _seed, bypass_auth, monkeypatch):
    _as_admin(monkeypatch, True)
    payload = {"spec": _ratio_spec(), "student_id": str(_seed)}
    assert (await _client.post("/v1/teaching-figures", json=payload)).status_code == 200
    resp = await _client.post(
        "/v1/teaching-figures/fig-tf-ratio/verify",
        params={"student_id": str(_seed)},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["verified"] is True
    # 学生列表可见已验证规格（切回非 admin 身份再查）
    _as_admin(monkeypatch, False)
    resp = await _client.get(
        "/v1/teaching-figures", params={"student_id": str(_seed)}
    )
    assert resp.status_code == 200
    assert [i["id"] for i in resp.json()["items"]] == ["fig-tf-ratio"]


@pytest.mark.asyncio
async def test_verify_requires_admin_and_rejects(
    _client, _seed, bypass_auth, monkeypatch
):
    _as_admin(monkeypatch, True)
    payload = {"spec": _ratio_spec(), "student_id": str(_seed)}
    assert (await _client.post("/v1/teaching-figures", json=payload)).status_code == 200
    _as_admin(monkeypatch, False)
    resp = await _client.post(
        "/v1/teaching-figures/fig-tf-ratio/verify",
        params={"student_id": str(_seed)},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_verify_failing_spec_stays_unverified(
    _client, _seed, bypass_auth, monkeypatch
):
    from obase.db import SessionLocal

    _as_admin(monkeypatch, True)
    async with SessionLocal() as db:
        db.add(TeachingFigureSpec(
            id="fig-tf-broken", ku_id="no-such-ku",
            spec=_ratio_spec(spec_id="fig-tf-broken", ku_id="no-such-ku"),
            verified=False, author_id=_seed,
        ))
        await db.commit()
    resp = await _client.post(
        "/v1/teaching-figures/fig-tf-broken/verify",
        params={"student_id": str(_seed)},
    )
    assert resp.status_code == 422
    assert "ku_not_found" in str(resp.json())
    async with SessionLocal() as db:
        row = await db.get(TeachingFigureSpec, "fig-tf-broken")
        assert row is not None and row.verified is False
        await db.delete(row)
        await db.commit()


@pytest.mark.asyncio
async def test_list_hides_unverified_from_students(
    _client, _seed, bypass_auth, monkeypatch
):
    _as_admin(monkeypatch, True)
    payload = {"spec": _ratio_spec(), "student_id": str(_seed)}
    assert (await _client.post("/v1/teaching-figures", json=payload)).status_code == 200
    # 切回学生身份：未验证的一律不可见，include_unverified 也不生效
    _as_admin(monkeypatch, False)
    resp = await _client.get(
        "/v1/teaching-figures", params={"student_id": str(_seed)}
    )
    assert resp.json()["items"] == []
    resp = await _client.get(
        "/v1/teaching-figures",
        params={"student_id": str(_seed), "include_unverified": "true"},
    )
    assert resp.json()["items"] == []
    # admin 带 flag 可见
    _as_admin(monkeypatch, True)
    resp = await _client.get(
        "/v1/teaching-figures",
        params={"student_id": str(_seed), "include_unverified": "true"},
    )
    assert [i["id"] for i in resp.json()["items"]] == ["fig-tf-ratio"]
