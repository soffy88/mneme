"""Shared DB result types for oprim database operations."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class WriteResult(BaseModel):
    rows_affected: int
    returned_id: Any | None = None


class AccessResult(BaseModel):
    user_id: str
    access_tier: str
    action: str
    success: bool
