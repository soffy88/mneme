"""start_session 回归：中途提交不得导致 MissingGreenlet；元认知超时不得拖垮 start。

背景（2026-10-27 生产故障）：
- 无缓存画像时 generate_learner_profile 末尾 await db.commit()，默认
  expire_on_commit=True 会过期会话上 wq 的全部属性；随后访问
  wq.question_text 触发懒加载刷新 → sqlalchemy.exc.MissingGreenlet。
- 元认知支架是可选 LLM 调用，原代码无超时上限，LLM 挂起会把整个
  start 请求拖到客户端超时（90–120 秒），且服务端不记新错误。

本文件刻意用 expire_on_commit=True 的生产形态会话（旧 end_session
夹具用 False，会掩盖此类 bug），并用桩复现“中途提交”这一生产机制。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from services import socratic_service as soc
from services.models import SocraticSession, User, UserRole, WrongQuestion
from services.socratic_service import start_session


@pytest.fixture()
async def db_student_wq():
    # 生产形态：expire_on_commit=True（默认），中途 commit 会过期实例属性。
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=True)

    async with factory() as db:
        student_id = uuid.uuid4()
        user = User(id=student_id, phone=f"1{str(student_id.int)[:10]}", role=UserRole.student)
        db.add(user)
        wq_id = uuid.uuid4()
        wq = WrongQuestion(
            id=wq_id,
            student_id=student_id,
            question_text="解方程 x+1=3，求 x。",
            subject="math",
            knowledge_points={},
        )
        db.add(wq)
        await db.commit()

        yield db, student_id, wq_id

        await db.execute(delete(SocraticSession).where(SocraticSession.student_id == student_id))
        await db.execute(delete(WrongQuestion).where(WrongQuestion.id == wq_id))
        await db.execute(delete(User).where(User.id == student_id))
        await db.commit()
    await engine.dispose()


async def _fast_workflow(*args, **kwargs):
    return {}


async def _fast_metacog(*args, **kwargs):
    return SimpleNamespace(self_eval={"options": []})


async def _committing_profile(db, student_id):
    # 复现生产机制：无缓存画像时 generate_learner_profile 末尾提交会话。
    await db.commit()
    return "画像（测试桩）"


@pytest.mark.asyncio
async def test_start_survives_mid_function_commit(db_student_wq, monkeypatch):
    """中途 commit 过期 wq 属性后，start 仍成功（快照保护），不报 MissingGreenlet。"""
    db, student_id, wq_id = db_student_wq
    monkeypatch.setattr(soc, "metacog_scaffold", _fast_metacog)
    monkeypatch.setattr(soc, "socratic_session_workflow", _fast_workflow)
    monkeypatch.setattr(
        "oprim.learner_profile_summary.get_latest_learner_profile", _committing_profile
    )

    result = await start_session(db, wq_id, student_id)

    assert "session_id" in result
    assert "解方程" in result["first_question"]
    assert result["mode"] in ("deep", "mixed")


@pytest.mark.asyncio
async def test_metacog_timeout_falls_back_to_deterministic_first_question(
    db_student_wq, monkeypatch
):
    """元认知 LLM 挂起时，start 应在上限内返回确定性锚定首问，而不是跟着挂起。"""

    async def _hanging_metacog(*args, **kwargs):
        await asyncio.sleep(60)
        return SimpleNamespace(self_eval={"options": []})

    db, student_id, wq_id = db_student_wq
    monkeypatch.setattr(soc, "metacog_scaffold", _hanging_metacog)
    monkeypatch.setattr(soc, "socratic_session_workflow", _fast_workflow)
    monkeypatch.setattr(soc, "METACOG_TIMEOUT_S", 1)
    monkeypatch.setattr(
        "oprim.learner_profile_summary.get_latest_learner_profile",
        lambda db, sid: asyncio.sleep(0, result="画像（测试桩）"),
    )

    t0 = time.monotonic()
    result = await start_session(db, wq_id, student_id)
    elapsed = time.monotonic() - t0

    assert elapsed < 30
    assert "session_id" in result
    assert "我们来看这道题" in result["first_question"]
    assert result["metacog_options"] == []
