"""visualize_service —— W4 Visualize 模式服务层。

同 services/solve_service.py 的模式：从 ProviderRegistry 取真实 LLM
caller，调 omodul.visualize_concept，把 omodul 标准返回结构转成 API
响应形状。
"""

from __future__ import annotations

from typing import Any

from obase.provider_registry import ProviderRegistry
from omodul.visualize_concept import (
    VisualizeConceptConfig,
    VisualizeConceptInput,
    visualize_concept,
)


async def handle_visualize_concept(concept_text: str) -> dict[str, Any]:
    caller = ProviderRegistry.get().llm() if ProviderRegistry._instance else None

    config = VisualizeConceptConfig()
    input_data = VisualizeConceptInput(concept_text=concept_text)

    result = await visualize_concept(
        config=config, input_data=input_data, caller=caller
    )

    if result["status"] == "failed":
        findings = result.get("findings") or {}
        raise ValueError(
            findings.get("error") or result.get("error") or "Visualize failed"
        )

    return result["findings"]
