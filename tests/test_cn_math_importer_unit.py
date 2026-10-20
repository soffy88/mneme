from unittest.mock import AsyncMock, MagicMock

from services.cn_math_importer import import_cn_math_taxonomy


async def test_cn_math_importer_branches():
    """已存在的行走 update；库里残留的旧 cnm_ext_* 行只标 deprecated，不删。"""
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_existing = MagicMock()
    mock_existing.rich_content = {"cnm_id": "x"}
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_existing
    mock_db.execute.return_value = mock_result

    res = await import_cn_math_taxonomy(mock_db)
    assert res["status"] == "success"
    assert res["updated"] == 531
    assert res["imported"] == 0
    assert res["deprecated"] == 18
    assert not mock_db.delete.called
    assert mock_existing.rich_content["deprecated"] is True
    assert mock_existing.rich_content["alias_targets"]
