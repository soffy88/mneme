"""oprim.canvas_node_execute — Execute a single canvas node via injected executor."""
from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel

from oprim._hevi_types import CanvasNode


class CanvasNodeResult(BaseModel):
    node_id: str
    output: Any
    node_type: str
    success: bool
    error: str = ""


async def canvas_node_execute(
    *,
    node: CanvasNode,
    upstream_outputs: dict = {},
    executor: Callable | None = None,
) -> CanvasNodeResult:
    """Execute a canvas node using an injected executor callable.

    Args:
        node: The CanvasNode to execute.
        upstream_outputs: Mapping of upstream node_id -> output, passed to executor.
        executor: Callable that accepts (node, upstream_outputs) and returns output.
            If None, execution fails gracefully with error="no executor".

    Returns:
        CanvasNodeResult with success/failure status and any output.
    """
    if executor is None:
        return CanvasNodeResult(
            node_id=node.node_id,
            output=None,
            node_type=node.node_type,
            success=False,
            error="no executor",
        )

    try:
        output = await executor(node, upstream_outputs) if _is_async(executor) else executor(node, upstream_outputs)
        return CanvasNodeResult(
            node_id=node.node_id,
            output=output,
            node_type=node.node_type,
            success=True,
        )
    except Exception as exc:
        return CanvasNodeResult(
            node_id=node.node_id,
            output=None,
            node_type=node.node_type,
            success=False,
            error=str(exc),
        )


def _is_async(fn: Callable) -> bool:
    import inspect
    return inspect.iscoroutinefunction(fn)
