"""Launch engineering gate; external owner/infra gates remain explicit blockers."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.backup_contract import BackupContract
from services.feature_flags import early_access_allowed, early_access_mode_enabled
from services.migration_preflight import migration_files_have_downgrades
from services.production_config import ProductionConfigError, validate_production_config, validate_session_contract
from services.readiness import readiness_payload
from services.upload_safety import safe_upload_path, validate_filename

def _run(command: list[str]) -> bool:
    result = subprocess.run(command, cwd=ROOT, check=False)
    return result.returncode == 0


def main() -> int:
    checks: list[tuple[str, bool]] = []
    checks.append(("secret_safety", _run([sys.executable, "scripts/secret_scan.py"])))
    checks.append(("unsafe_production_config_rejected", _unsafe_config_rejected()))
    checks.append(("session_contract", validate_session_contract({"AUTH_TRANSPORT": "cookie", "SESSION_COOKIE_SECURE": "1", "SESSION_COOKIE_HTTPONLY": "1", "SESSION_COOKIE_SAMESITE": "lax"})["valid"] is True))
    checks.append(("migration_files_have_downgrades", migration_files_have_downgrades(ROOT / "alembic" / "versions")))
    checks.append(("health_contract", readiness_payload(database=True, migrations=True)[1] == 200))
    checks.append(("critical_readiness_failure", readiness_payload(database=False, migrations=True)[1] == 503))
    checks.append(("upload_path_boundary", safe_upload_path(ROOT / "tmp", "safe.pdf").name == "safe.pdf"))
    checks.append(("upload_traversal_rejected", _traversal_rejected()))
    checks.append(("backup_contract", BackupContract(database=True, object_storage=True, encrypted=True, verified=True).verified))
    checks.append(("early_access_default_closed", not early_access_mode_enabled() and not early_access_allowed("unknown")))
    checks.append(("pilot_readiness", _run(["make", "pilot-readiness"])))
    checks.append(("product_readiness", _run(["make", "product-readiness"])))
    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    failed = [name for name, passed in checks if not passed]
    if failed:
        print("LAUNCH NOT READY")
        print("CODE BLOCKERS: " + ", ".join(failed))
        return 1
    print("LAUNCH ENGINEERING READY")
    print("BLOCKED_OWNER production secrets, legal/consent approval, and launch allowlist")
    print("BLOCKED_INFRA production database/current revision, backups, monitoring, and deployment")
    print("No production deployment or real-world evidence was performed.")
    return 0


def _unsafe_config_rejected() -> bool:
    try:
        validate_production_config({"MNEME_ENV": "production", "JWT_SECRET": "mneme-dev-secret-change-in-prod!", "DEMO_MODE": "1", "BILLING_PROVIDER": "fake"})
    except ProductionConfigError:
        return True
    return False


def _traversal_rejected() -> bool:
    try:
        validate_filename("../escape.pdf")
    except ValueError:
        return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
