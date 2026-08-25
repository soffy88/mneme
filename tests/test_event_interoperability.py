from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from event_schema import (
    LearningEvent,
    PrivacyClass,
    event_to_caliper,
    event_to_xapi,
    events_to_case_document,
    export_events,
)


EVENT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
STUDENT_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _event(**updates: object) -> LearningEvent:
    values: dict[str, object] = {
        "event_id": EVENT_ID,
        "actor_id": STUDENT_ID,
        "student_id": STUDENT_ID,
        "occurred_at": datetime(2026, 8, 25, 8, 0, tzinfo=timezone.utc),
        "received_at": datetime(2026, 8, 25, 8, 0, tzinfo=timezone.utc),
        "source": "web",
        "action": "attempted",
        "object_type": "question",
        "object_id": "question-1",
        "knowledge_refs": ["linear-equations"],
        "outcome": {"correctness": True, "partial_credit": 0.8},
        "process_signals": {"time_spent_seconds": 12},
        "response": {"answer": "x=2"},
    }
    values.update(updates)
    return LearningEvent.model_validate(values)


def test_xapi_adapter_preserves_result_and_uses_pseudonymous_actor() -> None:
    statement = event_to_xapi(_event())

    assert statement["id"] == str(EVENT_ID)
    assert statement["actor"]["account"]["name"] == str(STUDENT_ID)
    assert statement["result"]["success"] is True
    assert statement["result"]["score"]["scaled"] == 0.8
    assert statement["result"]["duration"] == "PT12S"
    assert statement["context"]["extensions"][
        "https://mneme.local/extensions/knowledge-refs"
    ] == ["linear-equations"]


def test_interop_adapters_redact_high_privacy_process_data() -> None:
    event = _event(privacy_class=PrivacyClass.P2)

    xapi = event_to_xapi(event)
    caliper = event_to_caliper(event)

    assert "response" not in xapi["result"]
    assert caliper["generated"]["extensions"][
        "https://mneme.local/extensions/privacy-class"
    ] == "P2"


def test_caliper_and_case_exports_have_stable_standard_shapes() -> None:
    event = _event()
    caliper = event_to_caliper(event)
    case = events_to_case_document([event])

    assert caliper["type"] == "AssessmentEvent"
    assert caliper["generated"]["result"]["success"] is True
    assert len(case["CFItems"]) == 1
    assert case["CFItems"][0]["fullStatement"] == "linear-equations"
    assert case["CFItemAssociations"][0]["associationType"] == "exemplifies"


def test_export_dispatch_supports_all_formats_and_rejects_unknown() -> None:
    event = _event()

    assert export_events([event], "mneme")[0]["schema_version"] == "2"
    assert export_events([event], "xapi")[0]["verb"]["display"]["en-US"] == "attempted"
    assert export_events([event], "caliper")[0]["type"] == "AssessmentEvent"
    assert export_events([event], "case")["extensions"]["mneme_export"] == "case/v1"
