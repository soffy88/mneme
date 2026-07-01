"""oprim.story_predict — 单 LLM 调用基于参考图推演剧情.

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from oprim.story_predict import story_predict, StoryPrediction
    >>> def my_llm(*, messages):
    ...     return {"content": '{"forward": [{"seconds": 3, "description": "ok"}], "backward": []}'}
    >>> result = asyncio.run(story_predict(
    ...     reference_image=Path("frame.png"),
    ...     llm=my_llm,
    ...     direction="forward",
    ... ))
    >>> isinstance(result, StoryPrediction)
    True

Raises:
    FileNotFoundError: reference_image 不存在.
    StoryPredictError: LLM 返回非合法 JSON / Pydantic 校验失败.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError


class StoryPredictError(Exception):
    """Raised when LLM returns invalid JSON or Pydantic validation fails."""


class TimePrediction(BaseModel):
    """单个时间点的剧情预测."""

    seconds: int
    description: str


class StoryPrediction(BaseModel):
    """完整剧情预测结果."""

    forward: list[TimePrediction]
    backward: list[TimePrediction]


@runtime_checkable
class LLMCaller(Protocol):
    """Protocol for synchronous LLM callers that accept messages and return a response dict."""

    def __call__(self, *, messages: list[dict[str, Any]]) -> dict[str, Any]: ...


def _build_messages(
    image_b64: str,
    direction: Literal["forward", "backward", "both"],
    prediction_points: list[int],
) -> list[dict[str, Any]]:
    """Build the LLM messages list with image + instruction."""
    direction_str = {
        "forward": "forward (future)",
        "backward": "backward (past)",
        "both": "both forward (future) and backward (past)",
    }[direction]

    forward_example = (
        [{"seconds": p, "description": "..."} for p in prediction_points]
        if direction in ("forward", "both")
        else []
    )
    backward_example = (
        [{"seconds": -p, "description": "..."} for p in prediction_points]
        if direction in ("backward", "both")
        else []
    )

    instruction = (
        f"Based on this image, predict story events in the {direction_str} direction.\n"
        f"Time points (seconds): {prediction_points}\n"
        "Return STRICT JSON only, no markdown:\n"
        "{\n"
        f'  "forward": {json.dumps(forward_example)},\n'
        f'  "backward": {json.dumps(backward_example)}\n'
        "}"
    )

    return [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                {"type": "text", "text": instruction},
            ],
        }
    ]


async def story_predict(
    *,
    reference_image: Path,
    llm: LLMCaller,
    direction: Literal["forward", "backward", "both"],
    prediction_points: list[int] | None = None,
) -> StoryPrediction:
    """单 LLM 调用基于参考图推演剧情.

    Args:
        reference_image: 参考图片路径，用于剧情推演。
        llm: LLMCaller Protocol 实例（同步 callable）。
        direction: 推演方向："forward"、"backward" 或 "both"。
        prediction_points: 推演时间点（秒），默认 [3, 5]。

    Returns:
        StoryPrediction，包含 forward / backward 列表。
        direction='forward' 时 backward 为空列表，反之亦然。

    Raises:
        FileNotFoundError: reference_image 文件不存在。
        StoryPredictError: LLM 返回内容不是合法 JSON 或 Pydantic 校验失败。

    Example:
        >>> def my_llm(*, messages):
        ...     return {"content": '{"forward": [{"seconds": 3}], "backward": []}'}
        >>> result = await story_predict(
        ...     reference_image=Path("frame.png"), llm=my_llm, direction="forward"
        ... )
    """
    if not reference_image.exists():
        raise FileNotFoundError(f"reference_image not found: {reference_image}")

    points = prediction_points if prediction_points is not None else [3, 5]
    image_bytes = reference_image.read_bytes()
    image_b64 = base64.b64encode(image_bytes).decode()

    messages = _build_messages(image_b64, direction, points)
    response = llm(messages=messages)

    content = response.get("content", "")
    try:
        raw = json.loads(content)
    except (json.JSONDecodeError, ValueError) as exc:
        raise StoryPredictError(f"LLM returned invalid JSON: {exc!r}") from exc

    # Enforce direction constraints
    if direction == "forward":
        raw["backward"] = []
    elif direction == "backward":
        raw["forward"] = []

    try:
        return StoryPrediction.model_validate(raw)
    except ValidationError as exc:
        raise StoryPredictError(f"Pydantic validation failed: {exc}") from exc


__all__ = [
    "story_predict",
    "StoryPrediction",
    "TimePrediction",
    "StoryPredictError",
    "LLMCaller",
]
