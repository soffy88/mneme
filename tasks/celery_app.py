"""Celery application factory."""
from celery import Celery
from celery.signals import worker_process_init
from obase.config import settings

celery_app = Celery(
    "mneme",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["tasks.paper_tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
)


@worker_process_init.connect
def _register_providers(**_kwargs):
    """worker 进程不跑 FastAPI lifespan，需自行注册 LLM/VLM provider，否则 OCR 无 VLM。"""
    from obase.llm import register_default_providers
    register_default_providers()
