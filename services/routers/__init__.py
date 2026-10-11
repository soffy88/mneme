"""域路由包：从 services.main 拆出的 APIRouter，main 只负责 app 装配 + lifespan。"""

from __future__ import annotations

from fastapi import FastAPI


def register_domain_routers(app: FastAPI) -> None:
    """挂载已拆出的域路由（idempotent：可重复调用，但不推荐）。"""
    from services.routers import (
        aria,
        auth,
        chemistry,
        cognitive,
        conic_geometry,
        cornell,
        edu_assets,
        geometry,
        health,
        immersive,
        learning,
        memory,
        insights,
        papers,
        parent,
        plan,
        pilot,
        product,
        operator,
        practice,
        progress,
        related_labs,
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
        product,
        operator,
        progress,
        subjects,
        immersive,
        learning,
        geometry,
        conic_geometry,
        chemistry,
        edu_assets,
        related_labs,
    ):
        app.include_router(mod.router)
