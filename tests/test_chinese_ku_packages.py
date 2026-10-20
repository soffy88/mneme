"""语文 KU 包结构校验（纯函数，不依赖 DB）。

覆盖 2026-10 补齐的两类内容：
- 小学 1–6 年级 12 册新增包（此前 mneme 小学语文为 0 条）；
- 中考/高考语文专题包（文言虚词、文言翻译与内容概括、阅读策略、
  整本书阅读、综合性学习/学习任务群）。

锁住 KU 包的字段契约、ID/集群引用完整性、ku_type 合法性与前置边不悬空，
防止后续手工编辑把包改成 import_ku_package.py 无法回放的结构。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PKG_DIR = _ROOT / "data" / "ku_packages"

PRIMARY_IDS = {
    f"TONGBIAN-G{g}-CHINESE-{v}" for g in range(1, 7) for v in ("S", "X")
}
SUPPLEMENT_IDS = {"ZHONGKAO-CHINESE-ZHUANTI", "GAOKAO-CHINESE-ZHUANTI"}
NEW_IDS = PRIMARY_IDS | SUPPLEMENT_IDS

VALID_KU_TYPES = {
    "wenyan_word", "wenyan_syntax", "mingju", "mingpian", "chengyu",
    "zixing_ziyin", "cizu_yunyong", "wenhua_changshi", "bingju", "biaodian",
    "jixuwen_yuedu", "shuomingwen_yuedu", "yilunwen_yuedu", "sanwen_yuedu",
    "wenyan_yuedu", "shici_jianshang", "mingzhu_yuedu", "xiaoshuo_yuedu",
    "xinxi_yuedu", "xiezuo", "kouyu_jiaoji", "goutong_chushi",
}


def _load_export():
    spec = importlib.util.spec_from_file_location(
        "export_ku_package", _ROOT / "scripts" / "export_ku_package.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load(tid: str) -> dict:
    with open(_PKG_DIR / f"{tid}.json", encoding="utf-8") as f:
        return json.load(f)


def test_all_expected_packages_exist():
    for tid in NEW_IDS:
        assert (_PKG_DIR / f"{tid}.json").is_file(), tid


def test_new_packages_match_export_contract():
    export = _load_export()
    expected = set(export.UNIT_FIELDS)
    for tid in NEW_IDS:
        pkg = _load(tid)
        assert pkg["textbook"]["id"] == tid
        assert pkg["textbook"]["subject"] == "chinese"
        for unit in pkg["units"]:
            assert set(unit.keys()) == expected, (tid, unit["id"])
            assert unit["textbook_id"] == tid
            assert isinstance(unit["prerequisites"], list)
            assert isinstance(unit["related_kus"], list)


def test_ids_clusters_and_links_are_consistent():
    seen_ids: dict[str, str] = {}
    seen_names: dict[str, str] = {}
    for tid in NEW_IDS:
        pkg = _load(tid)
        cluster_ids = {c["id"] for c in pkg["clusters"]}
        assert len(cluster_ids) == len(pkg["clusters"])
        unit_ids = {u["id"] for u in pkg["units"]}
        assert len(unit_ids) == len(pkg["units"])
        for unit in pkg["units"]:
            uid = unit["id"]
            assert uid not in seen_ids, (uid, seen_ids.get(uid))
            seen_ids[uid] = tid
            assert unit["name"] not in seen_names, (unit["name"], seen_names.get(unit["name"]))
            seen_names[unit["name"]] = tid
            assert unit["cluster_id"] in cluster_ids
            assert len(uid) <= 100
            for linked in unit["prerequisites"] + unit["related_kus"]:
                assert linked in unit_ids, (uid, linked)
                assert linked != uid


def test_ku_type_difficulty_and_description_quality():
    for tid in NEW_IDS:
        for unit in _load(tid)["units"]:
            assert unit["ku_type"] in VALID_KU_TYPES, (unit["id"], unit["ku_type"])
            assert 0.0 <= unit["difficulty"] <= 1.0
            desc = (unit["description"] or "").strip()
            assert len(desc) >= 20, unit["id"]
            assert "know-what:" in desc, unit["id"]
            assert "来源:" in desc, unit["id"]


def test_primary_packages_cover_core_strands():
    """每册至少有识字写字、词语、句子/标点、阅读、古诗文、表达、整本书七类。"""
    required = {
        "zixing_ziyin", "cizu_yunyong", "jixuwen_yuedu", "biaodian",
        "xiezuo", "kouyu_jiaoji", "mingzhu_yuedu",
    }
    for tid in PRIMARY_IDS:
        types = {u["ku_type"] for u in _load(tid)["units"]}
        missing = required - types
        assert not missing, (tid, missing)
        assert types & {"mingju", "shici_jianshang"}, tid
        assert types & {"wenhua_changshi", "wenyan_word"}, tid


def test_supplement_clusters_cover_confirmed_gaps():
    expectations = {
        "ZHONGKAO-CHINESE-ZHUANTI": {
            "文言虚词": 20, "文言翻译": 6, "文言内容概括": 4,
            "阅读策略": 5, "名著整本书": 10, "综合性学习": 4,
        },
        "GAOKAO-CHINESE-ZHUANTI": {
            "文言虚词": 16, "文言翻译与断句": 8, "文言内容概括": 5,
            "名篇名句默写": 16, "整本书阅读": 18, "学习任务群": 20,
        },
    }
    for tid, cluster_min in expectations.items():
        pkg = _load(tid)
        by_name = {c["name"]: c["id"] for c in pkg["clusters"]}
        counts: dict[str, int] = {name: 0 for name in by_name}
        for unit in pkg["units"]:
            for name, cid in by_name.items():
                if unit["cluster_id"] == cid:
                    counts[name] += 1
        for name, minimum in cluster_min.items():
            assert name in by_name, (tid, name)
            assert counts[name] >= minimum, (tid, name, counts[name])
