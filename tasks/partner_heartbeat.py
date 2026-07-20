"""Partners 心跳推送任务（W5 A3）。

Celery beat 周期触发（同 tasks/partner_tasks.py 既有模式，不依赖 oservi 装到
worker/beat 镜像里——见 W5 决策：oservi 目前只是本机 dev 挂载
[docker-compose.override.yml]，非正式生产依赖）。evaluator/文案生成/去重过滤在
oskill.partner_dispatch 里（真实 FSRS 信号驱动，红线：Partner 不自行判定
掌握度）；真正的渠道发送 + 推送流水记录留在本文件——3O 层（oprim/oskill）不应
反向依赖 services，发送动作是服务/任务层的职责。

事件总线（W5 A2, obase.partner_bus.PartnerMessageBus）：本任务每次执行创建一个
临时 bus，把待发消息发布到 outbound 队列再消费发送——W5 v1 是单次批处理任务
（无长驻监听进程），bus 在这里是"发布即消费"的用法，为未来双向入站/长驻
Partner 进程保留一致的消息形状。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import text as sa_text

from obase.db import SessionLocal
from obase.partner_bus import OutboundMessage, PartnerMessageBus
from oskill.partner_dispatch import compute_partner_pushes
from services.partner_channels import send_via_channel

logger = logging.getLogger(__name__)


async def _run_heartbeat() -> None:
    async with SessionLocal() as db:
        pushes = await compute_partner_pushes(db)
        if not pushes:
            return

        bus = PartnerMessageBus()
        for p in pushes:
            await bus.publish_outbound(
                OutboundMessage(
                    channel=p["channel"],
                    chat_id=p["target"],
                    content=p["text"],
                    metadata={
                        "student_id": str(p["student_id"]),
                        "dedup_key": p["dedup_key"],
                        "event_type": p["event_type"],
                    },
                )
            )

        while bus.outbound_size:
            msg = await bus.consume_outbound()
            try:
                ok = await send_via_channel(msg.channel, msg.chat_id, msg.content)
            except Exception as e:  # noqa: BLE001 — 单条推送失败不影响其余学生
                logger.error(
                    f"[PartnerHeartbeat] send failed channel={msg.channel}: {e}"
                )
                continue
            if not ok:
                logger.warning(
                    f"[PartnerHeartbeat] send rejected channel={msg.channel}"
                )
                continue

            await db.execute(
                sa_text(
                    "INSERT INTO agent.partner_push_log "
                    "(student_id, channel, event_type, dedup_key, sent_at) "
                    "VALUES (:sid, :ch, :et, :dk, :sent_at)"
                ),
                {
                    "sid": msg.metadata["student_id"],
                    "ch": msg.channel,
                    "et": msg.metadata["event_type"],
                    "dk": msg.metadata["dedup_key"],
                    "sent_at": datetime.now(timezone.utc),
                },
            )
        await db.commit()


from tasks.celery_app import celery_app  # noqa: E402 循环 import：celery_app 反向 import 本模块注册任务


@celery_app.task(name="tasks.partner_heartbeat")
def partner_heartbeat() -> None:
    """运行 Partner 心跳推送。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.run_until_complete(_run_heartbeat())
