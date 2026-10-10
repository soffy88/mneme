"""立体几何 3O 链路：oprim 精确计算 / oskill 解题 / omodul 复核 / Layer 4 路由。

期望值取自 edulab geometry_kernel 自检（2√22/11、√3/3、1/3、8/3 …）与手算。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import sympy as sp
from fastapi import FastAPI
from fastapi.testclient import TestClient

from omodul.solid_geometry_lesson import (
    SolidGeometryLessonConfig,
    SolidGeometryLessonInput,
    solid_geometry_lesson,
)
from oprim.solid_geometry import SolidGeometrySpec, numeric_query_value, parse_dimension
from oskill.solid_geometry_skill import solve_solid_geometry

CASES = [
    (
        {
            "body": "regular_quad_pyramid",
            "dims": {"base_edge": 2, "height": 1},
            "givens": [{"name": "E", "kind": "midpoint", "of": ["P", "C"]}],
            "query": {
                "type": "line_plane_angle",
                "line": ["B", "E"],
                "plane": ["P", "A", "C"],
            },
        },
        2 * sp.sqrt(22) / 11,
    ),
    (
        {
            "body": "cube",
            "dims": {"edge": 1},
            "query": {
                "type": "line_plane_angle",
                "line": ["A1", "C"],
                "plane": ["A", "B", "D"],
            },
        },
        sp.sqrt(3) / 3,
    ),
    (
        {
            "body": "cube",
            "dims": {"edge": 1},
            "query": {
                "type": "line_line_angle",
                "line": ["A1", "C"],
                "line2": ["A", "B"],
            },
        },
        sp.sqrt(3) / 3,
    ),
    (
        {
            "body": "cube",
            "dims": {"edge": 1},
            "query": {
                "type": "point_plane_distance",
                "point": ["A1"],
                "plane": ["A", "B", "D"],
            },
        },
        sp.Integer(1),
    ),
    (
        {
            "body": "cube",
            "dims": {"edge": 2},
            "query": {
                "type": "point_plane_distance",
                "point": ["A1"],
                "plane": ["A", "B1", "D1"],
            },
        },
        2 * sp.sqrt(3) / 3,
    ),
    (
        {
            "body": "regular_tetrahedron",
            "dims": {"edge": "2sqrt(2)"},
            "query": {
                "type": "dihedral_angle",
                "edge": ["A", "B"],
                "faces": ["C", "D"],
            },
        },
        sp.Rational(1, 3),
    ),
    (
        {
            "body": "cube",
            "dims": {"edge": 1},
            "query": {
                "type": "dihedral_angle",
                "edge": ["B", "D"],
                "faces": ["A", "C1"],
            },
        },
        -sp.sqrt(3) / 3,
    ),
    (
        {
            "body": "regular_tetrahedron",
            "dims": {"edge": "2*sqrt(2)"},
            "query": {"type": "tetra_volume", "points": ["A", "B", "C", "D"]},
        },
        sp.Rational(8, 3),
    ),
    (
        {
            "body": "cuboid",
            "dims": {"length": 3, "width": 4, "height": 5},
            "givens": [
                {"name": "M", "kind": "on_segment", "of": ["A1", "C1"], "ratio": "1/4"}
            ],
            "query": {"type": "segment_length", "points": ["M", "C"]},
        },
        sp.Rational(25, 4),
    ),
]


@pytest.mark.parametrize(("raw", "expected"), CASES)
def test_skill_exact_answers(raw: dict, expected: sp.Expr) -> None:
    sol = solve_solid_geometry(SolidGeometrySpec(**raw))
    assert sol.answer_latex == sp.latex(sp.radsimp(sp.simplify(expected)))
    assert sol.answer_value == pytest.approx(float(expected), abs=1e-12)
    assert sol.steps[0].title == "建立空间直角坐标系"
    assert sol.lesson_data["lesson"]["answerValue"] == f"${sol.answer_latex}$"
    # 每步 highlight 引用的元素都必须存在于模型里
    elements = sol.lesson_data["model"]["elements"]
    for step in sol.lesson_data["steps"]:
        assert set(step["highlight"]) <= set(elements)


@pytest.mark.parametrize(("raw", "expected"), CASES)
def test_omodul_cross_check_and_pillars(
    raw: dict, expected: sp.Expr, tmp_path: Path
) -> None:
    result = solid_geometry_lesson(
        SolidGeometryLessonConfig(),
        SolidGeometryLessonInput(spec=SolidGeometrySpec(**raw)),
        tmp_path,
    )
    assert result["status"] == "completed", result["error"]
    assert result["cost_usd"] == 0
    assert len(result["fingerprint"]) == 24
    assert result["decision_trail"]["steps"] >= 3
    trail = json.loads(next(tmp_path.glob("decision_trail_*.json")).read_text())
    assert [s["event"] for s in trail] == ["spec_received", "solved", "cross_checked"]
    assert json.loads(Path(result["report_path"]).read_text())["lesson"]["title"]


def test_on_step_callback_receives_each_step(tmp_path: Path) -> None:
    seen: list[str] = []
    solid_geometry_lesson(
        SolidGeometryLessonConfig(write_lesson_json=False),
        SolidGeometryLessonInput(spec=SolidGeometrySpec(**CASES[0][0])),
        tmp_path,
        on_step=lambda e: seen.append(e["event"]),
    )
    assert seen == ["spec_received", "solved", "cross_checked"]


def test_fingerprint_is_deterministic(tmp_path: Path) -> None:
    raw = CASES[0][0]
    a = solid_geometry_lesson(
        SolidGeometryLessonConfig(write_lesson_json=False),
        SolidGeometryLessonInput(spec=SolidGeometrySpec(**raw)),
        tmp_path,
    )
    b = solid_geometry_lesson(
        SolidGeometryLessonConfig(write_lesson_json=False),
        SolidGeometryLessonInput(spec=SolidGeometrySpec(**raw)),
        tmp_path,
    )
    assert a["fingerprint"] == b["fingerprint"]


@pytest.mark.parametrize(
    "value",
    [
        "__import__('os').system('id')",
        "2**1000",
        "x",
        "sqrt(2)+1",
        "1/0",
        "-1",
        "0",
        1e9,
        True,
        "1e3",
    ],
)
def test_parse_dimension_rejects_untrusted_or_out_of_range(value: object) -> None:
    with pytest.raises(ValueError):
        parse_dimension(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (2, sp.Integer(2)),
        (1.5, sp.Rational(3, 2)),
        ("3/2", sp.Rational(3, 2)),
        ("2sqrt(2)", 2 * sp.sqrt(2)),
        ("√3", sp.sqrt(3)),
        ("3*sqrt(2)/2", 3 * sp.sqrt(2) / 2),
    ],
)
def test_parse_dimension_accepts_literals(value: object, expected: sp.Expr) -> None:
    assert sp.simplify(parse_dimension(value) - expected) == 0  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "raw",
    [
        {
            "body": "cube",
            "dims": {"edge": 1},
            "query": {
                "type": "line_plane_angle",
                "line": ["A", "B"],
                "plane": ["A", "B", "A"],
            },
        },
        {
            "body": "cube",
            "dims": {"edge": 1},
            "query": {"type": "segment_length", "points": ["A", "Z"]},
        },
        {
            "body": "cube",
            "dims": {"edge": 1, "height": 2},
            "query": {"type": "segment_length", "points": ["A", "B"]},
        },
        {
            "body": "cube",
            "dims": {"edge": 1},
            "givens": [{"name": "A", "kind": "midpoint", "of": ["B", "C"]}],
            "query": {"type": "segment_length", "points": ["A", "B"]},
        },
        {
            "body": "cube",
            "dims": {"edge": 1},
            "query": {
                "type": "line_plane_angle",
                "line": ["A"],
                "plane": ["A", "B", "C"],
            },
        },
    ],
)
def test_invalid_specs_fail_cleanly(raw: dict, tmp_path: Path) -> None:
    result = solid_geometry_lesson(
        SolidGeometryLessonConfig(),
        SolidGeometryLessonInput(spec=SolidGeometrySpec(**raw)),
        tmp_path,
    )
    assert result["status"] == "failed"
    assert result["error"]["type"] == "ValueError"


def test_point_names_are_whitelisted() -> None:
    with pytest.raises(ValueError):
        SolidGeometrySpec(
            body="cube",
            dims={"edge": 1},
            query={"type": "segment_length", "points": ["A", "<img>"]},
        )


def test_numeric_check_is_independent_of_sympy() -> None:
    # 正方体 A1 到平面 AB1D1，手算 2√3/3（棱长 2）
    got = numeric_query_value(
        "point_plane_distance", coords=[[0, 0, 2], [0, 0, 0], [2, 0, 2], [0, 2, 2]]
    )
    assert got == pytest.approx(2 * 3**0.5 / 3)


def test_lesson_html_escapes_script_breakout() -> None:
    from services.solid_geometry_service import render_lesson_html

    html = render_lesson_html(
        {
            "lesson": {"title": "</script><script>alert(1)</script>"},
            "steps": [],
            "model": {},
        }
    )
    assert "</script><script>alert(1)" not in html
    assert "\\u003c/script\\u003e" in html


def _app(authenticated: bool) -> TestClient:
    from services.auth_deps import get_current_user
    from services.routers import geometry

    app = FastAPI()
    app.include_router(geometry.router)
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: object()
    return TestClient(app)


def test_router_requires_auth() -> None:
    from obase.db import get_db

    client = _app(authenticated=False)
    client.app.dependency_overrides[get_db] = lambda: None  # type: ignore[attr-defined]
    resp = client.post("/v1/geometry/solid/solve", json=CASES[0][0])
    assert resp.status_code == 401


def test_router_solve_and_lesson() -> None:
    client = _app(authenticated=True)
    resp = client.post("/v1/geometry/solid/solve", json=CASES[0][0])
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer_latex"] == r"\frac{2 \sqrt{22}}{11}"
    assert body["fingerprint"]

    page = client.post("/v1/geometry/solid/lesson", json=CASES[0][0])
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "__LESSON_DATA__" not in page.text
    assert "正四棱锥P-ABCD" in page.text

    bad = client.post(
        "/v1/geometry/solid/solve",
        json={
            "body": "cube",
            "dims": {"edge": 1},
            "query": {
                "type": "line_plane_angle",
                "line": ["A", "B"],
                "plane": ["A", "B", "A"],
            },
        },
    )
    assert bad.status_code == 422
