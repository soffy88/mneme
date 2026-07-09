import pytest
from unittest.mock import patch, MagicMock
from services.main import app, get_current_user
from httpx import AsyncClient, ASGITransport
import uuid


@pytest.mark.asyncio
async def test_review_due_returns_variants():
    student_id = uuid.uuid4()

    mock_variant = MagicMock()
    mock_variant.question_text = "Variant Question?"
    mock_variant.correct_answer = "Variant Answer"

    # Overriding the dependency in FastAPI app
    app.dependency_overrides[get_current_user] = lambda: MagicMock(
        id=student_id, role="student"
    )

    try:
        # Patch get_due_variants to avoid DB
        with patch(
            "services.main.get_due_variants",
            return_value=[
                {
                    "ku_id": "TEST-KC",
                    "variant_question": "Variant Question?",
                    "variant_answer": "Variant Answer",
                    "due_since": "2026-06-18T00:00:00Z",
                    "fsrs_interval": 1.0,
                }
            ],
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                response = await ac.get(f"/v1/review/due/{student_id}")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["variant_question"] == "Variant Question?"
        assert "variant_answer" in data[0]
    finally:
        app.dependency_overrides = {}
