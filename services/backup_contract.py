"""Backup/restore contract; drills are explicitly non-production."""

from __future__ import annotations

from dataclasses import dataclass


class ProductionRestoreDrillError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BackupContract:
    database: bool
    object_storage: bool
    encrypted: bool
    verified: bool
    rpo: str = "TBD_OWNER_DECISION"
    rto: str = "TBD_OWNER_DECISION"


@dataclass(frozen=True, slots=True)
class RestoreVerification:
    environment: str
    passed: bool
    database_restored: bool
    object_storage_restored: bool
    production_touched: bool = False


def validate_restore_drill_environment(environment: str) -> None:
    if environment.strip().lower() in {"prod", "production"}:
        raise ProductionRestoreDrillError("restore drills cannot target production")
    if environment.strip().lower() not in {"dev", "test", "staging"}:
        raise ValueError("restore drill environment must be dev, test, or staging")


def restore_verification(environment: str, *, database_restored: bool, object_storage_restored: bool) -> RestoreVerification:
    validate_restore_drill_environment(environment)
    return RestoreVerification(environment=environment, passed=database_restored and object_storage_restored, database_restored=database_restored, object_storage_restored=object_storage_restored)


__all__ = ["BackupContract", "ProductionRestoreDrillError", "RestoreVerification", "restore_verification", "validate_restore_drill_environment"]
