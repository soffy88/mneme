"""verifier — LLM-verified assessment for concept/design questions.
Produces evidence_ref required by verdict_guard for llm_verified verdicts."""
from __future__ import annotations
import uuid

class VerifyResult:
    def __init__(self, is_correct: bool, score: float, ref: str, reasoning: str):
        self.is_correct = is_correct
        self.score = score
        self.ref = ref          # evidence_ref for verdict_guard
        self.reasoning = reasoning

class Verifier:
    """Phase 1: rule-based stub. Phase 2: real LLM rubric assessment."""
    
    async def assess(self, answer: str, rubric: str, kc_name: str) -> VerifyResult:
        """Assess an open-ended answer against a rubric.
        Always produces evidence_ref (required by verdict_guard)."""
        # Phase 1: simple heuristic
        has_substance = len(answer.strip()) > 20
        mentions_topic = kc_name.lower() in answer.lower() if kc_name else True
        is_correct = has_substance and mentions_topic
        score = 1.0 if is_correct else 0.3
        
        ref = f"verifier:{uuid.uuid4().hex[:12]}"
        reasoning = (
            f"Answer length={len(answer)}, mentions_topic={mentions_topic}. "
            f"Rubric: {rubric[:100]}. Score: {score}"
        )
        
        return VerifyResult(
            is_correct=is_correct, score=score,
            ref=ref, reasoning=reasoning
        )
