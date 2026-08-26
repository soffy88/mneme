from services.purge_service import _STUDENT_TABLES


def test_new_student_linked_policy_trace_is_in_hard_delete_inventory():
    assert ("policy_decisions", "student_id") in _STUDENT_TABLES
