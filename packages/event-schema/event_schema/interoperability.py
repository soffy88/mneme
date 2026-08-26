"""Loss-minimising adapters for common learning-data standards.

The adapters are intentionally pure functions.  They do not change the Mneme
event contract and they never export a mastery judgement.  UUIDs are exposed as
pseudonymous account/object identifiers; names, email addresses, and raw
student identifiers are not added to any external representation.

This is a transport boundary, not a second source of truth: importing an xAPI,
Caliper, or CASE representation must first be normalised into
:class:`~event_schema.models.LearningEvent` by a separately versioned adapter.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from .models import LearningEvent

InteropFormat = Literal["mneme", "xapi", "caliper", "case"]
MNEME_BASE_URI = "https://mneme.local"


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _resource_uri(kind: str, value: str | UUID) -> str:
    return f"{MNEME_BASE_URI}/{kind}/{value}"


def _duration(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    return f"PT{seconds}S"


def _event_fields(event: LearningEvent, *, redact_private: bool) -> dict[str, Any]:
    """Return the event fields allowed in a third-party payload."""

    private = event.privacy_class.value in {"P2", "P3"}
    return {
        "knowledge_refs": list(event.knowledge_refs),
        "response": None if redact_private and private else event.response,
        "process_signals": (
            {}
            if redact_private and private
            else event.process_signals.model_dump(exclude_none=True)
        ),
        "metacognitive": (
            {}
            if redact_private and private
            else event.metacognitive.model_dump(exclude_none=True)
        ),
        "intervention": None if redact_private and private else event.intervention,
        "evaluation_phase": (
            event.evaluation_phase.value if event.evaluation_phase is not None else None
        ),
    }


def event_to_xapi(
    event: LearningEvent,
    *,
    redact_private: bool = True,
) -> dict[str, Any]:
    """Map one event to an xAPI 1.0-style statement.

    The actor is an account URI containing the stable Mneme UUID rather than a
    human name.  Mneme-specific fields live under a namespaced extension so an
    xAPI consumer can ignore them without losing the standard result fields.
    """

    fields = _event_fields(event, redact_private=redact_private)
    result: dict[str, Any] = {}
    if event.outcome is not None:
        if event.outcome.correctness is not None:
            result["success"] = event.outcome.correctness
        if event.outcome.partial_credit is not None:
            result["score"] = {
                "raw": event.outcome.partial_credit,
                "min": 0,
                "max": 1,
                "scaled": event.outcome.partial_credit,
            }
    if fields["response"] is not None:
        result["response"] = json.dumps(
            fields["response"], ensure_ascii=False, sort_keys=True
        )
    duration = _duration(event.process_signals.time_spent_seconds)
    if duration is not None:
        result["duration"] = duration

    statement: dict[str, Any] = {
        "id": str(event.event_id),
        "timestamp": _iso(event.occurred_at),
        "actor": {
            "objectType": "Agent",
            "account": {
                "homePage": MNEME_BASE_URI,
                "name": str(event.actor_id or event.student_id or "anonymous"),
            },
        },
        "verb": {
            "id": _resource_uri("verbs", event.action),
            "display": {"en-US": event.action},
        },
        "object": {
            "id": _resource_uri(event.object_type, event.object_id),
            "objectType": "Activity",
            "definition": {
                "type": _resource_uri("activity-types", event.object_type),
                "name": {"zh-CN": event.object_id},
            },
        },
        "context": {
            "extensions": {
                f"{MNEME_BASE_URI}/extensions/schema-version": event.schema_version,
                f"{MNEME_BASE_URI}/extensions/privacy-class": event.privacy_class.value,
                f"{MNEME_BASE_URI}/extensions/knowledge-refs": fields[
                    "knowledge_refs"
                ],
                f"{MNEME_BASE_URI}/extensions/trace-id": event.trace_id,
                f"{MNEME_BASE_URI}/extensions/evaluation-phase": fields[
                    "evaluation_phase"
                ],
            }
        },
        "result": result,
    }
    if event.session_id is not None:
        statement["context"]["registration"] = str(event.session_id)
    return statement


def event_to_caliper(
    event: LearningEvent,
    *,
    redact_private: bool = True,
) -> dict[str, Any]:
    """Map one event to a Caliper 1.2-compatible AssessmentEvent shape."""

    fields = _event_fields(event, redact_private=redact_private)
    generated: dict[str, Any] = {
        "id": _resource_uri("attempts", event.event_id),
        "type": "Attempt",
        "extensions": {
            f"{MNEME_BASE_URI}/extensions/schema-version": event.schema_version,
            f"{MNEME_BASE_URI}/extensions/privacy-class": event.privacy_class.value,
            f"{MNEME_BASE_URI}/extensions/knowledge-refs": fields["knowledge_refs"],
            f"{MNEME_BASE_URI}/extensions/evaluation-phase": fields[
                "evaluation_phase"
            ],
        },
    }
    if event.outcome is not None:
        generated["result"] = {
            "type": "Result",
            "success": event.outcome.correctness,
            "score": event.outcome.partial_credit,
        }
    action = "Completed" if event.outcome is not None else "Started"
    return {
        "id": _resource_uri("caliper/events", event.event_id),
        "type": "AssessmentEvent",
        "eventTime": _iso(event.occurred_at),
        "action": action,
        "actor": {
            "id": _resource_uri("agents", event.actor_id or event.student_id or "anonymous"),
            "type": "Person",
        },
        "object": {
            "id": _resource_uri(event.object_type, event.object_id),
            "type": "AssessmentItem",
        },
        "generated": generated,
        "edApp": {"id": MNEME_BASE_URI, "type": "SoftwareApplication"},
    }


def events_to_case_document(
    events: Iterable[LearningEvent],
    *,
    redact_private: bool = True,
) -> dict[str, Any]:
    """Create a CASE-style competency document from event knowledge refs.

    CASE describes competency-framework items rather than attempts.  Therefore
    this export contains stable CFItems for the referenced knowledge units and
    CFItemAssociations linking each observed object to those items.  It does not
    claim that an event proves mastery.
    """

    ordered = sorted(events, key=lambda item: (item.occurred_at, item.event_id.hex))
    refs = sorted({ref for event in ordered for ref in event.knowledge_refs})
    document_id = uuid5(NAMESPACE_URL, f"{MNEME_BASE_URI}/case/mneme")
    document_uri = _resource_uri("case/documents", document_id)
    now = _iso(datetime.now(timezone.utc))
    items: list[dict[str, Any]] = []
    item_uris: dict[str, str] = {}
    for ref in refs:
        item_id = uuid5(document_id, ref)
        item_uri = _resource_uri("case/items", item_id)
        item_uris[ref] = item_uri
        items.append(
            {
                "uri": item_uri,
                "identifier": str(item_id),
                "CFItemType": "Element",
                "fullStatement": ref,
                "humanCodingScheme": ref,
                "language": "zh-CN",
                "lastChangeDateTime": now,
            }
        )

    associations: list[dict[str, Any]] = []
    for event in ordered:
        for ref in event.knowledge_refs:
            association_id = uuid5(
                document_id, f"{event.event_id}:{ref}:exemplifies"
            )
            associations.append(
                {
                    "uri": _resource_uri("case/associations", association_id),
                    "identifier": str(association_id),
                    "associationType": "exemplifies",
                    "originNodeURI": _resource_uri(
                        event.object_type, event.object_id
                    ),
                    "destinationNodeURI": item_uris[ref],
                    "lastChangeDateTime": _iso(event.occurred_at),
                }
            )

    return {
        "CFDocument": {
            "uri": document_uri,
            "identifier": str(document_id),
            "CFDocumentType": "Document",
            "adoptionStatus": "Draft",
            "publisher": "Mneme",
            "lastChangeDateTime": now,
        },
        "CFItems": items,
        "CFItemAssociations": associations,
        "extensions": {
            "mneme_export": "case/v1",
            "redact_private": redact_private,
            "events_count": len(ordered),
        },
    }


def export_events(
    events: Iterable[LearningEvent],
    export_format: InteropFormat,
    *,
    redact_private: bool = True,
) -> Any:
    """Export events in one of the supported formats."""

    ordered = tuple(events)
    if export_format == "mneme":
        return [event.model_dump(mode="json", exclude_none=False) for event in ordered]
    if export_format == "xapi":
        return [event_to_xapi(event, redact_private=redact_private) for event in ordered]
    if export_format == "caliper":
        return [
            event_to_caliper(event, redact_private=redact_private) for event in ordered
        ]
    if export_format == "case":
        return events_to_case_document(ordered, redact_private=redact_private)
    raise ValueError(f"unsupported export format: {export_format}")
