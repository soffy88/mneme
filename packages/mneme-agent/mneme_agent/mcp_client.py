"""MCP client — agent's ONLY interface to core. Never imports mneme_core directly."""
from __future__ import annotations
import httpx
from typing import Optional

class McpClient:
    def __init__(self, base_url: str = "http://localhost:8100"):
        self.base_url = base_url
        self._client = httpx.AsyncClient(base_url=base_url, timeout=30.0)
    
    async def check_mastery(self, student_id: str, kc_id: str) -> dict:
        r = await self._client.post("/mcp/CheckMastery", json={"student_id": student_id, "kc_id": kc_id})
        r.raise_for_status()
        return r.json()
    
    async def get_next_objective(self, student_id: str, now: float | None = None) -> dict:
        r = await self._client.post("/mcp/GetNextObjective", json={"student_id": student_id, "now": now})
        r.raise_for_status()
        return r.json()
    
    async def get_review_queue(self, student_id: str, now: float | None = None) -> dict:
        r = await self._client.post("/mcp/GetReviewQueue", json={"student_id": student_id, "now": now})
        r.raise_for_status()
        return r.json()
    
    async def get_kc_info(self, kc_id: str) -> dict:
        r = await self._client.post("/mcp/GetKCInfo", json={"kc_id": kc_id})
        r.raise_for_status()
        return r.json()
    
    async def report_result(
        self, student_id: str, kc_id: str, question_id: str,
        is_correct: bool, verdict_source: str,
        evidence_ref: str | None = None,
        response_time_ms: int = 0, confidence: float = 0.5
    ) -> dict:
        r = await self._client.post("/mcp/ReportResult", json={
            "student_id": student_id, "kc_id": kc_id,
            "question_id": question_id, "is_correct": is_correct,
            "verdict_source": verdict_source, "evidence_ref": evidence_ref,
            "response_time_ms": response_time_ms, "confidence": confidence
        })
        r.raise_for_status()
        return r.json()
    
    async def setup_student(self, student_id: str, modules: list[dict]) -> dict:
        r = await self._client.post("/mcp/SetupStudent", json={"student_id": student_id, "modules": modules})
        r.raise_for_status()
        return r.json()
    
    async def close(self):
        await self._client.aclose()
