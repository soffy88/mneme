import pytest
from uuid import uuid4
from services.instant_solve_service import handle_instant_solve
from unittest.mock import patch, MagicMock

@pytest.mark.asyncio
async def test_instant_solve_never_returns_raw_answer():
    student_id = uuid4()
    image_b64 = "fake_b64_image_data"
    
    mock_result = {
        "status": "success",
        "decision_trail": [{"event": "session_started", "session_id": "test_session_id"}],
        "findings": {
            "status": "ready_for_guidance",
            "recognized_text": "x^2 - 4 = 0",
            "metacog": {
                "question": "你需要哪方面的帮助？",
                "options": ["看不懂", "不会算"]
            },
            # socratic_state normally contains SocraticStateV2, but we simulate standard response
            "socratic_state": MagicMock()
        }
    }
    
    with patch("services.instant_solve_service.instant_solve", return_value=mock_result), \
         patch("services.instant_solve_service.get_pg_pool", return_value=MagicMock()):
        
        result = await handle_instant_solve(student_id, image_b64)
        
        # Red line asserts
        assert "answer" not in result, "MUST NOT return raw numerical answer directly"
        assert "steps" not in result, "MUST NOT return raw solution steps"
        
        # Verify required fields
        assert "session_id" in result
        assert "first_question" in result
        assert result["first_question"] == "你需要哪方面的帮助？"

