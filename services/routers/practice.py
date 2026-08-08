"""练习 / 求解 / 讲解 / 变式 / 错题本 / 随手拍（自 main 拆出）。"""
from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from obase.db import get_db
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import (
    _ensure_student_access,
    _ensure_student_self,
    get_current_user,
    require_student_access,
)
from data.guangdong_math_kc import get_kc
from services.cognitive_service import process_interaction
from services.feature_flags import PEDAGOGY_FINE_FEEDBACK, pedagogy_enabled
from services.instant_solve_service import get_pg_pool, handle_instant_solve
from services.logging_config import logger
from services.math_grade import grade_math
from services.models import (
    KnowledgeCluster,
    KnowledgeUnit,
    Textbook,
    User,
    WrongQuestion,
)
from services.solve_service import solve_problem

router = APIRouter(tags=["practice"])

# ===== §H.1 求解接口 =====


from services.ratelimit import rate_limit

# 匿名昂贵端点限流：每 IP 60s 内 30 次求解（防刷算力）
_solve_rate_limit = rate_limit(limit=30, window_seconds=60, scope="solve")


@router.post("/v1/solve")
async def post_solve(
    ku_id: str = Query(...),
    expression: str = Query(...),
    low_bandwidth: bool = Query(False, description="U.23：跳过 SVG 生成，减小响应体积"),
    _: None = Depends(_solve_rate_limit),
):
    """POST /v1/solve — 调 oskill.solve_and_visualize 确定性求解。"""
    from oskill.solve_and_visualize import SolveAndVisualizeInput, solve_and_visualize

    inp = SolveAndVisualizeInput(
        expression=expression, problem_type="auto", generate_svg=not low_bandwidth
    )
    try:
        result = solve_and_visualize(inp)
        return {
            "ku_id": ku_id,
            "answer": result.solve_answer,
            "solvable": result.solvable,
            "steps": result.solve_steps,
            "svg": result.svg,
        }
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))


# ===== §H.2 讲解页 =====


def _trim_plot_data(plot_data: dict | None, low_bandwidth: bool) -> dict | None:
    """U.23 低带宽模式：去掉 svg（通常最大的字段），保留 steps 等文本内容。"""
    if not low_bandwidth or not plot_data:
        return plot_data
    return {k: v for k, v in plot_data.items() if k != "svg"}


@router.get("/v1/lesson/{question_id}")
async def get_lesson(
    question_id: UUID,
    low_bandwidth: bool = Query(False, description="U.23：跳过 SVG，减小响应体积"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/lesson/{question_id} — 讲解页（缓存优先）。
    鉴权：题目归属学生本人或绑定家长（公共题库题 student_id 为空则放行）。"""
    from services.models import LessonPage

    wq = (
        await db.execute(select(WrongQuestion).where(WrongQuestion.id == question_id))
    ).scalar_one_or_none()
    if wq is not None:
        await _ensure_student_access(db, current_user, wq.student_id)

    # Cache check
    cached = (
        await db.execute(
            select(LessonPage).where(LessonPage.question_id == question_id)
        )
    ).scalar_one_or_none()
    if cached:
        return {
            "question_id": str(question_id),
            "plot_data": _trim_plot_data(cached.plot_data, low_bandwidth),
            "self_check_passed": cached.self_check_passed,
            "cached": True,
        }
    if not wq:
        raise HTTPException(status_code=404, detail="Question not found")
    import hashlib as _hashlib

    from omodul.generate_lesson_page import (
        LessonPageConfig,
        LessonPageInput,
        generate_lesson_page,
    )

    kc_id = (
        next(iter(wq.knowledge_points.keys()), "")
        if isinstance(wq.knowledge_points, dict)
        else ""
    )
    question_text = wq.question_text or ""
    question_hash = _hashlib.sha256(question_text.encode()).hexdigest()[:16]
    result = await generate_lesson_page(
        config=LessonPageConfig(kc_id=kc_id, question_hash=question_hash),
        input_data=LessonPageInput(
            question_text=question_text,
            correct_answer=wq.correct_answer or "",
            problem_spec={},
        ),
        output_dir=Path(f"/tmp/mneme/lesson/{question_id}"),
    )
    # 同源自检红线：图示/答案/末步三处不一致 → 不交付（不是打个flag照样给）。
    if result.get("status") == "self_check_failed":
        raise HTTPException(
            status_code=422,
            detail="lesson_page 同源自检未通过（图示/答案/末步不一致），拒绝交付",
        )
    if result.get("status") == "ok":
        from services.models import LessonPage

        cached_row = LessonPage(
            question_id=question_id,
            fingerprint=result.get("fingerprint", ""),
            plot_data={"svg": result.get("svg", ""), "steps": result.get("steps", [])},
            self_check_passed=result.get("self_check_passed", False),
        )
        db.add(cached_row)
        try:
            await (
                db.commit()
            )  # 原仅 flush 无 commit → 会话关闭即回滚，lesson_pages 永远为 0
        except Exception:
            await db.rollback()
    return {
        "question_id": str(question_id),
        "plot_data": _trim_plot_data(
            {"svg": result.get("svg", ""), "steps": result.get("steps", [])},
            low_bandwidth,
        ),
        "answer": result.get("answer", ""),
        "self_check_passed": result.get("self_check_passed"),
        "status": result.get("status"),
        "cached": False,
    }


# ===== §I.1 变式题 =====


@router.get("/v1/question-bank")
async def list_question_bank(
    subject: str | None = Query(None),
    needs_image: bool | None = Query(None),
    ku_id: str | None = Query(None),
    student_id: UUID | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/question-bank — 公共题库查询（student_id IS NULL）。

    ?subject=math         按学科筛选
    ?needs_image=false    只返回纯文本题（专题练习用）
    ?ku_id=...            按已匹配KU筛选
    """
    stmt = select(WrongQuestion).where(WrongQuestion.student_id.is_(None))
    if subject:
        stmt = stmt.where(WrongQuestion.subject == subject)
    if needs_image is not None:
        stmt = stmt.where(WrongQuestion.needs_image == needs_image)
    if ku_id:
        stmt = stmt.where(WrongQuestion.knowledge_points.has_key(ku_id))

    total_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(total_stmt)).scalar_one()

    # ── 难度自适应排序 (ZPD Band) ──
    from services.learner_model import get_mastery, get_zpd_band

    order_clause = WrongQuestion.created_at
    if student_id and ku_id:
        mastery_info = await get_mastery(db, student_id, ku_id)
        p = mastery_info.get("p")
        if p is not None:
            zpd = get_zpd_band(p)
            target = (zpd["difficulty_min"] + zpd["difficulty_max"]) / 2.0
            # 使用 Postgres ABS 计算与目标难度的距离。未校准的题目 (item_difficulty IS NULL) 当作距离很远
            # 按距离升序排列，越接近 target 的题越排在前面
            order_clause = func.coalesce(
                func.abs(WrongQuestion.item_difficulty - target), 999.0
            ).asc()

    rows = (
        (await db.execute(stmt.order_by(order_clause).offset(offset).limit(limit)))
        .scalars()
        .all()
    )

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [
            {
                "id": str(q.id),
                "subject": q.subject,
                "question_text": q.question_text,
                "correct_answer": q.correct_answer,
                "knowledge_points": q.knowledge_points or {},
                "needs_image": q.needs_image,
                # 解析（答后展示，助学生看"为什么"）：取 gaokao analysis / ceval explanation
                "explanation": (q.profiler_analysis or {}).get("analysis")
                or (q.profiler_analysis or {}).get("explanation")
                or "",
            }
            for q in rows
        ],
    }


@router.post("/v1/practice/generate")
async def post_practice_generate(
    ku_id: str = Query(...),
    count: int = Query(3),
    difficulty: float = Query(0.5),
    question_type: str = Query("solve"),
    student_id: UUID | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/practice/generate — 生成变式题（调 omodul.practice_workflow）。
    KC 名称/学科先查 get_kc()（数学旧版 GDMATH-* 静态字典，历史 kc_id 仍在用，
    knowledge_units 表里没有这些 id，不能直接替换），查不到再退到 knowledge_units 表
    （DB-backed，覆盖物理/语文的新版 ku_id；英语暂无数据，两处都查不到照样 404）。"""
    await _ensure_student_access(db, current_user, student_id)
    from omodul.practice_workflow import PracticeConfig, practice_workflow

    kc = get_kc(ku_id)
    if kc:
        ku_name = kc.get("name", ku_id)
        ku_description = ""
        ku_subject = "math"
    else:
        ku_row = (
            await db.execute(
                select(KnowledgeUnit, Textbook.subject)
                .join(Textbook, KnowledgeUnit.textbook_id == Textbook.id)
                .where(KnowledgeUnit.id == ku_id)
            )
        ).first()
        if ku_row is None:
            raise HTTPException(status_code=404, detail="KC not found")
        ku, ku_subject = ku_row
        ku_name = ku.name or ku_id
        ku_description = ku.description or ""
    sid = student_id or uuid.uuid4()

    # ── 难度自适应出题 ──
    # 如果指定了学生，查其该题知识点的掌握度来覆写 difficulty
    if student_id:
        from services.learner_model import get_mastery, get_zpd_band

        mastery_info = await get_mastery(db, student_id, ku_id)
        p = mastery_info.get("p")
        if p is not None:
            zpd = get_zpd_band(p)
            difficulty = (zpd["difficulty_min"] + zpd["difficulty_max"]) / 2.0

    result = await practice_workflow(
        config=PracticeConfig(
            kc_id=ku_id,
            count=count,
            difficulty=difficulty,
            question_type=question_type,
            subject=ku_subject,
            ku_name=ku_name,
            ku_description=ku_description,
        ),
        input_data=None,
        output_dir=Path(f"/tmp/mneme/practice/{sid}"),
    )
    items = result.get("items", [])
    return {
        "ku_id": ku_id,
        "ku_name": ku_name,
        "items": items,
        "status": result.get("status", "ok"),
    }


@router.get("/v1/practice/topics")
async def list_practice_topics(
    subject: str = Query("math"),
    min_count: int = Query(5),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/practice/topics — 列出"有真实题库题（纯文本+带答案）"的练习主题及题量。

    供练习选题页用：知识体系是 GDMATH-* 命名，而题库题映射到 cmm-math-g{年级}-{主题} 键，
    这里直接列出有内容的 KU，避免学生点开练习是空的。
    """
    rows = (
        await db.execute(
            text(
                """
            select kv.key as ku_id, count(*) as n,
                   coalesce(max(ku.name), max(kv.value)) as ku_name
            from wrong_questions, jsonb_each_text(knowledge_points) as kv
            left join knowledge_units ku on ku.id = kv.key
            where student_id is null and subject = :subject and needs_image = false
              and correct_answer is not null and correct_answer <> ''
            group by kv.key having count(*) >= :min_count
            order by kv.key
            """
            ),
            {"subject": subject, "min_count": min_count},
        )
    ).all()
    return {
        "topics": [
            {"ku_id": r[0], "count": int(r[1]), "ku_name": r[2] or r[0]} for r in rows
        ]
    }



class PracticeSubmitReq(BaseModel):
    question_id: UUID  # 公共题库行（student_id IS NULL）
    student_id: UUID
    student_answer: str = ""
    is_correct: bool | None = (
        None  # None=先让后端自动判；自由作答判不了时再带自评二次提交
    )
    ku_id: str  # 对应知识单元 ID
    interleaved: bool = False  # 该题是否来自交错(混合KC)复习；True 才训练识别维度 p_recognition (M-G §4.5)
    predicted_confidence: float | None = Field(
        default=None, ge=0.0, le=1.0
    )  # JOL：作答前自评把握，供校准(努力错觉)分析
    self_explanation: str | None = Field(
        default=None, max_length=2000
    )  # 自我解释(Chi 效应,教育理念 04)：学生"为什么这么做"，纯采集
    student_steps: list[str] | None = Field(
        default=None
    )  # 解题步骤(教育理念 07·刻意练习)：答错时确定性定位首个错步


@router.post("/v1/practice/submit")
async def post_practice_submit(
    body: PracticeSubmitReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/practice/submit — 提交专题练习答案。仅学生本人可提交。

    学生做完一道题库题后调此接口：
    - 答错 → 写入该生 wrong_questions（不污染公共题库）
    - 调 cognitive_service.process_interaction 更新 BKT/FSRS
    - 返回掌握度更新结果
    """
    _ensure_student_self(current_user, body.student_id)
    # 1. 读公共题库行，确认 student_id IS NULL
    bank_q = (
        await db.execute(
            select(WrongQuestion).where(
                WrongQuestion.id == body.question_id, WrongQuestion.student_id.is_(None)
            )
        )
    ).scalar_one_or_none()
    if not bank_q:
        raise HTTPException(status_code=404, detail="公共题库题目不存在")
    correct_ans = (
        bank_q.correct_answer or ""
    )  # 先取出，避免 commit 后对象过期触发懒加载(MissingGreenlet)
    bank_subject = bank_q.subject or ""  # 同上，误解诊断要用，先取

    # 2. 自动判分（选择题/短答确定性判对错；自由作答判 unsure → 交学生对照答案自评）
    from oprim.answer_judge import judge_answer

    verdict = judge_answer(body.student_answer or "", correct_ans)["verdict"]
    auto_judged = verdict in ("correct", "wrong")
    if auto_judged:
        is_correct = verdict == "correct"
    elif body.is_correct is not None:
        is_correct = body.is_correct  # 第二次提交：带学生自评
    else:
        # 判不了 + 学生还没自评 → 揭示答案让其自评，先不落库
        return {
            "needs_self_grade": True,
            "auto_judged": False,
            "is_correct": None,
            "correct_answer": correct_ans,
            "p_mastery": None,
            "mastery_color": _mastery_color(None),
            "feedback": None,
        }

    # 3. 答错则写学生错题记录
    student_wq_id: UUID | None = None
    if not is_correct:
        student_wq = WrongQuestion(
            id=uuid.uuid4(),
            student_id=body.student_id,
            subject=bank_q.subject,
            question_text=bank_q.question_text,
            student_answer=body.student_answer or None,
            correct_answer=bank_q.correct_answer,
            knowledge_points=bank_q.knowledge_points or {body.ku_id: body.ku_id},
            needs_image=bank_q.needs_image,
        )
        db.add(student_wq)
        student_wq_id = student_wq.id
        await db.flush()

    # 4. BKT/FSRS 更新
    result = await process_interaction(
        db,
        student_id=body.student_id,
        kc_id=body.ku_id,
        is_correct=is_correct,
        question_id=bank_q.id,
        source="review",
        is_interleaved=body.interleaved,
        predicted_confidence=body.predicted_confidence,
        self_explanation=body.self_explanation,
    )
    await db.commit()

    # 刻意练习细颗粒反馈（教育理念 07）：答错且带步骤时，确定性定位首个错步（非整题重来）
    # U.24 教学机制 feature-flag（PEDAGOGY_FINE_FEEDBACK_ENABLED=0 急停）
    from services.feature_flags import PEDAGOGY_FINE_FEEDBACK, pedagogy_enabled

    step_analysis = None
    if (
        not is_correct
        and body.student_steps
        and pedagogy_enabled(PEDAGOGY_FINE_FEEDBACK)
    ):
        from oskill import verify_steps_chain

        chain = verify_steps_chain(body.student_steps)
        step_analysis = {
            "first_wrong_step": chain.get("first_wrong_step"),  # 0-based；None=未定位
            "step_verdicts": chain.get("step_verdicts"),
        }

    # L3 误解诊断（教育理念：答错→挂误解ID+重建方向，导向概念重建而非同类题再刷）
    misconception = None
    if not is_correct:
        from oprim.misconception import diagnose_misconception

        ku_name = (
            await db.execute(
                select(KnowledgeUnit.name).where(KnowledgeUnit.id == body.ku_id)
            )
        ).scalar_one_or_none()
        misconception = diagnose_misconception(
            bank_subject,
            ku_name or "",
            ku_id=body.ku_id,
            distractor=body.student_answer,
        )

    return {
        "is_correct": is_correct,
        "auto_judged": auto_judged,
        "needs_self_grade": False,
        "correct_answer": correct_ans,
        "wrong_question_id": str(student_wq_id) if student_wq_id else None,
        "p_mastery": result.get("p_mastery"),
        "mastery_color": _mastery_color(result.get("p_mastery")),
        "feedback": result.get("feedback"),
        "growth_message": result.get("growth_message"),  # 成长型措辞(05)
        "step_analysis": step_analysis,  # 首错步定位(07)
        "misconception": misconception,  # L3 误解诊断(答错才有)
    }


# start-for-ku → services/routers/socratic.py


# ===== §Instant Solve =====

import base64

from services.instant_solve_service import get_pg_pool, handle_instant_solve


@router.post("/v1/instant-solve")
async def post_instant_solve(
    kc_hint: str | None = Form(None),
    image: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    POST /v1/instant-solve
    随手拍单题（不给答案，苏格拉底引导）。
    """
    image_bytes = await image.read()
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    try:
        result = await handle_instant_solve(
            student_id=current_user.id, image_b64=image_b64, kc_hint=kc_hint
        )
        return result
    except Exception as e:
        # 不把内部异常原文回给客户端（可能泄露栈/连接串/内核细节），只记服务端日志。
        logger.error("instant-solve failed for %s: %s", current_user.id, e)
        raise HTTPException(status_code=500, detail="随手拍解析失败，请稍后重试")


class DeepSolveReq(BaseModel):
    problem_text: str


@router.post("/v1/deep-solve")
async def post_deep_solve(
    req: DeepSolveReq,
    current_user: User = Depends(get_current_user),
):
    """
    POST /v1/deep-solve
    深度解题多步推理：分析题目、提取考点、给出路线图。
    """
    from services.instant_solve_service import handle_deep_solve

    try:
        result = await handle_deep_solve(req.problem_text)
        return {"ok": True, "data": result}
    except Exception as e:
        logger.error("deep-solve failed for %s: %s", current_user.id, e)
        raise HTTPException(status_code=500, detail="深度推理解析失败，请稍后重试")


# ===== §Review Due / Quiz → services/routers/review.py =====

# ===== §Error Journal =====

from obase.error_tag_store import get_error_distribution


@router.get("/v1/error-journal/{student_id}")
async def get_error_journal(
    student_id: UUID,
    ku_id: str | None = Query(None),
    error_type: str | None = Query(None),
    subject: str | None = Query(None),
    limit: int = Query(20),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    GET /v1/error-journal/{student_id}
    错题本主动入口。鉴权：学生本人或绑定家长（原先任意家长可读）。
    L6 隐私分层：错题(过程数据)——家长需该生<12岁或已协商开放才可见。
    """
    await _ensure_student_access(db, current_user, student_id)
    from services.privacy import parent_sees_process

    if not await parent_sees_process(db, current_user, student_id):
        raise HTTPException(
            status_code=403, detail="过程数据（错题详情）默认仅学生本人可见"
        )

    # 1. Get distribution
    pool = await get_pg_pool()
    dist = await get_error_distribution(pool, student_id, ku_id)

    # 2. Get detailed wrong questions
    # Layer 4 query
    stmt = select(WrongQuestion).where(WrongQuestion.student_id == student_id)
    if ku_id:
        stmt = stmt.where(WrongQuestion.knowledge_points.has_key(ku_id))
    if subject:
        stmt = stmt.where(WrongQuestion.subject == subject)
    # Note: error_type filtering would require error_tag join if not in wrong_questions

    stmt = stmt.order_by(WrongQuestion.created_at.desc())
    all_rows = (await db.execute(stmt)).scalars().all()

    # 按题干去重：同一道题错多次合并成一条（计 wrong_count），保留最新一次
    seen: dict[str, dict] = {}
    for r in all_rows:
        key = (r.question_text or "").strip() or str(r.id)
        if key in seen:
            seen[key]["wrong_count"] += 1
        else:
            kid = (
                list(r.knowledge_points.keys())[0] if r.knowledge_points else "unknown"
            )
            seen[key] = {"row": r, "ku_id": kid, "wrong_count": 1}
    deduped = list(seen.values())  # dict 保序；all_rows 已按时间倒序
    page = deduped[offset : offset + limit]

    real_ids = {d["ku_id"] for d in page if d["ku_id"] != "unknown"}
    name_map: dict[str, str] = {}
    if real_ids:
        krows = (
            await db.execute(
                select(KnowledgeUnit.id, KnowledgeUnit.name).where(
                    KnowledgeUnit.id.in_(real_ids)
                )
            )
        ).all()
        name_map = {kid: nm for kid, nm in krows}

    res = []
    for d in page:
        r, kid = d["row"], d["ku_id"]
        _name = name_map.get(kid)
        if not _name:
            _kcd = get_kc(kid)
            _name = (_kcd.get("name") if _kcd else None) or kid
        res.append(
            {
                "question_id": str(r.id),
                "ku_id": kid,
                "ku_name": _name,
                "subject": r.subject or "math",
                "question_text": r.question_text or "",
                "student_answer": r.student_answer or "",
                "correct_answer": r.correct_answer or "",
                "error_tag": (r.error_type.value if r.error_type else "unknown"),
                "wrong_at": r.created_at.isoformat(),
                "wrong_count": d["wrong_count"],
                "can_practice_variant": True,
            }
        )

    return {"distribution": dist, "items": res}


