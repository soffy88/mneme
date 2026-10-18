import pytest
import os
import json
from unittest.mock import AsyncMock, MagicMock
from services.cn_math_importer import import_cn_math_taxonomy

@pytest.mark.asyncio
async def test_cn_math_importer_branches():
    mock_db = AsyncMock()
    # Test when topic already exists
    mock_existing = MagicMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_existing
    mock_db.execute.return_value = mock_result

    res = await import_cn_math_taxonomy(mock_db)
    assert res["status"] == "success"
    assert res["updated"] == 333
    assert res["imported"] == 0
