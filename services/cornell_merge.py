"""康奈尔笔记进度合并（纯函数，无 I/O）。

契约见 Master 附录「交互式康奈尔笔记（Phase B）」。
前后端导入/云同步必须使用同一并集策略。

红线：本模块只处理进度 JSON，禁止写掌握度或调用认知更新管线。
"""

from __future__ import annotations

from typing import Any


class CornellMergeError(ValueError):
    """进度合并失败（topic 不一致、结构非法等）。"""


def _bool_map(raw: Any) -> dict[str, bool]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CornellMergeError("mastered/collapsed must be objects")
    out: dict[str, bool] = {}
    for k, v in raw.items():
        if v:
            out[str(k)] = True
    return out


def _union_true(a: dict[str, bool], b: dict[str, bool]) -> dict[str, bool]:
    keys = set(a) | set(b)
    return {k: True for k in keys if a.get(k) or b.get(k)}


def merge_cornell_state(local: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """合并两份康奈尔进度。

    - mastered / collapsed：键级并集（任一端为 true → true）
    - selfTest / showAnswers：取 updatedAt 较新的一端
    - topicId 必须一致；version 取 max
    """
    if not isinstance(local, dict) or not isinstance(incoming, dict):
        raise CornellMergeError("state must be objects")

    tid_l = local.get("topicId")
    tid_i = incoming.get("topicId")
    if not tid_l or not tid_i:
        raise CornellMergeError("topicId required on both states")
    if tid_l != tid_i:
        raise CornellMergeError(f"topicId mismatch: {tid_l!r} vs {tid_i!r}")

    ts_l = str(local.get("updatedAt") or "")
    ts_i = str(incoming.get("updatedAt") or "")
    newer = incoming if ts_i >= ts_l else local

    ver_l = int(local.get("version") or 1)
    ver_i = int(incoming.get("version") or 1)

    return {
        "topicId": tid_l,
        "version": max(ver_l, ver_i),
        "mastered": _union_true(
            _bool_map(local.get("mastered")),
            _bool_map(incoming.get("mastered")),
        ),
        "collapsed": _union_true(
            _bool_map(local.get("collapsed")),
            _bool_map(incoming.get("collapsed")),
        ),
        "selfTest": bool(newer.get("selfTest", False)),
        "showAnswers": bool(newer.get("showAnswers", False)),
        "updatedAt": max(ts_l, ts_i) if (ts_l or ts_i) else newer.get("updatedAt"),
    }


def storage_key(topic_id: str, version: int = 1) -> str:
    return f"cornell_{topic_id}_v{version}"
