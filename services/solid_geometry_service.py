"""立体几何交互解题（Layer 4）。

调用 3O 事务 ``omodul.solid_geometry_lesson``（sympy 精确求解 + 独立浮点复核），
并把课数据注入 edulab 的交互课模板（``services/assets/solid_geometry/lesson.html``，
Apache-2.0，见同目录 LICENSE / NOTICE）。

纯计算、无 DB 写入、不调用 LLM。sympy 是 CPU 密集计算，放线程里跑并设超时，
不阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

from omodul.solid_geometry_lesson import (
    SolidGeometryLessonConfig,
    SolidGeometryLessonInput,
    solid_geometry_lesson,
)
from oprim.solid_geometry import SolidGeometrySpec

TEMPLATE_PATH = (
    Path(__file__).resolve().parent / "assets" / "solid_geometry" / "lesson.html"
)
PLACEHOLDER = "__LESSON_DATA__"
SOLVE_TIMEOUT_S = 15.0


class SolidGeometryError(ValueError):
    """题目无法求解（参数不合法、退化构型或复核不一致）。"""


@lru_cache(maxsize=1)
def _template() -> str:
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    if PLACEHOLDER not in text:
        raise RuntimeError(
            "solid geometry lesson template is missing its data placeholder"
        )
    return text


def _run(spec: SolidGeometrySpec) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="mneme-solid-") as tmp:
        return solid_geometry_lesson(
            SolidGeometryLessonConfig(write_lesson_json=False),
            SolidGeometryLessonInput(spec=spec),
            Path(tmp),
        )


async def solve(spec: SolidGeometrySpec) -> dict[str, Any]:
    """返回 omodul 结果中的 solution + fingerprint；失败抛 SolidGeometryError。"""
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_run, spec), timeout=SOLVE_TIMEOUT_S
        )
    except TimeoutError as exc:
        raise SolidGeometryError("solving timed out") from exc
    if result["status"] != "completed":
        raise SolidGeometryError(result["error"]["message"])
    solution = dict(result["solution"])
    solution["fingerprint"] = result.get("fingerprint")
    return solution


def render_lesson_html(lesson_data: dict[str, Any]) -> str:
    """把课数据安全注入模板。

    数据位于 ``<script type="application/json">`` 中，转义 ``<``/``>``/``&``，
    防止任何字段提前闭合 script 标签。
    """
    payload = (
        json.dumps(lesson_data, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    return _template().replace(PLACEHOLDER, payload, 1)
