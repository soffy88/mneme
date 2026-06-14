from fastapi import FastAPI, Depends, HTTPException, Query, UploadFile, File
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
import uuid
from typing import Optional, List
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path
import shutil
import os

from obase.db import get_db, SessionLocal
from obase.prior_provider import PriorProvider
from obase.llm import register_default_providers
from obase.auth import decode_access_token
from omodul.cognitive import InteractionInput
from omodul.auth import (
    send_code_workflow,
    register_student_workflow,
    login_workflow,
    AuthConfig,
    SendCodeInput,
    RegisterStudentInput,
    LoginInput
)
from omodul.paper import (
    upload_paper_workflow,
    PaperConfig,
    PaperUploadInput
)
from services.cognitive_service import (
    mastery_overview,
    process_interaction,
    review_queue,
)
from services.seed import seed_bkt_priors
from services.models import User, UserRole
from data.guangdong_math_kc import KC_LIST, get_kc

# ===== §8 认证依赖 =====
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="v1/auth/login", auto_error=False)

async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme), 
    db: AsyncSession = Depends(get_db)
) -> User:
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    
    stmt = select(User).where(User.id == uuid.UUID(user_id))
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with SessionLocal() as session:
        await seed_bkt_priors(session)
        await session.commit()
        await PriorProvider.warm_up(session)
    register_default_providers()
    yield

app = FastAPI(title="Mneme API", version="0.1.0", lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "healthy", "service": "mneme-api"}

# ===== §8 认证 API =====

@app.post("/v1/auth/send-code")
async def post_send_code(
    payload: SendCodeInput
):
    """
    POST /v1/auth/send-code
    发送短信验证码（dev mock）。
    """
    config = AuthConfig()
    result = await send_code_workflow(config, payload)
    return result["findings"]

@app.post("/v1/auth/register/student")
async def post_register_student(
    payload: RegisterStudentInput,
    db: AsyncSession = Depends(get_db)
):
    """注册学生并返回 Token。"""
    config = AuthConfig()
    result = await register_student_workflow(config, payload, db)
    if result["status"] == "failed":
        status_code = 400
        if result["findings"] and isinstance(result["findings"], dict):
            status_code = result["findings"].get("error_code", 400)
        raise HTTPException(status_code=status_code, detail=result["error"])
    return result["findings"]

@app.post("/v1/auth/login")
async def post_login(
    payload: LoginInput,
    db: AsyncSession = Depends(get_db)
):
    """登录并返回 Token。"""
    config = AuthConfig()
    result = await login_workflow(config, payload, db)
    if result["status"] == "failed":
        raise HTTPException(status_code=400, detail=result["error"])
    return result["findings"]

@app.get("/v1/auth/me")
async def get_me(
    user: User = Depends(get_current_user)
):
    """获取当前用户信息。"""
    return {
        "id": str(user.id),
        "phone": user.phone,
        "role": user.role.value,
        "name": user.name
    }

# ===== §8 认知状态 API =====

@app.post("/v1/interaction")
async def post_interaction(
    interaction: InteractionInput,
    db: AsyncSession = Depends(get_db)
):
    """POST /v1/interaction — 处理一次答题交互并更新认知状态。"""
    try:
        result = await process_interaction(
            db,
            student_id=interaction.student_id,
            kc_id=interaction.kc_id,
            is_correct=interaction.is_correct,
            question_type=interaction.question_type,
            question_id=interaction.question_id,
            source=interaction.source,
            used_answer=interaction.used_answer,
            struggled=interaction.struggled,
            effortless=interaction.effortless,
            is_interleaved=interaction.is_interleaved,
            time_spent_seconds=interaction.time_spent_seconds,
            now=interaction.now,
        )
        await db.commit()
        return result
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/mastery/{student_id}")
async def get_mastery(
    student_id: UUID,
    now: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db)
):
    """GET /v1/mastery/{student_id} — 掌握度总览（按薄弱排序，含百分位）。"""
    try:
        return await mastery_overview(db, student_id, now=now)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/review-queue/{student_id}")
async def get_review_queue(
    student_id: UUID,
    now: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db)
):
    """GET /v1/review-queue/{student_id} — 今日复习队列（interleaved）。"""
    try:
        return await review_queue(db, student_id, now=now)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/kc")
async def list_kc():
    """
    GET /v1/kc
    获取全部知识点字典。
    """
    return KC_LIST

@app.get("/v1/kc/{kc_id}")
async def get_kc_detail(kc_id: str):
    """
    GET /v1/kc/{kc_id}
    获取特定知识点详情。
    """
    kc = get_kc(kc_id)
    if not kc:
        raise HTTPException(status_code=404, detail="Knowledge Component not found")
    return kc

# ===== §3 试卷接口 =====

@app.post("/v1/papers/upload")
async def post_paper_upload(
    student_id: UUID = Query(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """
    POST /v1/papers/upload
    上传一张试卷并启动处理流程。
    """
    config = PaperConfig()
    
    # 临时保存本地
    temp_dir = "/tmp/mneme_uploads"
    os.makedirs(temp_dir, exist_ok=True)
    local_path = Path(temp_dir) / f"{uuid.uuid4()}_{file.filename}"
    
    try:
        with open(local_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        payload = PaperUploadInput(
            student_id=student_id,
            local_file_path=local_path,
            filename=file.filename or "unknown.jpg"
        )
        
        result = await upload_paper_workflow(config, payload, db)
        
        if result["status"] == "failed":
            raise HTTPException(status_code=500, detail=result["error"])
            
        return result["findings"]
        
    finally:
        # 清理临时文件
        if local_path.exists():
            os.remove(local_path)
