"""相关实验外链：目录完整性 + 确定性匹配 + 路由。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.related_labs import BY_SLUG, LABS, catalog, match_related_labs
from services.routers import related_labs as router_mod


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router_mod.router)
    return TestClient(app)


def test_catalog_has_25_unique_https_labs() -> None:
    assert len(LABS) == 25
    assert len(BY_SLUG) == 25
    for d in catalog():
        assert str(d["url"]).startswith("https://wedulab.com/labs/")
        assert d["subject_label"]
        assert "keywords" not in d


def test_kc_prefix_beats_keywords() -> None:
    out = match_related_labs("", kc_id="GDMATH-CONIC-04")
    assert [d["slug"] for d in out] == ["conic"]
    out = match_related_labs("向量法求空间角与距离", kc_id="GDMATH-SVEC-04")
    assert out[0]["slug"] == "geo"


def test_keyword_matching_across_subjects() -> None:
    assert match_related_labs("椭圆的定义、标准方程与几何性质")[0]["slug"] == "conic"
    assert match_related_labs("勾股定理（初中）")[0]["slug"] == "pythagoras"
    assert match_related_labs("楞次定律判断感应电流方向")[0]["slug"] == "fields"
    assert match_related_labs("质壁分离实验")[0]["slug"] == "micro"
    assert (
        match_related_labs("KMnO4 与浓盐酸的离子方程式配平")[0]["slug"] == "mechanism"
    )
    assert match_related_labs("正午太阳高度的变化")[0]["slug"] == "earth"


def test_no_hit_returns_empty_and_subject_filters() -> None:
    assert match_related_labs("集合的基本运算（交并补）") == []
    assert match_related_labs("") == []
    assert match_related_labs("光的折射", subject="math") == []
    assert len(match_related_labs("电场 磁场 电路 折射 干涉 振动", limit=2)) == 2


def test_routes() -> None:
    c = _client()
    r = c.get("/v1/related-labs")
    assert r.status_code == 200
    body = r.json()
    assert body["source"]["home"] == "https://wedulab.com/"
    assert len(body["labs"]) == 25
    assert "max-age" in r.headers["cache-control"]
    r = c.get("/v1/related-labs/match", params={"q": "双曲线离心率", "subject": "math"})
    assert r.status_code == 200
    assert r.json()["labs"][0]["slug"] == "conic"
    assert c.get("/v1/related-labs/match", params={"subject": "art"}).status_code == 422
