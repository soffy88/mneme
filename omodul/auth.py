"""
认证与用户管理业务事务
======================
omodul/auth.py
"""

from __future__ import annotations
from typing import Optional, Any
from pydantic import BaseModel, Field

from omodul.base import BaseConfig, standard_return
from obase.sms import send_otp, verify_otp

class AuthConfig(BaseConfig):
    _omodul_name = "auth_workflow"
    _omodul_version = "0.1.0"
    _enabled_pillars = {"decision_trail"}

class SendCodeInput(BaseModel):
    phone: str = Field(..., pattern=r"^1[3-9]\d{9}$")

async def send_code_workflow(
    config: AuthConfig,
    input_data: SendCodeInput
) -> dict:
    """发送短信验证码业务流程。"""
    code = await send_otp(input_data.phone)
    
    trail = [
        {"step": "send_otp", "phone": input_data.phone, "mock_code": code}
    ]
    
    return standard_return(
        findings={"ok": True, "message": "Code sent (dev mock)"},
        status="completed",
        trail=trail if "decision_trail" in config._enabled_pillars else None
    )
