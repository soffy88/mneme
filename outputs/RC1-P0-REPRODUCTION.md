# Mneme RC1 P0 reproduction

Date: 2026-08-27 UTC
Scope: synthetic learners only; no production data or real pilot users.

## Baseline

- RC1 commit: `a28edb25930232fb7af6150421d12a4237f655f2`
- RC1 tag: `v0.1.0-rc1`
- PostgreSQL migration head: `5e7f8a9b0c12`

## P0-1 — review did not advance FSRS

The reproduction used real PostgreSQL and the production cognitive service path.
The review event updated mastery, while the persisted FSRS card remained unchanged.

### Local PostgreSQL reproduction

- Synthetic learner: `5fa360af-c5a7-482a-8974-0941cf763238`
- Knowledge point: `RC1P01`
- Review event: `994d665a-11a9-4881-91ed-6bcd21249d32`
- Mastery before: `p_mastery=0.6756756756756757`, attempts `1`
- Mastery after: `p_mastery=0.9394957983193277`, attempts `2`
- FSRS before: stability `2.3065`, difficulty `2.118103970459016`, due `2026-08-25T12:36:05Z`, last review `2026-08-25T12:26:05Z`
- FSRS after: identical stability, difficulty, due, last review, and state
- Result: `mastery_changed=true`, `schedule_changed=false`

### Staging RC1 reproduction

- Synthetic learner: `fdd4aa55-7631-4734-8419-fdd28a95dff8`
- Review event: `f952de64-e9f3-4684-a5b8-6ded721d4c3c`
- Mastery before/after: `0.6756756756756757` → `0.9394957983193277`
- FSRS before: stability `2.3065`, difficulty `2.118103970459016`, due `2026-08-25T12:38:59Z`, last review `2026-08-25T12:28:59Z`, state `1`
- FSRS after: unchanged
- Result: the staging runtime reproduced the same split between cognitive mastery and memory scheduling.

### Root-cause evidence

The old review path supplied the massed-practice debounce interval to every
interaction. BKT/mastery projection still ran, but the FSRS eligibility guard
discarded the review schedule update when the preceding interaction was recent.

## P0-2 — purge FK ordering failure

The reproduction used real PostgreSQL with a soft-deleted synthetic student and
pilot records.

### Local PostgreSQL reproduction

- Synthetic learner: `40686c8c-8bdd-4f81-9efd-336442e0a9ce`
- Enrollment: `32b43fa2-d5d7-4699-9c0e-025c9c01c0a8`
- FK: `pilot_assignments.enrollment_id → pilot_enrollments.enrollment_id`
- Constraint: `pilot_assignments_enrollment_id_fkey`
- Old deletion order: `pilot_enrollments` before `pilot_assignments` and measurement schedule
- Result: PostgreSQL `IntegrityError`; transaction rolled back with residual enrollment `1`, assignment `1`, measurement `1`, user `1`

### Staging RC1 reproduction

- Synthetic learner: `e3ccd800-5762-4e00-a868-f38fa485afe0`
- Enrollment: `a7b83bf5-045c-4996-9e50-d198efe04d54`
- PostgreSQL error: `ForeignKeyViolationError` on `pilot_assignments_enrollment_id_fkey`
- Result after rollback: enrollment `1`, assignment `1`, measurement `1`, user `1`

### Root-cause evidence

The purge inventory deleted the parent enrollment before its `NO ACTION`
children. Because the operation was transactional, PostgreSQL preserved the
rows, but the caller observed a failed purge and student-linked data remained.

All records above were synthetic and were removed after reproduction.
