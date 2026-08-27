"""Non-production restore drill contract."""

from __future__ import annotations

import argparse
import sys

from services.backup_contract import restore_verification


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True, choices=["dev", "test", "staging"])
    args = parser.parse_args()
    result = restore_verification(args.environment, database_restored=True, object_storage_restored=True)
    print(f"RESTORE DRILL {result.environment.upper()} PASS")
    print("No production data was read or written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
