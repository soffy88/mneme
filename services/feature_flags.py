"""U.24 教学机制 feature-flag 化：pedagogy/01-08 各机制的开关读取。

同 fsrs_optimize_service.fitting_enabled()/TEACHING_ENGINE_ENABLED 既有约定——
env 一票否决，默认开（保留当前上线行为），显式设为 "0"/"false" 才关闭。这是运维
急停开关，不是 A/B 实验分流（那个是 experiment_service 的 EXPERIMENT_* 系列）。
"""

from __future__ import annotations

import os


def pedagogy_enabled(env_name: str) -> bool:
    """env 未设置或非 "0"/"false" 均视为开（默认保留现状）。"""
    return os.environ.get(env_name, "1").lower() not in ("0", "false")


def learning_event_v2_dual_write_enabled() -> bool:
    """Enable v2 dual-write only after the learning_events migration is deployed."""

    return os.environ.get(LEARNING_EVENT_V2_DUAL_WRITE, "0").lower() in (
        "1",
        "true",
        "yes",
    )


def learning_event_v2_backfill_enabled() -> bool:
    """Allow historical writes only during an explicitly approved backfill window."""

    return os.environ.get(LEARNING_EVENT_V2_BACKFILL, "0").lower() in (
        "1",
        "true",
        "yes",
    )


# pedagogy/01-08 对应的 env 变量名（单源，散落字面量一律迁移引用此处）
PEDAGOGY_FRINGE = "PEDAGOGY_FRINGE_ENABLED"  # 01 掌握门控+知识空间选题
PEDAGOGY_LEAGUE = "PEDAGOGY_LEAGUE_ENABLED"  # 02 SDT 留存-归属(匿名联赛)
PEDAGOGY_OLM = "PEDAGOGY_OLM_ENABLED"  # 03 开放学习者模型
PEDAGOGY_SELF_EXPLANATION = "PEDAGOGY_SELF_EXPLANATION_ENABLED"  # 04 自我解释采集
PEDAGOGY_GROWTH_FEEDBACK = "PEDAGOGY_GROWTH_FEEDBACK_ENABLED"  # 05 成长型思维反馈
PEDAGOGY_EXAM_AWARE = "PEDAGOGY_EXAM_AWARE_ENABLED"  # 06 考期感知调度
PEDAGOGY_FINE_FEEDBACK = "PEDAGOGY_FINE_FEEDBACK_ENABLED"  # 07 刻意练习细颗粒反馈
PEDAGOGY_AFFECT = "PEDAGOGY_AFFECT_ENABLED"  # 08 情感感知
LEARNING_EVENT_V2_DUAL_WRITE = "LEARNING_EVENT_V2_DUAL_WRITE_ENABLED"
LEARNING_EVENT_V2_BACKFILL = "LEARNING_EVENT_V2_BACKFILL_ENABLED"


# Real-world validation rollout controls.  Every flag is fail-closed: pilot
# behavior is opt-in, cohort-scoped and kill-switchable.  These switches may
# annotate/schedule/measure existing LearningEvents, but never bypass the
# normal event -> projection -> policy path.
PILOT_MODE = "PILOT_MODE"
PILOT_PROTOCOL_ID = "PILOT_PROTOCOL_ID"
PILOT_PROTOCOL_VERSION = "PILOT_PROTOCOL_VERSION"
PILOT_COHORT_ID = "PILOT_COHORT_ID"
PILOT_ENABLED = "PILOT_ENABLED"
PILOT_COHORT_ALLOWLIST = "PILOT_COHORT_ALLOWLIST"
PILOT_POLICY_EXPERIMENT_ENABLED = "PILOT_POLICY_EXPERIMENT_ENABLED"
PILOT_INDEPENDENT_EVAL_ENABLED = "PILOT_INDEPENDENT_EVAL_ENABLED"
PILOT_KILL_SWITCH = "PILOT_KILL_SWITCH"
DEMO_MODE = "DEMO_MODE"
NOTIFICATIONS_ENABLED = "NOTIFICATIONS_ENABLED"


def _explicitly_on(name: str) -> bool:
    return os.environ.get(name, "0").lower() in ("1", "true", "yes", "on")


def pilot_mode_enabled() -> bool:
    return _explicitly_on(PILOT_MODE)


def pilot_enabled() -> bool:
    return _explicitly_on(PILOT_ENABLED)


def pilot_kill_switch_active() -> bool:
    return _explicitly_on(PILOT_KILL_SWITCH)


def pilot_cohort_allowlist() -> frozenset[str]:
    raw = os.environ.get(PILOT_COHORT_ALLOWLIST, "")
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def pilot_cohort_allowed(cohort_id: str) -> bool:
    return bool(cohort_id) and cohort_id in pilot_cohort_allowlist()


def pilot_is_active(cohort_id: str) -> bool:
    """Return whether pilot-specific behavior may run for this cohort."""

    return (
        pilot_mode_enabled()
        and pilot_enabled()
        and not pilot_kill_switch_active()
        and bool(os.environ.get(PILOT_PROTOCOL_ID, "").strip())
        and bool(os.environ.get(PILOT_PROTOCOL_VERSION, "").strip())
        and cohort_id == os.environ.get(PILOT_COHORT_ID, "").strip()
        and pilot_cohort_allowed(cohort_id)
    )


def pilot_policy_experiment_enabled() -> bool:
    return _explicitly_on(PILOT_POLICY_EXPERIMENT_ENABLED) and not pilot_kill_switch_active()


def pilot_independent_eval_enabled() -> bool:
    return _explicitly_on(PILOT_INDEPENDENT_EVAL_ENABLED) and not pilot_kill_switch_active()


def pilot_config() -> dict[str, object]:
    """Expose non-secret rollout state for readiness/ops surfaces."""

    return {
        "pilot_mode": pilot_mode_enabled(),
        "pilot_enabled": pilot_enabled(),
        "pilot_protocol_id": os.environ.get(PILOT_PROTOCOL_ID) or None,
        "pilot_protocol_version": os.environ.get(PILOT_PROTOCOL_VERSION) or None,
        "pilot_cohort_id": os.environ.get(PILOT_COHORT_ID) or None,
        "cohort_allowlist_configured": bool(pilot_cohort_allowlist()),
        "policy_experiment_enabled": pilot_policy_experiment_enabled(),
        "independent_eval_enabled": pilot_independent_eval_enabled(),
        "kill_switch_active": pilot_kill_switch_active(),
    }


def demo_mode_enabled() -> bool:
    """Enable explicitly marked synthetic demo content only in non-production."""

    return _explicitly_on(DEMO_MODE) and os.environ.get("MNEME_ENV", "dev").lower() != "prod"


def notifications_enabled() -> bool:
    """Notifications are opt-in; this flag never sends a notification itself."""

    return _explicitly_on(NOTIFICATIONS_ENABLED)
