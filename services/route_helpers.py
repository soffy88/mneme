"""路由层共享小工具（无业务状态）。"""

from __future__ import annotations

import re


def grade_sort_key(grade: str) -> int:
    """年级字符串排序键：G7…G12 / 初一…高三。"""
    m = re.match(r"G(\d+)$", grade or "")
    if m:
        return int(m.group(1))
    for hs, n in [("高一", 10), ("高二", 11), ("高三", 12)]:
        if (grade or "").startswith(hs):
            return n
    for ms, n in [("初一", 7), ("初二", 8), ("初三", 9)]:
        if (grade or "").startswith(ms):
            return n
    return 99
