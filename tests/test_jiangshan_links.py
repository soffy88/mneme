"""江山时序外链数据（data/jiangshan_links/links.json）的结构与一致性校验。

这些链接只是第三方示意地图的外链，不复制对方任何 JS/几何数据；测试只读
mneme 自己的 KU 包与链接清单，不依赖外部仓库。

口径（JL2）：560 个名称直指候选 + 别名/放宽地名扩展（827）+ 古诗文篇目级扩展，
合计 2062 个候选 KU；生成 1751 条深链，剔除 311 条（原因见 dropped.json）。
"""

from __future__ import annotations

import json
import urllib.parse
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "jiangshan_links"
LINKS_PATH = DATA_DIR / "links.json"
DROPPED_PATH = DATA_DIR / "dropped.json"
KU_DIR = ROOT / "data" / "ku_packages"
URL_PREFIX = "https://deanchen.me/jiangshan-map/?"
LABEL = "第三方示意地图，非教材标准地图"
FIELDS = [
    "ku_id",
    "ku_name",
    "grade",
    "kind",
    "url",
    "year",
    "place",
    "person",
    "label",
    "confidence",
    "reason",
]
DROP_FIELDS = ["ku_id", "ku_name", "grade", "ku_type", "reason"]
TOTAL = 1751
TEXT_TOTAL = 482
GLOSS_TOTAL = 1269
DROPPED_TOTAL = 311
GRADE_COUNTS = {
    "G1": 1,
    "G5": 1,
    "G7": 182,
    "G8": 374,
    "G9": 510,
    "G10": 429,
    "G11": 88,
    "G12": 166,
}
# 字词/句子级条目：依附篇目，前端默认折叠，只展示 text 级。
GLOSS_TYPES = {
    "wenyan_word",
    "wenyan_syntax",
    "mingju",
    "zixing_ziyin",
    "chengyu",
    "cizu_yunyong",
    "biaodian",
    "bingju",
}
# 江山时序 PERSON_PROFILES 中实际用到的 key（外部仓库不可作为测试依赖）。
PERSON_KEYS = {
    "quyuan",
    "liuyuxi",
    "libai",
    "zhugeliang",
    "sushi",
    "xuanzang",
    "dufu",
    "luyou",
    "ouyangxiu",
    "wangwei",
    "baijuyi",
    "taoyuanming",
    "fanzhongyan",
    "xinqiji",
    "wentianxiang",
    "caocao",
    "liuzongyuan",
    "hanyu",
}


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
                "ku_type": unit.get("ku_type"),
            }
    return index


@pytest.fixture(scope="module")
def links() -> list[dict]:
    assert LINKS_PATH.is_file(), f"missing {LINKS_PATH}"
    return json.loads(LINKS_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ku_index() -> dict[str, dict]:
    return _load_ku_index()


def test_links_json_shape_and_ku_ids(links, ku_index):
    assert isinstance(links, list)
    assert len(links) == TOTAL

    ids = [row["ku_id"] for row in links]
    assert len(ids) == len(set(ids)), "ku_id 不应重复"
    grade_order = {g: i for i, g in enumerate(GRADE_COUNTS, start=1)}
    assert links == sorted(
        links, key=lambda r: (grade_order[r["grade"]], r["ku_id"])
    ), "应按年级、ku_id 稳定排序"

    for row in links:
        assert list(row) == FIELDS, f"字段顺序/集合不符：{row.get('ku_id')}"
        assert row["ku_id"] in ku_index, f"ku_id 不在 ku_packages：{row['ku_id']}"
        assert row["ku_name"] == ku_index[row["ku_id"]]["name"]
        assert row["grade"] == ku_index[row["ku_id"]]["grade"]
        assert row["grade"] in GRADE_COUNTS
        assert row["label"] == LABEL
        assert row["confidence"] in {"high", "medium"}
        assert row["kind"] in {"text", "gloss"}
        assert isinstance(row["reason"], str) and row["reason"].strip()


def test_kind_matches_ku_type(links, ku_index):
    for row in links:
        ku_type = ku_index[row["ku_id"]]["ku_type"]
        expected = "gloss" if ku_type in GLOSS_TYPES else "text"
        assert row["kind"] == expected, f"{row['ku_id']} ({ku_type}) 应为 {expected}"


def test_links_urls_are_deep_links_and_match_fields(links):
    for row in links:
        url = row["url"]
        assert url.startswith(URL_PREFIX), url

        query = urllib.parse.parse_qs(
            urllib.parse.urlsplit(url).query, keep_blank_values=True
        )
        assert set(query) <= {"year", "place", "person"}, url

        assert row["place"] or row["person"], "place 与 person 至少一个非空"
        assert not (row["place"] and row["person"]), "place 与 person 不应同时使用"

        if row["person"]:
            assert row["person"] in PERSON_KEYS, row["person"]
            assert query["person"] == [row["person"]], url
            assert row["year"] is None, "人物深链不写 year 字段"
        else:
            assert "year" in query, f"地点深链必须带 year：{url}"
            assert query["place"] == [row["place"]], url
            assert isinstance(row["year"], int)
            assert -403 <= row["year"] <= 2026
            assert query["year"] == [str(row["year"])], url
            for stop in row["place"].split(","):
                assert stop and any("\u4e00" <= ch <= "\u9fff" for ch in stop), stop
            if any("\u4e00" <= ch <= "\u9fff" for ch in row["place"]):
                assert "%" in url.split("?", 1)[1], f"中文 place 应 URL 编码：{url}"


def test_links_grade_and_kind_distribution(links):
    assert Counter(row["grade"] for row in links) == Counter(GRADE_COUNTS)
    kinds = Counter(row["kind"] for row in links)
    assert kinds == Counter({"gloss": GLOSS_TOTAL, "text": TEXT_TOTAL})


def test_pilot_sentinels_keep_their_anchors(links):
    by_id = {row["ku_id"]: row for row in links}

    def check(ku_id: str, place: str | None, person: str | None, year: int | None):
        assert ku_id in by_id, ku_id
        row = by_id[ku_id]
        assert (row["place"], row["person"], row["year"]) == (place, person, year)

    # 苏轼黄州文赤壁 / 杜牧蒲圻武赤壁 必须分开
    check("GAOKAO-CHINESE-ZHUANTI-ku-赤壁赋--寄蜉蝣于天地", "黄州", None, 1082)
    check("TONGBIAN-G8-CHINESE-S-ku-东风不与周郎便-赤壁", "赤壁", None, 208)
    # 韩愈蓝关、文天祥零丁洋、张养浩潼关
    check(
        "TONGBIAN-G9-CHINESE-S-ku-云横秦岭家何在-左迁至蓝关示侄孙湘",
        "蓝田关",
        None,
        819,
    )
    check("TONGBIAN-G9-CHINESE-X-ku-人生自古谁无死-过零丁洋", "零丁洋", None, 1279)
    check("TONGBIAN-G9-CHINESE-X-ku-兴-百姓苦-山坡羊-潼关怀古", "潼关", None, 1329)
    # 人物档案链
    check("TONGBIAN-G7-CHINESE-S-ku-李白-文学常识", None, "libai", None)


def test_dropped_records_are_complete_and_disjoint(links):
    assert DROPPED_PATH.is_file(), f"missing {DROPPED_PATH}"
    dropped = json.loads(DROPPED_PATH.read_text(encoding="utf-8"))
    assert len(dropped) == DROPPED_TOTAL

    ku_index = _load_ku_index()
    live_ids = {row["ku_id"] for row in links}
    drop_ids = [row["ku_id"] for row in dropped]
    assert len(drop_ids) == len(set(drop_ids))
    assert not (set(drop_ids) & live_ids), "剔除清单不应与已生成清单重叠"
    assert len(live_ids) + len(drop_ids) == 2062, "候选总数应为 2062"

    for row in dropped:
        assert list(row) == DROP_FIELDS
        assert row["ku_id"] in ku_index
        assert row["ku_name"] == ku_index[row["ku_id"]]["name"]
        assert row["grade"] == ku_index[row["ku_id"]]["grade"]
        assert row["ku_type"] == ku_index[row["ku_id"]]["ku_type"]
        assert isinstance(row["reason"], str) and row["reason"].strip()
