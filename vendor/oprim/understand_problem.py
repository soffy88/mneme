"""理解问题基元。用于分析题目文本，识别题型与所需的知识点（KU）。"""

from typing import Any

async def understand_problem(problem_text: str, caller: Any) -> dict:
    prompt = f"""
请分析以下题目，识别它的题型以及解答该题所需的核心知识点（KU）。
题目：{problem_text}

请以 JSON 格式输出，包含以下字段：
- problem_type: 题型（如“代数证明题”、“几何计算题”）
- required_kus: 列表，每个元素是所需知识点的名称
- difficulty_estimate: 难度预估（0到1之间的小数）
"""
    if caller:
        try:
            res = await caller(
                messages=[{"role": "user", "content": prompt}],
                system="你是一个专业的数学老师，善于分析题目的考察意图和所需知识点。",
                response_format={"type": "json_object"}
            )
            import json
            return json.loads(res.get("content", "{}"))
        except Exception:
            pass
            
    return {
        "problem_type": "未知题型",
        "required_kus": [],
        "difficulty_estimate": 0.5
    }
