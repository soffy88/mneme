# Teaching Engine v1 pilot protocol

Status: `protocol_only`. This document freezes the measurement contract; it is
not evidence that a pilot has run.

## Scope and assignment

The experiment compares `worked_example` with `control` (the conservative
Socratic path). Assignment is deterministic from `student_id` and the frozen
experiment name, so a replay can reproduce the arm. The flag
`EXPERIMENT_TEACHING_ENGINE` must remain off until consent, eligibility, and a
real cohort are ready. Existing students must not be silently enrolled by
turning the flag on.

The enrollment manifest must record protocol version, consent timestamp,
eligibility decision, assignment hash, and enrollment window. It must not
contain raw answers in the experiment report.

## Endpoints

Primary endpoint: accuracy on a D7 delayed transfer probe where
`source=transfer_probe`, `independent_mode=true`, and `ai_assisted=false`.

Secondary endpoints:

- D30 delayed transfer accuracy with the same explicit no-AI flags;
- frustration dropout: at least three consecutive incorrect events followed by
  at least seven inactive days;
- safety: answer leakage, verifier failures, and guardian/student withdrawal.

All events must retain both `occurred_at` and `received_at`. Events without
explicit independence and AI flags remain ordinary transfer observations and
must not enter the no-AI endpoint.

## Analysis rules

- Primary analysis is intention-to-treat by frozen assignment arm.
- Report arm size, eligible/consented counts, endpoint denominator, point
  estimate, uncertainty interval, and missingness before comparing arms.
- Use the same event/time-window rules for both arms; exclude future events by
  `as_of` and pair delayed observations only where the protocol requires it.
- An observed arm difference is not a causal claim until the owner has approved
  the real randomized protocol, pre-registered the endpoint, and met the
  minimum arm size. No synthetic fixture can satisfy that gate.
- Stop/rollback immediately for answer leakage, consent violations, or a
  material rise in safety guardrail failures; the feature flag is a kill switch,
  not an experiment result.

## Required evidence package

1. Approved consent/eligibility manifest (private, access-controlled).
2. Frozen protocol JSON/hash and assignment version.
3. Aggregate event extract with no student IDs in the report.
4. D7/D30, no-AI transfer, dropout, and safety metrics with denominators.
5. Independent review sign-off and rollback record.

Until this package exists, the repository may report only `contract`, `offline`,
or `observational` evidence labels as defined in
[`docs/GOVERNANCE.md`](GOVERNANCE.md).
