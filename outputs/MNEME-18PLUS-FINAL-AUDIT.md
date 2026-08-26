# Mneme 18+/20 Final Audit

Date: 2026-08-26
Base HEAD: `552ce7decf9ebeebdb44950aaba9fc36d111d9db`
Audit mode: local working tree, dedicated `mneme_test`, no production writes

## Acceptance summary

- Engineering score: **18.25 / 20** (contract/readiness score, not a learning-effect claim).
- Real-student, randomized, commercial evidence: **not present**.
- Required status: **ENGINEERING COMPLETE / REAL-WORLD EVIDENCE PENDING**.
- The code-review-graph MCP tools were unavailable in this session; the audit
  used the repository's fallback local inspection plus tests and quality gates.

## 20-item audit

### 1. Category / Strategy

- Score: **18/20**
- Evidence: Mneme is consistently implemented as Personal Learning Memory OS /
  Cognitive Infrastructure: immutable events, cognitive projection, policy and
  action loop.
- Code: `README.md`, `MNEME_MASTER_DESIGN.md`, `services/cognitive_state_v2.py`.
- Tests: full quality gate and Cognitive State contract tests.
- Remaining gap: product strategy still needs validation with the target cohort.
- Evidence level: `contract`.

### 2. JTBD

- Score: **17/20**
- Evidence: practice, review, Tutor, replay, learner state, evidence explanation,
  export and next-action surfaces are wired.
- Code: `services/routers/memory.py`, `services/cognitive_service.py`,
  `packages/mneme-agent/`.
- Tests: route, memory, Tutor and full pytest suites pass.
- Remaining gap: no measured student task completion, retention or satisfaction.
- Evidence level: `contract`; real usage pending.

### 3. Differentiation / Moat

- Score: **19/20**
- Evidence: state is built from durable LearningEvent history and deterministic
  BKT+FSRS+recognition projections with evidence references.
- Code: `packages/event-schema/`, `services/learning_event_replay_service.py`,
  `services/cognitive_state_v2.py`.
- Tests: replay determinism, provenance, model shadow and kernel guards pass.
- Remaining gap: moat strength requires longitudinal real-student accumulation;
  no commercial defensibility claim is made.
- Evidence level: `contract` / `offline` infrastructure.

### 4. Learning Science

- Score: **19/20**
- Evidence: BKT mastery, FSRS retrievability, retrieval/spacing, recognition,
  transfer phases, JOL and independence contamination rules are separated.
- Code: `vendor/oprim/`, `services/cognitive_state_v2.py`,
  `services/evaluation_os.py`, `mneme_core/tutor_control.py`.
- Tests: kernel, recognition, retrieval, transfer, delayed and Tutor red-line
  tests pass.
- Remaining gap: effect sizes and generalization require real delayed endpoints.
- Evidence level: `contract` / `offline`; no causal claim.

### 5. Cognitive Model

- Score: **19/20**
- Evidence: typed `CognitiveStateV2` covers knowledge, memory, recognition,
  transfer, misconception, metacognition, uncertainty and provenance; unknown
  dimensions stay `None`.
- Code: `services/cognitive_state_v2.py`, `services/learner_model.py` facade.
- Tests: `test_cognitive_state_contract.py`, replay, uncertainty, provenance and
  no-fake-evidence tests.
- Remaining gap: OOD detection remains an explicit unknown (`None`) until a
  validated detector exists.
- Evidence level: `contract`.

### 6. Learning Memory

- Score: **19/20**
- Evidence: append-only v2 events, checksums, corrections, as-of replay,
  version comparison and FSRS card projection are in one memory loop.
- Code: `packages/event-schema/`, `services/learning_event_service.py`,
  `services/learning_event_replay_service.py`.
- Tests: Event v2 ingest/replay/backfill and full pytest pass.
- Remaining gap: historical production backfill requires owner approval and a
  reversible operational window.
- Evidence level: `contract`.

### 7. Event / Evidence

- Score: **19/20**
- Evidence: `EvidenceRef` and `EvidenceClaim` enforce event references, model /
  verifier versions and the closed five-level evidence vocabulary.
- Code: `services/evidence_graph.py`, `services/routers/memory.py`, migration
  `4a6b7c8d9e01`.
- Tests: provenance, claim-reference, privacy and event contract tests pass.
- Remaining gap: no real-world claims exist yet; the system correctly does not
  create them without evidence.
- Evidence level: `contract`.

### 8. Policy Engine

- Score: **19/20**
- Evidence: deterministic `mneme-core` ranking now carries state version,
  reason codes, candidate actions, uncertainty signals and evidence refs;
  routes persist `PolicyDecision` traces.
- Code: `packages/mneme-core/mneme_core/policy_engine.py`,
  `services/policy_trace.py`, `services/routers/memory.py`.
- Tests: policy trace, replay determinism, no-direct-mastery-write and full
  quality gate pass.
- Remaining gap: utility estimates remain contract heuristics until calibrated
  against real outcomes.
- Evidence level: `contract`.

### 9. AI Tutor

- Score: **18/20**
- Evidence: Tutor control, answer tiering, independent mode, deterministic
  leakage guard and MCP boundary are present; Tutor cannot write mastery.
- Code: `packages/mneme-core/mneme_core/tutor_control.py`,
  `packages/mneme-agent/`, `services/mcp_router.py`.
- Tests: Tutor, answer-leakage, partner and agent boundary tests pass.
- Remaining gap: no measured Tutor learning effect, no live pilot completion
  or no-AI delayed endpoint result.
- Evidence level: `contract`.

### 10. Deterministic Kernel

- Score: **19/20**
- Evidence: BKT, FSRS, recognition, grading and solve paths are reused; static
  guards prevent a second mastery write path and sandbox bypass.
- Code: `vendor/oprim/`, `vendor/oskill/`, `services/cognitive_service.py`,
  `tests/test_mastery_write_path_guards.py`.
- Tests: smoke 44 passed, kernel/sandbox suites and full pytest pass.
- Remaining gap: real-student calibration and domain expansion remain future work.
- Evidence level: `contract` / `offline`.

### 11. Evaluation OS

- Score: **18/20**
- Evidence: D7/D30, transfer, no-AI, delayed pairing, time split, shadow metrics,
  slice metrics and ModelRegistry promotion gates exist.
- Code: `services/evaluation_os.py`, `services/shadow_evaluation.py`,
  `services/model_registry.py`, `services/pilot_protocol.py`.
- Tests: evaluation, shadow, registry, pilot and slice contracts pass.
- Remaining gap: no actual registered pilot cohort or randomized result.
- Evidence level: `contract` / `offline` infrastructure.

### 12. Data Flywheel

- Score: **17/20**
- Evidence: event checksums, replay, evidence provenance, shadow evaluation and
  policy traces provide a non-fabricating flywheel foundation.
- Code: `services/learning_event_service.py`, replay/evidence/policy modules.
- Tests: replay determinism, model promotion and observability tests pass.
- Remaining gap: the flywheel has no real-student volume or proven improvement
  loop yet.
- Evidence level: `contract`; observational data pending.

### 13. Architecture

- Score: **19/20**
- Evidence: existing services/packages/3O boundaries are preserved; Event = Fact,
  State = Inference, Policy = Decision remains explicit.
- Code: `CLAUDE.md`, `services/`, `packages/`, `vendor/` and AST guards.
- Tests: vendor closure, no-gating-coupling, no-direct-write and full checks pass.
- Remaining gap: code-review-graph was unavailable for this audit session.
- Evidence level: `contract`.

### 14. Reproducibility

- Score: **19/20**
- Evidence: `uv.lock`, `npm` lockfile, self-bootstrapping Alembic paths,
  vendored 3O runtime and test path shim work in a new worktree.
- Code: `alembic/env.py`, `tests/conftest.py`, `oprim/__init__.py`, CI workflow.
- Tests: clean-room `uv sync --locked`, Ruff, MyPy, Alembic and 34 closure tests
  passed.
- Remaining gap: CI hosted execution itself was not fabricated or manually
  asserted; GitHub Actions must run on push/PR.
- Evidence level: `contract`.

### 15. Testing

- Score: **19/20**
- Evidence: final quality gate: **1250 passed, 14 skipped, 110 warnings**;
  coverage **82.08%**; frontend build and audit pass.
- Code: `scripts/check.sh`, `tests/`, new closure contract tests.
- Tests: Ruff, MyPy, smoke, migrations, full pytest, npm audit/build and
  clean-room core gate pass.
- Remaining gap: warnings and skipped external/live tests remain explicitly
  documented; they are not converted to passes.
- Evidence level: `contract`.

### 16. Repository Governance

- Score: **19/20**
- Evidence: evidence levels, production-operation restrictions, migration policy,
  pilot blockers and final report discipline are documented.
- Code/docs: `CLAUDE.md`, `docs/GOVERNANCE.md`, `TASKS.md`, ADRs.
- Tests: DB guard, hard-delete, privacy and production safety tests pass.
- Remaining gap: legal repository license and any live rollout approval remain
  owner decisions.
- Evidence level: `contract`.

### 17. Reliability / Observability

- Score: **18/20**
- Evidence: bounded trace IDs, request metrics and named pipeline counters:
  ingest, projection lag/failures, policy, shadow evaluation and insufficient
  evidence.
- Code: `services/observability.py`, event/state/policy/shadow integrations.
- Tests: observability and closure counter tests pass.
- Remaining gap: metrics are process-local; durable production telemetry and
  alert thresholds need deployment configuration.
- Evidence level: `contract`.

### 18. Privacy / Governance

- Score: **18/20**
- Evidence: P0–P3 event classes, P2/P3 interop redaction, process privacy,
  purge inventory and export boundary are preserved for new traces.
- Code: `packages/event-schema/event_schema/interoperability.py`,
  `services/purge_service.py`, `services/routers/memory.py`.
- Tests: privacy, partner minimization, hard-delete, export and closure privacy
  tests pass.
- Remaining gap: jurisdiction-specific legal review and live retention policy
  approval are not engineering evidence.
- Evidence level: `contract`.

### 19. Interoperability

- Score: **18/20**
- Evidence: xAPI, Caliper and CASE adapters preserve stable pseudonymous
  identifiers and now carry evaluation phase without exposing private P2/P3
  process fields by default.
- Code: `packages/event-schema/event_schema/interoperability.py`.
- Tests: event interoperability and privacy tests pass.
- Remaining gap: no external LMS/partner certification or deployed interchange
  evidence is claimed.
- Evidence level: `contract`.

### 20. Product / Commercial

- Score: **14/20**
- Evidence: product surfaces and pilot/commercial measurement schemas exist;
  frontend builds successfully.
- Code: `apps/mneme-studio/`, `services/pilot_protocol.py`, README/docs.
- Tests: frontend build and npm audit pass; no commercial test is claimed.
- Remaining gap: real acquisition, activation, retention, pricing, payment,
  support and unit-economics evidence are entirely pending.
- Evidence level: `contract`; commercial evidence absent.

## Evidence boundary and blockers

The following cannot be resolved by local code changes alone:

1. **Real students:** consented cohort, no-AI/delayed/transfer observations,
   retention windows and RMG/AM measurements.
2. **Owner decision:** legal license, pilot protocol/consent, feature-flag
   activation and approval of any historical backfill.
3. **Production environment:** applying additive migrations to production,
   enabling live writes, durable metrics/alerts and rollout monitoring.
4. **Commercial evidence:** real funnel, pricing, payment and support data.
5. **Randomized evidence:** pre-registered assignment and eligible independent
   delayed endpoints; no observed difference is being called causal.

No blocker was hidden with synthetic data, skipped tests, fabricated GitHub
Actions, production claims, pilot outcomes or commercial claims.

## Final answers

**Mneme 是否已经达到工程意义上的 18+/20？**

**是。** 按本报告的工程/contract/readiness 口径为 **18.25/20**；核心状态、
证据、策略、replay、迁移、隐私、观测和质量门已形成可验证闭环。该分数不
等于真实学习效果或商业成功。

**Mneme 是否已经有足够真实世界证据，可以声称产品整体达到 18+/20？**

**否。** 目前没有真实学生 pilot、RCT 因果结果或 commercial evidence；
正确表述仍是：**ENGINEERING COMPLETE / REAL-WORLD EVIDENCE PENDING**。
