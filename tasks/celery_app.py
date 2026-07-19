"""Celery application factory."""

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init
from obase.config import settings

celery_app = Celery(
    "mneme",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "tasks.paper_tasks",
        "tasks.calibration_tasks",
        "tasks.textbook_tasks",
        "tasks.fsrs_optimize_tasks",
        "tasks.evaluation_tasks",
        "tasks.alert_tasks",
        "tasks.purge_tasks",
        "tasks.partner_tasks",
        "tasks.memory_tasks",
    ],
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
        # 每周一 05:00 评估护城河：KT/FSRS 对真实作答的预测 AUC（实证监控）。
        "weekly-moat-eval": {
            "task": "tasks.evaluate_moat",
            "schedule": crontab(hour=5, minute=0, day_of_week=1),
        },
        # 每日 20:00 对全部家长-学生绑定跑 5 类预警检查（G.2 定时化，原仅手动触发）。
        "daily-parent-alerts": {
            "task": "tasks.run_parent_alert_checks",
            "schedule": crontab(hour=20, minute=0),
        },
        # 每日 04:30 合规硬删：物理清除软删超宽限期(RETENTION_HARD_DELETE_DAYS)的用户及全部 PII。
        "daily-purge-deleted-users": {
            "task": "tasks.purge_deleted_users",
            "schedule": crontab(hour=4, minute=30),
        },
        # 每日 17:30 运行主动家教推送：检查连续未登录、复习积压等情况发送邮件
        "daily-partner-push": {
            "task": "tasks.partner_push",
            "schedule": crontab(hour=17, minute=30),
        },
        # 每日 04:00 清理过期的 agent.working_memory（C5：working-memory 短期上下文
        # 只按 expires_at 惰性判断可读性，仍需定期物理清理，避免无限增长）。
        "daily-cleanup-expired-working-memory": {
            "task": "tasks.cleanup_expired_working_memory",
            "schedule": crontab(hour=4, minute=0),
        },
    },
)


@worker_process_init.connect
def _register_providers(**_kwargs):
    """worker 进程不跑 FastAPI lifespan，需自行注册 LLM/VLM provider，否则 OCR 无 VLM。

    审计 P0-4：与 API lifespan 共用同一装配函数，确保 MNEME_LLM=ollama 覆盖也在 worker 生效
    （此前 worker 只调 register_default_providers → 用死 DeepSeek key，异步链跑不通）。
    """
    from services.providers.setup import configure_llm_providers

    configure_llm_providers()
