from fastapi import FastAPI, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
import uuid
from typing import List, Optional
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path
import shutil
import os

from obase.db import get_db, SessionLocal
from obase.cognitive_store import PgStore
from obase.prior_provider import PriorProvider
from obase.llm import register_default_providers
from omodul.cognitive import (
    process_interaction_workflow, 
    InteractionConfig, 
    InteractionInput,
    mastery_overview_workflow,
    review_queue_workflow
)
from omodul.auth import (
    send_code_workflow,
    AuthConfig,
    SendCodeInput
)
from omodul.paper import (
    upload_paper_workflow,
    PaperConfig,
    PaperUploadInput
)
from data.guangdong_math_kc import KC_LIST, get_kc

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 预热 BKT 先验参数缓存
    async with SessionLocal() as session:
        await PriorProvider.warm_up(session)
    
    # 注册 LLM 提供商
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

# ===== §8 认知状态 API =====

@app.post("/v1/interaction")
async def post_interaction(
    interaction: InteractionInput,
    db: AsyncSession = Depends(get_db)
):
    """
    POST /v1/interaction
    处理一次答题交互并更新认知状态。
    """
    store = PgStore(db)
    config = InteractionConfig()
    
    try:
        result = await process_interaction_workflow(config, interaction, store)
        await db.commit()
        return result["findings"]
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/mastery/{student_id}")
async def get_mastery(
    student_id: UUID,
    now: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    GET /v1/mastery/{student_id}
    获取学生所有知识点的掌握度总览（按薄弱排序）。
    """
    store = PgStore(db)
    try:
        result = await mastery_overview_workflow(store, student_id, now=now)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/review-queue/{student_id}")
async def get_review_queue(
    student_id: UUID,
    now: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    GET /v1/review-queue/{student_id}
    今日到期复习池。
    """
    store = PgStore(db)
    try:
        result = await review_queue_workflow(store, student_id, now=now)
        return result
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
