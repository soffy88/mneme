"""Animator —— 确定性步骤动画时间线（POST /v1/animate）。

守三件事：①时间线确定性（同输入逐字节相同）且与内核答案自洽；②输入校验（未知
kind / 多余字段 / 坏参数 → 422）；③无代码执行（服务端无 eval/exec，播放器只按白名单
画图、不用 innerHTML/eval，时间线白名单校验拒绝任何未知图元/属性）。
"""

from __future__ import annotations

import ast
import asyncio
import copy
import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.animate_service import (
    SWEEP_ANGLES,
    AnimateError,
    _conic_coeffs,
    build_timeline,
    chord_points,
    chord_target_value,
    pretty_formula,
    validate_spec,
)

ROOT = Path(__file__).resolve().parents[1]
PLAYER = ROOT / "services" / "assets" / "vendor" / "mneme-animator-1" / "player.js"

SOLID = {
    "body": "regular_quad_pyramid",
    "dims": {"base_edge": 2, "height": 1},
    "givens": [{"name": "E", "kind": "midpoint", "of": ["P", "C"]}],
    "query": {"type": "line_plane_angle", "line": ["B", "E"], "plane": ["P", "A", "C"]},
}
CONIC_DOT = {
    "conic": {"kind": "ellipse", "a": 2, "b": "sqrt(3)"},
    "query": {"through": [1, 0], "target": "dot_product", "vertex": [-1, 0]},
}
CONIC_LEN = {
    "conic": {"kind": "ellipse", "a": 2, "b": "sqrt(3)"},
    "query": {"through": [1, 0], "target": "chord_length"},
}
CONIC_FIXED = {
    "conic": {"kind": "parabola", "p": 2},
    "query": {"through": [1, 0], "target": "fixed_value_dot", "vertex": [0, 0]},
}
CONIC_HYP = {
    "conic": {"kind": "hyperbola", "a": 1, "b": "sqrt(3)"},
    "query": {"through": [2, 0], "target": "dot_product", "vertex": [0, 0]},
}
CHEM = {"reactants": ["MnO4^-", "Fe^2+", "H^+"], "products": ["Mn^2+", "Fe^3+", "H2O"]}
FUNC = {"expression": "x**2 - 2*x - 3", "x_min": -3, "x_max": 5}

CASES = [
    ("solid_geometry", SOLID),
    ("conic_chord", CONIC_DOT),
    ("conic_chord", CONIC_LEN),
    ("conic_chord", CONIC_FIXED),
    ("conic_chord", CONIC_HYP),
    ("equation_balance", CHEM),
    ("function_graph", FUNC),
]


def _build(kind: str, params: dict) -> dict:
    return asyncio.run(build_timeline(kind, copy.deepcopy(params)))


@pytest.mark.parametrize("kind,params", CASES)
def test_spec_is_deterministic_and_valid(kind: str, params: dict) -> None:
    a = _build(kind, params)
    b = _build(kind, params)
    assert json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(
        b, sort_keys=True, ensure_ascii=False
    )
    assert a["fingerprint"] == b["fingerprint"] and len(a["fingerprint"]) == 24
    assert a["spec_version"] == "mneme.anim/1" and a["kind"] == kind
    validate_spec(a)
    assert len(a["frames"]) >= 3
    # 纯数据：可无损 JSON 往返
    assert json.loads(json.dumps(a)) == a


def test_different_inputs_give_different_fingerprints() -> None:
    assert (
        _build("conic_chord", CONIC_DOT)["fingerprint"]
        != _build("conic_chord", CONIC_LEN)["fingerprint"]
    )


def test_solid_answer_comes_from_kernel() -> None:
    spec = _build("solid_geometry", SOLID)
    assert spec["answer"]["latex"] == r"\frac{2 \sqrt{22}}{11}"
    assert spec["canvas"]["mode"] == "3d"
    assert all("camera" in f for f in spec["frames"][:1])


@pytest.mark.parametrize(
    "params,lo,hi",
    [(CONIC_DOT, -3.0, 1.75), (CONIC_LEN, 3.0, 4.0), (CONIC_FIXED, -3.0, -3.0)],
)
def test_conic_sweep_values_stay_inside_exact_answer(
    params: dict, lo: float, hi: float
) -> None:
    spec = _build("conic_chord", params)
    sweep = [f for f in spec["frames"] if f.get("readout")]
    assert len(sweep) >= 10
    conic = {
        "kind": params["conic"]["kind"],
        **{k: float(eval_num(v)) for k, v in params["conic"].items() if k != "kind"},
    }
    coeffs = _conic_coeffs(conic)
    through = [float(v) for v in params["query"]["through"]]
    vertex = params["query"].get("vertex")
    for theta in SWEEP_ANGLES:
        hit = chord_points(coeffs, through, theta)
        if hit is None:
            continue
        v = chord_target_value(params["query"]["target"], hit[0], hit[1], vertex)
        assert lo - 1e-6 <= v <= hi + 1e-6
    for f in sweep:
        m = re.search(r"≈ (-?\d+\.\d+)", f["readout"])
        assert m and lo - 1e-3 <= float(m.group(1)) <= hi + 1e-3


def eval_num(v: object) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    assert v == "sqrt(3)"
    return 3**0.5


def test_chem_final_frame_is_balanced() -> None:
    spec = _build("equation_balance", CHEM)
    last = spec["frames"][-1]["set"]
    rows = sorted({k.split("_")[1] for k in last if k.startswith("barL_")})
    assert rows
    for j in rows:
        assert last[f"barL_{j}"]["value"] == last[f"barR_{j}"]["value"]
    first = spec["frames"][0]
    assert first["highlight"], "unbalanced rows are highlighted at the start"
    assert last["coef_1"]["text"] == "5" and last["coef_2"]["text"] == "8"
    assert (
        pretty_formula("MnO4^-") == "MnO₄⁻" and pretty_formula("Cu(NO3)2") == "Cu(NO₃)₂"
    )


def test_function_graph_uses_visualize_kernel_zeros() -> None:
    spec = _build("function_graph", FUNC)
    zeros = sorted(s["at"][0] for s in spec["shapes"] if s["id"].startswith("zero_"))
    assert zeros == pytest.approx([-1.0, 3.0], abs=0.05)


@pytest.mark.parametrize(
    "kind,params",
    [
        (
            "function_graph",
            {"expression": "__import__('os').system('touch /tmp/pwned')"},
        ),
        ("function_graph", {"expression": "x" * 200}),
        ("function_graph", {"expression": "x", "x_min": 3, "x_max": 1}),
        ("function_graph", {"expression": "x", "evil": 1}),
        ("conic_chord", {"conic": {"kind": "circle"}}),
        (
            "solid_geometry",
            {
                "body": "cube",
                "dims": {"edge": "__import__('os')"},
                "query": {"type": "segment_length", "points": ["A", "B"]},
            },
        ),
        ("equation_balance", {"reactants": ["H2; import os"], "products": ["H2O"]}),
    ],
)
def test_bad_params_raise_animate_error(kind: str, params: dict) -> None:
    with pytest.raises(AnimateError):
        _build(kind, params)
    assert not Path("/tmp/pwned").exists()


def _app(authenticated: bool) -> TestClient:
    from services.auth_deps import get_current_user
    from services.routers import animate

    app = FastAPI()
    app.include_router(animate.router)
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: object()
    return TestClient(app)


def test_router_requires_auth() -> None:
    from obase.db import get_db

    client = _app(authenticated=False)
    client.app.dependency_overrides[get_db] = lambda: None  # type: ignore[attr-defined]
    assert (
        client.post(
            "/v1/animate", json={"kind": "function_graph", "params": FUNC}
        ).status_code
        == 401
    )


def test_router_validation_and_success() -> None:
    client = _app(authenticated=True)
    ok = client.post("/v1/animate", json={"kind": "equation_balance", "params": CHEM})
    assert ok.status_code == 200 and ok.json()["kind"] == "equation_balance"
    assert (
        client.post("/v1/animate", json={"kind": "manim", "params": {}}).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/animate", json={"kind": "function_graph", "params": FUNC, "code": "x"}
        ).status_code
        == 422
    )
    bad = client.post(
        "/v1/animate",
        json={"kind": "function_graph", "params": {"expression": "__import__('os')"}},
    )
    assert bad.status_code == 422


# ── 无代码执行保证 ────────────────────────────────────────────────────────────

_FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__", "execfile"}
_FORBIDDEN_MODULES = {
    "subprocess",
    "importlib",
    "runpy",
    "ctypes",
    "multiprocessing",
    "pty",
}


@pytest.mark.parametrize(
    "rel", ["services/animate_service.py", "services/routers/animate.py"]
)
def test_server_side_never_executes_code(rel: str) -> None:
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            # 裸名调用 eval/exec/compile/__import__（re.compile 之类的属性调用不算）
            if isinstance(fn, ast.Name):
                assert fn.id not in _FORBIDDEN_CALLS, f"{rel}: {fn.id}()"
            if isinstance(fn, ast.Attribute):
                assert fn.attr not in {"system", "popen", "spawn", "exec_module"}, (
                    f"{rel}: .{fn.attr}()"
                )
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            for m in mods:
                assert m.split(".")[0] not in _FORBIDDEN_MODULES, f"{rel}: import {m}"
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert "services.providers" not in src and "get_text_caller" not in src, rel


def test_player_is_data_driven_only() -> None:
    js = PLAYER.read_text(encoding="utf-8")
    for bad in (
        "eval(",
        "new Function",
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "import(",
        "fetch(",
        "XMLHttpRequest",
        "postMessage",
        "localStorage",
        "cookie",
    ):
        assert bad not in js, bad
    assert not re.search(r"setTimeout\(\s*['\"]", js)
    urls = set(re.findall(r"https?://[^\s\"')]+", js))
    assert urls == {"http://www.w3.org/2000/svg"}, urls


def test_player_served_from_edu_assets() -> None:
    from services.routers.edu_assets import resolve_asset

    assert resolve_asset("mneme-animator-1/player.js") is not None
    assert resolve_asset("mneme-animator-1/player.css") is not None
    assert resolve_asset("mneme-animator-1/../../animate_service.py") is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s["shapes"].append({"id": "x1", "type": "script", "src": "evil.js"}),
        lambda s: s["shapes"][0].update({"onclick": "alert(1)"}),
        lambda s: s["shapes"][0].update({"color": "javascript:alert(1)"}),
        lambda s: s["frames"][0]["set"].update(
            {s["shapes"][0]["id"]: {"innerHTML": "<img onerror=x>"}}
        ),
        lambda s: s["frames"][0].update({"code": "while(1){}"}),
        lambda s: s.update({"exec": "x"}),
        lambda s: s["frames"][0]["show"].append("nope"),
        lambda s: s.update({"spec_version": "manim"}),
    ],
)
def test_validate_spec_rejects_tampering(mutate) -> None:  # type: ignore[no-untyped-def]
    spec = _build("equation_balance", CHEM)
    mutate(spec)
    with pytest.raises(AnimateError):
        validate_spec(spec)
