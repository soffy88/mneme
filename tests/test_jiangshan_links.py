"""江山时序外链数据（data/jiangshan_links/links.json）的结构与一致性校验。

这些链接只是第三方示意地图的外链，不复制对方任何 JS/几何数据；测试只读
mneme 自己的 KU 包与链接清单，不依赖外部仓库。
"""

from __future__ import annotations

import json
import urllib.parse
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINKS_PATH = ROOT / "data" / "jiangshan_links" / "links.json"
KU_DIR = ROOT / "data" / "ku_packages"
URL_PREFIX = "https://deanchen.me/jiangshan-map/?"
LABEL = "第三方示意地图，非教材标准地图"
FIELDS = [
    "ku_id",
    "ku_name",
    "grade",
    "url",
    "year",
    "place",
    "person",
    "label",
    "confidence",
    "reason",
]


def _load_ku_index() -> dict[str, dict]:
    index: dict[str, dict] = {}
    for path in sorted(KU_DIR.glob("*.json")):
        package = json.loads(path.read_text(encoding="utf-8"))
        textbook = package.get("textbook") or {}
        if textbook.get("subject") != "chinese":
            continue
        for unit in package.get("units", []):
            index[unit["id"]] = {
                "name": unit.get("name"),
                "grade": textbook.get("grade"),
            }
    return index


def test_links_json_shape_and_ku_ids():
    assert LINKS_PATH.is_file(), f"missing {LINKS_PATH}"
    links = json.loads(LINKS_PATH.read_text(encoding="utf-8"))
    assert isinstance(links, list)
    assert len(links) == 153, "pilot 批次应为 153 个高置信语文 KU"

    ku_index = _load_ku_index()
    ids = [row["ku_id"] for row in links]
    assert len(ids) == len(set(ids)), "ku_id 不应重复"

    for row in links:
        assert list(row) == FIELDS, f"字段顺序/集合不符：{row.get('ku_id')}"
        assert row["ku_id"] in ku_index, f"ku_id 不在 ku_packages：{row['ku_id']}"
        assert row["ku_name"] == ku_index[row["ku_id"]]["name"]
        assert row["grade"] == ku_index[row["ku_id"]]["grade"]
        assert row["grade"] in {"G4", "G5", "G6", "G7", "G8", "G9", "G10", "G11", "G12"}
        assert row["label"] == LABEL
        assert row["confidence"] in {"high", "medium"}
        assert isinstance(row["reason"], str) and row["reason"].strip()


def test_links_urls_are_deep_links_and_match_fields():
    links = json.loads(LINKS_PATH.read_text(encoding="utf-8"))
    for row in links:
        url = row["url"]
        assert url.startswith(URL_PREFIX), url

        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query, keep_blank_values=True)
        assert set(query) <= {"year", "place", "person"}, url

        assert row["place"] or row["person"], "place 与 person 至少一个非空"
        assert not (row["place"] and row["person"]), "place 与 person 不应同时使用"

        if row["person"]:
            assert query["person"] == [row["person"]], url
            assert row["year"] is None, "人物深链不写 year 字段"
        else:
            assert "year" in query, f"地点深链必须带 year：{url}"
            assert query["place"] == [row["place"]], url
            assert isinstance(row["year"], int)
            assert -403 <= row["year"] <= 2026
            assert query["year"] == [str(row["year"])], url
            # place 必须是中文（可含逗号分隔的多站路线），并在 URL 中完成百分号编码
            for stop in row["place"].split(","):
                assert stop and any("\u4e00" <= ch <= "\u9fff" for ch in stop), stop
            if any("\u4e00" <= ch <= "\u9fff" for ch in row["place"]):
                assert "%" in url.split("?", 1)[1], f"中文 place 应 URL 编码：{url}"


def test_links_grade_distribution_matches_pilot_report():
    links = json.loads(LINKS_PATH.read_text(encoding="utf-8"))
    distribution = Counter(row["grade"] for row in links)
    assert distribution == Counter(
        {"G9": 57, "G8": 46, "G10": 22, "G7": 13, "G12": 11, "G11": 4}
    )
