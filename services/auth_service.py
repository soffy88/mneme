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
from datetime import date

import redis.asyncio as aioredis
from obase.auth import create_access_token
from obase.config import settings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── 常量 ─────────────────────────────────────────────────────────────────────
CODE_TTL = 300  # 验证码有效期：5分钟
RATE_TTL = 60  # 防刷窗口：60秒
MOCK_CODE = "123456"
MAX_VERIFY_ATTEMPTS = 5  # 验证码连续输错次数上限
VERIFY_LOCKOUT_SECONDS = 900  # 超限后锁定时长：15分钟


def _is_mock() -> bool:
    return os.environ.get("SMS_PROVIDER", "mock").lower() != "aliyun"


def _mock_bypass_allowed() -> bool:
    """mock 万能码旁路仅在非生产环境可用（MNEME_ENV != prod）。

    生产即使 SMS_PROVIDER 误配为 mock，万能码 123456 也不得放行——
    否则任何人可登录任何已知账号（C2 修复：demo/dev 保留演示机制，
    生产必须走真实验证通道，main._assert_prod_safety 同时把关）。"""
    return os.environ.get("MNEME_ENV", "dev").lower() != "prod"


def _mask_phone(phone: str) -> str:
    """日志脱敏：138****1234，不在日志里落完整手机号（PII）。"""
    if len(phone) != 11:
        return "***"
    return f"{phone[:3]}****{phone[-4:]}"


def _mask_email(email: str) -> str:
    """日志脱敏：a***@example.com。"""
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    return f"{local[:1]}***@{domain}"


def _is_email_mock() -> bool:
    """邮箱验证码 mock 旁路仅在非 smtp 模式生效（同 SMS：生产设 EMAIL_PROVIDER=smtp 关闭）。"""
    return os.environ.get("EMAIL_PROVIDER", "mock").lower() != "smtp"


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
            logger.warning(f"SMS provider返回失败 phone={_mask_phone(phone)}")
            return {"ok": False, "message": "发送失败，请稍后重试"}

        logger.info(
            f"SMS code sent phone={_mask_phone(phone)} provider={type(provider).__name__}"
        )
        return {"ok": True, "message": "验证码已发送"}
    finally:
        await r.aclose()


# ── 验证码校验 ────────────────────────────────────────────────────────────────


async def _check_lockout(r, lock_key: str) -> bool:
    """是否已被暴力尝试锁死。"""
    return await r.get(lock_key) is not None


async def _register_failure(r, attempt_key: str, lock_key: str) -> None:
    """验证码连续输错：计数，超限即锁定至验证码过期（C2 防暴力破解）。"""
    attempts = await r.incr(attempt_key)
    await r.expire(attempt_key, CODE_TTL)
    if attempts >= MAX_VERIFY_ATTEMPTS:
        await r.setex(lock_key, VERIFY_LOCKOUT_SECONDS, "1")
        await r.delete(attempt_key)
        logger.warning(f"验证码连续输错 {MAX_VERIFY_ATTEMPTS} 次，已锁定验证码通道")


async def verify_code(phone: str, code: str) -> bool:
    """从 Redis 校验验证码，成功则消费（删除）。
    mock 万能码旁路——仅 demo/dev 环境可用（C2：生产 MNEME_ENV=prod 拒放行）。
    连续输错 MAX_VERIFY_ATTEMPTS 次 → 锁定 VERIFY_LOCKOUT_SECONDS 秒（防暴力破解）。
    """
    r = _redis()
    try:
        lock_key = f"sms:lock:{phone}"
        if await _check_lockout(r, lock_key):
            return False

        # mock 万能码旁路——仅限非 aliyun 模式且非生产环境
        if _is_mock() and _mock_bypass_allowed() and code == MOCK_CODE:
            return True

        stored = await r.get(f"sms:code:{phone}")
        if not stored:
            return False
        if stored == code:
            await r.delete(f"sms:code:{phone}")
            await r.delete(f"sms:attempt:{phone}")
            return True
        await _register_failure(r, f"sms:attempt:{phone}", lock_key)
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
    guardian_phone: str | None = None,
    guardian_consent: bool = False,
    ip_address: str | None = None,
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

    # 合规：年龄。用单源日历算法（privacy._age），不用 //365——后者会少算几天，
    # 生日前几天的 13 岁会被当成 14 岁，绕过监护同意闸门（合规红线，宁可算小不算大）。
    from services.privacy import _age

    age = _age(birth_date)
    if age is not None and age < 14:
        if not guardian_phone or not guardian_consent:
            return {
                "error_code": 422,
                "error": "Guardian consent required for students under 14",
            }

    # 手机号唯一
    existing = (
        await db.execute(select(User).where(User.phone == phone))
    ).scalar_one_or_none()
    if existing:
        return {"error_code": 409, "error": "该手机号已注册"}

    user = User(
        id=uuid.uuid4(),
        phone=phone,
        name=name,
        role=UserRole.student,
        grade=grade,
        invite_code=uuid.uuid4().hex[:6].upper(),  # 供家长绑定
    )
    db.add(user)
    await db.flush()

    if age is not None and age < 14 and guardian_phone:
        db.add(
            GuardianConsent(
                id=uuid.uuid4(),
                student_id=user.id,
                guardian_phone=guardian_phone,
                consent_type="registration",
                consent_version="1.0",
                ip_address=ip_address,
            )
        )
        await db.flush()

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return {
        "token": token,
        "user": {
            "id": str(user.id),
            "name": user.name,
            "phone": user.phone,
            "invite_code": user.invite_code,
        },
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

    existing = (
        await db.execute(select(User).where(User.phone == phone))
    ).scalar_one_or_none()
    if existing:
        return {"error_code": 409, "error": "该手机号已注册"}

    student = (
        await db.execute(
            select(User).where(
                User.invite_code == invite_code, User.role == UserRole.student
            )
        )
    ).scalar_one_or_none()
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

    user = (
        await db.execute(
            select(User).where(User.phone == phone, User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if not user:
        return {"error_code": 404, "error": "用户不存在，请先注册"}

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return {
        "token": token,
        "user": {"id": str(user.id), "name": user.name},
    }


# ── 邮箱注册/登录（新主标识；手机号流程完整保留向后兼容）──────────────────────


async def send_email_code(email: str, provider) -> dict:
    """发送邮箱验证码，存 Redis TTL=5min，60s 防刷。渠道走 email provider（可插拔）。"""
    r = _redis()
    try:
        rate_key = f"email:limit:{email}"
        if await r.get(rate_key):
            return {"ok": False, "message": "请稍后再试（60秒内只能发一条）"}

        code = MOCK_CODE if _is_email_mock() else str(random.randint(100000, 999999))
        await r.setex(f"email:code:{email}", CODE_TTL, code)
        await r.setex(rate_key, RATE_TTL, "1")

        ok = await provider.send_code(email, code)
        if not ok:
            logger.warning(f"Email provider 返回失败 to={_mask_email(email)}")
            return {"ok": False, "message": "发送失败，请稍后重试"}

        logger.info(
            f"Email code sent to={_mask_email(email)} provider={type(provider).__name__}"
        )
        return {"ok": True, "message": "验证码已发送"}
    finally:
        await r.aclose()


async def verify_email_code(email: str, code: str) -> bool:
    """从 Redis 校验邮箱验证码，成功则消费。
    mock 模式 MOCK_CODE 旁路——仅 demo/dev 可用（C2：生产 MNEME_ENV=prod 拒放行）。
    连续输错 MAX_VERIFY_ATTEMPTS 次 → 锁定 VERIFY_LOCKOUT_SECONDS 秒（防暴力破解）。
    """
    r = _redis()
    try:
        lock_key = f"email:lock:{email}"
        if await _check_lockout(r, lock_key):
            return False

        if _is_email_mock() and _mock_bypass_allowed() and code == MOCK_CODE:
            return True

        stored = await r.get(f"email:code:{email}")
        if not stored:
            return False
        if stored == code:
            await r.delete(f"email:code:{email}")
            await r.delete(f"email:attempt:{email}")
            return True
        await _register_failure(r, f"email:attempt:{email}", lock_key)
        return False
    finally:
        await r.aclose()


async def register_student_email(
    db: AsyncSession,
    email: str,
    code: str,
    name: str,
    birth_date: date,
    grade: str,
    guardian_email: str | None = None,
    guardian_consent: bool = False,
    ip_address: str | None = None,
) -> dict:
    """邮箱注册学生：验证码校验 + 合规红线(<14须监护同意) + 邮箱唯一 + 写库 + JWT。
    与手机号版同构，仅标识换成 email、监护联系方式换成 guardian_email。"""
    from services.models import GuardianConsent, User, UserRole

    if not await verify_email_code(email, code):
        return {"error_code": 400, "error": "验证码无效或已过期"}

    # 合规：年龄（单源 privacy._age，不用 //365）
    from services.privacy import _age

    age = _age(birth_date)
    if age is not None and age < 14:
        if not guardian_email or not guardian_consent:
            return {
                "error_code": 422,
                "error": "Guardian consent required for students under 14",
            }

    existing = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing:
        return {"error_code": 409, "error": "该邮箱已注册"}

    user = User(
        id=uuid.uuid4(),
        email=email,
        name=name,
        role=UserRole.student,
        grade=grade,
        invite_code=uuid.uuid4().hex[:6].upper(),
    )
    db.add(user)
    await db.flush()

    if age is not None and age < 14 and guardian_email:
        db.add(
            GuardianConsent(
                id=uuid.uuid4(),
                student_id=user.id,
                guardian_email=guardian_email,
                consent_type="registration",
                consent_version="1.0",
                ip_address=ip_address,
            )
        )
        await db.flush()

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return {
        "token": token,
        "user": {
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "invite_code": user.invite_code,
        },
    }


async def register_parent_email(
    db: AsyncSession,
    email: str,
    code: str,
    name: str,
    invite_code: str,
) -> dict:
    """邮箱注册家长：验证码校验 → 邮箱唯一 → 凭 invite_code 绑定孩子 → JWT。"""
    from services.models import ParentStudent, User, UserRole

    if not await verify_email_code(email, code):
        return {"error_code": 400, "error": "验证码无效或已过期"}

    existing = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing:
        return {"error_code": 409, "error": "该邮箱已注册"}

    student = (
        await db.execute(
            select(User).where(
                User.invite_code == invite_code, User.role == UserRole.student
            )
        )
    ).scalar_one_or_none()
    if not student:
        return {"error_code": 404, "error": "邀请码无效"}

    parent = User(id=uuid.uuid4(), email=email, name=name, role=UserRole.parent)
    db.add(parent)
    await db.flush()
    db.add(ParentStudent(parent_id=parent.id, student_id=student.id))
    await db.flush()

    token = create_access_token({"sub": str(parent.id), "role": parent.role.value})
    return {
        "token": token,
        "user": {"id": str(parent.id), "name": parent.name, "email": parent.email},
    }


async def login_email(db: AsyncSession, email: str, code: str) -> dict:
    """邮箱登录：验证码校验 → 查用户 → JWT。"""
    from services.models import User

    if not await verify_email_code(email, code):
        return {"error_code": 400, "error": "验证码无效或已过期"}

    user = (
        await db.execute(
            select(User).where(User.email == email, User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if not user:
        return {"error_code": 404, "error": "用户不存在，请先注册"}

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return {"token": token, "user": {"id": str(user.id), "name": user.name}}
