"""域路由包：从 services.main 拆出的 APIRouter，main 只负责 app 装配 + lifespan。"""

from __future__ import annotations

from fastapi import FastAPI


def register_domain_routers(app: FastAPI) -> None:
    """挂载已拆出的域路由（idempotent：可重复调用，但不推荐）。"""
    from services.routers import (
        aria,
        auth,
        cognitive,
        cornell,
        health,
        insights,
        papers,
        parent,
        plan,
        practice,
        progress,
        review,
        socratic,
        subjects,
        textbook,
    )

    for mod in (
        health,
        cornell,
        auth,
        aria,
        socratic,
        review,
        textbook,
        cognitive,
        papers,
        plan,
        insights,
        parent,
        practice,
        progress,
        subjects,
    ):
        app.include_router(mod.router)
