"""
KU 内容包 export↔import 往复对称性守卫（审计 P0-2）。

动机：12,573 个 KU 曾只存在于 DB、无固化 → 容器重建即清零且不可复现。
现在内容可 export 成 JSON 包（含 rich_content）、import 幂等回放。本测试锁住
export/import 的字段契约对称——防止未来加了列却漏了一侧，导致"导出的包无法完整回放"。

纯函数测试：不连 DB，CI 可跑。
"""

import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _load(mod_name: str):
    spec = importlib.util.spec_from_file_location(
        mod_name, _ROOT / "scripts" / f"{mod_name}.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_package_is_stable_and_covers_all_fields():
    export = _load("export_ku_package")

    tb = {
        "id": "TB-1",
        "subject": "math",
        "grade": "G10",
        "edition": "人教版",
        "book_name": "必修一",
    }
    clusters = [
        {"id": "C2", "name": "第二章", "display_order": 2, "description": None},
        {"id": "C1", "name": "第一章", "display_order": 1, "description": "集合"},
    ]
    units = [
        {
            "id": "U2",
            "textbook_id": "TB-1",
            "cluster_id": "C1",
            "name": "交集",
            "description": "d",
            "prerequisites": ["U1"],
            "related_kus": [],
            "difficulty": 0.6,
            "exam_frequency": "high",
            "question_types": ["choice"],
            "ku_type": "concept",
            "curriculum_standard": "cs",
            "mastery_levels": [],
            "rich_content": {"讲透": "x"},
            "provenance": {"src": "pdf"},
            "source_excerpt": "原文",
            "ai_generated": True,
            "verified": True,
        },
        {
            "id": "U1",
            "textbook_id": "TB-1",
            "cluster_id": "C1",
            "name": "集合",
            "description": None,
            "prerequisites": [],
            "related_kus": [],
            "difficulty": 0.5,
            "exam_frequency": "mid",
            "question_types": [],
            "ku_type": "concept",
            "curriculum_standard": None,
            "mastery_levels": [],
            "rich_content": None,
            "provenance": None,
            "source_excerpt": None,
            "ai_generated": True,
            "verified": False,
        },
    ]

    pkg = export.build_package(tb, clusters, units)

    # 每个 unit 都带全部往复字段（含 rich_content 等内容列）
    for u in pkg["units"]:
        assert set(u.keys()) == set(export.UNIT_FIELDS)
    # rich_content 被保留（不是被剥掉）
    assert pkg["units"][1]["rich_content"] == {"讲透": "x"}  # U2 排序后在后（按 id）
    # clusters 按 display_order 稳定排序
    assert [c["id"] for c in pkg["clusters"]] == ["C1", "C2"]
    # units 按 id 稳定排序
    assert [u["id"] for u in pkg["units"]] == ["U1", "U2"]

    # 幂等：把导出的 units 当作库行再次 build，结果逐字节一致
    pkg2 = export.build_package(tb, pkg["clusters"], pkg["units"])
    assert json.dumps(pkg2, ensure_ascii=False, sort_keys=True) == json.dumps(
        pkg, ensure_ascii=False, sort_keys=True
    )


def test_import_expects_same_unit_fields_as_export_emits():
    """import 的 upsert 覆盖 export 输出的每个内容字段——防单侧漂移。"""
    export = _load("export_ku_package")
    import_src = (_ROOT / "scripts" / "import_ku_package.py").read_text(
        encoding="utf-8"
    )

    # export 声明的每个 unit 字段，import 的 upsert_unit 必须处理（出现在 INSERT 列或参数里）
    # textbook_id/cluster_id 由包结构携带，其余内容字段必须在 import 源码中出现
    for field in export.UNIT_FIELDS:
        assert field in import_src, (
            f"import_ku_package.py 未处理 export 输出字段: {field}"
        )


def test_sample_package_matches_import_contract():
    """仓库内 sample 包能被 export 的字段集覆盖（结构合法）。"""
    export = _load("export_ku_package")
    sample = json.loads(
        (_ROOT / "scripts" / "sample_ku_package.json").read_text(encoding="utf-8")
    )
    assert "textbook" in sample and "units" in sample and "clusters" in sample
    for u in sample["units"]:
        # sample 的每个字段都在往复字段集内（不存在 export 无法表达的字段）
        assert set(u.keys()) <= set(export.UNIT_FIELDS), set(u.keys()) - set(
            export.UNIT_FIELDS
        )
