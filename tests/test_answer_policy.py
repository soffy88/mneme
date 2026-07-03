"""L2 答案分级政策（红线松绑后的新契约）。纯函数，确定性。"""

from oprim.answer_policy import (
    FULL_EXAMPLE,
    HINT_LADDER,
    NEVER,
    OWN_HOMEWORK,
    STUCK,
    SYSTEM_TAUGHT,
    WRITING,
    answer_policy,
)


def test_own_homework_never_gives_even_with_engine_on():
    """红线保留：学生自带原题永不给完整答案，flag 开也不给。"""
    for en in (True, False):
        p = answer_policy(OWN_HOMEWORK, "worked_example", enabled=en)
        assert p["mode"] == NEVER
        assert p["allow_full_answer"] is False


def test_writing_never_ghostwrites():
    """红线最严：写作永不代写成段，flag 开也不给。"""
    for en in (True, False):
        p = answer_policy(WRITING, None, enabled=en)
        assert p["mode"] == NEVER and p["allow_full_answer"] is False


def test_engine_off_conservative_fallback():
    """feature-flag 关：系统教学也保守回退 never（保持旧行为，等 RCT）。"""
    p = answer_policy(SYSTEM_TAUGHT, "worked_example", enabled=False)
    assert p["mode"] == NEVER


def test_system_taught_new_knowledge_must_give_example():
    """flag 开 + 新知阶段：必须给完整样例（专长逆转，新手需样例非纯提问）。"""
    p = answer_policy(SYSTEM_TAUGHT, "worked_example", enabled=True)
    assert p["mode"] == FULL_EXAMPLE
    assert p["allow_worked_example"] is True and p["allow_full_answer"] is True


def test_system_taught_later_stages_scaffold_only():
    """flag 开 + 半熟/已掌握：脚手架/独立检索，不再给完整解。"""
    for stage in ("completion", "retrieval", "consolidation"):
        p = answer_policy(SYSTEM_TAUGHT, stage, enabled=True)
        assert p["mode"] == HINT_LADDER and p["allow_full_answer"] is False


def test_stuck_ladder_never_gives_original():
    p = answer_policy(STUCK, "retrieval", enabled=True)
    assert p["mode"] == HINT_LADDER and p["allow_full_answer"] is False
