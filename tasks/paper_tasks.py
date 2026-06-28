"""D.2 — Celery task: analyze paper (assembly only, zero business logic)."""
from __future__ import annotations

import asyncio
from pathlib import Path

from tasks.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10, name="tasks.paper_tasks.process_paper")
def process_paper(self, paper_id: str) -> dict:
    """Assembly task: read DB → call omodul.analyze_paper_workflow → write results."""
    return asyncio.run(_process_paper_async(paper_id))


async def _process_paper_async(paper_id: str) -> dict:
    from obase.db import SessionLocal
    from omodul.analyze_paper import AnalyzePaperConfig, AnalyzePaperInput, analyze_paper_workflow
    from services.cognitive_service import process_interaction
    from services.models import Paper, PaperStatus, WrongQuestion
    from sqlalchemy import select, update
    import uuid as _uuid

    pid = _uuid.UUID(paper_id)

    async with SessionLocal() as db:
        paper = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one_or_none()
        if not paper:
            return {"status": "failed", "error": "paper not found"}

        image_urls = paper.image_urls or {}
        image_paths = list(image_urls.values())

        try:
            config = AnalyzePaperConfig()
            inp = AnalyzePaperInput(
                student_id=str(paper.student_id),
                image_paths=image_paths,
                subject=paper.subject or "math",
            )
            output_dir = Path(f"/tmp/mneme/papers/{paper_id}")
            result = await analyze_paper_workflow(config, inp, output_dir)

            findings = result.get("findings") or {}
            wrong_questions = findings.get("wrong_questions", [])

            # Write wrong_questions + trigger cognitive updates
            for wq_data in wrong_questions:
                kc_ids = wq_data.get("kc_ids", [])
                wq = WrongQuestion(
                    id=_uuid.uuid4(),
                    paper_id=pid,
                    student_id=paper.student_id,
                    subject=paper.subject or "math",
                    question_text=wq_data.get("question_text", ""),
                    student_answer=wq_data.get("student_answer", ""),
                    correct_answer=wq_data.get("correct_answer", ""),
                    knowledge_points={kc: 1.0 for kc in kc_ids},
                )
                db.add(wq)
                await db.flush()

                for kc_id in kc_ids:
                    await process_interaction(
                        db, paper.student_id, kc_id, is_correct=False,
                        source="paper", question_id=wq.id,
                    )

            await db.execute(
                update(Paper).where(Paper.id == pid)
                .values(status=PaperStatus.done, ocr_result=findings)
            )
            await db.commit()
            return {"status": "done", "wrong_count": len(wrong_questions)}

        except Exception as exc:
            await db.execute(update(Paper).where(Paper.id == pid).values(status=PaperStatus.failed))
            await db.commit()
            return {"status": "failed", "error": str(exc)}
