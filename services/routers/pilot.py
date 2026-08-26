"""Minimal pilot operations surface; no raw student answers are exposed."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from obase.db import get_db
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import _ensure_student_self, get_current_user, require_student_access
from services.feature_flags import pilot_config, pilot_is_active
from services.models import (
    PilotAssignment as PilotAssignmentRow,
    PilotEnrollment as PilotEnrollmentRow,
    PilotEvidenceRegistry,
    PilotMeasurementSchedule,
    User,
)
from services.pilot_protocol import (
    ConsentStatus,
    PilotProtocol,
    assign_pilot_student,
    enroll_pilot_student,
    persist_measurement_schedule,
    persist_pilot_assignment,
    persist_pilot_enrollment,
    pilot_export_payload,
    revoke_pilot_consent_in_db,
    schedule_measurement,
)

router = APIRouter(tags=["pilot"])


class PilotEnrollmentRequest(BaseModel):
    protocol: PilotProtocol
    cohort_id: str = Field(min_length=1, max_length=120)
    consent_status: ConsentStatus = ConsentStatus.UNKNOWN
    consent_version: str | None = Field(default=None, max_length=40)
    consent_recorded_at: datetime | None = None


class PilotMeasurementRequest(BaseModel):
    protocol: PilotProtocol
    cohort_id: str = Field(min_length=1, max_length=120)
    phase: str = Field(min_length=1, max_length=32)
    anchor_at: datetime


class PilotConsentRevokeRequest(BaseModel):
    protocol_id: str = Field(min_length=1, max_length=120)
    protocol_version: str = Field(min_length=1, max_length=40)


def _require_pilot_admin(user: User) -> None:
    from obase.admin_identity import is_admin

    if not is_admin(user):
        raise HTTPException(status_code=403, detail="仅 admin 可访问 pilot 运维接口")


@router.get("/v2/pilot/config")
async def get_pilot_config(current_user: User = Depends(get_current_user)):
    _require_pilot_admin(current_user)
    return pilot_config()


@router.get("/v2/pilot/dashboard")
async def get_pilot_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate-only dashboard; empty data is never displayed as 0% effect."""

    _require_pilot_admin(current_user)
    enrollment_count = int(
        (await db.execute(select(func.count()).select_from(PilotEnrollmentRow))).scalar_one()
    )
    assignment_count = int(
        (await db.execute(select(func.count()).select_from(PilotAssignmentRow))).scalar_one()
    )
    schedule_count = int(
        (await db.execute(select(func.count()).select_from(PilotMeasurementSchedule))).scalar_one()
    )
    registry_count = int(
        (await db.execute(select(func.count()).select_from(PilotEvidenceRegistry))).scalar_one()
    )
    return {
        "data_state": "NO REAL-WORLD EVIDENCE YET"
        if registry_count == 0
        else "REAL_WORLD_DATA_PRESENT",
        "pilot_config": pilot_config(),
        "enrollment_count": enrollment_count,
        "assignment_count": assignment_count,
        "measurement_completion": {
            "scheduled": schedule_count,
            "registry_artifacts": registry_count,
        },
        "endpoints": {
            "retention_7d": None,
            "retention_30d": None,
            "near_transfer": None,
            "far_transfer": None,
            "jol_calibration": None,
            "rmg_am": None,
        },
        "evidence_level": "contract" if registry_count == 0 else "pending",
    }


@router.post("/v2/pilot/enrollment/{student_id}", status_code=201)
async def post_pilot_enrollment(
    student_id: UUID,
    body: PilotEnrollmentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_student_self(current_user, student_id)
    if not pilot_is_active(body.cohort_id):
        raise HTTPException(status_code=409, detail="pilot 未启用或 cohort 不在 allowlist")
    try:
        enrollment = enroll_pilot_student(
            student_id=student_id,
            protocol=body.protocol,
            cohort_id=body.cohort_id,
            consent_status=body.consent_status,
            consent_version=body.consent_version,
            consent_recorded_at=body.consent_recorded_at,
            enrolled_at=datetime.now(UTC),
        )
        row = await persist_pilot_enrollment(db, enrollment)
        assignment = assign_pilot_student(enrollment, body.protocol)
        await persist_pilot_assignment(db, assignment)
        await db.commit()
    except PermissionError as exc:
        await db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {
        "enrollment_id": str(row.enrollment_id),
        "protocol_id": row.protocol_id,
        "protocol_version": row.protocol_version,
        "cohort_id": row.cohort_id,
        "consent_status": row.consent_status,
        "assignment_arm": assignment.arm,
    }


@router.post("/v2/pilot/measurement/{student_id}", status_code=201)
async def post_pilot_measurement_schedule(
    student_id: UUID,
    body: PilotMeasurementRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_student_self(current_user, student_id)
    if not pilot_is_active(body.cohort_id):
        raise HTTPException(status_code=409, detail="pilot 未启用或 cohort 不在 allowlist")
    enrollment = (
        await db.execute(
            select(PilotEnrollmentRow).where(
                PilotEnrollmentRow.student_id == student_id,
                PilotEnrollmentRow.protocol_id == body.protocol.protocol_id,
                PilotEnrollmentRow.protocol_version == body.protocol.version,
            )
        )
    ).scalar_one_or_none()
    if enrollment is None:
        raise HTTPException(status_code=404, detail="pilot enrollment not found")
    if enrollment.consent_status not in {ConsentStatus.GRANTED.value, ConsentStatus.NOT_REQUIRED.value}:
        raise HTTPException(status_code=403, detail="pilot consent is not active")
    enrollment_model = enroll_pilot_student(
        student_id=student_id,
        protocol=body.protocol,
        cohort_id=enrollment.cohort_id,
        consent_status=ConsentStatus(enrollment.consent_status),
        consent_version=enrollment.consent_version,
        consent_recorded_at=enrollment.consent_recorded_at,
        enrolled_at=enrollment.enrolled_at,
    ).model_copy(update={"enrollment_id": enrollment.enrollment_id})
    schedule = schedule_measurement(
        enrollment_model,
        body.protocol,
        body.phase,
        anchor_at=body.anchor_at,
    )
    await persist_measurement_schedule(db, schedule)
    await db.commit()
    return schedule.model_dump(mode="json")


@router.get("/v2/pilot/export/{student_id}")
async def get_pilot_export(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    return await pilot_export_payload(db, student_id=student_id)


@router.post("/v2/pilot/consent/revoke/{student_id}")
async def post_pilot_consent_revoke(
    student_id: UUID,
    body: PilotConsentRevokeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.id != student_id:
        _require_pilot_admin(current_user)
    invalidated = await revoke_pilot_consent_in_db(
        db,
        student_id=student_id,
        protocol_id=body.protocol_id,
        protocol_version=body.protocol_version,
        revoked_at=datetime.now(UTC),
    )
    await db.commit()
    return {
        "student_id": str(student_id),
        "protocol_id": body.protocol_id,
        "protocol_version": body.protocol_version,
        "consent_status": ConsentStatus.REVOKED.value,
        "invalidated_measurements": invalidated,
    }
