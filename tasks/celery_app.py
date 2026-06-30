"""Celery application factory."""
from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init
from obase.config import settings

celery_app = Celery(
    "mneme",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["tasks.paper_tasks", "tasks.calibration_tasks", "tasks.textbook_tasks",
             "tasks.fsrs_optimize_tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    # item 5：数据飞轮——每日 03:30 从累积作答校准 BKT 先验。
    beat_schedule={
        "daily-bkt-calibration": {
            "task": "tasks.calibrate_bkt_priors",
            "schedule": crontab(hour=3, minute=30),
        },
        # 每周一 04:00 从复习日志优化 FSRS 权重（个性化调度基础设施）。
        "weekly-fsrs-optimize": {
            "task": "tasks.optimize_fsrs_weights",
            "schedule": crontab(hour=4, minute=0, day_of_week=1),
        },
    },
)


@worker_process_init.connect
def _register_providers(**_kwargs):
    """worker 进程不跑 FastAPI lifespan，需自行注册 LLM/VLM provider，否则 OCR 无 VLM。"""
    from obase.llm import register_default_providers
    register_default_providers()
