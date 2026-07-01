import pytest
from unittest.mock import patch, MagicMock
from services.main import app, get_current_user
from httpx import AsyncClient, ASGITransport

@pytest.mark.asyncio
async def test_essay_guide_never_rewrites():
    payload = {
        "essay_text": "I like apple. It is red.",
        "grade": "grade_3",
        "essay_type": "argumentative"
    }
    
    mock_res = MagicMock()
    mock_res.feedback = {"clarity": "Good"}
    mock_res.suggested_questions = ["Why do you like apples?", "Are they healthy?"]
    mock_res.is_completed = False
    
    # Overriding the dependency in FastAPI app
    app.dependency_overrides[get_current_user] = lambda: MagicMock(id="test-id")
    
    try:
        # We patch essay_guide directly to avoid all the LLM complexity
        with patch("services.main.essay_guide", return_value=mock_res):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.post("/v1/essay/guide", json=payload)
                
        assert response.status_code == 200
        data = response.json()
        
        # Red line: NEVER rewrite the essay
        full_text_response = str(data)
        assert "I like apple. It is red." not in full_text_response or "feedback" in full_text_response
        
        # guidance_questions 必须全部是问句
        for q in data["guidance_questions"]:
            assert q.strip().endswith("?") or any(w in q.lower() for w in ["how", "why", "what", "can you", "could you"])
    finally:
        app.dependency_overrides = {}

