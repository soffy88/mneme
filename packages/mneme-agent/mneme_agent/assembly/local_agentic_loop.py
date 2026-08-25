"""Small, dependency-free agent loop used by Mneme chat.

This is deliberately a Layer 4 runtime primitive, not a second business agent:
it only handles the provider/tool-call protocol. Mneme-specific tools remain
HTTP adapters in :mod:`tutor_loop`, so this module has no database or service
imports and can be loaded when the optional oservi package is absent.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal


LoopLLM = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Provider-neutral tool adapter contract."""

    name: str
    description: str
    input_schema: dict[str, Any]
    callable: Callable[[dict[str, Any]], Any]
    readonly: bool = False


@dataclass(slots=True)
class _SessionState:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    messages: list[dict[str, Any]] = field(default_factory=list)
    iteration: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)

    def record(self, **payload: Any) -> None:
        self.events.append({"ts": time.time(), "iter": self.iteration, **payload})


class LocalAgenticLoop:
    """In-memory tool-calling loop with the chat-facing oservi session contract."""

    def __init__(
        self,
        *,
        max_iterations: int = 40,
        budget_usd: float = 5.0,
        model: str = "tutor",
        mode: Literal["build", "plan"] = "build",
        output_dir: Path = Path("/tmp/mneme_tutor"),
        context_limit_tokens: int = 180_000,
    ) -> None:
        if max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        self.max_iterations = max_iterations
        self.budget_usd = budget_usd
        self.model = model
        self.mode = mode
        # Retained for interface compatibility; this loop intentionally does
        # not write session state to disk.
        self.output_dir = Path(output_dir)
        self.context_limit_tokens = context_limit_tokens
        self._llm_caller: LoopLLM | None = None
        self._tool_specs: list[ToolSpec] = []
        self._output_guard: Callable[[str], str] | None = None
        self._running = False
        self._tick_count = 0

    def assemble(
        self,
        *,
        llm_caller: LoopLLM,
        tools: list[ToolSpec],
        output_guard: Callable[[str], str] | None = None,
    ) -> "LocalAgenticLoop":
        if llm_caller is None:
            raise ValueError("llm_caller is required")
        if not tools:
            raise ValueError("at least one tool is required")
        self._llm_caller = llm_caller
        self._tool_specs = list(tools)
        self._output_guard = output_guard
        return self

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy" if self._running else "stopped",
            "tick_count": self._tick_count,
            "injected": ["llm_caller", "tools"],
        }

    @property
    def _tools(self) -> list[ToolSpec]:
        if self.mode == "plan":
            return [tool for tool in self._tool_specs if tool.readonly]
        return self._tool_specs

    def _tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in self._tools
        ]

    def _estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        return sum(len(json.dumps(message, ensure_ascii=False)) for message in messages) // 4

    def _effective_system(self, system_prompt: str) -> str:
        base = system_prompt or "你是善学记的学习助手。"
        return f"{base}\n\n运行模式：{self.mode}。"

    async def session(
        self,
        task: str,
        *,
        system_prompt: str = "",
        on_step: Callable[[dict[str, Any]], None] | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Run one in-memory session and return the established loop result shape."""

        if self._llm_caller is None:
            raise RuntimeError("LocalAgenticLoop must be assembled before session()")

        self._running = True
        state = _SessionState(messages=[{"role": "user", "content": task}])
        final_text = ""
        status = "completed"
        total_cost = 0.0
        input_tokens = 0
        output_tokens = 0
        tool_schemas = self._tool_schemas() or None

        if on_step:
            on_step(
                {
                    "event": "session_start",
                    "session_id": state.session_id,
                    "mode": self.mode,
                    "task_preview": task[:120],
                }
            )

        try:
            for iteration in range(self.max_iterations):
                state.iteration = iteration
                self._tick_count += 1
                if self._estimate_tokens(state.messages) > self.context_limit_tokens:
                    state.messages = state.messages[-20:]
                    state.record(event="context_truncated")

                state.record(event="llm_call")
                response = await self._llm_caller(
                    messages=state.messages,
                    tools=tool_schemas,
                    max_tokens=8192,
                    thinking_budget=None,
                    system=self._effective_system(system_prompt),
                )
                if not isinstance(response, dict):
                    raise TypeError("llm_caller must return a dict")

                usage = response.get("usage") or {}
                input_tokens += int(usage.get("input_tokens", 0) or 0)
                output_tokens += int(usage.get("output_tokens", 0) or 0)
                total_cost += _estimate_cost(
                    int(usage.get("input_tokens", 0) or 0),
                    int(usage.get("output_tokens", 0) or 0),
                )
                if total_cost > self.budget_usd:
                    status = "budget_exceeded"
                    state.record(event="budget_exceeded", total_usd=total_cost)
                    break

                content = _normalize_content(response.get("content", []))
                for block in content:
                    if block.get("type") == "text":
                        final_text = str(block.get("text", ""))
                        if self._output_guard is not None:
                            final_text = self._output_guard(final_text)
                            # Do not leave the raw completion in the in-memory
                            # conversation when a later tool turn continues.
                            block["text"] = final_text
                        if on_token:
                            on_token(final_text)
                        state.record(event="text", preview=final_text[:80])
                    elif block.get("type") == "thinking":
                        state.record(
                            event="thinking",
                            preview=str(block.get("thinking", ""))[:60],
                        )

                tool_uses = [block for block in content if block.get("type") == "tool_use"]
                stop_reason = response.get("stop_reason", "end_turn")
                if stop_reason != "tool_use" and not tool_uses:
                    state.record(event="loop_done", reason=stop_reason)
                    break
                if not tool_uses:
                    state.record(event="loop_done", reason=stop_reason)
                    break

                tool_results = []
                for tool_use in tool_uses:
                    tool_results.append(await self._handle_tool_use(tool_use, state, on_step))
                state.messages.append({"role": "assistant", "content": content})
                state.messages.append({"role": "user", "content": tool_results})
                if on_step:
                    on_step(
                        {
                            "event": "iteration_done",
                            "iteration": iteration,
                            "n_tools": len(tool_uses),
                            "cost_usd": round(total_cost, 6),
                        }
                    )
        except asyncio.CancelledError:
            status = "interrupted"
            state.record(event="cancelled")
            raise
        except Exception as exc:
            status = "failed"
            state.record(event="error", error=str(exc))
            final_text = f"[engine error: {exc}]"
        finally:
            self._running = False

        result = {
            "result": final_text,
            "status": status,
            "iterations": state.iteration + 1,
            "cost_usd": round(total_cost, 6),
            "in_tokens": input_tokens,
            "out_tokens": output_tokens,
            "session_id": state.session_id,
            "events": state.events,
        }
        if on_step:
            on_step(
                {
                    "event": "session_done",
                    "status": status,
                    "iterations": result["iterations"],
                    "cost_usd": result["cost_usd"],
                }
            )
        return result

    async def _handle_tool_use(
        self,
        tool_use: dict[str, Any],
        state: _SessionState,
        on_step: Callable[[dict[str, Any]], None] | None,
    ) -> dict[str, Any]:
        name = str(tool_use.get("name", ""))
        tool_input = tool_use.get("input") or {}
        tool_use_id = str(tool_use.get("id") or uuid.uuid4())
        state.record(event="tool_call", tool=name, input_preview=str(tool_input)[:150])
        if on_step:
            on_step({"event": "tool_call", "tool": name, "input": tool_input})

        tool = next((candidate for candidate in self._tools if candidate.name == name), None)
        if tool is None:
            result_text = f"[tool not found: {name}]"
        else:
            try:
                value = tool.callable(tool_input)
                if inspect.isawaitable(value):
                    value = await value
                result_text = _stringify_tool_result(value)
                state.record(event="tool_result", tool=name, result_preview=result_text[:200])
            except Exception as exc:
                result_text = f"[tool error: {exc}]"
                state.record(event="tool_error", tool=name, error=str(exc))

        if on_step:
            on_step({"event": "tool_result", "tool": name, "result_preview": result_text[:120]})
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": result_text,
        }


def _normalize_content(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _stringify_tool_result(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return input_tokens * 3e-6 + output_tokens * 15e-6
