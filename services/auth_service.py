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
import re
import uuid
from datetime import UTC, date, datetime

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

# 密码登录的独立配额：密码没有 TTL 可依附，所以按 IP+账号双维度计数。
# 比验证码更严格——验证码输错只锁验证码通道，密码输错直接锁登录。
PASSWORD_MAX_ATTEMPTS = 5
PASSWORD_LOCKOUT_SECONDS = 900
PASSWORD_ATTEMPT_TTL = 900


def _is_mock() -> bool:
    return os.environ.get("SMS_PROVIDER", "mock").lower() != "aliyun"


def _mock_bypass_allowed(identifier: str | None = None) -> bool:
    """Only explicitly allowlisted test identities may use the fixed mock code.

    MNEME_ENV=demo is a public deployment, not a developer sandbox.  Exact,
    normalized identifiers are required; wildcards and an empty allowlist fail
    closed. Keep MNEME_MOCK_CODE_ALLOWLIST limited to non-real test accounts.
    """
    environment = os.environ.get("MNEME_ENV", "").strip().lower()
    if environment not in {"dev", "development", "test"} or not identifier:
        return False
    normalized = identifier.strip().lower()
    allowlist = {
        item.strip().lower()
        for item in os.environ.get("MNEME_MOCK_CODE_ALLOWLIST", "").split(",")
        if item.strip()
    }
    return bool(normalized) and normalized in allowlist


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
    """邮箱验证采用 mock 还是 SMTP；mock 是否可发码还需通过测试环境 allowlist 门禁。"""
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
        if _is_mock() and not _mock_bypass_allowed(phone):
            return {"ok": False, "message": "当前未配置真实短信通道，请使用邮箱密码登录或联系管理员"}
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

        # Fixed code is test-only, even if an old mock code remains in Redis.
        if _is_mock() and code == MOCK_CODE:
            if _mock_bypass_allowed(phone):
                return True
            stored_mock = await r.get(f"sms:code:{phone}")
            if stored_mock == MOCK_CODE:
                await r.delete(f"sms:code:{phone}")
                await _register_failure(r, f"sms:attempt:{phone}", lock_key)
                return False

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

#: 未成年人（<14）注册必须提供监护人联系方式并显式同意。
GUARDIAN_CONSENT_AGE = 14


def assess_registration_age(
    birth_date: date,
    *,
    guardian_phone: str | None = None,
    guardian_email: str | None = None,
    guardian_consent: bool = False,
) -> tuple[int | None, dict | None]:
    """学生注册的唯一年龄闸门（手机/邮箱/邀请码/用户名四条路径共用）。

    返回 ``(age, error)``。error 为 None 表示可继续；否则调用方直接返回它。
    规则：
    - 生日不能是未来日期，也不接受 >120 岁；
    - <14 岁必须有监护人手机或邮箱 **且** 显式 consent=true；
    - 年龄算法只走 ``privacy._age``（日历周岁），不用 //365。
    """
    from services.privacy import _age

    today = datetime.now(UTC).date()
    if birth_date > today:
        return None, {"error_code": 422, "error": "出生日期不合法"}
    age = _age(birth_date)
    if age is not None and age > 120:
        return None, {"error_code": 422, "error": "出生日期不合法"}
    if age is not None and age < GUARDIAN_CONSENT_AGE:
        if not guardian_consent or not (guardian_phone or guardian_email):
            return age, {
                "error_code": 422,
                "error": "Guardian consent required for students under 14",
            }
    return age, None


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

    # 合规：年龄。与邮箱/用户名/邀请码注册共用同一闸门（单源 privacy._age）。
    age, age_error = assess_registration_age(
        birth_date, guardian_phone=guardian_phone, guardian_consent=guardian_consent
    )
    if age_error is not None:
        return age_error

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
        birth_date=birth_date,
        grade=grade,
        invite_code=uuid.uuid4().hex[:6].upper(),  # 供家长绑定
    )
    db.add(user)
    await db.flush()

    if age is not None and age < GUARDIAN_CONSENT_AGE and guardian_phone:
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
        if _is_email_mock() and not _mock_bypass_allowed(email):
            return {"ok": False, "message": "当前未配置真实邮件通道，请使用密码登录或联系管理员"}
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

        if _is_email_mock() and code == MOCK_CODE:
            if _mock_bypass_allowed(email):
                return True
            stored_mock = await r.get(f"email:code:{email}")
            if stored_mock == MOCK_CODE:
                await r.delete(f"email:code:{email}")
                await _register_failure(r, f"email:attempt:{email}", lock_key)
                return False

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
    """邮箱注册学生：必须验证邮箱验证码，再执行年龄合规与唯一性检查。"""
    from services.models import GuardianConsent, User, UserRole

    if not await verify_email_code(email, code):
        return {"error_code": 400, "error": "验证码无效或已过期"}

    # 合规：年龄（与其它学生注册路径共用同一闸门）
    age, age_error = assess_registration_age(
        birth_date, guardian_email=guardian_email, guardian_consent=guardian_consent
    )
    if age_error is not None:
        return age_error

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
        birth_date=birth_date,
        grade=grade,
        invite_code=uuid.uuid4().hex[:6].upper(),
    )
    db.add(user)
    await db.flush()

    if age is not None and age < GUARDIAN_CONSENT_AGE and guardian_email:
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
    """邮箱注册家长：必须验证邮箱验证码及学生邀请码。"""
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


_ACCOUNT_EMAIL_DOMAIN = "accounts.mneme.invalid"
_ACCOUNT_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,31}$")


def normalize_account_username(username: str) -> str:
    """Validate a public username; this is not an email/phone ownership claim."""
    normalized = (username or "").strip().lower()
    if not _ACCOUNT_USERNAME_RE.fullmatch(normalized):
        raise ValueError("用户名需为 3–32 位字母、数字、点、下划线或连字符，且以字母/数字开头")
    return normalized


def username_account_email(username: str) -> str:
    """Map usernames to a reserved .invalid email key to avoid a DB migration."""
    return f"u-{normalize_account_username(username)}@{_ACCOUNT_EMAIL_DOMAIN}"


def username_from_account_email(email: str | None) -> str | None:
    if not email or not email.endswith("@" + _ACCOUNT_EMAIL_DOMAIN):
        return None
    local = email.partition("@")[0]
    return local[2:] if local.startswith("u-") else None


async def _register_password_account(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    name: str,
    role,
    birth_date: date | None = None,
    grade: str | None = None,
    guardian_id=None,
    guardian_email: str | None = None,
    guardian_consent: bool = False,
    ip_address: str | None = None,
) -> dict:
    from services.models import GuardianConsent, ParentStudent, User, UserRole
    from services.passwords import PasswordPolicyError, hash_password

    normalized = normalize_account_username(username)
    try:
        password_hash = hash_password(password)
    except PasswordPolicyError as exc:
        return {"error_code": 422, "error": str(exc)}

    email_key = username_account_email(normalized)
    existing = (await db.execute(select(User).where(User.email == email_key))).scalar_one_or_none()
    if existing:
        return {"error_code": 409, "error": "用户名已被使用"}

    user = User(
        id=uuid.uuid4(), email=email_key, name=name, role=role,
        birth_date=birth_date, grade=grade, password_hash=password_hash,
        invite_code=uuid.uuid4().hex[:6].upper() if role == UserRole.student else None,
    )
    db.add(user)
    await db.flush()

    if guardian_id is not None:
        db.add(ParentStudent(parent_id=guardian_id, student_id=user.id))
        age = None
        if birth_date is not None:
            from services.privacy import _age
            age = _age(birth_date)
        if age is not None and age < GUARDIAN_CONSENT_AGE:
            db.add(GuardianConsent(
                id=uuid.uuid4(), student_id=user.id,
                consent_type="authenticated_parent_account",
                consent_version="1.0", ip_address=ip_address,
            ))
    elif guardian_email and guardian_consent and birth_date is not None:
        from services.privacy import _age
        age = _age(birth_date)
        if age is not None and age < GUARDIAN_CONSENT_AGE:
            db.add(GuardianConsent(
                id=uuid.uuid4(), student_id=user.id,
                guardian_email=guardian_email,
                consent_type="registration",
                consent_version="1.0", ip_address=ip_address,
            ))
    if guardian_id is not None or (guardian_email and guardian_consent):
        await db.flush()

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    public_user = {"id": str(user.id), "name": user.name, "username": normalized}
    if role == UserRole.student:
        public_user["invite_code"] = user.invite_code
    return {"token": token, "user": public_user}


async def register_student_account(
    db: AsyncSession, *, username: str, password: str, name: str,
    birth_date: date, grade: str,
    guardian_email: str | None = None, guardian_consent: bool = False,
) -> dict:
    """Username/password student registration; under-14 needs guardian consent.

    Age 14+ may self-register. Under-14 must supply a guardian email and explicit
    consent, or be created by an authenticated parent (create_student_for_parent).
    """
    from services.models import UserRole

    _, age_error = assess_registration_age(
        birth_date, guardian_email=guardian_email, guardian_consent=guardian_consent
    )
    if age_error is not None:
        return age_error
    return await _register_password_account(
        db, username=username, password=password, name=name,
        role=UserRole.student, birth_date=birth_date, grade=grade,
        guardian_email=guardian_email, guardian_consent=guardian_consent,
    )


async def register_parent_account(
    db: AsyncSession, *, username: str, password: str, name: str,
) -> dict:
    """Create a parent login identity without pretending an email address was verified."""
    from services.models import UserRole
    return await _register_password_account(
        db, username=username, password=password, name=name, role=UserRole.parent,
    )


async def create_student_for_parent(
    db: AsyncSession, *, parent, username: str, password: str, name: str,
    birth_date: date, grade: str, ip_address: str | None = None,
) -> dict:
    """A logged-in parent creates and is linked to a child account."""
    from services.models import UserRole
    if parent.role != UserRole.parent:
        return {"error_code": 403, "error": "仅家长账号可以创建学生"}
    return await _register_password_account(
        db, username=username, password=password, name=name,
        role=UserRole.student, birth_date=birth_date, grade=grade,
        guardian_id=parent.id, ip_address=ip_address,
    )


async def register_student_with_invite(
    db: AsyncSession, *, invitation_code: str, username: str, password: str,
    name: str, birth_date: date, grade: str,
    guardian_email: str | None = None, guardian_consent: bool = False,
    ip_address: str | None = None,
) -> dict:
    """Invitation-only student registration (no email/SMS dependency).

    The invite row is locked ``FOR UPDATE`` for the whole transaction so two
    concurrent redemptions cannot both succeed. Invite-based registration is
    intentionally not gated by ``REGISTRATION_OPEN``: possession of an
    admin-issued code *is* the admission control.
    """
    from services.models import RegistrationInvite, UserRole

    _, age_error = assess_registration_age(
        birth_date, guardian_email=guardian_email, guardian_consent=guardian_consent
    )
    if age_error is not None:
        return age_error

    normalized_code = (invitation_code or "").strip().upper()
    invite = (
        await db.execute(
            select(RegistrationInvite)
            .where(RegistrationInvite.code == normalized_code)
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if (
        invite is None
        or invite.revoked_at is not None
        or invite.student_id is not None
        or invite.used_at is not None
        or (invite.expires_at is not None and invite.expires_at <= now)
    ):
        return {"error_code": 400, "error": "邀请码无效、已使用或已过期"}

    result = await _register_password_account(
        db, username=username, password=password, name=name,
        role=UserRole.student, birth_date=birth_date, grade=grade,
        guardian_email=guardian_email, guardian_consent=guardian_consent,
        ip_address=ip_address,
    )
    if "error" in result:
        return result

    invite.student_id = uuid.UUID(result["user"]["id"])
    invite.used_at = now
    await db.flush()
    return result


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


# ── 可选密码登录 ──────────────────────────────────────────────────────────────
# 认证有两条独立通道：邮箱/手机验证码（始终可用）与密码（可选，仅当用户
# 显式设置过 password_hash）。两者互不替代：设了密码不禁用验证码登录，反之
# 亦然，避免把用户锁在自己选的方式之外。


async def login_password(db: AsyncSession, email: str, password: str) -> dict:
    """密码登录：bcrypt 校验 → JWT。

    三条抗枚举/抗爆破约束：
    1. "账号不存在" 与 "密码错误" 返回**完全相同**的 401 文案，不泄露邮箱是否注册。
    2. 账号不存在时仍跑一次等价 bcrypt（burn_password_verification）抹平时序差。
    3. Redis 记失败次数，超限锁 15 分钟，按 email+IP 双维度。
    """
    from services.models import User
    from services.passwords import (
        burn_password_verification,
        verify_password,
    )

    email = (email or "").strip().lower()
    if not email or not password:
        # 与下面保持同一形状，别让"空输入"成为绕过计数的旁路。
        burn_password_verification(password or "x")
        return _password_login_failed("邮箱或密码错误")

    r = _redis()
    try:
        # 失败计数按邮箱聚合：够到上限就锁这个邮箱的密码通道（验证码通道不受影响）。
        fail_key = f"password:fail:{email}"
        lock_key = f"password:lock:{email}"
        if await _check_lockout(r, lock_key):
            return {
                "error_code": 429,
                "error": f"密码错误次数过多，请 {PASSWORD_LOCKOUT_SECONDS // 60} 分钟后再试",
            }

        user = (
            await db.execute(
                select(User).where(User.email == email, User.deleted_at.is_(None))
            )
        ).scalar_one_or_none()

        if user is None:
            burn_password_verification(password)
            await _register_password_failure(r, fail_key, lock_key, email)
            return _password_login_failed("邮箱或密码错误")

        if not verify_password(password, user.password_hash):
            await _register_password_failure(r, fail_key, lock_key, email)
            return _password_login_failed("邮箱或密码错误")

        # 成功即清零，让偶发手滑不会累积成锁定。
        await r.delete(fail_key)
        token = create_access_token({"sub": str(user.id), "role": user.role.value})
        return {"token": token, "user": {"id": str(user.id), "name": user.name}}
    finally:
        await r.aclose()


def _password_login_failed(message: str) -> dict:
    """密码登录的唯一失败形状——文案统一，避免枚举已注册邮箱。"""
    return {"error_code": 401, "error": message}


async def _register_password_failure(
    r, fail_key: str, lock_key: str, email: str
) -> None:
    """密码连续输错计数，超限锁定。只记邮箱，不记明文。"""
    attempts = await r.incr(fail_key)
    await r.expire(fail_key, PASSWORD_ATTEMPT_TTL)
    if attempts >= PASSWORD_MAX_ATTEMPTS:
        await r.setex(lock_key, PASSWORD_LOCKOUT_SECONDS, "1")
        await r.delete(fail_key)
        logger.warning(
            f"密码登录连续输错 {PASSWORD_MAX_ATTEMPTS} 次，已锁定该邮箱的密码通道"
        )
    else:
        logger.warning(
            f"密码登录失败 to={_mask_email(email)} "
            f"({attempts}/{PASSWORD_MAX_ATTEMPTS})"
        )


async def set_password(db: AsyncSession, user, password: str) -> dict:
    """为已登录用户设置/改密码。走验证码通道时也可用于绑定。

    不在日志或返回值里出现密码或哈希。
    """
    from services.passwords import PasswordPolicyError, hash_password

    try:
        password_hash = hash_password(password)
    except PasswordPolicyError as exc:
        return {"error_code": 422, "error": str(exc)}

    user.password_hash = password_hash
    await db.flush()

    # 改密后清掉失败计数，避免刚改完密码仍被旧锁定挡住。
    r = _redis()
    try:
        email = (user.email or "").strip().lower()
        if email:
            await r.delete(
                f"password:fail:{email}", f"password:lock:{email}"
            )
    finally:
        await r.aclose()

    logger.info(f"密码已设置 user={user.id}")
    return {"ok": True}


def has_password(user) -> bool:
    """该账号是否已设密码——前端据此决定是否展示密码登录入口。"""
    return bool(getattr(user, "password_hash", None))
