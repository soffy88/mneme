"""tool_solve_problem（services/mcp_router.py）单测——可脱离 HTTP 直测，
同 tool_list_books/tool_get_book 的既有约定。

只测"服务失败时优雅降级成安全字典，不向前端抛 500"这一层——真实求解链路
的正确性已由 tests/test_solve_problem_omodul.py 覆盖。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from services.mcp_router import tool_solve_problem


@pytest.mark.asyncio
async def test_service_exception_degrades_to_safe_dict_not_500():
    with patch(
        "services.solve_service.handle_solve_problem",
        new=AsyncMock(side_effect=ValueError("题意理解失败")),
    ):
        result = await tool_solve_problem("随便一道题")
    assert result["solvable"] is False
    assert result["error"] == "题意理解失败"
    assert result["steps"] == []
    assert result["narration"] == ""


@pytest.mark.asyncio
async def test_successful_findings_passed_through_unchanged():
    fake_findings = {
        "kernel": "function",
        "task": "zeros",
        "restated_problem": "求 x^2-4=0 的解",
        "solvable": True,
        "answer": "zeros: [-2, 2]",
        "steps": [
            {"step_number": 1, "description": "x", "expression": "x", "result": "x"}
        ],
        "error": "",
        "narration": "讲解内容",
    }
    with patch(
        "services.solve_service.handle_solve_problem",
        new=AsyncMock(return_value=fake_findings),
    ):
        result = await tool_solve_problem("求 x^2-4=0 的解")
    assert result == fake_findings
