# Mneme Product Closure Audit

Audit scope: JTBD, product loop, learning data flywheel, and commercial
readiness. This is an engineering audit. It does not claim real users,
revenue, retention, payment, learning effect, or product-market fit.

## Baseline and boundaries

- Baseline HEAD: `20cff85f314381c1357f691338bf472844146e0b`
- Product closure reuses LearningEvent v2, CognitiveStateV2, PolicyDecision,
  Evaluation OS, PilotProtocol, and ModelRegistry. No second learner model,
  event store, recommendation engine, or analytics system was added.
- Product behavior is represented by normal LearningEvent v2 product events.
  `PolicyOutcomeLink` and `LearningOutcomeLedger` are query projections.
- `DEMO_MODE` and notifications are disabled by default. Synthetic events are
  explicitly marked and excluded from product, evaluation, and commercial
  results.
- No production database, production service, payment provider, or real
  student data was accessed or modified.

## Product contracts implemented

- JTBD contract and acceptance vocabulary: `Learn Now`, `Today`, `Memory`,
  `Weak Areas`, `Progress`, and `Why this?`.
- Resumable first-value state machine: `NEW → CONTENT_READY → FIRST_ATTEMPT →
  FIRST_STATE → FIRST_RECOMMENDATION → FIRST_VALUE_COMPLETE`; TTFLV is derived
  only from real event timestamps.
- Learn Now and Today consume the existing server PolicyDecision. The frontend
  does not rank tasks or calculate mastery. Empty queues say `You're caught up`.
- Memory projects cognitive state to `Strong`, `Learning`, `Fading`, or
  `Unknown`; advanced precision is optional and uncertainty remains visible.
- Weak Areas require evidence-backed misconception claims and use `Possible
  misconception` when confidence is insufficient.
- Activity Progress is separate from Learning Progress. No streak, click, or
  wall-clock activity value is presented as learning improvement. Missing
  delayed evidence says `Long-term retention not measured yet.`
- Session summaries, return reasons, and notifications are grounded in real
  event/state/schedule input. Notifications remain disabled by default.

## Data flywheel contracts implemented

- `Interaction → LearningEvent → Evidence → CognitiveState → PolicyDecision →
  Action → Outcome → Evaluation → ModelRegistry → Policy improvement` is
  represented by the existing layers plus policy-outcome and outcome-ledger
  projections.
- `FlywheelHealthReport` includes event, state, policy, outcome, independent,
  delayed, contamination, model-evaluation coverage, and
  `usable_evidence_rate`. Evidence quality is not reduced to event volume.
- Candidate datasets are temporal/student isolated, contamination filtered,
  protocol aware, and shadow-only. Model promotion still requires the existing
  ModelRegistry evidence gate; no automatic upgrade exists.

## Commercial readiness contracts implemented

- FREE keeps the core learning loop available. PRO gates only advanced
  analytics/history/export/AI capabilities.
- Entitlements are server-side and fail closed for unknown, expired, canceled,
  or synthetic subscriptions.
- `BillingProvider` is provider-neutral. `FakeBillingProvider` is test-only and
  forbidden in production. Without a configured provider the result is
  `BILLING_PROVIDER_NOT_CONFIGURED`.
- Prices are `TBD_OWNER_DECISION`. Without real billing records, metrics return
  `NO COMMERCIAL EVIDENCE`, not zero.

## Validation

- `./scripts/check.sh`: PASS — **1304 passed, 14 skipped, 110 warnings**;
  coverage **81.36%**; Ruff PASS; MyPy PASS for **164 source files**; smoke
  PASS; migration upgrade PASS.
- `make pilot-readiness`: PASS — `PILOT ENGINEERING READY`.
- `make product-readiness`: PASS — `PRODUCT ENGINEERING READY`.
- Product contract tests: **26 passed**.
- `npm --prefix apps/mneme-studio ci`: PASS — 453 packages audited.
- `npm --prefix apps/mneme-studio audit --audit-level=moderate`: PASS — 0
  vulnerabilities.
- `npm --prefix apps/mneme-studio run build`: PASS — 14 routes built.
- Migration head: `4d9e0f123456` (single head); the migration is additive,
  downgradeable, and contains no production data change.
- Clean checkout validation: locked Python dependencies, Ruff, MyPy, migration
  head, 38 closure/pilot tests, pilot readiness, product readiness, frontend
  build, and npm audit all passed against the dedicated `mneme_test` context
  where database access was required.

## Scores

Scores are separated so engineering completeness cannot be mistaken for market
or learning evidence.

| Area | Engineering | Evidence | Evidence level | Remaining gap |
|---|---:|---:|---|---|
| JTBD | 18/20 | 8/20 | contract/offline | Real users must validate first value, daily usefulness, and return reasons. |
| Data Flywheel | 18/20 | 6/20 | contract/offline | Real event/outcome volume and independent/delayed evidence are pending. |
| Product / Commercial | 18/20 | 4/20 | contract only | Real users, billing, conversion, revenue, and PMF evidence are pending. |

## Explicit answers

1. PRODUCT ENGINEERING READY? **YES**
2. DATA FLYWHEEL CLOSED? **YES, engineering contract closed; real evidence pending**
3. CORE JTBD CLOSED? **YES, engineering contract closed; user validation pending**
4. BILLING ENGINEERING READY? **YES, provider-neutral readiness only**
5. REAL USERS EXIST? **NO**
6. REAL D7/D30 RETENTION EXISTS? **NO**
7. REAL COMMERCIAL CONVERSION EXISTS? **NO**
8. PRODUCT-MARKET FIT PROVEN? **NO**

## Remaining blockers

No repository-level engineering blocker remains for this phase. Owner or real-
world intervention is required for:

- JTBD interviews/usage and a real approved cohort;
- consent, legal/guardian/ethics and production deployment decisions;
- real delayed/independent learning outcomes and sufficient sample sizes;
- any randomized learning-effect claim;
- price, terms, billing provider, refunds, and commercial operations;
- real payment, conversion, retention, revenue, and PMF evidence.

**ENGINEERING COMPLETE**

**REAL-WORLD EVIDENCE PENDING**
