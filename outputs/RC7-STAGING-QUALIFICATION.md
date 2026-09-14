# Mneme v0.1.0-rc7 staging qualification

Status: **NOT QUALIFIED**.

RC7 was created because the public RC6 tag could not be rewritten after the
frontend dependency fixes. RC7 source SHA is
`2377731f236e6f7733eb7ee3b74d24d91c5b96b6`; runtime delta versus RC5 is
`NONE`.

## Completed

- `check.sh`: 1417 passed, 15 skipped, coverage 80.24%.
- Frontend Next.js 16.3.5 build and TypeScript check: PASS.
- `npm audit`: 0 critical, 0 high, 0 moderate, 0 low.
- pip-audit against the project `.venv`: 0 known vulnerabilities.
- gitleaks RC6→RC7 diff: 0 new findings.
- GHCR publication and independent fresh-runner pull-by-digest: PASS.
- OCI revision metadata matches the RC7 manifest.

## Blocking evidence

- Full RC7 isolated-staging deployment and 30-minute soak were not run.
- Veya live completion was not rerun from an RC7 staging container.
- trivy container scan could not complete locally because the temporary layer
  extraction hit the host disk quota. The filesystem scan separately reported
  25 HIGH/CRITICAL findings under the unrelated `.echo/echomimic_repo`
  依赖树; they require explicit scope/base-image disposition before release.

Immersive remains OFF, the canary policy is not opened, registration is not
changed, and production is not deployed.
