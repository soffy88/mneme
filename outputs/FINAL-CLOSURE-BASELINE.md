# Mneme 18+/20 Final Closure — Baseline Audit

Date: 2026-08-26
HEAD: `552ce7decf9ebeebdb44950aaba9fc36d111d9db`
Branch: `chore/test-pythonpath-fix` (tracking `origin/chore/test-pythonpath-fix`)

## Repository state

`git status --short --branch` at audit start:

```text
## chore/test-pythonpath-fix...origin/chore/test-pythonpath-fix
?? outputs/FINAL-CLOSURE-BASELINE.md
```

The baseline report was an existing untracked workspace artifact; it was
replaced with this evidence record. No production database, container, webhook,
or irreversible migration was touched.

## Baseline commands and results

| Command | Result | Classification |
|---|---|---|
| `uv sync --locked` | PASS — resolved 116, checked 113 packages | reproducible dependency install |
| `uv run alembic upgrade head` | FAIL — `ModuleNotFoundError: obase` | repository entry-point path defect; no DB change |
| `./scripts/check.sh` | PASS — Ruff, vendor closure, smoke, MyPy, migration, pytest | authoritative local quality gate |
| `npm --prefix apps/mneme-studio ci` | PASS — 453 packages, 0 vulnerabilities | frontend dependency install |
| `npm --prefix apps/mneme-studio audit --audit-level=moderate` | PASS — 0 vulnerabilities | frontend security gate |
| `npm --prefix apps/mneme-studio run build` | PASS after `npm ci` completed | frontend build gate |

The first build started concurrently with `npm ci` and reported missing
`baseline-browser-mapping`; the required sequential rerun after install passed.

`./scripts/check.sh` baseline details:

- Ruff: PASS
- vendor education boundary: PASS, 98 imports/file checks
- red-line/sandbox smoke: 44 passed
- MyPy: PASS, 157 source files
- Alembic against `mneme_test`: PASS
- pytest: **1229 passed, 14 skipped, 110 warnings**
- coverage: **82.38%**, required 60%

## Existing capability audit

| Area | Existing at baseline | Structural gap remaining at baseline |
|---|---|---|
| Event | `packages/event-schema` LearningEvent v2, immutable checksum, correction and replay ordering | explicit evaluation phase and full projection trace still incomplete |
| Cognitive state | `services/learner_state_service.py` read-only mastery/memory/recognition/transfer/metacognition/uncertainty view | no typed unified CognitiveStateV2, version comparison or complete provenance contract |
| Kernel | existing vendor BKT, FSRS, recognition and `omodul.cognitive` write path | new state must consume, not duplicate, those kernels |
| Evidence | memory claim/evidence tables and event evidence adapter | no shared EvidenceRef/EvidenceClaim contract with evidence levels |
| Policy | deterministic `mneme_core.policy_engine` and next-action route | no full decision trace/persistence or uncertainty-first selection contract |
| Transfer | explicit `tutor_mode`, `ai_assisted`, `independent_mode`, `evaluation_phase` on legacy events | no strict IndependentMasteryEvidence query / contaminated-event guard |
| Evaluation | Evaluation OS v2, delayed/no-AI guards, shadow evaluation and ModelRegistry | no registered PilotProtocol/RMG-AM runner and slice report contract |
| Privacy | purge inventory, P0–P3 event export redaction, xAPI/Caliper/CASE adapters | new trace data must join purge/export/observability guards |
| Observability | request metrics and X-Trace-Id | required learning-pipeline counters and end-to-end trace fields incomplete |
| Reproducibility | locked uv/npm dependencies and CI path setup | direct Alembic command did not self-bootstrap repository module paths |

## Evidence discipline

The baseline contains contract and offline/observational infrastructure only.
It contains no real-student pilot result, randomized causal result, commercial
result, production rollout claim, or fabricated synthetic substitute for those
claims. Any final score must keep `ENGINEERING COMPLETE` separate from
`REAL-WORLD EVIDENCE PENDING`.
