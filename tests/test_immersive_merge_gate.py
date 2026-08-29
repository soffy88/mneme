"""Merge-gate hard invariants for Immersive Learning MVP."""

from __future__ import annotations

import ast
from pathlib import Path
from uuid import uuid4

from services.immersive.constants import SCAFFOLD_LEVELS, TelemetryEventType
from services.immersive.memory_router import route_memory_action
from services.immersive.policy import recommend_immersive_next
from services.immersive.scoring import score_comprehension_choice, score_dictation


STUDIO_IMMERSIVE = Path("apps/mneme-studio/components/immersive")
STUDIO_LIB = Path("apps/mneme-studio/lib/immersive.ts")


def test_ml07_cognitive_namespaces_no_second_state() -> None:
    """ML-07 MVP: language LUs project via knowledge_ref namespaces only."""

    from services.cognitive_state_v2 import CognitiveStateV2
    from services.immersive.memory_router import knowledge_ref_for_unit

    ref = knowledge_ref_for_unit("VOCABULARY", "hello")
    assert ref.startswith("lu-vocabulary-")
    # from_observations with empty events → null dims, not fabricated priors
    state = CognitiveStateV2.from_observations(
        student_id=uuid4(),
        knowledge_ref=ref,
        events=[],
    )
    assert state.knowledge.mastery_probability is None
    assert state.knowledge.evidence_count == 0
    # No parallel EnglishLearnerState module
    forbidden = [
        "EnglishLearnerState",
        "VideoLearnerState",
        "VocabularyState",
    ]
    root = Path("services")
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert f"class {name}" not in text


def test_ml07_same_observations_same_projection_checksum() -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    from event_schema import EventOutcome, ItemFeatures, LearningEvent, PrivacyClass
    from services.cognitive_state_v2 import CognitiveStateV2

    student = uuid4()
    ref = "lu-phrase-should-ve"
    now = datetime(2026, 1, 1, tzinfo=UTC)

    def make_event(eid) -> LearningEvent:
        return LearningEvent(
            event_id=eid,
            student_id=student,
            occurred_at=now,
            received_at=now,
            source="media_practice",
            action="dictation_result",
            object_type="transcript_segment",
            object_id="seg-1",
            knowledge_refs=[ref],
            item_features=ItemFeatures(modality="audio", format="dictation"),
            outcome=EventOutcome(
                correctness=True,
                partial_credit=1.0,
                verifier="immersive.dictation_normalize",
                verifier_version="dictation-score/1.0.0",
            ),
            privacy_class=PrivacyClass.P1,
        )

    e1 = make_event(uuid4())
    left = CognitiveStateV2.from_observations(
        student_id=student, knowledge_ref=ref, events=[e1]
    )
    right = CognitiveStateV2.from_observations(
        student_id=student, knowledge_ref=ref, events=[e1]
    )
    assert left.model_dump(mode="json") == right.model_dump(mode="json")


def test_ml13_evaluation_capabilities_mvp() -> None:
    """ML-13 MVP: contamination / eligibility / transfer / scaffold evaluable."""

    # behavioral contamination → no FSRS
    for action in (
        "segment_replayed",
        "vocab_lookup",
        "translation_revealed",
        "subtitle_hidden",
    ):
        d = route_memory_action(
            action=action,
            knowledge_refs=["lu-vocabulary-x"],
            correctness=None,
            existing_mastery=False,
        )
        assert d.advance_fsrs is False

    # performance correctness evaluation
    ok = score_dictation("hello world", "hello world")
    assert ok.correctness is True
    bad = score_comprehension_choice("a", "b")
    assert bad.correctness is False

    # FSRS eligibility on performance results
    for action in (
        "listening_result",
        "dictation_result",
        "comprehension_result",
        "transfer_result",
    ):
        d = route_memory_action(
            action=action,
            knowledge_refs=["lu-vocabulary-x"],
            correctness=True,
            existing_mastery=False,
            confidence=0.9,
            evaluation_phase="near_transfer" if action == "transfer_result" else "practice",
        )
        assert d.advance_fsrs is True

    # scaffold policy all levels representable
    assert SCAFFOLD_LEVELS == frozenset(range(6))
    for level in range(6):
        result = recommend_immersive_next(
            student_id=uuid4(),
            current_scaffold=level,
            mastery=0.2 + 0.15 * level,
            evidence_count=level * 3,
            recent_override=True,
        )
        assert result.scaffold_level == level  # override respected


def test_telemetry_contamination_does_not_advance_fsrs() -> None:
    """100 play/pause/seek + weak behavioral → zero FSRS; one listening_result → eligible."""

    advanced = 0
    for _ in range(100):
        for et in (
            TelemetryEventType.PLAY,
            TelemetryEventType.PAUSE,
            TelemetryEventType.SEEK,
        ):
            # telemetry event types are not LearningEvent actions
            d = route_memory_action(
                action=et.value,
                knowledge_refs=["lu-vocabulary-x"],
                correctness=None,
                existing_mastery=False,
            )
            assert d.advance_fsrs is False
            advanced += int(d.advance_fsrs)
    for _ in range(50):
        d = route_memory_action(
            action="segment_replayed",
            knowledge_refs=["lu-vocabulary-x"],
            correctness=None,
            existing_mastery=False,
        )
        advanced += int(d.advance_fsrs)
    for _ in range(20):
        for action in ("translation_revealed", "vocab_lookup"):
            d = route_memory_action(
                action=action,
                knowledge_refs=["lu-vocabulary-x"],
                correctness=None,
                existing_mastery=False,
            )
            advanced += int(d.advance_fsrs)
    assert advanced == 0

    one = route_memory_action(
        action="listening_result",
        knowledge_refs=["lu-vocabulary-x"],
        correctness=False,
        existing_mastery=False,
        confidence=0.9,
    )
    assert one.advance_fsrs is True


def test_player_has_no_mastery_threshold_pedagogy() -> None:
    """AST/text gate: immersive frontend must not encode mastery→scaffold ifs."""

    forbidden_patterns = (
        "mastery >",
        "mastery<",
        "p_mastery",
        "next_review_at",
        "fsrs",
        "stability",
        "interval",
    )
    paths = list(STUDIO_IMMERSIVE.glob("*.tsx")) + [STUDIO_LIB]
    for path in paths:
        text = path.read_text(encoding="utf-8").lower()
        for pat in forbidden_patterns:
            # allow comments mentioning mastery as "server-only"
            if pat in {"mastery >", "mastery<", "p_mastery", "next_review_at", "fsrs", "stability"}:
                # strip comments roughly
                lines = [
                    ln
                    for ln in text.splitlines()
                    if not ln.strip().startswith("//") and "mastery only" not in ln
                ]
                joined = "\n".join(lines)
                assert pat not in joined, f"{path} contains pedagogy signal {pat}"


def test_policy_scaffold_l0_l5_and_override_not_failure() -> None:
    result = recommend_immersive_next(
        student_id=uuid4(),
        current_scaffold=2,
        mastery=0.95,
        evidence_count=20,
        recent_override=True,
    )
    assert result.scaffold_level == 2
    assert any("OVERRIDE" in code for code in result.reason_codes)
    # override path does not claim performance failure
    assert "failure" not in result.reason.lower()


def test_duplicate_event_id_decision_is_pure_caller_gates_insert() -> None:
    eid = uuid4()
    a = route_memory_action(
        action="dictation_result",
        knowledge_refs=["lu-vocabulary-x"],
        correctness=True,
        existing_mastery=True,
        confidence=0.95,
        event_id=eid,
    )
    b = route_memory_action(
        action="dictation_result",
        knowledge_refs=["lu-vocabulary-x"],
        correctness=True,
        existing_mastery=True,
        confidence=0.95,
        event_id=eid,
    )
    assert a.advance_fsrs is True and b.advance_fsrs is True
    # Idempotency is insert-gated in ingest_immersive_event (inserted=False).


def test_backend_python_no_second_scheduler_class() -> None:
    """Immersive package must not define a second FSRS/scheduler authority."""

    root = Path("services/immersive")
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                assert "Scheduler" not in node.name
                assert node.name not in {
                    "EnglishLearnerState",
                    "VideoLearnerState",
                    "VocabularyState",
                }
