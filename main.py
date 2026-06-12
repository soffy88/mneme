"""
自我助学系统 · 认知状态服务 (FastAPI)
=====================================
把 KT + FSRS 内核暴露为 HTTP 接口。

接口：
  POST /v1/interaction              上报一次答题/回顾事件，触发 KT+FSRS 更新
  GET  /v1/mastery/{student_id}     当前各 KC 掌握度总览（按薄弱排序）
  GET  /v1/review-queue/{student_id} 今日到期复习池
  GET  /v1/kc                       广东数学 KC 字典摘要
  GET  /v1/kc/{kc_id}               单个 KC 详情（含前置链）

运行：  uvicorn api.main:app --reload
文档：  访问 /docs
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.cognitive_state import (
    CognitiveStore, process_interaction, mastery_overview, review_queue,
)
from data.guangdong_math_kc import (
    KC_INDEX, get_kc, kc_summary, all_prerequisites,
)

app = FastAPI(
    title="自我助学系统 · 认知状态服务",
    description="KT(知识追踪) + FSRS(间隔重复) 算法内核 | 广东数学",
    version="1.3.0",
)

# 内存存储（生产替换为 PostgreSQL）
STORE = CognitiveStore()


class InteractionIn(BaseModel):
    student_id: str = Field(..., examples=["stu_001"])
    kc_id: str = Field(..., examples=["GDMATH-CONIC-01"])
    is_correct: bool
    used_answer: bool = False
    struggled: bool = False
    effortless: bool = False
    source: str = Field("paper", examples=["paper", "quick", "review", "socratic"])


@app.get("/")
def root():
    return {"service": "self-learning-os", "version": "1.3.0",
            "kc_subject": "广东数学", "docs": "/docs"}


@app.post("/v1/interaction")
def post_interaction(body: InteractionIn):
    if body.kc_id not in KC_INDEX:
        raise HTTPException(404, f"未知知识点: {body.kc_id}")
    result = process_interaction(
        STORE, body.student_id, body.kc_id, body.is_correct,
        used_answer=body.used_answer, struggled=body.struggled,
        effortless=body.effortless,
    )
    result["kc_name"] = KC_INDEX[body.kc_id]["name"]
    result["source"] = body.source
    return result


@app.get("/v1/mastery/{student_id}")
def get_mastery(student_id: str):
    overview = mastery_overview(STORE, student_id)
    for row in overview:
        kc = get_kc(row["kc_id"])
        row["kc_name"] = kc["name"] if kc else row["kc_id"]
    return {"student_id": student_id, "knowledge_points": overview,
            "count": len(overview)}


@app.get("/v1/review-queue/{student_id}")
def get_review_queue(student_id: str):
    queue = review_queue(STORE, student_id)
    for row in queue:
        kc = get_kc(row["kc_id"])
        row["kc_name"] = kc["name"] if kc else row["kc_id"]
    return {"student_id": student_id, "due_today": queue, "count": len(queue)}


@app.get("/v1/kc")
def get_kc_dict():
    return kc_summary()


@app.get("/v1/kc/{kc_id}")
def get_kc_detail(kc_id: str):
    kc = get_kc(kc_id)
    if not kc:
        raise HTTPException(404, f"未知知识点: {kc_id}")
    return {**kc, "full_prerequisite_chain": all_prerequisites(kc_id)}
