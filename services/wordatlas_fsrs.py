"""wordatlas_fsrs.py — FSRS-6 复习调度（纯函数，无数据库依赖）。

借鉴口径与定义署名：Word Atlas contributors — CC BY 4.0
（算法本身是公开的 FSRS 算法；署名针对借鉴的口径与定义：
四档评分、目标记忆率默认 90%、「稳定度 >= 21 天即掌握」、
只有第一次作答更新记忆、答错换题型重试不计分、
先复习到期项、再按 5 个一组学新项。）

本模块是照 FSRS 公开算法公式自己实现的干净实现，不复制
ts-fsrs / py-fsrs / fsrs-rs 的源码，也不依赖 pip 的 ``fsrs`` 包
（模块名特意不叫 ``fsrs``，避免遮蔽该包）。参数表取 FSRS-6
官方默认参数（21 维，衰减 w[20] = 0.1542，见
docs/FSRS-INTEGRATION.md 参数表与来源说明）。

与仓内既有 FSRS 的关系：
- services/fsrs_optimize_service.py 是权重选择（用真实复习日志
  在候选权重里择优），不负责单次调度；本模块是单次调度。
- services/learner_model.py 的 BKT 管掌握度推断（p_mastery、
  GATE、MASTERED）；本模块只管复测排期，绝不写 p_mastery
  或 mastery_confirmed（分工见 FSRS-INTEGRATION.md）。
- KCMastery.fsrs_card_json 已是仓内既有字段，本模块的
  to_dict/from_dict 与它兼容，但本模块本身不读库不写库：
  持久化是调用方的事，测试因此只用纯内存。

状态约定：
- 新卡：stability/difficulty 为 None，review_count == 0，due 为 None。
- 复习过的卡：stability（天）、difficulty（1~10）、due（下次到期
  时间）、last_review（上次作答时间）齐全。
- retrievability（可提取率 R）不是存量字段：它由 stability 与
  距上次作答的流逝天数算出（current_retrievability），目标记忆率
  desired_retention 只在算下次间隔时用，默认 0.90。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from typing import AbstractSet, Iterable, Optional, Sequence

# ── 署名（凡用到 word-atlas 口径处，文档与本模块头注均带此串）──
WORD_ATLAS_ATTRIBUTION = "Word Atlas contributors — CC BY 4.0"

# ── FSRS-6 默认参数（21 维；来源见 FSRS-INTEGRATION.md）──
DEFAULT_PARAMETERS: tuple[float, ...] = (
    0.212,   # w[0]  Again 首评初始稳定度（天）
    1.2931,  # w[1]  Hard 首评初始稳定度
    2.3065,  # w[2]  Good 首评初始稳定度
    8.2956,  # w[3]  Easy 首评初始稳定度
    6.4133,  # w[4]  初始难度基线
    0.8334,  # w[5]  初始难度评分因子
    3.0194,  # w[6]  难度变化率
    0.001,   # w[7]  难度均值回归强度
    1.8722,  # w[8]  成功后稳定度增长底数（取 exp）
    0.1666,  # w[9]  成功后稳定度衰减指数
    0.796,   # w[10] 成功后可提取率影响
    1.4835,  # w[11] 遗忘后稳定度基数
    0.0614,  # w[12] 遗忘后难度惩罚指数
    0.2629,  # w[13] 遗忘后稳定度保留指数
    1.6483,  # w[14] 遗忘后可提取率影响
    0.6014,  # w[15] Hard 惩罚乘子（<1）
    1.8729,  # w[16] Easy 奖励乘子（>1）
    0.5425,  # w[17] 短期稳定度评分因子
    0.0912,  # w[18] 短期稳定度评分偏移
    0.0658,  # w[19] 短期稳定度指数
    0.1542,  # w[20] 遗忘曲线衰减率（FSRS-6，FSRS-5 为 0.5）
)

DEFAULT_DESIRED_RETENTION = 0.90
MASTERED_STABILITY_DAYS = 21.0  # Word Atlas 口径：稳定度 >= 21 天即掌握
NEW_GROUP_SIZE = 5  # Word Atlas 每日旅程口径：新学项按 5 个一组取
MAX_INTERVAL_DAYS = 36500.0  # FSRS 默认最大间隔（100 年）
MIN_STABILITY = 0.1
MIN_INTERVAL_DAYS = 1.0 / 1440.0  # 1 分钟；本模块不用 Anki 式学习步进


class Rating(IntEnum):
    """四档评分；数值与仓内 InteractionEvent.fsrs_rating 一致。"""

    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


# ── gap drill 映射阈值 ──────────────────────────────────────────────
# FAST_THRESHOLD_MS 沿用仓内既有值：learning_scoring.derive_fsrs_rating
# 的 fast_threshold_ms 默认 3000（快 <= 3 秒为 Easy 的那条线）。
FAST_THRESHOLD_MS = 3000
# SLOW_THRESHOLD_MS 是本模块新增的策略参数（仓内此前只有快线、没有
# 慢线；见 FSRS-INTEGRATION.md）：gap drill 是单点微题，单题作答
# >= 30 秒视为吃力，答对也只给 Hard，不给 Good/Easy。
SLOW_THRESHOLD_MS = 30000


@dataclass
class FSRSState:
    """一张卡的 FSRS 状态（纯数据，可直接进 fsrs_card_json）。"""

    key: str = ""
    stability: Optional[float] = None  # 天；None = 新卡
    difficulty: Optional[float] = None  # 1~10；None = 新卡
    due: Optional[datetime] = None
    last_review: Optional[datetime] = None
    review_count: int = 0

    @property
    def is_new(self) -> bool:
        return self.review_count == 0 or self.stability is None


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, value))


def _as_aware(moment: datetime) -> datetime:
    """naive 时间按 UTC 计（仓内时间一律 UTC，见 practice_queue_service）。"""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _check_parameters(parameters: Sequence[float]) -> tuple[float, ...]:
    params = tuple(float(p) for p in parameters)
    if len(params) != 21:
        raise ValueError("FSRS 参数必须是 21 维")
    return params


def _check_retention(desired_retention: float) -> float:
    if not 0.0 < desired_retention < 1.0:
        raise ValueError("desired_retention 必须在 (0, 1) 之间")
    return float(desired_retention)


def _as_rating(rating: Rating | int) -> Rating:
    try:
        return Rating(int(rating))
    except (ValueError, TypeError) as exc:
        raise ValueError("rating 必须是 Again/Hard/Good/Easy（1~4）") from exc


# ── 遗忘曲线与间隔 ──────────────────────────────────────────────────
def forgetting_factor(parameters: Sequence[float] = DEFAULT_PARAMETERS) -> float:
    """遗忘曲线因子 F = 0.9 ** (1 / -decay) - 1，decay = w[20]。"""
    decay = _check_parameters(parameters)[20]
    return 0.9 ** (1.0 / -decay) - 1.0


def retrievability(
    elapsed_days: float,
    stability: float,
    parameters: Sequence[float] = DEFAULT_PARAMETERS,
) -> float:
    """可提取率 R(t, S) = (1 + F * t / S) ** (-decay)，取值 (0, 1]。"""
    params = _check_parameters(parameters)
    if stability <= 0:
        raise ValueError("stability 必须为正")
    if elapsed_days <= 0:
        return 1.0
    factor = forgetting_factor(params)
    return _clamp(
        (1.0 + factor * elapsed_days / stability) ** (-params[20]), 0.0, 1.0
    )


def interval_days(
    stability: float,
    desired_retention: float = DEFAULT_DESIRED_RETENTION,
    parameters: Sequence[float] = DEFAULT_PARAMETERS,
) -> float:
    """把遗忘曲线反解到目标记忆率时的间隔（天）。

    t = S / F * (R_d ** (-1 / decay) - 1)。目标 90% 时约等于 S 本身。
    """
    params = _check_parameters(parameters)
    retention = _check_retention(desired_retention)
    if stability <= 0:
        raise ValueError("stability 必须为正")
    factor = forgetting_factor(params)
    interval = stability / factor * (retention ** (-1.0 / params[20]) - 1.0)
    return _clamp(interval, MIN_INTERVAL_DAYS, MAX_INTERVAL_DAYS)


def current_retrievability(
    card: FSRSState,
    at: datetime,
    parameters: Sequence[float] = DEFAULT_PARAMETERS,
) -> Optional[float]:
    """卡在 ``at`` 时刻的可提取率；新卡返回 None（尚无记忆可提取）。"""
    if card.stability is None:
        return None
    last = card.last_review
    if last is None:
        return 1.0
    elapsed = (_as_aware(at) - _as_aware(last)).total_seconds() / 86400.0
    return retrievability(elapsed, card.stability, parameters)


# ── 难度与稳定度更新（FSRS-6 公式，见 FSRS-INTEGRATION.md）──
def initial_stability(
    rating: Rating | int, parameters: Sequence[float] = DEFAULT_PARAMETERS
) -> float:
    """首评初始稳定度 S0(G) = w[G-1]，下限 0.1 天。"""
    params = _check_parameters(parameters)
    return max(params[_as_rating(rating) - 1], MIN_STABILITY)


def initial_difficulty(
    rating: Rating | int, parameters: Sequence[float] = DEFAULT_PARAMETERS
) -> float:
    """首评初始难度 D0(G) = clamp(w[4] - exp(w[5] * (G-1)) + 1, 1, 10)。"""
    params = _check_parameters(parameters)
    grade = float(_as_rating(rating))
    return _clamp(params[4] - math.exp(params[5] * (grade - 1.0)) + 1.0, 1.0, 10.0)


def next_difficulty(
    difficulty: float,
    rating: Rating | int,
    parameters: Sequence[float] = DEFAULT_PARAMETERS,
) -> float:
    """难度更新：线性阻尼 + 向 Easy 首评难度均值回归，再 clamp 到 [1, 10]。

    D' = D + (-w[6] * (G-3)) * (10 - D) / 9
    D'' = w[7] * D0(4) + (1 - w[7]) * D'
    """
    params = _check_parameters(parameters)
    grade = float(_as_rating(rating))
    delta = -params[6] * (grade - 3.0)
    damped = difficulty + delta * (10.0 - difficulty) / 9.0
    reverted = params[7] * initial_difficulty(Rating.EASY, params) + (
        1.0 - params[7]
    ) * damped
    return _clamp(reverted, 1.0, 10.0)


def next_recall_stability(
    stability: float,
    difficulty: float,
    retrievability_value: float,
    rating: Rating | int,
    parameters: Sequence[float] = DEFAULT_PARAMETERS,
) -> float:
    """成功回忆（Hard/Good/Easy）后的稳定度。

    S' = S * (1 + m * exp(w[8]) * (11 - D) * S ** (-w[9])
                 * (exp((1 - R) * w[10]) - 1))
    m = w[15]（Hard）/ w[16]（Easy）/ 1（Good）。
    R < 1 时括号内为正，故成功回忆必不降低稳定度。
    """
    params = _check_parameters(parameters)
    grade = _as_rating(rating)
    if grade == Rating.AGAIN:
        raise ValueError("next_recall_stability 只用于成功回忆，Again 走遗忘分支")
    modifier = (
        params[15] if grade == Rating.HARD else params[16] if grade == Rating.EASY else 1.0
    )
    growth = (
        math.exp(params[8])
        * (11.0 - difficulty)
        * stability ** (-params[9])
        * (math.exp((1.0 - retrievability_value) * params[10]) - 1.0)
    )
    return max(stability * (1.0 + modifier * growth), MIN_STABILITY)


def next_forget_stability(
    stability: float,
    difficulty: float,
    retrievability_value: float,
    parameters: Sequence[float] = DEFAULT_PARAMETERS,
) -> float:
    """遗忘（Again）后的稳定度，含 FSRS-6 的上限钳制。

    S' = w[11] * D ** (-w[12]) * ((S + 1) ** w[13] - 1)
         * exp((1 - R) * w[14])
    S' = min(S', S / exp(w[17] * w[18]))
    上限保证 Again 必降低稳定度（至少约 4.8%，因 w[17]*w[18] 很小），
    且下限 0.1 天。
    """
    params = _check_parameters(parameters)
    raw = (
        params[11]
        * difficulty ** (-params[12])
        * ((stability + 1.0) ** params[13] - 1.0)
        * math.exp((1.0 - retrievability_value) * params[14])
    )
    capped = min(raw, stability / math.exp(params[17] * params[18]))
    return max(capped, MIN_STABILITY) if stability >= MIN_STABILITY else capped


def short_term_stability(
    stability: float,
    rating: Rating | int,
    parameters: Sequence[float] = DEFAULT_PARAMETERS,
) -> float:
    """同日复评（距上次作答 < 1 天）的短期稳定度（FSRS-6 短期分支）。

    sinc = exp(w[17] * (G - 3 + w[18])) * S ** (-w[19])
    S' = S * sinc；Good/Easy 不降低稳定度（S' >= S 的保底）。
    Again 不走本分支，走遗忘分支。
    """
    params = _check_parameters(parameters)
    grade = _as_rating(rating)
    if grade == Rating.AGAIN:
        raise ValueError("short_term_stability 不用于 Again，Again 走遗忘分支")
    sinc = math.exp(params[17] * (float(grade) - 3.0 + params[18])) * stability ** (
        -params[19]
    )
    new_value = stability * sinc
    if grade >= Rating.GOOD:
        new_value = max(new_value, stability)
    return max(new_value, MIN_STABILITY)


# ── 单次调度 ────────────────────────────────────────────────────────
def review(
    card: FSRSState,
    rating: Rating | int,
    now: datetime,
    *,
    parameters: Sequence[float] = DEFAULT_PARAMETERS,
    desired_retention: float = DEFAULT_DESIRED_RETENTION,
) -> tuple[FSRSState, dict]:
    """对一张卡施加一次评分，返回（新卡，说明）。

    分支：新卡 → 初始 S/D；Again → 遗忘分支；同日复评（< 1 天）
    且成功 → 短期分支；其余成功 → 回忆分支。难度每次都更新。
    下次到期 = now + interval_days(新稳定度)。
    本函数是纯函数：不改入参卡，不读库，不写库。
    """
    params = _check_parameters(parameters)
    retention = _check_retention(desired_retention)
    grade = _as_rating(rating)
    moment = _as_aware(now)

    if card.is_new:
        new_stability = initial_stability(grade, params)
        new_difficulty = initial_difficulty(grade, params)
        branch = "initial"
        before_r: Optional[float] = None
        elapsed_days: Optional[float] = None
    else:
        assert card.stability is not None and card.difficulty is not None
        old_stability = card.stability
        if card.last_review is None:
            elapsed_days = 0.0
        else:
            elapsed_days = max(
                0.0, (moment - _as_aware(card.last_review)).total_seconds() / 86400.0
            )
        before_r = retrievability(elapsed_days, old_stability, params)
        new_difficulty = next_difficulty(card.difficulty, grade, params)
        if grade == Rating.AGAIN:
            new_stability = next_forget_stability(
                old_stability, card.difficulty, before_r, params
            )
            branch = "forget"
        elif elapsed_days < 1.0:
            new_stability = short_term_stability(old_stability, grade, params)
            branch = "short_term"
        else:
            new_stability = next_recall_stability(
                old_stability, card.difficulty, before_r, grade, params
            )
            branch = "recall"

    interval = interval_days(new_stability, retention, params)
    new_card = FSRSState(
        key=card.key,
        stability=new_stability,
        difficulty=new_difficulty,
        due=moment + timedelta(days=interval),
        last_review=moment,
        review_count=card.review_count + 1,
    )
    info = {
        "rating": grade.name,
        "branch": branch,
        "stability_before": card.stability,
        "stability_after": new_stability,
        "difficulty_after": new_difficulty,
        "retrievability_before": before_r,
        "elapsed_days": elapsed_days,
        "interval_days": interval,
        "due": new_card.due,
    }
    return new_card, info


def is_mastered(card: FSRSState) -> bool:
    """Word Atlas 口径：已掌握 = FSRS 复习状态且稳定度 >= 21 天。"""
    return card.stability is not None and card.stability >= MASTERED_STABILITY_DAYS


# ── 序列化（与 KCMastery.fsrs_card_json 兼容的键名）──
def to_dict(card: FSRSState) -> dict:
    return {
        "key": card.key,
        "stability": card.stability,
        "difficulty": card.difficulty,
        "due": card.due.isoformat() if card.due else None,
        "last_review": card.last_review.isoformat() if card.last_review else None,
        "review_count": card.review_count,
    }


def from_dict(data: dict) -> FSRSState:
    def _parse(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        parsed = datetime.fromisoformat(value)
        return _as_aware(parsed)

    return FSRSState(
        key=str(data.get("key") or ""),
        stability=data.get("stability"),
        difficulty=data.get("difficulty"),
        due=_parse(data.get("due")),
        last_review=_parse(data.get("last_review")),
        review_count=int(data.get("review_count") or 0),
    )


# ── gap drill 作答 → 四档映射 ───────────────────────────────────────
def map_gap_drill_to_rating(answer: dict) -> Optional[Rating]:
    """gap drill 一次作答 → FSRS 四档；不计分时返回 None。

    输入（dict，键名以仓内实有字段为准，缺失则按规则退化）：
    - result/verdict：gap_drill_service 会话 results 条目的 "result"
     （correct/wrong/skip）；或 is_correct（bool）兜底。
    - self_assessed：gap_drill_service.answer_drill 返回的 answered
      里的同名字段；为 True 表示自评，不计分。
    - used_hint：learning_engine.submit_answer 的同名参数。
    - hints_used：QuestionRecord.hints_used（> 0 即用过提示）。
    - latency_ms / duration_ms / response_time_ms：三者任一，
      分别对应 learning_engine.latency_ms、QuestionRecord.duration_ms、
      MCP SubmitAnswer 的 response_time_ms；取首个非空值。

    关键事实：gap_drill_service 的会话 results 条目本身只有
    question_id/ku_id/result 三个键，没有耗时、没有提示字段——
    所以耗时与提示必须由调用方从上述作答路径传入，本函数绝不
    从会话 results 里编造它们；两者都缺省时答对只给 Good。

    映射表（Word Atlas 口径 + 仓内既有线对齐）：
    - 自评 / skip → None（不更新 FSRS；gap drill 红线是自评/skip
      不回写掌握度，FSRS 排期同理不写；与词汇线的 SKIPPED→AGAIN
      不同，那是另一条线的既有约定，本映射不照搬）。
    - wrong → Again。
    - correct + 用提示 → Hard（与 derive_fsrs_rating 的
      PARTIAL/used_hint→HARD 一致）。
    - correct + latency >= SLOW_THRESHOLD_MS（30 秒）→ Hard
      （本模块新增慢线；仓内此前只有快线）。
    - correct + latency <= FAST_THRESHOLD_MS（3 秒，沿用仓内
      derive_fsrs_rating 的 fast_threshold_ms 默认值）→ Easy。
    - correct + 其余 → Good。
    """
    if not isinstance(answer, dict):
        raise ValueError("answer 必须是 dict")
    if answer.get("self_assessed"):
        return None
    result = answer.get("result", answer.get("verdict"))
    if result is None and "is_correct" in answer:
        result = "correct" if answer.get("is_correct") else "wrong"
    if result is None:
        raise ValueError("answer 缺少 result/verdict/is_correct")
    result = str(result).strip().lower()
    if result == "skip":
        return None
    if result == "wrong":
        return Rating.AGAIN
    if result != "correct":
        raise ValueError(f"未知的 gap drill 结果：{result!r}")
    if answer.get("used_hint") or int(answer.get("hints_used") or 0) > 0:
        return Rating.HARD
    latency = None
    for key in ("latency_ms", "duration_ms", "response_time_ms"):
        if answer.get(key) is not None:
            latency = answer.get(key)
            break
    if latency is not None:
        latency = float(latency)
        if latency >= SLOW_THRESHOLD_MS:
            return Rating.HARD
        if latency <= FAST_THRESHOLD_MS:
            return Rating.EASY
    return Rating.GOOD


# ── 调用层：同一轮重答不重复计分 ───────────────────────────────────
def apply_review(
    card: FSRSState,
    rating: Rating | int,
    now: datetime,
    *,
    review_id: Optional[str] = None,
    applied_ids: Optional[AbstractSet[str]] = None,
    parameters: Sequence[float] = DEFAULT_PARAMETERS,
    desired_retention: float = DEFAULT_DESIRED_RETENTION,
) -> tuple[FSRSState, bool, Optional[set[str]]]:
    """施加一次评分并做幂等：同一 review_id 只计分一次。

    返回（卡，是否本次计分，更新后的已计分 id 集合）。
    第二次传同一 review_id 时返回原卡不动、applied=False——这就是
    「同一轮重答不重复计分」与 Word Atlas「只有第一次作答更新记忆、
    答错换题型重试不计分」的落地点：重试（即使换了题型、即使
    这次答对了）也不改卡；该卡按第一次的 Again 排期，下一轮再计分。
    review_id 为 None 时不做幂等（调用方自担去重），照常计分。
    """
    if review_id is not None and applied_ids is not None and review_id in applied_ids:
        return card, False, set(applied_ids)
    new_card, _info = review(
        card, rating, now, parameters=parameters, desired_retention=desired_retention
    )
    if review_id is None:
        return new_card, True, applied_ids if applied_ids is None else set(applied_ids)
    updated = set(applied_ids) if applied_ids is not None else set()
    updated.add(review_id)
    return new_card, True, updated


def apply_gap_drill_answer(
    card: FSRSState,
    answer: dict,
    now: datetime,
    *,
    session_id: Optional[str] = None,
    review_id: Optional[str] = None,
    applied_ids: Optional[AbstractSet[str]] = None,
    parameters: Sequence[float] = DEFAULT_PARAMETERS,
    desired_retention: float = DEFAULT_DESIRED_RETENTION,
) -> tuple[FSRSState, Optional[Rating], bool, Optional[set[str]]]:
    """gap drill 一次作答 → 映射 → 幂等施加，返回（卡，档位，是否计分，id 集）。

    review_id 优先显式传入；否则 session_id 给定时按
    gap:{session_id}:{卡 key 或答案 ku_id} 生成——同一节 drill 里
    同一 KU 只计第一次作答的分，同一 KU 的换题型重试不重复计分。
    不计分（自评/skip）时不占 review_id：之后同一节里该 KU 的
    真实作答仍可计分。
    """
    rating = map_gap_drill_to_rating(answer)
    if rating is None:
        return card, None, False, applied_ids if applied_ids is None else set(applied_ids)
    rid = review_id
    if rid is None and session_id is not None:
        subject = card.key or str(answer.get("ku_id") or "card")
        rid = f"gap:{session_id}:{subject}"
    new_card, applied, updated = apply_review(
        card,
        rating,
        now,
        review_id=rid,
        applied_ids=applied_ids,
        parameters=parameters,
        desired_retention=desired_retention,
    )
    return new_card, rating, applied, updated


# ── 复习队列：先到期、再 5 个一组学新 ───────────────────────────────
def build_review_queue(
    cards: Iterable[FSRSState],
    now: datetime,
    *,
    group_size: int = NEW_GROUP_SIZE,
) -> dict:
    """组装一轮复习队列（Word Atlas 每日旅程口径）。

    顺序：已到期项在前（due <= now，最久逾期的在最前）；然后是
    新学项，按传入顺序取 group_size 个一组（默认 5 个）。
    未到期项不进队列，单列 upcoming（按 due 升序）供展示。
    新学项判定：review_count == 0 或 due 为 None（且未到期）。
    返回 {"queue", "due", "new_batch", "new_remaining", "upcoming",
    "due_count", "new_batch_count"}；queue = due + new_batch。
    """
    if group_size < 1:
        raise ValueError("group_size 至少为 1")
    moment = _as_aware(now)
    due: list[FSRSState] = []
    new: list[FSRSState] = []
    upcoming: list[FSRSState] = []
    for card in cards:
        if card.due is not None and _as_aware(card.due) <= moment:
            due.append(card)
        elif card.is_new:
            new.append(card)
        elif card.due is not None:
            upcoming.append(card)
        else:  # 有复习记录却无 due：视为新学（防御分支，不应常见）
            new.append(card)
    due.sort(key=lambda c: _as_aware(c.due))  # type: ignore[arg-type]
    upcoming.sort(key=lambda c: _as_aware(c.due))  # type: ignore[arg-type]
    new_batch = new[:group_size]
    queue = due + new_batch
    return {
        "queue": queue,
        "due": due,
        "new_batch": new_batch,
        "new_remaining": new[group_size:],
        "upcoming": upcoming,
        "due_count": len(due),
        "new_batch_count": len(new_batch),
    }
