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
- `.echo/echomimic_repo` is excluded by the root `.dockerignore`, is not copied
  by either release Dockerfile, and has no Mneme import path: **NOT_RUNTIME_REACHABLE**.

## Blocking evidence

- Full RC7 isolated-staging deployment and 30-minute soak were not run.
- Veya live completion was not rerun from an RC7 staging container.
- Hosted-runner Trivy scan of the exact API digest completed with **56 findings
  (53 HIGH, 3 CRITICAL)**, so the image security gate is **FAIL**.
- The frontend exact-digest scan was launched in the same hosted workflow, but
  its final result was not retrievable after the GitHub API rate limit was hit;
  it is not treated as PASS.
- The separate filesystem scan reported 25 HIGH/CRITICAL findings under the
  non-runtime `.echo/echomimic_repo` dependency tree; they are not included in
  the RC7 image, but remain an audit finding outside the release runtime.

Immersive remains OFF, the canary policy is not opened, registration is not
changed, and production is not deployed.
