# Mneme Staging Restore Drill

Run date: 2026-08-27 UTC
Release baseline: `ce8dc1a881152ef54e938685f68a63022169ebae`

## Result

`BLOCKED_INFRA`

No staging database, object-storage target, backup artifact, or isolated restore target was supplied. No backup was created, no restore was attempted, and no production data was accessed.

## Required drill when staging infrastructure is supplied

1. Create and verify a staging database and object-storage backup.
2. Record backup identifiers, timestamps, schema revision, and checksum metadata.
3. Restore into an independent temporary database and storage target; never overwrite the source staging targets.
4. Verify schema head, row counts, critical learning records, and event/state consistency.
5. Record the test-environment-only result and destroy the temporary targets according to the approved retention policy.

RPO and RTO remain `TBD_OWNER_DECISION`. A local test database or Docker volume is not evidence of a staging backup/restore drill.
