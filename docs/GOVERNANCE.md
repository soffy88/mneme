# Mneme engineering governance

This file records the release and evidence rules that are easy to lose in a
long task list. Normative architecture and safety rules remain in `CLAUDE.md`
and `MNEME_MASTER_DESIGN.md`.

## Evidence labels

Every Blueprint claim must use one of these labels:

| Label | Meaning | May claim real learning effect? |
|---|---|---|
| `contract` | deterministic code, schema, or red-line test | No |
| `offline` | replay or external public dataset evaluated without live students | No |
| `observational` | real product events without randomized assignment | No causal claim |
| `randomized` | pre-registered treatment/control with independent delayed endpoint | Yes, only within its protocol |
| `commercial` | real funnel, retention, pricing, or payment evidence | Only for the measured cohort/window |

The repository currently has contract and offline/observational mechanisms. It
does not contain fabricated randomized, student, or commercial evidence.

The cognitive closure contracts are implemented in
`services/cognitive_state_v2.py`, `services/evidence_graph.py`,
`services/policy_trace.py`, and `services/pilot_protocol.py`. Their outputs are
still contract/observational infrastructure; implementation does not upgrade
the repository to randomized or commercial evidence.

## Release gates

1. `./scripts/check.sh` passes against `mneme_test` after Alembic migrations.
2. Studio `npm ci`, `npm audit --audit-level=moderate`, and `npm run build` pass.
3. A production migration is applied before enabling a feature flag that writes
   the new schema; rollback keeps the old read/write path available.
4. A model cannot move to candidate/production without the shadow-evaluation
   evidence gate in `services/model_registry.py`.
5. A learning-effect announcement requires the evidence label, cohort size,
   time window, endpoint definition, baseline, and uncertainty interval.

## Decisions still requiring owner input

- Choose and commit a legal repository license; no license is inferred from
  the code or from a dependency license.
- Approve any live-container restart, production migration, historical
  backfill, or external webhook activation.
- Supply the real pilot cohort and pre-registered no-AI/delayed-transfer
  protocol needed to turn code contracts into Blueprint evidence.

## Real-world validation boundary

Pilot-specific tables are split into student-scoped enrollment, assignment and
measurement metadata plus aggregate analysis artifacts/registry rows. The former
are included in `services/purge_service._STUDENT_TABLES`; the latter contain no
student identifiers. Consent is a technical gate only: the default is
`requires_consent=true`, and enrollment requires explicit `GRANTED` status,
version and timestamp. Revocation invalidates future measurements without
disabling ordinary learning.

`services.pilot_validation.EvidenceContaminationClassifier` is the single source
for clean/AI-assisted/hint-assisted/answer-exposed/invalidated/unknown evidence.
Independent endpoints consume only clean evidence. RMG/AM consumes explicit
active-learning time and excludes idle, background, upload, AI-latency and system
wait time; session wall-clock is not a substitute. `make pilot-readiness` checks
these contracts while leaving all rollout flags off.

Engineering readiness is not real-world evidence. No pilot, randomized effect or
commercial claim may be published until owner-approved consent/protocol and real
student observations produce a replayable analysis artifact.
## Product and commercial boundary

Learner-facing surfaces use `Learn Now`, `Today`, `Memory`, `Weak Areas`,
`Progress`, and `Why this?`; they must not require knowledge of BKT, FSRS, IRT,
or Policy Engine. Learn Now/Today consume the existing server PolicyDecision.
Frontend code may not compute mastery or choose a learning policy. Memory and
misconception views retain evidence references and use `Unknown`/`Possible
misconception` when evidence is insufficient.

Product retention is not learning retention. Synthetic/demo events are marked
and excluded from formal analytics, evaluation, and commercial metrics. Without
real users or billing, surfaces show `NO REAL USER DATA` or `NO COMMERCIAL
EVIDENCE`, never fabricated zeros. FREE/PRO entitlement is server-side and the
billing adapter is provider-neutral until the owner approves a provider and the
associated legal/operational policy.
