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
