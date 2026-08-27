"""Minimal admin-only operational status surface; no private answers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from obase.admin_identity import is_admin
from obase.db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import get_current_user
from services.models import User
from services.observability import metrics_snapshot
from services.production_config import validate_session_contract
from services.worker_health import worker_health_snapshot

router = APIRouter(tags=["operator"])


@router.get("/v2/operator/status")
async def operator_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="仅 admin 可访问运维状态")
    del db  # The endpoint is deliberately read-only and does not inspect learner rows.
    return {
        "system": {"status": "alive"},
        "worker": worker_health_snapshot(),
        "metrics": metrics_snapshot(),
        "session": validate_session_contract(),
        "private_learning_answers": "not_included",
    }
