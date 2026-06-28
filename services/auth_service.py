"""
认证服务层装配
=============
协调 SMS provider + Redis 验证码存储 + 用户注册/登录。
服务层只做装配：Redis 存取、验证码校验、DB 写入、JWT 生成。
业务规则（合规红线：<14岁须监护人同意）在此层显式实现，
因为 omodul.auth 的 verify_otp 接口与 Redis 验证码机制耦合，
无法在不重建镜像的情况下透明替换。
"""
from __future__ import annotations

import logging
import os
import random
import uuid
from datetime import date, datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
from obase.auth import create_access_token
from obase.config import settings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── 常量 ─────────────────────────────────────────────────────────────────────
CODE_TTL = 300      # 验证码有效期：5分钟
RATE_TTL = 60       # 防刷窗口：60秒
MOCK_CODE = "123456"


def _is_mock() -> bool:
    return os.environ.get("SMS_PROVIDER", "mock").lower() != "aliyun"


def _redis() -> aioredis.Redis:
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


# ── SMS 存码 ─────────────────────────────────────────────────────────────────

async def send_code(phone: str, provider) -> dict:
    """
    生成验证码 → 防刷检查 → 存 Redis → 调 SMS provider 发送。
    mock 模式固定 123456，aliyun 模式随机 6 位。
    """
    r = _redis()
    try:
        rate_key = f"sms:limit:{phone}"
        if await r.get(rate_key):
            return {"ok": False, "message": "请稍后再试（60秒内只能发一条）"}

        code = MOCK_CODE if _is_mock() else str(random.randint(100000, 999999))

        await r.setex(f"sms:code:{phone}", CODE_TTL, code)
        await r.setex(rate_key, RATE_TTL, "1")

        ok = await provider.send_code(phone, code)
        if not ok:
            logger.warning(f"SMS provider返回失败 phone={phone}")
            return {"ok": False, "message": "发送失败，请稍后重试"}

        logger.info(f"SMS code sent phone={phone} provider={type(provider).__name__}")
        return {"ok": True, "message": "验证码已发送"}
    finally:
        await r.aclose()


# ── 验证码校验 ────────────────────────────────────────────────────────────────

async def verify_code(phone: str, code: str) -> bool:
    """从 Redis 校验验证码，成功则消费（删除）。
    mock 模式下 MOCK_CODE 直接通过，无需先调 send-code。
    """
    # mock 万能码旁路——仅限非 aliyun 模式，生产环境此分支永远不走
    if _is_mock() and code == MOCK_CODE:
        return True

    r = _redis()
    try:
        stored = await r.get(f"sms:code:{phone}")
        if not stored:
            return False
        if stored == code:
            await r.delete(f"sms:code:{phone}")
            return True
        return False
    finally:
        await r.aclose()


# ── 注册/登录 ─────────────────────────────────────────────────────────────────

async def register_student(
    db: AsyncSession,
    phone: str,
    code: str,
    name: str,
    birth_date: date,
    grade: str,
    guardian_phone: Optional[str] = None,
    guardian_consent: bool = False,
) -> dict:
    """
    注册学生：
    1. 验证码校验（Redis）
    2. 合规红线：<14岁须监护人同意
    3. 手机号重复检查
    4. 写 users + guardian_consents
    5. 返回 JWT token
    """
    from services.models import GuardianConsent, User, UserRole

    # 验证码
    if not await verify_code(phone, code):
        return {"error_code": 400, "error": "验证码无效或已过期"}

    # 合规：年龄
    today = datetime.now(timezone.utc).date()
    age = (today - birth_date).days // 365
    if age < 14:
        if not guardian_phone or not guardian_consent:
            return {"error_code": 422, "error": "Guardian consent required for students under 14"}

    # 手机号唯一
    existing = (await db.execute(select(User).where(User.phone == phone))).scalar_one_or_none()
    if existing:
        return {"error_code": 409, "error": "该手机号已注册"}

    user = User(
        id=uuid.uuid4(),
        phone=phone,
        name=name,
        role=UserRole.student,
        grade=grade,
        invite_code=uuid.uuid4().hex[:6].upper(),   # 供家长绑定
    )
    db.add(user)
    await db.flush()

    if age < 14 and guardian_phone:
        db.add(GuardianConsent(
            id=uuid.uuid4(),
            student_id=user.id,
            guardian_phone=guardian_phone,
            consent_type="registration",
            consent_version="1.0",
        ))
        await db.flush()

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return {
        "token": token,
        "user": {"id": str(user.id), "name": user.name, "phone": user.phone,
                 "invite_code": user.invite_code},
    }


async def register_parent(
    db: AsyncSession,
    phone: str,
    code: str,
    name: str,
    invite_code: str,
) -> dict:
    """注册家长：验证码校验 → 手机唯一 → 写 users(parent) → 凭 invite_code 绑定孩子 → JWT。"""
    from services.models import ParentStudent, User, UserRole

    if not await verify_code(phone, code):
        return {"error_code": 400, "error": "验证码无效或已过期"}

    existing = (await db.execute(select(User).where(User.phone == phone))).scalar_one_or_none()
    if existing:
        return {"error_code": 409, "error": "该手机号已注册"}

    student = (await db.execute(
        select(User).where(User.invite_code == invite_code, User.role == UserRole.student)
    )).scalar_one_or_none()
    if not student:
        return {"error_code": 404, "error": "邀请码无效"}

    parent = User(id=uuid.uuid4(), phone=phone, name=name, role=UserRole.parent)
    db.add(parent)
    await db.flush()
    db.add(ParentStudent(parent_id=parent.id, student_id=student.id))
    await db.flush()

    token = create_access_token({"sub": str(parent.id), "role": parent.role.value})
    return {
        "token": token,
        "user": {"id": str(parent.id), "name": parent.name, "phone": parent.phone},
    }


async def login(db: AsyncSession, phone: str, code: str) -> dict:
    """登录：验证码校验（Redis）→ 查用户 → 返回 JWT。"""
    from services.models import User

    if not await verify_code(phone, code):
        return {"error_code": 400, "error": "验证码无效或已过期"}

    user = (await db.execute(
        select(User).where(User.phone == phone, User.deleted_at.is_(None))
    )).scalar_one_or_none()
    if not user:
        return {"error_code": 404, "error": "用户不存在，请先注册"}

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return {
        "token": token,
        "user": {"id": str(user.id), "name": user.name},
    }
