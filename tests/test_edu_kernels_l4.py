"""教学内核 Layer 4：解析几何 / 化学配平路由、自托管前端依赖、模板无境外 CDN。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ASSETS = Path(__file__).resolve().parents[1] / "services" / "assets"

CONIC = {
    "conic": {"kind": "ellipse", "a": 2, "b": "sqrt(3)"},
    "query": {"through": [1, 0], "target": "dot_product", "vertex": [-1, 0]},
}
CHEM = {"reactants": ["KMnO4", "HCl"], "products": ["KCl", "MnCl2", "Cl2", "H2O"]}


def _app(*routers: object, authenticated: bool = True) -> TestClient:
    from obase.db import get_db

    from services.auth_deps import get_current_user

    app = FastAPI()
    for r in routers:
        app.include_router(r.router)  # type: ignore[attr-defined]
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: object()
    else:
        app.dependency_overrides[get_db] = lambda: None
    return TestClient(app)


def test_conic_and_chem_require_auth() -> None:
    from services.routers import chemistry, conic_geometry

    client = _app(conic_geometry, chemistry, authenticated=False)
    assert client.post("/v1/geometry/conic/solve", json=CONIC).status_code == 401
    assert client.post("/v1/geometry/conic/lesson", json=CONIC).status_code == 401
    assert client.post("/v1/chemistry/equation/balance", json=CHEM).status_code == 401


def test_conic_solve_and_board() -> None:
    from services.routers import conic_geometry

    client = _app(conic_geometry)
    resp = client.post("/v1/geometry/conic/solve", json=CONIC)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer_kind"] == "range"
    assert body["answer_lo"] == pytest.approx(-3.0)
    assert body["answer_hi"] == pytest.approx(1.75)
    assert body["answer_latex"] == r"\left[-3,\ \frac{7}{4}\right]"
    assert body["fingerprint"] and body["steps"]

    page = client.post("/v1/geometry/conic/lesson", json=CONIC)
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "__LESSON_DATA__" not in page.text
    assert "/v1/edu-assets/katex-0.16.8/katex.min.js" in page.text

    bad = client.post(
        "/v1/geometry/conic/solve",
        json={"conic": {"kind": "ellipse", "a": "__import__('os')", "b": 1}, "query": CONIC["query"]},
    )
    assert bad.status_code == 422


def test_chem_balance() -> None:
    from services.routers import chemistry

    client = _app(chemistry)
    resp = client.post("/v1/chemistry/equation/balance", json=CHEM)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["coefficients"] == [2, 16, 2, 2, 5, 8]
    assert body["equation_text"].startswith("2KMnO₄ + 16HCl")
    multi = client.post(
        "/v1/chemistry/equation/balance",
        json={"reactants": ["H2", "O2"], "products": ["H2O2", "H2O"]},
    )
    assert multi.status_code == 422
    assert "多解" in multi.json()["detail"]
    bad = client.post("/v1/chemistry/equation/balance", json={"reactants": ["Xx"], "products": ["H2"]})
    assert bad.status_code == 422


def test_edu_assets_served_with_cors_and_cache() -> None:
    from services.routers import edu_assets

    client = _app(edu_assets, authenticated=False)
    for path, ctype in (
        ("three-0.160.0/three.module.js", "text/javascript"),
        ("three-0.160.0/addons/controls/OrbitControls.js", "text/javascript"),
        ("mathjax-3.2.2/tex-svg.js", "text/javascript"),
        ("katex-0.16.8/katex.min.css", "text/css"),
        ("katex-0.16.8/fonts/KaTeX_Main-Regular.woff2", "font/woff2"),
        ("tailwindcss-play-3.4.17.js", "text/javascript"),
    ):
        resp = client.get(f"/v1/edu-assets/{path}")
        assert resp.status_code == 200, path
        assert resp.headers["content-type"].startswith(ctype)
        assert resp.headers["access-control-allow-origin"] == "*"
        assert "immutable" in resp.headers["cache-control"]


@pytest.mark.parametrize(
    "path",
    [
        "../solid_geometry/lesson.html",
        "..%2F..%2Frouters%2Fedu_assets.py",
        "three-0.160.0/LICENSE",
        "three-0.160.0/missing.js",
        "",
    ],
)
def test_edu_assets_rejects_traversal_and_non_whitelisted(path: str) -> None:
    from services.routers import edu_assets

    assert edu_assets.resolve_asset(path.replace("%2F", "/")) is None
    client = _app(edu_assets, authenticated=False)
    assert client.get(f"/v1/edu-assets/{path}").status_code in (404, 405)


@pytest.mark.parametrize("template", ["solid_geometry/lesson.html", "conic_geometry/board.html"])
def test_lesson_templates_have_no_external_cdn(template: str) -> None:
    text = (ASSETS / template).read_text(encoding="utf-8")
    assert not re.search(r"(src|href)=\"https?://", text)
    assert "cdn.jsdelivr" not in text and "unpkg.com" not in text and "cdnjs" not in text
    assert "/v1/edu-assets/" in text
