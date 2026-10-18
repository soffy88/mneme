import pytest
import os
import json
from unittest.mock import AsyncMock, MagicMock
from services.cn_math_importer import import_cn_math_taxonomy

@pytest.mark.asyncio
async def test_cn_math_importer():
    data_dir = os.getenv("CN_MATH_DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cn_math_taxonomy"))
    # Verify files exist in data dir
    assert os.path.exists(os.path.join(data_dir, "topics.json"))
    assert os.path.exists(os.path.join(data_dir, "dependencies.json"))
    assert os.path.exists(os.path.join(data_dir, "questions.json"))

    # Mock async session
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = mock_result

    res = await import_cn_math_taxonomy(mock_db)
    assert res["status"] == "success"
    assert res["total"] == 333
    assert res["imported"] == 333
    assert mock_db.commit.called
