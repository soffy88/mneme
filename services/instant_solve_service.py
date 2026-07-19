from uuid import UUID
import uuid
from typing import Optional
from obase.config import settings
from obase.persistence.pool import PgPool
from omodul.instant_solve import InstantSolveConfig, InstantSolveInput, instant_solve
from obase.provider_registry import ProviderRegistry


async def get_pg_pool() -> PgPool:
    dsn = settings.DATABASE_URL.replace("+asyncpg", "")
    return await PgPool.get_or_create(dsn=dsn)


async def handle_instant_solve(
    student_id: UUID, image_b64: str, kc_hint: Optional[str] = None
) -> dict:
    pool = await get_pg_pool()
    caller = ProviderRegistry.get().llm() if ProviderRegistry._instance else None

    config = InstantSolveConfig()
    input_data = InstantSolveInput(
        student_id=student_id, input_type="image", content=image_b64
    )

    result = await instant_solve(
        config=config, input_data=input_data, caller=caller, pool=pool
    )

    if result["status"] == "failed":
        raise ValueError(result.get("error", "Instant solve failed"))

    findings = result.get("findings", {})

    session_id = None
    for event in result.get("decision_trail", []):
        if event.get("event") == "session_started":
            session_id = event.get("session_id")

    metacog = findings.get("metacog", {})
    first_question = metacog.get("question", "需要什么帮助？")

    return {
        "session_id": session_id or str(uuid.uuid4()),
        "first_question": first_question,
        "ku_id": kc_hint or "unknown",
        "recognized_text": findings.get("recognized_text"),
        "options": metacog.get("options", []),
    }

async def handle_deep_solve(problem_text: str) -> dict:
    """深度研究 (Deep Solve): 执行多步推理解题路线图。"""
    from vendor.omodul.deep_solve_workflow import deep_solve_workflow, DeepSolveConfig, DeepSolveInput
    caller = ProviderRegistry.get().llm() if ProviderRegistry._instance else None

    config = DeepSolveConfig()
    input_data = DeepSolveInput(problem_text=problem_text)

    result = await deep_solve_workflow(
        config=config, input_data=input_data, caller=caller
    )

    if result["status"] == "failed":
        raise ValueError(result.get("error", "Deep solve failed"))

    findings = result.get("findings", {})
    return {
        "analysis": findings.get("analysis", {}),
        "method_template": findings.get("method_template", ""),
        "roadmap": findings.get("roadmap", "")
    }
