# Contributing to Mneme

Mneme is a learning-memory system for K-12 students. Contributions must keep
the safety and evidence boundaries in `AGENTS.md`, `CLAUDE.md`, and
`MNEME_MASTER_DESIGN.md`.

## Before opening a change

```bash
uv sync --locked
npm --prefix apps/mneme-studio ci
./scripts/check.sh
npm --prefix apps/mneme-studio audit --audit-level=moderate
npm --prefix apps/mneme-studio run build
```

The Python suite writes only to `mneme_test`; never point tests at the live
`mneme` database. Database changes must be Alembic migrations and must include
the corresponding purge/retention review for any student-linked table.

## Architectural requirements

- Keep the dependency direction `omodul → oskill → oprim`; `services/` handles
  authorization, routing, and orchestration.
- Facts are append-only Learning Events. Projections, claims, policy decisions,
  and model outputs must carry a version and evidence reference.
- Only `SubmitAnswer → cognitive kernel` may update mastery. Tutor, Agent, CLI,
  Partner, and export adapters must not manufacture mastery.
- Deterministic kernels remain authoritative for supported answer types. LLM
  output must pass the relevant verifier and answer-leakage gate.
- New claims about learning effect must be labelled as code contract, offline
  evaluation, observational evidence, or randomized/real-student evidence.
  Synthetic tests cannot be reported as pilot results.

## Pull request checklist

- [ ] Tests cover the changed contract and red-line behavior.
- [ ] No student PII, secrets, or production database URL is committed.
- [ ] New student data is included in `services/purge_service._STUDENT_TABLES`.
- [ ] Migration, rollback considerations, and deployment order are documented.
- [ ] External evidence claims include cohort, time window, baseline, and
      whether the result is observational or causal.
- [ ] `git diff --check`, Ruff, Mypy, full tests, frontend audit, and frontend
      build pass.

## Production changes

Do not restart live containers, downgrade/drop data, enable a backfill, or
change public access settings as part of a normal PR. Obtain an explicit
release decision, take a recoverable snapshot, apply migrations first, and
record the resulting health/rollback evidence.
