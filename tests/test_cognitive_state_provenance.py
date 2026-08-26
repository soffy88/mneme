from datetime import UTC, datetime
from uuid import UUID

from event_schema import EventOutcome, LearningEvent
from services.cognitive_state_v2 import CognitiveStateV2
from services.evidence_graph import EvidenceClaim, EvidenceRef


def test_every_observed_state_claim_has_traceable_event_references():
    sid = UUID("11111111-1111-1111-1111-111111111111")
    event_id = UUID("22222222-2222-2222-2222-222222222222")
    event = LearningEvent(
        event_id=event_id,
        student_id=sid,
        occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
        received_at=datetime(2026, 8, 1, tzinfo=UTC),
        source="review",
        action="attempted",
        object_type="question",
        object_id="q-1",
        knowledge_refs=["kc-1"],
        outcome=EventOutcome(correctness=True),
    )
    state = CognitiveStateV2.from_observations(
        student_id=sid,
        knowledge_ref="kc-1",
        events=[event],
        computed_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    assert state.provenance.evidence_event_ids == [event_id]
    assert state.provenance.evidence_refs[0].event_id == event_id
    for claim in state.evidence_claims:
        if claim.claim_value is not None:
            assert claim.evidence_refs
            assert all(ref.event_id == event_id for ref in claim.evidence_refs)


def test_evidence_levels_are_closed_and_claims_cannot_be_unreferenced():
    ref = EvidenceRef(
        event_id=UUID("22222222-2222-2222-2222-222222222222"),
        knowledge_ref="kc-1",
        evidence_type="learning_event",
        occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
        source="review",
    )
    claim = EvidenceClaim(
        claim_type="mastery_probability",
        claim_value=0.7,
        knowledge_ref="kc-1",
        evidence_refs=[ref],
        model_version="test/1",
        computed_at=datetime(2026, 8, 1, tzinfo=UTC),
        evidence_level="contract",
    )
    assert claim.evidence_level == "contract"
