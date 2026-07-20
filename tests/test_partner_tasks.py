"""tasks.partner_tasks 崩溃修复回归测试。

背景：Celery beat 每天 17:30 跑 daily-partner-push，`_check_and_notify_students`
一直在真实 User 行上崩——`student.last_login`（User 模型压根没有这个字段，
全仓也没有任何登录时间戳追踪机制，不是重命名问题）、`student.username`
（模型上只有 `.name`）。当前只是被 EMAIL_PROVIDER=mock 掩盖了才没有更严重的
连带影响。这里核心断言：函数在真实 User 行上跑完整流程不再抛
AttributeError，且通知内容正确落到 `.name`。

用真实 DB（同 tests/test_authz.py 的 fixture 写法）而不是 mock db.execute——
insert 精确构造出"该被提醒"和"不该被提醒"的学生，跑完整查询+分支逻辑，
比 mock 掉 SQLAlchemy 调用更能验证真实回归。email provider 用假实现拦截，
不依赖当前环境 EMAIL_PROVIDER 配置，确保测试本身永远不会真的发信。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from services.models import User, UserRole, WrongQuestion


class _FakeEmailProvider:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send_code(self, email: str, code: str) -> bool:
        raise NotImplementedError

    async def send_notification(self, email: str, title: str, content: str) -> bool:
        self.sent.append((email, title, content))
        return True


@pytest.fixture(scope="function")
async def db():
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture(scope="function")
async def students(db):
    """三个学生：① 注册已久、无 name（该收"好几天没来"提醒 + 同学兜底）；
    ② 刚注册但有 10+ 道 FSRS 到期错题（该收"待复习"提醒）；③ 刚注册且无到期
    错题（不该收到任何提醒）——覆盖 partner_push 的两条分支 + 一条负向对照。
    """
    now = datetime.now(timezone.utc)
    stale_id, due_id, quiet_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    db.add(
        User(
            id=stale_id,
            email=f"stale-{stale_id.hex[:8]}@test.mneme.invalid",
            role=UserRole.student,
            name=None,
            created_at=now - timedelta(days=10),
        )
    )
    db.add(
        User(
            id=due_id,
            email=f"due-{due_id.hex[:8]}@test.mneme.invalid",
            role=UserRole.student,
            name="学生due",
            created_at=now,
        )
    )
    db.add(
        User(
            id=quiet_id,
            email=f"quiet-{quiet_id.hex[:8]}@test.mneme.invalid",
            role=UserRole.student,
            name="学生quiet",
            created_at=now,
        )
    )
    await db.flush()

    for i in range(11):
        db.add(
            WrongQuestion(
                student_id=due_id,
                fsrs_due=now - timedelta(hours=1),
                fsrs_state="review",
            )
        )
    await db.commit()

    yield {"stale": stale_id, "due": due_id, "quiet": quiet_id}

    await db.execute(delete(WrongQuestion).where(WrongQuestion.student_id == due_id))
    await db.execute(delete(User).where(User.id.in_([stale_id, due_id, quiet_id])))
    await db.commit()


@pytest.mark.asyncio
async def test_check_and_notify_does_not_crash_on_real_user_rows(students):
    """核心回归：不再因 last_login/username 不存在而 AttributeError。"""
    from tasks.partner_tasks import _check_and_notify_students

    fake_provider = _FakeEmailProvider()
    with patch("tasks.partner_tasks.get_email_provider", return_value=fake_provider):
        await _check_and_notify_students()  # 不应该抛异常


@pytest.mark.asyncio
async def test_stale_student_gets_inactivity_reminder_with_name_fallback(students):
    from tasks.partner_tasks import _check_and_notify_students

    fake_provider = _FakeEmailProvider()
    with patch("tasks.partner_tasks.get_email_provider", return_value=fake_provider):
        await _check_and_notify_students()

    stale_email = f"stale-{students['stale'].hex[:8]}@test.mneme.invalid"
    matches = [s for s in fake_provider.sent if s[0] == stale_email]
    assert len(matches) == 1
    _, title, content = matches[0]
    assert "好几天没来" in title
    assert "同学" in content  # name=None 应该落到"同学"兜底，不是 None/报错


@pytest.mark.asyncio
async def test_due_review_student_gets_review_reminder_with_real_name(students):
    from tasks.partner_tasks import _check_and_notify_students

    fake_provider = _FakeEmailProvider()
    with patch("tasks.partner_tasks.get_email_provider", return_value=fake_provider):
        await _check_and_notify_students()

    due_email = f"due-{students['due'].hex[:8]}@test.mneme.invalid"
    matches = [s for s in fake_provider.sent if s[0] == due_email]
    assert len(matches) == 1
    _, title, content = matches[0]
    assert "待复习" in title
    assert "学生due" in content


@pytest.mark.asyncio
async def test_quiet_student_gets_no_notification(students):
    from tasks.partner_tasks import _check_and_notify_students

    fake_provider = _FakeEmailProvider()
    with patch("tasks.partner_tasks.get_email_provider", return_value=fake_provider):
        await _check_and_notify_students()

    quiet_email = f"quiet-{students['quiet'].hex[:8]}@test.mneme.invalid"
    assert not any(s[0] == quiet_email for s in fake_provider.sent)
