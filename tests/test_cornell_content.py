"""康奈尔 content.json 契约校验 + 合并红线。"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from services.cornell_merge import (
    CornellMergeError,
    merge_cornell_state,
    storage_key,
)

ROOT = Path(__file__).resolve().parents[1]
TOPICS = ROOT / "data" / "cornell_topics"
REQUIRED = {
    "topicId",
    "version",
    "subject",
    "title",
    "cues",
    "modules",
    "summary",
    "oneLiner",
}


def _all_content_files() -> list[Path]:
    if not TOPICS.is_dir():
        return []
    return sorted(TOPICS.glob("*/content.json"))


@pytest.mark.parametrize("path", _all_content_files(), ids=lambda p: p.parent.name)
def test_content_schema(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = REQUIRED - set(data)
    assert not missing, f"{path}: missing {missing}"
    assert data["topicId"] == path.parent.name
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["cues"], list) and 8 <= len(data["cues"]) <= 12
    assert isinstance(data["modules"], list) and 4 <= len(data["modules"]) <= 8

    mod_ids = {m["id"] for m in data["modules"]}
    cue_ids: set[str] = set()
    for c in data["cues"]:
        assert "id" in c and "mod" in c and "text" in c
        assert c["mod"] in mod_ids, f"cue {c['id']} mod {c['mod']} not in modules"
        assert c["id"] not in cue_ids
        cue_ids.add(c["id"])
    for m in data["modules"]:
        assert "id" in m and "title" in m and "body" in m


def test_storage_key() -> None:
    assert storage_key("pythagoras", 1) == "cornell_pythagoras_v1"


def test_merge_union_mastered_and_newer_prefs() -> None:
    a = {
        "topicId": "pythagoras",
        "version": 1,
        "mastered": {"q1": True},
        "collapsed": {},
        "selfTest": False,
        "showAnswers": False,
        "updatedAt": "2026-07-28T10:00:00.000Z",
    }
    b = {
        "topicId": "pythagoras",
        "version": 1,
        "mastered": {"q3": True},
        "collapsed": {"m2": True},
        "selfTest": True,
        "showAnswers": True,
        "updatedAt": "2026-07-28T12:00:00.000Z",
    }
    m = merge_cornell_state(a, b)
    assert m["mastered"] == {"q1": True, "q3": True}
    assert m["collapsed"] == {"m2": True}
    assert m["selfTest"] is True
    assert m["showAnswers"] is True
    assert m["updatedAt"] == "2026-07-28T12:00:00.000Z"


def test_merge_topic_mismatch() -> None:
    with pytest.raises(CornellMergeError, match="topicId mismatch"):
        merge_cornell_state(
            {"topicId": "a", "mastered": {}, "updatedAt": "1"},
            {"topicId": "b", "mastered": {}, "updatedAt": "2"},
        )


def test_cornell_modules_never_import_mastery_write_path() -> None:
    """红线：cornell 合并/内容模块不得耦合掌握度写入。"""
    forbidden = (
        "process_interaction",
        "cognitive_service",
        "mastery_gate",
        "math_grade",
    )
    path = ROOT / "services" / "cornell_merge.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(a.name for a in node.names)
    hits = [f for f in forbidden if any(f in imp for imp in imported)]
    assert not hits, f"cornell_merge imports mastery path: {hits}"
    # 禁止函数体里出现调用/属性访问痕迹（允许文档注释用中文描述）
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in forbidden:
            raise AssertionError(f"cornell_merge references {node.id}")
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            raise AssertionError(f"cornell_merge references .{node.attr}")
