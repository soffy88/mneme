"""解析几何（圆锥曲线弦问题）交互解题（Layer 4）。

调用 3O 事务 ``omodul.conic_chord_lesson``（sympy 精确求范围/定值 + 独立浮点扫描复核），
并把画板数据注入 edulab 的交互画板模板（``services/assets/conic_geometry/board.html``，
Apache-2.0，见同目录 LICENSE / NOTICE）。纯计算、无 DB 写入、不调用 LLM。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from omodul.conic_chord_lesson import (
    ConicChordLessonConfig,
    ConicChordLessonInput,
    conic_chord_lesson,
)
from oprim.conic_analysis import AnalyticGeometrySpec

from services.edu_lesson_common import render_template, run_omodul

TEMPLATE = "conic_geometry/board.html"


async def solve(spec: AnalyticGeometrySpec) -> dict[str, Any]:
    def _fn(tmp: Path) -> dict[str, Any]:
        return conic_chord_lesson(
            ConicChordLessonConfig(write_lesson_json=False),
            ConicChordLessonInput(spec=spec),
            tmp,
        )

    return await run_omodul(_fn, prefix="mneme-conic-")


def render_board_html(board_data: dict[str, Any]) -> str:
    return render_template(TEMPLATE, board_data)
