"""solve_service —— W4 Solve 模式服务层。

同 services/instant_solve_service.py 的 handle_deep_solve() 模式：从
ProviderRegistry 取真实 LLM caller，调 omodul.solve_problem，把 omodul
标准返回结构（findings/status/error/decision_trail）转成 API 响应形状。
"""

from __future__ import annotations

from typing import Any

from obase.provider_registry import ProviderRegistry
from omodul.solve_problem import SolveProblemConfig, SolveProblemInput, solve_problem


async def handle_solve_problem(problem_text: str) -> dict[str, Any]:
    caller = ProviderRegistry.get().llm() if ProviderRegistry._instance else None

    config = SolveProblemConfig()
    input_data = SolveProblemInput(problem_text=problem_text)

    result = await solve_problem(config=config, input_data=input_data, caller=caller)

    if result["status"] == "failed":
        findings = result.get("findings") or {}
        raise ValueError(findings.get("error") or result.get("error") or "Solve failed")

    return result["findings"]
