"""主动家教（Partners）推送任务。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func

from obase.db import SessionLocal
from services.models import User, WrongQuestion
from services.email.factory import get_email_provider

logger = logging.getLogger(__name__)


async def _check_and_notify_students() -> None:
    now = datetime.now(timezone.utc)
    email_provider = get_email_provider()

    async with SessionLocal() as db:
        # 获取所有绑定了邮箱的学生
        students = (
            (
                await db.execute(
                    select(User).where(
                        User.role == "student", User.email.isnot(None), User.email != ""
                    )
                )
            )
            .scalars()
            .all()
        )

        for student in students:
            # 查询已过滤 email 非空非空串（见上面 select），这里断言仅为帮
            # mypy 收窄 Optional[str] → str，不改变运行时行为。
            assert student.email
            # 1. 检查连续未登录 (3天)
            # 注：User 模型没有 last_login 字段，全仓没有任何登录时间戳追踪机制
            # （不是重命名问题，是从未实现）——这里退化为"距注册已过 3 天"，
            # 不是真正的"距上次登录"。真正的登录时间戳需要新增列
            # + migration + 在登录路径写入，超出本次崩溃修复范围。
            if (now - student.created_at) > timedelta(days=3):
                title = "【善学记】家教助理提醒：你已经好几天没来学习啦"
                content = f"你好，{student.name or '同学'}：\n\n助理发现你已经连续3天没有登录善学记了。学习需要持之以恒，快来看看为你准备的今日计划吧！"
                await email_provider.send_notification(student.email, title, content)
                continue  # 一天最多一条提醒，避免轰炸

            # 2. 检查 FSRS 到期卡片数量
            due_count = (
                await db.execute(
                    select(func.count(WrongQuestion.id)).where(
                        WrongQuestion.student_id == student.id,
                        WrongQuestion.fsrs_due <= now,
                        WrongQuestion.fsrs_state.in_(
                            ["learning", "review", "relearning"]
                        ),
                    )
                )
            ).scalar_one_or_none() or 0

            if due_count > 10:
                title = "【善学记】家教助理提醒：有待复习的错题"
                content = f"你好，{student.name or '同学'}：\n\n根据记忆曲线，你有 {due_count} 道错题到了最佳的复习时间。趁热打铁，花几分钟清空复习队列，让短期记忆转化为长期记忆吧！"
                await email_provider.send_notification(student.email, title, content)
                continue

            # 3. 如果需要，可以添加 P(L) 下降的检查等


from tasks.celery_app import celery_app  # noqa: E402 循环 import：celery_app 反向 import 本模块注册任务


@celery_app.task(name="tasks.partner_push")
def partner_push() -> None:
    """运行主动推送任务。通常每天下午或者傍晚执行。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.run_until_complete(_check_and_notify_students())
