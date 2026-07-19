"""检索解法基元。用于根据题型和知识点检索解题模板或思路。"""

from typing import Any, List

async def retrieve_method(problem_type: str, required_kus: List[str], caller: Any) -> str:
    # 理论上这里可以查询本地的解题方法向量库，这里简化为由 LLM 生成/回忆解题模板
    kus_str = ", ".join(required_kus)
    prompt = f"""
请针对题型【{problem_type}】，涉及知识点【{kus_str}】，
总结出标准的通用解题步骤（解法模板），不要给出针对特定题目的具体数字解答。
"""
    if caller:
        try:
            res = await caller(
                messages=[{"role": "user", "content": prompt}],
                system="你是一个数学方法学专家，专门总结解题的通用步骤框架。"
            )
            return res.get("content", "暂无通用解法框架。")
        except Exception:
            pass
            
    return "1. 阅读并理解题目条件；\n2. 根据知识点列出方程式或几何关系；\n3. 求解并验证结果。"
