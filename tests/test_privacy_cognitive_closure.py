from datetime import UTC, datetime
from uuid import UUID

from event_schema import EventOutcome, LearningEvent, PrivacyClass, event_to_xapi


def test_private_response_and_metacognitive_signals_are_redacted_from_interop():
    event = LearningEvent(
        student_id=UUID("11111111-1111-1111-1111-111111111111"),
        occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
        received_at=datetime(2026, 8, 1, tzinfo=UTC),
        source="review",
        action="attempted",
        object_type="question",
        object_id="q-1",
        knowledge_refs=["kc-1"],
        response={"private_response": "学生原始答案"},
        outcome=EventOutcome(correctness=True),
        privacy_class=PrivacyClass.P3,
    )
    payload = event_to_xapi(event)
    assert "学生原始答案" not in str(payload)
    assert "private_response" not in str(payload)
