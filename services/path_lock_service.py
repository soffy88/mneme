"""path_lock_service —— 服务端掌握路径锁（学习者自发的新学习）。

GetMasteryPath 把路径上每个 KC 标成 mastered / current / locked（状态完全由确定性
内核 is_mastered + GetPath 章节序派生，见 mcp_router.tool_get_mastery_path）。此前锁只
在前端呈现，学生直接调 /mcp/RequestQuestion 仍可对任意 KC 出题。本模块把锁落到服务端：

    学生经 HTTP /mcp/RequestQuestion 请求一个 **locked** KC 的新题 → 拒绝（path_locked）。

始终放行（按判定顺序，便宜的先查）：
  1. 开关关闭（env MNEME_PATH_LOCK=0/false/off/no；默认开）；
  1b. 指派小测：家长/管理员经 HTTP GenerateQuiz 为学生组的卷会附带 quiz_token（独立
      密钥签名、绑定 student_id + kc_sequence、7 天过期；**不是**登录 token），学生按
      卷逐题 RequestQuestion 时带上它 → 卷内 KC 放行。学生给自己组卷不发 token；
  2. 该 KC 已有本人待答题（RequestQuestion 幂等返回既有题）；
  3. 已作答过 / 有 FSRS 排程：kc_mastery 有 FSRS 卡，或 gate.qualitative_mastery 有行；
  4. 错题复习：本人 wrong_questions 关联该 KC；
  5. 本人收藏（question_bookmarks）关联该 KC；
  6. 路径派生：mastered / current / review_due / n_obs>0，或该 KC 不在路径上（不在路径
     上就谈不上 locked——阅读"检查一下"、活书块等既有流程不受影响）；路径为空/派生失败
     也放行。

作用范围：只挂在 HTTP 端点 mcp_request_question（学习者自发）。tool_request_question
本身不变——教师/管理员/系统出的小测（GenerateQuiz、quiz_service、agent 工具）不经此锁。

确定性、零 LLM、只读（不写任何表）。红线：本模块不 import 判分/门控写入模块，不改
掌握度；它只**读**派生状态做准入判断。仅基础设施异常（DB/内核调用抛错）fail-open 并记日志。
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_OFF_VALUES = {"0", "false", "off", "no"}


def path_lock_enabled() -> bool:
    return os.getenv("MNEME_PATH_LOCK", "1").strip().lower() not in _OFF_VALUES


@dataclass(frozen=True)
class PathLockDecision:
    allowed: bool
    reason: str
    kc_id: str
    current_kc_id: Optional[str] = None
    current_kc_name: Optional[str] = None
    kc_name: Optional[str] = None

    def rejection_detail(self) -> dict:
        cur = self.current_kc_name or self.current_kc_id
        return {
            "code": "path_locked",
            "kc_id": self.kc_id,
            "kc_name": self.kc_name,
            "current_kc_id": self.current_kc_id,
            "current_kc_name": self.current_kc_name,
            "message": (
                f"这个知识点还没解锁，先完成「{cur}」吧。"
                if cur
                else "这个知识点还没解锁，先完成当前知识点吧。"
            ),
        }


# ── 指派小测 token（家长/管理员 GenerateQuiz → 学生 RequestQuestion）────────────
_QUIZ_TOKEN_TTL = 7 * 24 * 3600
_QUIZ_TOKEN_TYP = "mneme-assigned-quiz"


def _quiz_secret() -> str:
    # 与登录 JWT 不同的派生密钥：quiz token 永远不能当 access token 用，反之亦然。
    from obase.config import settings

    return f"{settings.JWT_SECRET}|{_QUIZ_TOKEN_TYP}-v1"


def issue_quiz_token(
    student_id: uuid.UUID, kc_ids: list[str], issued_by: uuid.UUID
) -> str:
    from obase.auth import jwt_sign_hs256

    return jwt_sign_hs256(
        payload={
            "typ": _QUIZ_TOKEN_TYP,
            "student_id": str(student_id),
            "kcs": list(kc_ids),
            "by": str(issued_by),
        },
        secret=_quiz_secret(),
        expires_in_seconds=_QUIZ_TOKEN_TTL,
    )


def quiz_token_allows(token: Optional[str], student_id: uuid.UUID, kc_id: str) -> bool:
    if not token:
        return False
    try:
        from obase.auth import jwt_verify_hs256

        claims = jwt_verify_hs256(token=token, secret=_quiz_secret())
    except Exception:
        return False
    return (
        claims.get("typ") == _QUIZ_TOKEN_TYP
        and claims.get("student_id") == str(student_id)
        and kc_id in (claims.get("kcs") or [])
    )


async def _exists(db: AsyncSession, sql: str, params: dict) -> bool:
    return (await db.execute(text(sql), params)).first() is not None


async def _practice_or_review_reason(
    db: AsyncSession, student_id: uuid.UUID, kc_id: str
) -> Optional[str]:
    p = {"sid": str(student_id), "kc": kc_id}
    if await _exists(
        db,
        "SELECT 1 FROM gate.pending_question "
        "WHERE student_id = CAST(:sid AS uuid) AND kc_id = :kc LIMIT 1",
        p,
    ):
        return "pending"
    if await _exists(
        db,
        "SELECT 1 FROM kc_mastery "
        "WHERE student_id = CAST(:sid AS uuid) AND knowledge_point = :kc "
        "AND jsonb_typeof(fsrs_card_json) = 'object' LIMIT 1",
        p,
    ):
        return "attempted"
    if await _exists(
        db,
        "SELECT 1 FROM gate.qualitative_mastery "
        "WHERE student_id = CAST(:sid AS uuid) AND kc_id = :kc LIMIT 1",
        p,
    ):
        return "attempted"
    if await _exists(
        db,
        "SELECT 1 FROM wrong_questions "
        "WHERE student_id = CAST(:sid AS uuid) AND knowledge_points ? :kc LIMIT 1",
        p,
    ):
        return "wrong_question_review"
    if await _exists(
        db,
        "SELECT 1 FROM question_bookmarks "
        "WHERE student_id = CAST(:sid AS uuid) AND kc_id = :kc LIMIT 1",
        p,
    ):
        return "bookmarked"
    return None


async def check_path_lock(
    db: AsyncSession,
    student_id: uuid.UUID,
    kc_id: str,
    *,
    quiz_token: Optional[str] = None,
) -> PathLockDecision:
    """学习者自发 RequestQuestion 的准入判定。只读；异常 fail-open（记日志）。"""
    if not path_lock_enabled():
        return PathLockDecision(True, "disabled", kc_id)
    if quiz_token_allows(quiz_token, student_id, kc_id):
        return PathLockDecision(True, "assigned_quiz", kc_id)
    try:
        reason = await _practice_or_review_reason(db, student_id, kc_id)
        if reason is not None:
            return PathLockDecision(True, reason, kc_id)

        from services.mcp_router import tool_get_mastery_path

        view = await tool_get_mastery_path(db, student_id)
        if view.get("status") != "completed":
            return PathLockDecision(True, f"path_{view.get('status')}", kc_id)
        nodes = view.get("nodes") or []
        node = next((n for n in nodes if n["kc_id"] == kc_id), None)
        if node is None:
            return PathLockDecision(True, "not_on_path", kc_id)
        if node["state"] in ("mastered", "current"):
            return PathLockDecision(True, node["state"], kc_id)
        if node.get("review_due"):
            return PathLockDecision(True, "review_due", kc_id)
        if int(node.get("n_obs") or 0) > 0:
            return PathLockDecision(True, "attempted", kc_id)
        cur_id = view.get("current_kc_id")
        cur_name = next((n["name"] for n in nodes if n["kc_id"] == cur_id), None)
        return PathLockDecision(
            False,
            "locked",
            kc_id,
            current_kc_id=cur_id,
            current_kc_name=cur_name,
            kc_name=node.get("name"),
        )
    except Exception as exc:  # 基础设施异常：fail-open，绝不因锁本身挡住学习
        logger.warning(
            "path_lock_fail_open student=%s kc=%s error=%s",
            student_id,
            kc_id,
            type(exc).__name__,
        )
        try:
            await db.rollback()
        except Exception:
            pass
        return PathLockDecision(True, "fail_open", kc_id)
