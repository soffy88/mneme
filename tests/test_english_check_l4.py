"""英语确定性批改 Layer 4：``POST /v1/english/check`` 路由 + 既有判分路径的英语等价补判开关。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def _client(authenticated: bool = True) -> TestClient:
    from obase.db import get_db

    from services.auth_deps import get_current_user
    from services.routers import english_check

    app = FastAPI()
    app.include_router(english_check.router)
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: object()
    else:
        app.dependency_overrides[get_db] = lambda: None
    return TestClient(app)


def test_english_check_requires_auth() -> None:
    resp = _client(authenticated=False).post("/v1/english/check", json={"text": "hi"})
    assert resp.status_code == 401


def test_english_check_contraction_has_vs_is() -> None:
    c = _client()
    ok = c.post(
        "/v1/english/check",
        json={"text": "He's finished", "accepted": ["He has finished"]},
    ).json()
    assert (
        ok["ok"] is True
        and ok["answer_ok"] is True
        and "he has finished" in ok["normalized_forms"]
    )
    bad = c.post(
        "/v1/english/check", json={"text": "He's a car", "accepted": ["He has a car"]}
    ).json()
    assert bad["ok"] is False and bad["answer_ok"] is False


def test_english_check_pronoun_and_pattern() -> None:
    c = _client()
    p = c.post(
        "/v1/english/check",
        json={"text": "He is a teacher.", "context": "Tell me about your sister."},
    ).json()
    assert [(e["wrong"], e["right"]) for e in p["pronoun_errors"]] == [("He", "She")]
    assert p["corrected_text"] == "She is a teacher." and p["ok"] is False
    q = c.post(
        "/v1/english/check",
        json={"text": "We put the meeting off", "pattern": "put ___ off"},
    ).json()
    assert q["pattern_used"] is True and q["ok"] is True


def test_english_check_dictation_edits() -> None:
    body = (
        _client()
        .post(
            "/v1/english/check",
            json={
                "text": "I dont like apple",
                "accepted": ["I don't like apples."],
                "type": "dictation",
            },
        )
        .json()
    )
    assert body["dictation_edits"] == 1 and body["answer_ok"] is True
    assert body["kernel_version"].startswith("english-answer-check/")


def test_english_check_validation_422() -> None:
    c = _client()
    assert (
        c.post("/v1/english/check", json={"text": "x", "type": "essay"}).status_code
        == 422
    )
    assert (
        c.post("/v1/english/check", json={"text": "x", "pattern": "___"}).status_code
        == 422
    )
    assert (
        c.post("/v1/english/check", json={"text": "x", "accepted": [""]}).status_code
        == 422
    )


def test_english_router_registered() -> None:
    from services.routers import register_domain_routers

    app = FastAPI()
    register_domain_routers(app)
    assert "/v1/english/check" in app.openapi()["paths"]


def test_english_equivalent_answer_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.english_check_service import english_equivalent_answer

    monkeypatch.delenv("MNEME_ENGLISH_ANSWER_FORMS", raising=False)
    assert (
        english_equivalent_answer("He's finished", "He has finished") is True
    )  # 默认开
    assert english_equivalent_answer("He's a car", "He has a car") is False
    assert english_equivalent_answer("can't", "can not") is True
    monkeypatch.setenv("MNEME_ENGLISH_ANSWER_FORMS", "0")
    assert english_equivalent_answer("He's finished", "He has finished") is False


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("x=2", "x=2"),  # 数学留给 sympy
        ("sin x cos x", "Sin x cos x"),
        ("ab", "AB"),  # 单词、无撇号：不做英语补判
        ("1/2", "0.5"),
        ("等差数列", "等差数列"),
        ("A", "a"),
    ],
)
def test_english_equivalent_answer_skips_non_english(
    answer: str, expected: str
) -> None:
    from services.english_check_service import english_equivalent_answer

    assert english_equivalent_answer(answer, expected) is False


def test_submit_answer_uses_english_forms_behind_flag() -> None:
    """接线只在既有判分为错时补判，且受开关控制；不改门控 / 不越过 guard。"""
    src = (ROOT / "services" / "mcp_router.py").read_text(encoding="utf-8")
    assert "english_equivalent_answer" in src
    i = src.index("english_equivalent_answer(answer, expected)")
    assert src.rfind("if not is_correct", 0, i) > src.rfind(
        'elif qtype in ("choice", "short")', 0, i
    )
    assert src.index('enforce("deterministic", None, origin="core")') > i


def test_notice_and_license_kept() -> None:
    d = ROOT / "services" / "assets" / "english_grading"
    assert "MIT License" in (d / "LICENSE").read_text(encoding="utf-8")
    assert "recepyagmur" in (d / "LICENSE").read_text(encoding="utf-8")
    notice = (d / "NOTICE").read_text(encoding="utf-8")
    assert "recepyagmur/EnglishPractice" in notice and "app/content" in notice
