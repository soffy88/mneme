from __future__ import annotations
import hashlib
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Sequence, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from oprim import due_compute
from oskill import variant_for_review, ReviewVariantInput
from omodul.due_recall_push import (
    due_recall_push_workflow,
    DueRecallPushConfig,
    DueRecallPushInput,
)
from services.models import (
    InteractionEvent,
    InteractionSource,
    KCMastery,
    WrongQuestion,
)
from obase.provider_registry import ProviderRegistry
from obase.persistence.pool import PgPool
from obase.config import settings

# ── 保留探针（T.2）：30 天保留抽测埋点 ───────────────────────────────────────
# 复习队列约 1/20 天混入一张"远未到期的稳定卡"，学生作答结果 vs 当时预测 R
# 即可实测真实遗忘曲线（校准数据从此有米下锅）。探针对前端透明——就是队列里普通一项。
_PROBE_RATE_DENOMINATOR = 20  # ≈1/20 概率
_PROBE_RECENT_DAYS = 7  # 最近 7 天被探测过的卡不再抽中
_PROBE_MIN_HOURS_SINCE_REVIEW = (
    24.0  # 距上次 FSRS 复习不足 24h 不算探针（排除到期复习后的重复提交）
)


def probe_gate(student_id: uuid.UUID, on_date: date) -> bool:
    """确定性伪随机门：同一 (学生, 日期) 结果恒定（sha256，跨进程可复现，
    不用 random.random——不可测的坑已有先例），约 1/20 的天命中。"""
    digest = hashlib.sha256(
        f"probe:{student_id}:{on_date.isoformat()}".encode()
    ).digest()
    return int.from_bytes(digest[:8], "big") % _PROBE_RATE_DENOMINATOR == 0


def _parse_card_ts(raw: object) -> Optional[datetime]:
    """解析 fsrs_card_json 里的时间字段（ISO 字符串或 datetime）。"""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


async def _pick_probe_card(
    db: AsyncSession,
    student_id: uuid.UUID,
    masteries: Sequence[KCMastery],
    *,
    now: datetime,
) -> Optional[KCMastery]:
    """选保留探针卡：已复习过（有 last_review）、**未到期**（due 在未来）的卡中，
    取 due 距今最远者（平手按 stability 高者）；最近 7 天已被探测过的 KC 排除。"""
    recent_cutoff = now - timedelta(days=_PROBE_RECENT_DAYS)
    recently_probed = {
        kc
        for (kc,) in (
            await db.execute(
                select(InteractionEvent.knowledge_point)
                .where(InteractionEvent.student_id == student_id)
                .where(InteractionEvent.source == InteractionSource.probe)
                .where(InteractionEvent.occurred_at >= recent_cutoff)
                .distinct()
            )
        ).all()
    }

    best: Optional[Tuple[datetime, float, KCMastery]] = None
    for m in masteries:
        card = m.fsrs_card_json
        if not card or m.knowledge_point in recently_probed:
            continue
        if _parse_card_ts(card.get("last_review")) is None:
            continue  # 从未复习过的卡没有可信的预测 R
        due = _parse_card_ts(card.get("due"))
        if due is None or due <= now:
            continue  # 只有"远未到期"的卡才当探针；到期卡走正常复习
        stability = float(card.get("stability") or 0.0)
        key = (due, stability)
        if best is None or key > (best[0], best[1]):
            best = (due, stability, m)
    return best[2] if best else None


async def _probe_context(
    db: AsyncSession,
    student_id: uuid.UUID,
    kc_id: str,
    *,
    now: Optional[datetime] = None,
) -> Tuple[str, Optional[float]]:
    """判定本次复习作答是否保留探针，返回 (source, predicted_r)。

    探针判据（与队列侧混入规则一致，无须前端回传标记）：该 KC 的卡片**未到期**
    （正常复习队列只发到期卡）且距上次 FSRS 复习 ≥24h（排除到期复习刚提交后的
    重复提交被误判）。是探针则算出**此刻**的 FSRS 预测可提取性 R（用该生实际
    生效的个性化权重，与调度同口径）随事件落库。

    U.18 迁移探针优先判定：Redis 里若缓存着该 (student, kc) 的迁移探针答案
    （由 transfer_probe_service 现场生成时写入），说明这就是一道迁移探针，
    直接返回 source="transfer_probe"（不需要 predicted_r，那是 FSRS 保留探针
    专属概念）——优先于下面的保留探针时序判定，避免同一 KU 被误判成保留探针。"""
    from services.transfer_probe_service import get_cached_transfer_probe_answer

    if await get_cached_transfer_probe_answer(student_id, kc_id):
        return "transfer_probe", None

    now = now or datetime.now(timezone.utc)
    card = (
        await db.execute(
            select(KCMastery.fsrs_card_json).where(
                KCMastery.student_id == student_id, KCMastery.knowledge_point == kc_id
            )
        )
    ).scalar_one_or_none()
    if not card:
        return "review", None
    last_review = _parse_card_ts(card.get("last_review"))
    if last_review is None or due_compute(card_dict=card, now=now):
        return "review", None
    if (now - last_review).total_seconds() < _PROBE_MIN_HOURS_SINCE_REVIEW * 3600:
        return "review", None
    from oprim.fsrs_engine import fsrs_retrievability
    from services.fsrs_optimize_service import load_weights_for_student

    params = await load_weights_for_student(db, student_id)
    r = fsrs_retrievability(card_dict=card, now=now, parameters=params)
    return "probe", round(float(r), 4)


async def get_pg_pool() -> PgPool:
    dsn = settings.DATABASE_URL.replace("+asyncpg", "")
    return await PgPool.get_or_create(dsn=dsn)


# ── 变式答案一致性（P0-5 红线）────────────────────────────────────────────────
# 红线：有 solve_* 覆盖的题型，数值结论必来自内核；变式的判分答案必须与**展示的题面**
# 一致。submit/reveal 是无状态的（只按 kc_id 反查原题答案），因此若展示了数值不同的
# LLM 变式，却仍用原题答案判分 = 误判（诱导错误）。修法：
#   · 只有当变式**内核已验证**（kernel_verified 且带 answer）才展示变式题面，
#     并把该内核答案随 (student, kc) 缓存进 Redis；submit/reveal 优先用它。
#   · 未验证的变式一律降级为**同题复现**（展示原题面），原答案天然一致。
_REVIEW_ANSWER_TTL = 3600  # 展示后 1h 内提交/揭示都用同一内核答案


def _review_answer_key(student_id: uuid.UUID, kc_id: str) -> str:
    return f"review_variant_answer:{student_id}:{kc_id}"


async def _cache_variant_answer(student_id: uuid.UUID, kc_id: str, answer: str) -> None:
    import redis.asyncio as aioredis

    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await r.setex(_review_answer_key(student_id, kc_id), _REVIEW_ANSWER_TTL, answer)
    finally:
        await r.aclose()


async def _answer_for_review(
    db: AsyncSession, student_id: uuid.UUID, kc_id: str
) -> str:
    """判分/揭示用的答案：优先取 U.18 迁移探针的内核答案，其次取"本次展示的内核
    已验证变式答案"（Redis），否则回退原错题答案（同题复现路径，题面=原题，答案天然一致）。"""
    from services.transfer_probe_service import get_cached_transfer_probe_answer

    transfer_answer = await get_cached_transfer_probe_answer(student_id, kc_id)
    if transfer_answer:
        return str(transfer_answer)

    import redis.asyncio as aioredis

    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        cached = await r.get(_review_answer_key(student_id, kc_id))
    finally:
        await r.aclose()
    if cached:
        return str(cached)
    return await _original_answer_for_kc(db, student_id, kc_id)


async def get_due_variants(
    db: AsyncSession, student_id: uuid.UUID, *, generate_variants: bool = False
) -> List[dict]:
    """到期复习池。默认**不**逐卡同步调 LLM 生成变式（性能/稳定性）——直接发原题面
    供检索练习；generate_variants=True 才生成变式（变式纯锦上添花，非闭环必需）。"""
    # 1. Fetch all mastery for student
    stmt = select(KCMastery).where(KCMastery.student_id == student_id)
    masteries = (await db.execute(stmt)).scalars().all()

    due_items = []
    now = datetime.now(timezone.utc)

    caller = (
        (ProviderRegistry.get().llm() if ProviderRegistry._instance else None)
        if generate_variants
        else None
    )

    for m in masteries:
        if not m.fsrs_card_json:
            continue

        # 2. Check if due
        is_due = due_compute(card_dict=m.fsrs_card_json, now=now)
        if is_due:
            # Find an original question for context
            wq_stmt = (
                select(WrongQuestion)
                .where(
                    WrongQuestion.student_id == student_id,
                    WrongQuestion.knowledge_points.has_key(m.knowledge_point),
                )
                .limit(1)
            )
            wq = (await db.execute(wq_stmt)).scalar_one_or_none()

            orig_q = wq.question_text if wq else "已知知识点为 " + m.knowledge_point
            orig_a = wq.correct_answer if wq else "无"

            # 默认走原题面（无 LLM、无 N+1 延迟）；仅在显式开启变式时调 LLM。
            # 红线（P0-5）：只有**内核已验证**的变式（kernel_verified 且带 answer）才展示，
            # 并缓存其内核答案供 submit/reveal 判分；否则一律降级同题复现（原题面），
            # 绝不展示"数值改了但仍用原答案判分"的变式。
            question_text = orig_q
            answer_source = "original"
            if generate_variants:
                try:
                    variant = await variant_for_review(
                        ReviewVariantInput(
                            student_id=str(student_id),
                            kc_id=m.knowledge_point,
                            original_question=orig_q,
                            original_answer=orig_a,
                        ),
                        caller=caller,
                    )
                    if (
                        variant
                        and variant.question
                        and variant.kernel_verified
                        and variant.answer
                    ):
                        question_text = variant.question
                        answer_source = "kernel"
                        await _cache_variant_answer(
                            student_id, m.knowledge_point, variant.answer
                        )
                    # 未内核验证 → 保持原题面（同题复现），不误判
                except Exception:
                    pass  # 用原题面兜底，不丢到期项

            # 检索练习红线（item 4）：到期复习只发题面，**不附答案**——
            # 学生必须先尝试回忆作答；答案只能经 reveal/submit 显式获取，
            # 而"看答案=放弃检索"会被 reveal 记为 FSRS Again。
            due_items.append(
                {
                    "ku_id": m.knowledge_point,
                    "variant_question": question_text,
                    "answer_source": answer_source,  # kernel(内核验证变式) | original(同题复现)
                    "requires_retrieval": True,
                    # 原错题 id（供复习页"问问AI"接苏格拉底；无原题则 None）
                    "question_id": str(wq.id) if wq else None,
                    "due_since": m.last_interaction_at.isoformat()
                    if m.last_interaction_at
                    else None,
                    "fsrs_interval": m.fsrs_card_json.get("stability", 0),
                }
            )

    # 保留探针（T.2）：约 1/20 天（确定性哈希门，同日同生结果可复现）额外混入
    # 一张远未到期的稳定卡。探针同样只发题面**不带答案**（检索门红线），对前端
    # 透明；作答走现有 submit/reveal 路径，由 _probe_context 在提交侧识别落
    # source="probe" + predicted_r，并照常更新 BKT/FSRS（本就是一次真实检索）。
    if probe_gate(student_id, now.date()):
        probe = await _pick_probe_card(db, student_id, masteries, now=now)
        if probe is not None:
            p_wq = (
                await db.execute(
                    select(WrongQuestion)
                    .where(
                        WrongQuestion.student_id == student_id,
                        WrongQuestion.knowledge_points.has_key(probe.knowledge_point),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            due_items.append(
                {
                    "ku_id": probe.knowledge_point,
                    "variant_question": p_wq.question_text
                    if p_wq
                    else "已知知识点为 " + probe.knowledge_point,
                    "requires_retrieval": True,
                    "question_id": str(p_wq.id) if p_wq else None,
                    "due_since": probe.last_interaction_at.isoformat()
                    if probe.last_interaction_at
                    else None,
                    "fsrs_interval": (probe.fsrs_card_json or {}).get("stability", 0),
                }
            )

    # 迁移探针（U.18）：独立于 generate_variants 参数——它是这条队列里**唯一**必须
    # 现场生成才有意义的项（同题复现无法测迁移），由自己的概率门（约1/20天）控制
    # 调用频率，与"是否愿意为常规变式付 LLM 成本"的参数解耦，否则默认关闭的
    # generate_variants 会让 U.18 和 R.14/R.15 一样变成永远不触发的死配置。
    from services.transfer_probe_service import maybe_build_transfer_probe

    transfer_item = await maybe_build_transfer_probe(
        db, student_id, masteries, caller=caller, now=now
    )
    if transfer_item is not None:
        due_items.append(transfer_item)

    if due_items:
        # 4. Wrap with due_recall_push (omodul)
        # Note: omodul.due_recall_push_workflow might trigger actual push (e.g. Telegram)
        # Here we just use it for the "business transaction" recording if needed.
        pool = await get_pg_pool()
        await due_recall_push_workflow(
            config=DueRecallPushConfig(),
            input_data=DueRecallPushInput(
                batch_id=str(uuid.uuid4()), due_items=due_items
            ),
            pool=pool,
        )

    return due_items


async def _original_answer_for_kc(
    db: AsyncSession, student_id: uuid.UUID, kc_id: str
) -> str:
    """取该 kc 一条原错题的参考答案（复习核对/揭示用）。"""
    wq = (
        await db.execute(
            select(WrongQuestion)
            .where(
                WrongQuestion.student_id == student_id,
                WrongQuestion.knowledge_points.has_key(kc_id),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return (wq.correct_answer if wq else "") or ""


async def reveal_review_answer(
    db: AsyncSession, student_id: uuid.UUID, kc_id: str
) -> dict:
    """揭示复习答案（学生放弃检索）。检索练习红线：看答案 = FSRS Again。

    记一次 used_answer=True 的交互（映射 Again，掌握度按答错衰减），再返回答案。
    探针卡看答案 = 召回失败，也是有效探针信号（source=probe + predicted_r）。
    """
    from services.cognitive_service import process_interaction

    answer = await _answer_for_review(db, student_id, kc_id)
    source, predicted_r = await _probe_context(db, student_id, kc_id)
    await process_interaction(
        db,
        student_id=student_id,
        kc_id=kc_id,
        is_correct=False,
        question_type="solve",
        source=source,
        used_answer=True,  # 看答案 → fsrs_map_rating 返回 Again
        predicted_r=predicted_r,
    )
    return {"ku_id": kc_id, "answer": answer, "recorded_again": True}


async def submit_review_answer(
    db: AsyncSession, student_id: uuid.UUID, kc_id: str, student_answer: str
) -> dict:
    """提交复习作答（先检索后核对）。确定性判分并记入 BKT/FSRS，再返回参考答案。"""
    from oprim.answer_judge import judge_answer
    from services.cognitive_service import process_interaction

    answer = await _answer_for_review(db, student_id, kc_id)
    verdict = judge_answer(student_answer, answer).get("verdict", "unsure")
    # unsure（自由作答）按"未确定"不武断判错：交学生自评，这里仅在可判定时入算法
    if verdict in ("correct", "wrong"):
        # 保留探针识别：未到期卡的作答即探针 → source="probe" + 当时预测 R 落事件
        source, predicted_r = await _probe_context(db, student_id, kc_id)
        await process_interaction(
            db,
            student_id=student_id,
            kc_id=kc_id,
            is_correct=(verdict == "correct"),
            question_type="solve",
            source=source,
            predicted_r=predicted_r,
        )
    return {"ku_id": kc_id, "verdict": verdict, "answer": answer}
