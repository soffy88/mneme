"""Xiaoya English 陪练 — 端点存根（STUB，尚未注册到生产 app）。

设计见 docs/xiaoya_practice.md。本文件是「未来接入点」的占位：
- 复用 ``vendor/oskill/english_answer_check_skill.check_english_answer`` 做确定性打分；
- 音频/视频由 hevi-live 侧按 unit/句 id 提供（EG2 检索 + lipsync），本端点不持有媒体。

**未注册**：不要在生产 app（services/main.py）include 本路由，除非走完设计里的
接入评审（资产入 Stratum、会话额度、鉴权）。仅做研发期本地 import 与单元自测用。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/v1/english/practice", tags=["english-practice"])


class PracticeRequest(BaseModel):
    """学生输入 + 教材定位。"""

    book: str  # e.g. "pep-g7a"
    unit: str  # e.g. "u1"
    item_id: str | None = None  # 指定教材句；为空则由服务端就近选
    student_text: str = ""  # 学生作答（口语/文本）
    mode: str = "check"  # "present" | "check"


class PracticeResponse(BaseModel):
    target_id: str
    target_text: str
    target_gloss: str = ""
    motion: str = "talk_a"
    audio_ref: str = ""  # hevi-live 侧资源引用，本端点不直接返回媒体
    score: dict[str, Any] = {}


@router.post("", response_model=PracticeResponse)
async def practice(request: PracticeRequest) -> PracticeResponse:
    """未来实现：取教材句 → 调 check_english_answer 打分 → 返回 target + 反馈。

    当前为占位：直接报 501，提醒走 hevi-live 原型（eng_lib/practice.py）。
    """
    raise NotImplementedError(
        "Xiaoya practice endpoint not deployed yet; see docs/xiaoya_practice.md "
        "and the hevi-live prototype (eng_lib.practice.PracticeSession)."
    )
