# Mneme v0.1.0-rc5 staging qualification

Status: **isolated staging and fake-provider qualification PASS**; overall RC5
qualification remains **NO** until owner supplies the live-provider staging
connectivity gate.

## Exact artifacts

| Service | Tag | Digest | Source SHA |
|---|---|---|---|
| API | `mneme-api:v0.1.0-rc5-2dda33e` | `sha256:dc02c73d2057b2d40416b2ad8cfd1d8029302780cfa4f60f015823bde5b6d2bf` | `2dda33e1fa5532d0375aaeed47e793cac9da720c` |
| Worker | `mneme-worker:v0.1.0-rc5-2dda33e` | `sha256:dc02c73d2057b2d40416b2ad8cfd1d8029302780cfa4f60f015823bde5b6d2bf` | `2dda33e1fa5532d0375aaeed47e793cac9da720c` |
| Beat | `mneme-beat:v0.1.0-rc5-2dda33e` | `sha256:dc02c73d2057b2d40416b2ad8cfd1d8029302780cfa4f60f015823bde5b6d2bf` | `2dda33e1fa5532d0375aaeed47e793cac9da720c` |
| Frontend production | `mneme-web:v0.1.0-rc5-3769bce` | `sha256:6f2659ee4a269734837b9e4521c6e774f01e39af7d4e6c2264f8f6bbd551f204` | `3769bce5e401e0bbd8022fd46231a54da4e7564c` |
| Frontend staging | `mneme-web:v0.1.0-rc5-3769bce-staging` | `sha256:849a0605652cb3dfee7dc1fe31ab8eb5f4b07960b99887e5fdd2e6a605fe4229` | `3769bce5e401e0bbd8022fd46231a54da4e7564c` |

Staging used the existing isolated Compose project with loopback-only API
(`127.0.0.1:18000`) and frontend (`127.0.0.1:13001`) ports. No production
container, DNS, Cloudflare, Aegis, Caddy, or public ingress was changed.

## Canary and routing

- Immersive global flag: **OFF**.
- Synthetic allowlist A: enabled with reason `CANARY`.
- Synthetic control B: denied with reason `DISABLED`.
- Staging frontend bundle contained the staging API origin and had zero hits
  for retired `api.sxueji.com`.
- Production frontend artifact is separately built with
  `https://api-prod.sxueji.com`; demo/staging/prod isolation tests passed.

## Fake-provider staging matrix

The exact RC5 API image called a loopback fake endpoint using synthetic input.
Success returned usage (7 input, 3 output); timeout, 5xx, 429, and malformed
responses degraded to safe typed errors. Three 5xx failures opened the circuit;
the half-open recovery probe succeeded after the bounded recovery window.
No real provider key or real user data was used.

## Soak

The staging health/metrics loop ran **183 samples at 10 s**, approximately
**30.5 minutes**. Results: HTTP 5xx **0**, health/metrics failures **0**, API
restarts **0**, worker restarts **0**, beat restarts **0**, projection errors
**0**, FSRS errors **0**. Provider failure probes ran outside the soak process
and did not mutate learning state.

## Outstanding gate

Owner must inject a real staging provider secret through the existing staging
secret mechanism and authorize exactly one synthetic text call and, if needed
for the next stage, one synthetic image fixture call. Until that happens,
RC5_QUALIFIED is **NO**. Production remains undeployed.
