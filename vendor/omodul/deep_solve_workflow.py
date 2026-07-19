"""深度研究（Deep Solve）多步推理解题流程。"""
from __future__ import annotations

import asyncio
from typing import ClassVar, Any
from pydantic import BaseModel

from omodul.base import BaseConfig, standard_return
from oprim.understand_problem import understand_problem
from oprim.retrieve_method import retrieve_method

class DeepSolveConfig(BaseConfig):
    _omodul_name: ClassVar[str] = "deep_solve"
    _omodul_version: ClassVar[str] = "0.1.0"
    _enabled_pillars: ClassVar[set] = {"decision_trail"}

class DeepSolveInput(BaseModel):
    problem_text: str

async def deep_solve_workflow(
    config: DeepSolveConfig,
    input_data: DeepSolveInput,
    *,
    caller: Any
) -> dict:
    """执行多步推理，给出解题路线图。"""
    trail = []
    
    try:
        # Step 1: Understand Problem
        analysis = await understand_problem(input_data.problem_text, caller)
        trail.append({"step": "understand_problem", "result": analysis})
        
        problem_type = analysis.get("problem_type", "未知题型")
        required_kus = analysis.get("required_kus", [])
        
        # Step 2: Retrieve Method Template
        method_template = await retrieve_method(problem_type, required_kus, caller)
        trail.append({"step": "retrieve_method", "template": method_template})
        
        # Step 3: Generate Solution Roadmap (using LLM)
        prompt = f"""
你正在为一个学生提供“解题路线图”。注意：【绝对不要】直接给出答案和具体的最终计算结果。你的目标是提供一个思维脚手架，让学生自己填补关键信息。

【原题】：
{input_data.problem_text}

【问题分析】：
题型：{problem_type}
所需知识点：{", ".join(required_kus)}

【通用解法模板参考】：
{method_template}

请结合上面的题意和模板，输出这道题的具体解题路线图，分步骤说明，并在每一步指出“你需要自己计算的内容”或“提示”。
"""
        roadmap_content = "暂无法生成路线图"
        if caller:
            res = await caller(
                messages=[{"role": "user", "content": prompt}],
                system="你是一个不会泄露答案，只会给路线图的严格家教助手。"
            )
            roadmap_content = res.get("content", roadmap_content)
            
        trail.append({"step": "generate_roadmap", "status": "completed"})
        
        return standard_return(
            findings={
                "analysis": analysis,
                "method_template": method_template,
                "roadmap": roadmap_content
            },
            status="success",
            trail=trail
        )
    except Exception as e:
        trail.append({"event": "error", "message": str(e)})
        return standard_return(
            findings=None,
            status="failed",
            error=str(e),
            trail=trail
        )
