"""tool_visualize_concept（services/mcp_router.py）单测——可脱离 HTTP
直测，同 tool_solve_problem 的既有约定。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from services.mcp_router import tool_visualize_concept


@pytest.mark.asyncio
async def test_service_exception_degrades_to_safe_dict_not_500():
    with patch(
        "services.visualize_service.handle_visualize_concept",
        new=AsyncMock(side_effect=ValueError("概念理解失败")),
    ):
        result = await tool_visualize_concept("随便一个概念")
    assert result["success"] is False
    assert result["error"] == "概念理解失败"


@pytest.mark.asyncio
async def test_successful_findings_passed_through_unchanged():
    fake_findings = {
        "render_type": "svg_plot",
        "restated_concept": "画出 y=x^2-4 的图像",
        "success": True,
        "svg": "<svg>...</svg>",
        "data_source": "kernel_to_plot2d",
    }
    with patch(
        "services.visualize_service.handle_visualize_concept",
        new=AsyncMock(return_value=fake_findings),
    ):
        result = await tool_visualize_concept("画出 y=x^2-4 的图像")
    assert result == fake_findings
