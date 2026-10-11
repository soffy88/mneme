"""教学内核 Layer 4 公共件：线程 + 超时执行 3O 事务、交互课模板安全注入。"""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
PLACEHOLDER = "__LESSON_DATA__"
SOLVE_TIMEOUT_S = 15.0


class EduKernelError(ValueError):
    """题目无法求解（参数不合法、退化构型或独立复核不一致）。"""


@lru_cache(maxsize=8)
def load_template(relative: str) -> str:
    text = (ASSETS_DIR / relative).read_text(encoding="utf-8")
    if PLACEHOLDER not in text:
        raise RuntimeError(f"lesson template {relative} is missing its data placeholder")
    return text


def render_template(relative: str, lesson_data: dict[str, Any]) -> str:
    """把课数据注入 ``<script type="application/json">``，转义 ``<``/``>``/``&``。"""
    payload = (
        json.dumps(lesson_data, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    return load_template(relative).replace(PLACEHOLDER, payload, 1)


async def run_omodul(fn: Callable[[Path], dict[str, Any]], *, prefix: str) -> dict[str, Any]:
    """在线程里跑 omodul（sympy 为 CPU 密集），超时/失败抛 EduKernelError。

    返回 solution 字典并附上 fingerprint。
    """

    def _call() -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
            return fn(Path(tmp))

    try:
        result = await asyncio.wait_for(asyncio.to_thread(_call), timeout=SOLVE_TIMEOUT_S)
    except TimeoutError as exc:
        raise EduKernelError("solving timed out") from exc
    if result["status"] != "completed":
        raise EduKernelError(result["error"]["message"])
    solution = dict(result["solution"])
    solution["fingerprint"] = result.get("fingerprint")
    return solution
