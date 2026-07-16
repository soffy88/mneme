"""LLM adapter — Phase 1 stub. Replace with Ollama/OpenAI in production."""
from __future__ import annotations

class LlmAdapter:
    """Stub LLM for Phase 1. Generates simple questions and feedback."""
    
    async def make_question(self, kc_name: str, kc_type: str) -> dict:
        """Generate a question for the given KC. Phase 1: returns template questions."""
        if kc_type == "memory":
            return {
                "prompt": f"请回答关于【{kc_name}】的以下问题：{kc_name}的定义是什么？",
                "expected": kc_name,
                "qtype": "short"
            }
        elif kc_type == "procedure":
            return {
                "prompt": f"请完成关于【{kc_name}】的计算题：应用{kc_name}求解。",
                "expected": "正确",
                "qtype": "short"
            }
        else:  # concept/design
            return {
                "prompt": f"请用自己的话解释【{kc_name}】的核心概念。",
                "expected": "",
                "qtype": "open"
            }
    
    async def generate_feedback(self, is_correct: bool, kc_name: str) -> str:
        if is_correct:
            return f"回答正确！你对{kc_name}的理解很到位。"
        return f"这道题答错了。让我们再看看{kc_name}的关键点。"
