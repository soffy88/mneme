import json
import os
from unittest.mock import AsyncMock, MagicMock

from services.cn_math_importer import import_cn_math_taxonomy

DATA_DIR = os.getenv("CN_MATH_DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cn_math_taxonomy"))


def _n_topics() -> int:
    with open(os.path.join(DATA_DIR, "topics.json"), encoding="utf-8") as f:
        return len(json.load(f))


async def test_cn_math_importer():
    for name in ("topics.json", "dependencies.json", "questions.json", "cn-curriculum-standards.json", "id-aliases.json"):
        assert os.path.exists(os.path.join(DATA_DIR, name)), name

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = mock_result

    res = await import_cn_math_taxonomy(mock_db)
    n = _n_topics()
    assert n == 531
    assert res["status"] == "success"
    assert res["total"] == n and res["imported"] == n and res["deprecated"] == 0
    assert mock_db.commit.called
    kus = {c.args[0].id: c.args[0] for c in mock_db.add.call_args_list}
    ku = kus["cnmath:cnm_221"]
    assert ku.prerequisites == ["cnmath:cnm_220", "cnmath:cnm_148"]
    assert "全国中考" in ku.exam_region_tags
    assert "小学" in kus["cnmath:cnm_p001"].exam_region_tags
    assert json.loads(ku.curriculum_standard)[0]["text"]
    assert ku.provenance["license"] == "CC BY-NC 4.0" and ku.provenance["commit"]
    assert ku.rich_content["questions"] and isinstance(ku.rich_content["order"], int)
