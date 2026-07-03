"""L2 · 答案分级政策（教学引擎核心）。纯函数，确定性。

据专家评审 v1.0 + 用户 2026-07-03 批准：旧"任何模式永不给答案"松绑为**按情境分级**
（Bastani 2024：裸答案后测−17%、护栏组无损害 → 支持分级非永不示解；专长逆转：新手需样例）。
硬约束保留：学生自带作业/试卷原题、写作/作文 —— 永不输出可抄答案/完整步骤。

feature-flag 保守默认：未开启教学引擎时，一律回退旧行为（never，只提示不给答案）。
"""

from __future__ import annotations

# 情境
OWN_HOMEWORK = "own_homework"  # 学生自带作业/试卷原题
WRITING = "writing"  # 写作/作文
SYSTEM_TAUGHT = "system_taught"  # 系统教学的同构题（受学习阶段调度）
STUCK = "stuck"  # 卡壳升级阶梯

# 输出模式
NEVER = "never"  # 永不给可抄答案/完整步骤（只提问/标注）
FULL_EXAMPLE = "full_example"  # 给完整样例 + 自我解释提示（worked_example 阶段）
HINT_LADDER = "hint_ladder"  # 元认知→定位→步骤→同构例题，原题始终不给


def answer_policy(
    context: str,
    stage: str | None = None,
    *,
    enabled: bool = False,
) -> dict:
    """返回该情境+学习阶段下允许的答案模式。

    Parameters
    ----------
    context : 见上（own_homework / writing / system_taught / stuck）
    stage   : learner_model.get_stage 的学习阶段（仅 system_taught 用）
    enabled : 教学引擎 feature-flag；关闭时保守回退（一律 never）

    Returns {mode, allow_full_answer, allow_worked_example, rationale}
    """

    def _mk(mode: str, rationale: str) -> dict:
        return {
            "mode": mode,
            "allow_full_answer": mode == FULL_EXAMPLE,  # 完整可抄解答仅样例态
            "allow_worked_example": mode == FULL_EXAMPLE,
            "rationale": rationale,
        }

    # 硬约束：无论 flag，自带原题与写作永不给（旧红线保留于此）
    if context == OWN_HOMEWORK:
        return _mk(NEVER, "学生自带原题：给答案=作弊，裸答案后测−17%")
    if context == WRITING:
        return _mk(NEVER, "写作：代写引发元认知惰性(Fan 2024)，只标注/提问/给 rubric")

    # feature-flag 关：保守回退旧行为
    if not enabled:
        return _mk(NEVER, "教学引擎未开启，保守回退（等 RCT 裁决默认值）")

    # 系统教学同构题：按学习阶段渐退（专长逆转 → 新手先给样例）
    if context == SYSTEM_TAUGHT:
        if stage == "worked_example":
            return _mk(FULL_EXAMPLE, "新知/新手：必须给完整样例 + 自我解释（样例效应）")
        # completion/retrieval/consolidation：不再给完整解，走脚手架/独立检索
        return _mk(HINT_LADDER, f"阶段 {stage}：脚手架渐退，原题不给完整解")

    # 卡壳阶梯：分级提示，原题不给
    if context == STUCK:
        return _mk(HINT_LADDER, "卡壳：元认知→定位→步骤→同构例题，原题始终不给")

    return _mk(NEVER, "未知情境，保守 never")


__all__ = [
    "answer_policy",
    "OWN_HOMEWORK",
    "WRITING",
    "SYSTEM_TAUGHT",
    "STUCK",
    "NEVER",
    "FULL_EXAMPLE",
    "HINT_LADDER",
]
