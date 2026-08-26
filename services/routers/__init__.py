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
        memory,
        insights,
        papers,
        parent,
        plan,
        pilot,
        practice,
        progress,
        review,
        socratic,
        subjects,
        textbook,
    )

    for mod in (
        health,
        memory,
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
        pilot,
        progress,
        subjects,
    ):
        app.include_router(mod.router)
