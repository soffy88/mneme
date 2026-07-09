"""
认证请求/响应 schema（wire contract）
======================
omodul/auth.py

X.6 项目体检审计：这里此前还有 send_code_workflow/register_student_workflow/
login_workflow 三个"业务事务"函数，实测全仓库（含 tasks/ Celery 任务）零调用方
——真正的认证逻辑一直是 services/auth_service.py 的独立实现（services/main.py
的端点直接调用它，不经这几个 workflow 函数）。三份重复实现只留一份 canonical，
已删除这里的死代码，只保留 main.py 实际导入使用的请求体 schema。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class SendCodeInput(BaseModel):
    phone: str = Field(..., pattern=r"^1[3-9]\d{9}$")


class RegisterStudentInput(BaseModel):
    phone: str = Field(..., pattern=r"^1[3-9]\d{9}$")
    code: str
    name: str
    birth_date: date
    grade: str
    guardian_phone: Optional[str] = None
    guardian_consent: bool = False


class LoginInput(BaseModel):
    phone: str
    code: str
