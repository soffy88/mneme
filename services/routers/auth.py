"""认证 / 家长绑定路由（自 main 拆出）。

SMS/Email provider 仍挂在 services.main 模块级（lifespan 会替换实例），
本 router 通过 ``import services.main`` 取当前 provider，避免双份状态。
"""

from __future__ import annotations

import os
import re as _re_email
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from obase.db import get_db
from omodul.auth import LoginInput, RegisterStudentInput, SendCodeInput
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services import auth_service
from services.auth_deps import get_current_user
from services.models import ParentStudent, User, UserRole

router = APIRouter(tags=["auth"])


def _sms_provider():
    import services.main as _main

    return _main._sms_provider


def _email_provider():
    import services.main as _main

    return _main._email_provider


def _require_registration_open() -> None:
    """公网注册闸门（默认关）。SMS 仍是 mock 时公网放开注册风险高。"""
    if os.environ.get("REGISTRATION_OPEN", "0").lower() not in ("1", "true", "yes"):
        raise HTTPException(
            status_code=403,
            detail="注册暂未开放（公网注册需短信实名，报备后开启）",
        )


# 轻量邮箱格式校验（真正所有权靠验证码）
_EMAIL_RE = _re_email.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(v: str) -> str:
    v = v.strip()
    if not _EMAIL_RE.match(v):
        raise ValueError("邮箱格式不正确")
    return v.lower()


class RegisterParentInput(BaseModel):
    phone: str
    code: str
    name: str
    invite_code: str


class SendEmailCodeReq(BaseModel):
    email: str

    _v = field_validator("email")(lambda cls, v: _validate_email(v))


class RegisterStudentEmailReq(BaseModel):
    email: str
    code: str
    name: str
    birth_date: date
    grade: str
    guardian_email: str | None = None
    guardian_consent: bool = False

    _v = field_validator("email")(lambda cls, v: _validate_email(v))

    @field_validator("guardian_email")
    @classmethod
    def _v_guardian(cls, v: str | None) -> str | None:
        return _validate_email(v) if v else v


class RegisterParentEmailReq(BaseModel):
    email: str
    code: str
    name: str
    invite_code: str

    _v = field_validator("email")(lambda cls, v: _validate_email(v))


class LoginEmailReq(BaseModel):
    email: str
    code: str

    _v = field_validator("email")(lambda cls, v: _validate_email(v))


@router.post("/v1/auth/send-code")
async def post_send_code(payload: SendCodeInput):
    """POST /v1/auth/send-code — 发送短信验证码，存 Redis TTL=5min，60s防刷。"""
    result = await auth_service.send_code(payload.phone, _sms_provider())
    if not result["ok"]:
        raise HTTPException(status_code=429, detail=result["message"])
    return result


@router.post("/v1/auth/register/student", status_code=201)
async def post_register_student(
    payload: RegisterStudentInput,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """注册学生：验证码 + 合规 + 写库 + JWT。"""
    _require_registration_open()
    result = await auth_service.register_student(
        db=db,
        phone=payload.phone,
        code=payload.code,
        name=payload.name,
        birth_date=payload.birth_date,
        grade=payload.grade,
        guardian_phone=payload.guardian_phone,
        guardian_consent=payload.guardian_consent,
        ip_address=request.client.host if request.client else None,
    )
    if "error" in result:
        raise HTTPException(status_code=result["error_code"], detail=result["error"])
    await db.commit()
    return result


@router.post("/v1/auth/register/parent", status_code=201)
async def post_register_parent(
    payload: RegisterParentInput,
    db: AsyncSession = Depends(get_db),
):
    """注册家长：验证码 + invite_code 绑定孩子 + JWT。"""
    _require_registration_open()
    result = await auth_service.register_parent(
        db=db,
        phone=payload.phone,
        code=payload.code,
        name=payload.name,
        invite_code=payload.invite_code,
    )
    if "error" in result:
        raise HTTPException(status_code=result["error_code"], detail=result["error"])
    await db.commit()
    return result


@router.post("/v1/auth/login")
async def post_login(payload: LoginInput, db: AsyncSession = Depends(get_db)):
    """登录：Redis 验证码 → JWT。"""
    result = await auth_service.login(db=db, phone=payload.phone, code=payload.code)
    if "error" in result:
        raise HTTPException(status_code=result["error_code"], detail=result["error"])
    return result


@router.post("/v1/auth/send-email-code")
async def post_send_email_code(payload: SendEmailCodeReq):
    """POST /v1/auth/send-email-code — 邮箱验证码。"""
    result = await auth_service.send_email_code(
        str(payload.email), _email_provider()
    )
    if not result["ok"]:
        raise HTTPException(status_code=429, detail=result["message"])
    return result


@router.post("/v1/auth/register/student-email", status_code=201)
async def post_register_student_email(
    payload: RegisterStudentEmailReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """邮箱注册学生。"""
    _require_registration_open()
    result = await auth_service.register_student_email(
        db=db,
        email=str(payload.email),
        code=payload.code,
        name=payload.name,
        birth_date=payload.birth_date,
        grade=payload.grade,
        guardian_email=str(payload.guardian_email) if payload.guardian_email else None,
        guardian_consent=payload.guardian_consent,
        ip_address=request.client.host if request.client else None,
    )
    if "error" in result:
        raise HTTPException(status_code=result["error_code"], detail=result["error"])
    await db.commit()
    return result


@router.post("/v1/auth/register/parent-email", status_code=201)
async def post_register_parent_email(
    payload: RegisterParentEmailReq,
    db: AsyncSession = Depends(get_db),
):
    """邮箱注册家长。"""
    _require_registration_open()
    result = await auth_service.register_parent_email(
        db=db,
        email=str(payload.email),
        code=payload.code,
        name=payload.name,
        invite_code=payload.invite_code,
    )
    if "error" in result:
        raise HTTPException(status_code=result["error_code"], detail=result["error"])
    await db.commit()
    return result


@router.post("/v1/auth/login-email")
async def post_login_email(
    payload: LoginEmailReq, db: AsyncSession = Depends(get_db)
):
    """邮箱登录。"""
    result = await auth_service.login_email(
        db=db, email=str(payload.email), code=payload.code
    )
    if "error" in result:
        raise HTTPException(status_code=result["error_code"], detail=result["error"])
    return result


@router.get("/v1/auth/me")
async def get_me(user: User = Depends(get_current_user)):
    """当前用户信息。"""
    return {
        "id": str(user.id),
        "phone": user.phone,
        "email": getattr(user, "email", None),
        "role": user.role.value,
        "name": user.name,
        "grade": getattr(user, "grade", None),
        "invite_code": user.invite_code,
        "share_process_with_parent": getattr(user, "share_process_with_parent", False),
    }


@router.post("/v1/auth/bind-child")
async def post_bind_child(
    invite_code: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """家长绑定孩子。"""
    student = (
        await db.execute(
            select(User).where(
                User.invite_code == invite_code, User.role == UserRole.student
            )
        )
    ).scalar_one_or_none()
    if not student:
        raise HTTPException(
            status_code=404, detail="Student not found with invite code"
        )
    student_id_str = str(student.id)
    student_name = student.name
    existing = (
        await db.execute(
            select(ParentStudent).where(
                ParentStudent.parent_id == current_user.id,
                ParentStudent.student_id == student.id,
            )
        )
    ).scalar_one_or_none()
    if not existing:
        db.add(ParentStudent(parent_id=current_user.id, student_id=student.id))
        await db.commit()
    return {"ok": True, "student_id": student_id_str, "student_name": student_name}


@router.get("/v1/parent/children")
async def get_children(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """家长的孩子列表。"""
    rows = (
        await db.execute(
            select(ParentStudent, User)
            .join(User, ParentStudent.student_id == User.id)
            .where(ParentStudent.parent_id == current_user.id)
            .order_by(ParentStudent.display_order)
        )
    ).all()
    return [
        {"student_id": str(ps.student_id), "name": u.name, "grade": u.grade}
        for ps, u in rows
    ]
