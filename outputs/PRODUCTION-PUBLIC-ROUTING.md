# Production public routing and provider preflight — v0.1.0-rc4

Date: 2026-08-31 UTC
Status: `PUBLIC_ROUTING_READY=NO`; owner action required. No public route was
changed, no runtime code was changed, and no ordinary-user rollout occurred.

This audit contains no credentials, tokens, learner content, or real-user
identifiers.

## Decision

The independently provisioned production stack is healthy on its internal
loopback route, but no owner-approved production hostname was identified and no
safe Cloudflare/DNS/tunnel write authority was available. Existing public/demo
routes were therefore left unchanged.

`PRODUCTION_HOSTNAME_SELECTED=NONE`
`ROUTING_OWNER_ACCESS=NO`
`OWNER_ACTION_REQUIRED=YES`

## Current public route map

| Host/path | Cloudflare/tunnel and proxy evidence | Current service/environment classification | Probe |
|---|---|---|---|
| `sxueji.com/studio/*` | Cloudflare-managed ingress is documented to reach the shared Aegis Caddy `:8083`; Caddy `/studio*` targets `mneme-studio:3001` | Existing shared/demo-shaped studio; not `mneme-production` | HTTP 200 observed for `/studio/learn`, but no production identity proof |
| `sxueji.com/mcp/*` | Same shared `:8083`; documented `/mcp/*` target is `mneme-api-1:8000` | Existing API route; current local runtime is demo-shaped, not the new production stack | HTTP 404 observed for `/mcp/health` |
| `sxueji.com/*` fallback | Shared `:8083` fallback targets `mneme-web:3000` | Existing frontend; not `mneme-production-frontend-1` | Existing route left untouched |
| `api.sxueji.com/*` | Documented/shared Aegis Caddy `:8081` targets `mneme-api-1:8000` | Existing API; exact public environment identity is not proven and must not be treated as production | HTTP 200 observed for `/health` |
| `mneme.uex.hk` | Local legacy cloudflared config maps to `mneme-web:3000` | Legacy alias; not production | No route change |
| `mneme-api.uex.hk` | Local legacy cloudflared config maps to `mneme-api-1:8000` | Legacy API alias; not production | No route change |
| `prod.*`, `production.*`, staging hostnames | No owner-backed active production mapping found | Not configured/proven | No write attempted |

The local `aegis-caddy` container is attached to existing shared networks and
has no attachment to `mneme-production-edge`. Its active Mneme targets are
`mneme-api-1`, `mneme-web`, and `mneme-studio`, not the new production edge.
The active Cloudflare connector is token-managed without a local route file that
proves an owner-approved production hostname. Existing Cloudflare/tunnel route
configuration was not modified.

## New internal production route

The new stack is reachable only through:

`127.0.0.1:18081` → `mneme-production-edge-1` → production API/frontend

The edge is loopback-only. It is not a public production route and was not
presented as one.

## Owner action required

An infrastructure/Cloudflare owner must first approve the canonical production
hostname. A candidate such as `prod.sxueji.com` is not selected by this audit.
After approval, the owner must:

1. Create the DNS/tunnel ingress for the approved hostname to the dedicated
   production edge entry point, not to the shared demo Aegis targets.
2. Preserve `Host`, `X-Forwarded-Proto`, `X-Forwarded-For`, and
   `X-Forwarded-Host` safely; enforce HTTPS and redirect HTTP to HTTPS.
3. Route the approved production API paths (`/health`, `/readiness`, `/v1/*`,
   `/v2/*`, and `/mcp/*`) only to `mneme-production-edge-1` and route the
   frontend paths only to `mneme-production-frontend-1`.
4. Configure and verify WebSocket/streaming support, upload body limits, idle
   and upstream timeouts, and bounded proxy retries without creating retry
   storms.
5. Run the identity proof below through the approved hostname before any
   public-route smoke or canary decision.

No existing `sxueji.com` or `api.sxueji.com` route may be repointed without an
explicit owner-approved routing contract proving that the change is intended.

## Production identity proof

Internal production identity proof passed:

- `MNEME_ENV=production` on API, worker, beat, and frontend.
- Runtime `GIT_SHA` and OCI revision labels:
  `a359877676a39fc2627a6f429adea77b0ed41311`.
- Release: `v0.1.0-rc4`.
- API/worker/beat digest:
  `sha256:32aec19baf11a7523398fa6b013d09ee65c83c548f732709d430f7dd90007c33`.
- Frontend digest:
  `sha256:aefdde6da5a7580ff596dfffa9849f2d66c9705d1c37a8a00e17958628d73495`.
- DB: `mneme_production`; Redis namespace/instance: `mneme-production`;
  storage bucket/prefix: `mneme-production` / `production/`.
- Internal `/health` and `/readiness`: HTTP 200.

Public route identity proof is `FAIL/NOT_VERIFIED` because no public hostname
currently terminates at that edge.

## TLS and public smoke status

The existing public HTTPS front door responds, but that proves only an existing
HTTPS edge, not that it terminates at this production stack. The new production
route has no selected hostname, certificate binding, redirect proof, proxy
header proof, timeout/upload proof, or public readiness proof.

Accordingly, the following gates are not claimed as passed:

- Public production TLS/HTTPS: `NOT_VERIFIED`.
- Production-route proxy headers/timeouts/upload configuration: `NOT_VERIFIED`.
- Public `/health`, `/readiness`, and frontend: `NOT_VERIFIED` as production
  endpoints.
- Production resource isolation over a public route: `NOT_VERIFIED`.
- Public immersive denial and public core smoke: `NOT_RUN`.

The internal production smoke remains global-off and passed in the separate
provisioning audit. No production public request was used for that conclusion.

## Immersive and registration safety

- `IMMERSIVE_LEARNING_ENABLED=OFF`.
- `IMMERSIVE_LEARNING_CANARY_USER_IDS=EMPTY`.
- No real user was added to a canary list.
- Production registration is `CLOSED`.
- No ordinary-user rollout, GA, or public promotion occurred.

The existing RC4 server-side gate and internal/staging qualification remain
unchanged. Public immersive denial cannot be certified until the approved
production hostname is actually connected and tested.

## Provider activation preflight

### Configuration and secret handling

The configured mechanism is server-side runtime configuration. Production
provider secret values are not in Git, images, frontend assets, or audit files;
the dedicated production config is mode 600 under a mode-700 directory, and no
secret value appeared in sampled production logs.

The production config has `MNEME_LLM=default`, mock mode explicitly disabled,
and no live provider key or provider endpoint configured. The production
`/health/providers` result is therefore the default/mock fallback for both text
and vision. A host-local Veya gateway exposes a model catalog, but production
cannot currently reach it and no Mneme production provider contract authorizes
using that unrelated service.

### Activation result

| Gate | Result | Evidence |
|---|---|---|
| LLM provider activated | NO | No approved production provider config/key; runtime reports default/mock fallback |
| VLM provider activated | NO | No approved production VLM config/key; required before immersive provider use |
| Real provider connectivity | FAIL/NOT_RUN | No production provider endpoint is configured or reachable |
| Normal real-provider response | NOT_RUN | No approved provider activation |
| Timeout/retry behavior | FAIL/NOT_VERIFIED | RC4 Veya caller has a 300s client timeout and no caller-level retry/backoff contract |
| Failure graceful degradation | PASS for offline contract only | Existing synthetic/unit resilience checks passed; no live-provider claim |
| Malformed/rate-limit handling | NOT_RUN | Requires an approved provider test endpoint/fixture |
| Mastery/FSRS mutation on provider failure | NO in tested fallback path | Existing failure fallback preserves core learning availability and fabricated-result=false; public/live provider path not exercised |
| Provider observability | FAIL/NOT_READY | Aggregate core counters exist, but provider latency/usage/cost/error series are not activated for production |

The isolated offline provider/degradation selection ran 56 tests and passed.
This result is deliberately not substituted for live provider connectivity.
No runtime code was changed; therefore RC4 remains the exact runtime artifact.

Before activation, the owner must supply the approved provider endpoint/model,
bounded timeout and retry policy, rate/cost budget, server-only secret delivery,
synthetic fixture endpoint, and aggregate metrics without user/email/phone
labels. If implementing missing runtime retry or provider observability is
required, that is a new RC and must not be shipped under the RC4 name.

## Soak and preservation status

Public-route soak: `NOT_RUN` because no public production route exists. The
internal production soak already passed separately with 30 samples, zero 5xx,
zero restarts, and zero DB/worker/projection/FSRS errors.

- Existing demo data modified: `NO`.
- Existing staging data modified: `NO`.
- Existing demo routes modified: `NO`.
- Existing staging routes modified: `NO`.
- RC1/RC2/RC3/RC4 tags moved: `NO`.
- RC4 runtime code changed: `NO`.
- Production publicly exposed: `NO`.

## Final gate status

- P0 blockers: `NONE`.
- P1 blockers: `ROUTING_OWNER_BLOCKER`; `PROVIDER_ACTIVATION_OWNER_BLOCKER`.
- `PUBLIC_ROUTING_READY=NO`.
- `PRODUCTION_CODE_DEPLOYED_INTERNALLY=YES`.
- `PRODUCTION_PUBLICLY_EXPOSED=NO`.
- `FORMAL_USER_ROLLOUT=NO`.

Recommended next gate: `OWNER ROUTING ACTION`. After owner routing and provider
readiness are separately approved and verified, run the public-route smoke and
30-minute soak, then enter a specifically authorized `PRODUCTION CANARY`.
