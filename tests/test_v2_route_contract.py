from services.main import app


def test_blueprint_v2_routes_are_registered():
    paths = set(app.openapi()["paths"])
    expected = {
        "/v2/memory/timeline",
        "/v2/memory/claims",
        "/v2/memory/evidence/{claim_id}",
        "/v2/learner-state/{student_id}",
        "/v2/learner-state/{student_id}/ku/{ku_id}",
        "/v2/growth/{student_id}/period/{term}",
        "/v2/events",
        "/v2/replay",
        "/v2/export",
        "/v2/policy/next-action/{student_id}",
        "/v2/evaluation/os",
        "/v2/evaluation/models",
        "/v2/evaluation/models/{model_id}/status",
    }
    assert expected <= paths


def test_privacy_safe_operational_routes_are_registered():
    paths = set(app.openapi()["paths"])
    assert "/health/metrics" in paths
    assert "/health/grading" in paths
