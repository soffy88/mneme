"""活书编译任务：POST /v1/books/compile 投递，worker 里跑 omodul.book_compile。

任务体在 services/book_compile_service.run_compile_job（幂等：只认 status=queued
的占位行，acks_late 重投不会二次花钱）。
"""

from __future__ import annotations

import asyncio

from tasks.celery_app import celery_app


@celery_app.task(name="tasks.compile_book", soft_time_limit=3300, time_limit=3500)
def compile_book_task(book_id: str) -> dict:
    from services.book_compile_service import run_compile_job

    return asyncio.run(run_compile_job(book_id))
