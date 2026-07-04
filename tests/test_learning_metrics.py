"""L0 学习层北极星四指标（架构重排）：结构 + 可算。cohort 聚合，无 PII。"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from obase.config import settings
from services.learning_metrics_service import compute_learning_metrics


@pytest.mark.asyncio
async def test_learning_metrics_shape():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as db:
        m = await compute_learning_metrics(db)
    await engine.dispose()
    # 四指标齐全
    for k in (
        "mastery_speed",
        "delayed_retention",
        "calibration_overconfidence",
        "transfer_rate",
    ):
        assert k in m
    # 迁移探针题池已建（U.18），但本次聚合口径下暂无 transfer_probe 事件 → None + 说明
    assert m["transfer_rate"] is None and "转移" not in m  # 有 note
    assert "transfer_note" in m
    # 数值型或 None（不编数）
    for k in ("mastery_speed", "delayed_retention", "calibration_overconfidence"):
        assert m[k] is None or isinstance(m[k], (int, float))
    # 计数字段
    assert isinstance(m["delayed_retention_n"], int)
    assert isinstance(m["calibration_n"], int)
    assert isinstance(m["mastery_speed_detail"]["mastered_ku"], int)
