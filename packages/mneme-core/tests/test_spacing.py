"""Tests for FSRS spacing."""
from mneme_core.oprim.spacing import get_initial_state, schedule_next, build_review_queue, due_reviews
from mneme_core.oprim.models import ReviewTask

def test_initial_state():
    state = get_initial_state(1000.0)
    assert state.stability > 0
    assert state.reps == 0

def test_schedule_next():
    state = get_initial_state(1000.0)
    new_state = schedule_next(state, rating=3, now=1000.0)  # good
    assert new_state.due_at > 1000.0
    assert new_state.reps == 1

def test_error_linked_priority():
    """error-linked KP gets priority=1 (highest)."""
    fsrs = {
        "k1": get_initial_state(1000.0),
        "k2": get_initial_state(1000.0),
    }
    queue = build_review_queue(fsrs, error_linked={"k1"})
    k1_tasks = [t for t in queue if t.knowledge_point_id == "k1"]
    k2_tasks = [t for t in queue if t.knowledge_point_id == "k2"]
    assert k1_tasks[0].priority == 1
    assert k2_tasks[0].priority > 1

def test_due_reviews():
    tasks = [
        ReviewTask(knowledge_point_id="k1", due_at=50.0, priority=1),
        ReviewTask(knowledge_point_id="k2", due_at=200.0, priority=2),
    ]
    due = due_reviews(tasks, now=100.0)
    assert len(due) == 1
    assert due[0].knowledge_point_id == "k1"
