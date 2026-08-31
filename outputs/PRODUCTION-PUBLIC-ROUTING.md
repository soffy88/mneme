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

## Owner action packet — recommended production hostnames

This packet is executable by the infrastructure/Cloudflare owner. It is a
request for owner-side changes, not evidence that those changes have been
performed. The recommended names are:

- Frontend: `app-prod.sxueji.com`
- API: `api-prod.sxueji.com`

No DNS answer, HTTPS route, or local deployment reference was found for either
name during this audit. `CONFLICT_CHECK=PASS` means no visible local/DNS
conflict; the owner must still confirm that both names are unclaimed in the
Cloudflare account before creating them. Existing `sxueji.com/*`,
`api.sxueji.com/*`, `mneme.uex.hk`, and `mneme-api.uex.hk` routes are excluded
from this packet and must not be changed.

### Production target and network

The production edge is the only intended public entry point:

```text
app-prod.sxueji.com  ─┐
                      ├─ Cloudflare Tunnel → 127.0.0.1:18081
api-prod.sxueji.com  ─┘                         → mneme-production-edge-1:80
                                                   ├─ API paths → api:8000
                                                   └─ frontend  → frontend:3001
```

The exact Docker identities are:

- edge container: `mneme-production-edge-1`, container port `80`, host binding
  `127.0.0.1:18081`, Docker network `mneme-production-edge`;
- API target: service `api:8000` / container `mneme-production-api-1` on
  `mneme-production-edge`;
- frontend target: service `frontend:3001` / container
  `mneme-production-frontend-1` on `mneme-production-edge`.

Preferred minimal owner procedure (run on the production host, with the
Cloudflare and Docker owner identities):

```sh
# Confirm the isolated edge before touching routing.
docker inspect mneme-production-edge-1 \
  --format 'name={{.Name}} port={{(index .Config.ExposedPorts "80/tcp")}} networks={{json .NetworkSettings.Networks}}'
curl --fail --silent --show-error http://127.0.0.1:18081/health
curl --fail --silent --show-error http://127.0.0.1:18081/readiness

# Add the existing Aegis Caddy container to the production edge network only
# if the owner chooses Aegis as the tunnel origin. Do not disconnect it from
# any existing network and do not change an existing route.
docker network connect mneme-production-edge aegis-caddy
```

If the tunnel daemon runs on this same host, its two new ingress entries may
point directly to `http://127.0.0.1:18081`, avoiding any shared Aegis route.
If the owner standard requires Aegis, point both names to the dedicated edge
service `mneme-production-edge-1:80` from Aegis after the network attachment.
Do not point either name to `mneme-api-1`, `mneme-web`, `mneme-studio`, or a
shared `:8081`/`:8083` listener.

### Cloudflare/Tunnel action

With the existing tunnel name or ID filled in by the owner:

```sh
TUNNEL='<OWNER_APPROVED_TUNNEL_NAME_OR_ID>'
cloudflared tunnel route dns "$TUNNEL" app-prod.sxueji.com
cloudflared tunnel route dns "$TUNNEL" api-prod.sxueji.com
cloudflared tunnel ingress validate
```

Add these ingress rules to the authoritative tunnel configuration, before its
catch-all rule, and reload the tunnel through its managed service. The exact
configuration form is:

```yaml
ingress:
  - hostname: app-prod.sxueji.com
    service: http://127.0.0.1:18081
  - hostname: api-prod.sxueji.com
    service: http://127.0.0.1:18081
  - service: http_status:404
```

If Cloudflare runs outside the production host, replace the service target with
the owner-approved private Aegis endpoint; do not expose port 18081 publicly.
Enable proxied DNS, TLS mode `Full (strict)`, HTTPS redirect, and the normal
Cloudflare WebSocket setting. Do not make any DNS or ingress change for the
existing demo/legacy names.

### Aegis/Caddy action

If Aegis is the selected origin, add the following host blocks to the
authoritative Aegis Caddyfile and reload only after `caddy validate` succeeds.
The upstream is the dedicated production edge, not the shared demo services:

```caddyfile
app-prod.sxueji.com {
    encode zstd gzip
    reverse_proxy mneme-production-edge-1:80 {
        header_up Host {http.request.host}
        header_up X-Forwarded-Proto https
        header_up X-Forwarded-Host {http.request.host}
        transport http {
            dial_timeout 5s
            response_header_timeout 30s
            read_timeout 305s
            write_timeout 305s
        }
    }
}

api-prod.sxueji.com {
    request_body {
        max_size 25MB
    }
    reverse_proxy mneme-production-edge-1:80 {
        header_up Host {http.request.host}
        header_up X-Forwarded-Proto https
        header_up X-Forwarded-Host {http.request.host}
        transport http {
            dial_timeout 5s
            response_header_timeout 30s
            read_timeout 305s
            write_timeout 305s
        }
    }
}
```

Caddy's `reverse_proxy` provides WebSocket upgrade support; verify it with a
synthetic authenticated streaming/WebSocket fixture if that path is used.
Preserve `X-Forwarded-For` using the managed proxy's trusted-proxy policy;
accept forwarded headers only from the Cloudflare/Aegis source ranges, and do
not trust arbitrary client-supplied `X-Forwarded-*` values. The 305-second
upstream read/write ceiling is intentionally above the current provider
caller's maximum 300 seconds, but it does not fix the caller's retry policy.
The 25 MB body limit must be checked against the API's actual upload contract
before activation; lower it if the owner contract permits a smaller limit.

The production edge's existing path split remains authoritative:

```text
/health, /readiness, /v1/*, /v2/*, /mcp/* → api:8000
/studio* and fallback                       → frontend:3001
```

### Post-routing verification packet

Codex can run these checks after the owner confirms the two changes. They must
be run against synthetic production credentials only; values containing keys,
tokens, cookies, or user content must not be pasted into the audit:

```sh
set -eu
for host in app-prod.sxueji.com api-prod.sxueji.com; do
  curl --fail --silent --show-error --proto '=https' --tlsv1.2 \
    "https://$host/health" >/tmp/mneme-prod-health.json
  curl --fail --silent --show-error --proto '=https' --tlsv1.2 \
    "https://$host/readiness" >/tmp/mneme-prod-readiness.json
done
curl --fail --silent --show-error --proto '=https' --tlsv1.2 \
  -o /tmp/mneme-prod-frontend.html https://app-prod.sxueji.com/studio

# The operator must compare these redacted fields from health/readiness and
# container labels; never print environment files or secret-bearing headers.
docker inspect mneme-production-api-1 mneme-production-worker-1 \
  mneme-production-beat-1 mneme-production-frontend-1 \
  --format '{{.Name}} {{index .Config.Labels "org.opencontainers.image.revision"}} {{index .Config.Labels "org.opencontainers.image.version"}}'
```

Expected identity is `MNEME_ENV=production`,
`GIT_SHA=a359877676a39fc2627a6f429adea77b0ed41311`, release
`v0.1.0-rc4`, API/worker/beat digest
`sha256:32aec19baf11a7523398fa6b013d09ee65c83c548f732709d430f7dd90007c33`,
and frontend digest
`sha256:aefdde6da5a7580ff596dfffa9849f2d66c9705d1c37a8a00e17958628d73495`.
The verifier must also confirm the production DB/storage/Redis identity, HTTPS
redirect, Host/forwarded-header behavior, upload limit, WebSocket/streaming
behavior, and that the existing demo/staging route probes and resource marker
counts are unchanged.

Important artifact finding: the exact RC4 frontend image was built with
`NEXT_PUBLIC_API_BASE=https://api.sxueji.com`. It therefore cannot safely be
used as the browser frontend for `app-prod.sxueji.com` while the API is
`api-prod.sxueji.com`; the browser would call the existing shared API. The
owner must either provide an explicitly approved same-origin/API routing design
that is proven not to hit the demo API, or request a new frontend build with
`NEXT_PUBLIC_API_BASE=https://api-prod.sxueji.com`. That build-time artifact
change is not being made here and cannot be represented as the existing RC4
frontend artifact.

## Provider activation owner template

The following are the variables read by the current RC4 code. Fill only the
chosen provider branch; leave unused provider secrets unset. `MODEL`, `API_KEY`,
and `BASE_URL` are explanatory placeholders, not generic variables recognized
by the current code.

```dotenv
# Selector: qwen | veya | ollama | (empty/default priority mode)
MNEME_LLM=<OWNER_CHOICE>
MNEME_ALLOW_MOCK_LLM=0

# Qwen (text + VLM through the OpenAI-compatible caller)
DASHSCOPE_API_KEY=<SECRET>
QWEN_API_KEY=<SECRET_OR_EMPTY>
QWEN_BASE_URL=<APPROVED_HTTPS_ENDPOINT>
QWEN_MODEL=<APPROVED_TEXT_MODEL>
QWEN_VL_MODEL=<APPROVED_VISION_MODEL>

# Veya (text + VLM; only an owner-approved reachable gateway)
VEYA_API_KEY=<SECRET_OR_EMPTY>
VEYA_BASE_URL=<APPROVED_HTTPS_OR_PRIVATE_ENDPOINT>
VEYA_MODEL=<APPROVED_TEXT_MODEL>
VEYA_VL_MODEL=<APPROVED_VISION_MODEL>

# Default-priority providers (only if MNEME_LLM is empty/default)
DEEPSEEK_API_KEY=<SECRET_OR_EMPTY>
OPENAI_API_KEY=<SECRET_OR_EMPTY>
ANTHROPIC_API_KEY=<SECRET_OR_EMPTY>
GEMINI_API_KEY=<SECRET_OR_EMPTY>

# Ollama only (text; it does not configure a VLM)
OLLAMA_BASE_URL=<APPROVED_PRIVATE_ENDPOINT>
OLLAMA_MODEL=<APPROVED_TEXT_MODEL>
```

Authoritative defaults are Qwen text `qwen-plus`, Qwen VLM `qwen-vl-max`,
Veya text `veya1.2-128K`, Veya VLM `veya1.2-vl`, Ollama text `qwen2.5:7b`,
DeepSeek text `deepseek-chat`, Claude text `claude-3-5-sonnet-20240620`,
OpenAI text `gpt-4o-mini`, and Gemini VLM/text `gemini-1.5-flash`. The owner
must explicitly approve the actual model and endpoint rather than relying on a
default. Qwen's current custom caller needs a reachable OpenAI-compatible
`/chat/completions` endpoint; the host-local Veya gateway observed in this
environment is not reachable from production and is not an approved production
dependency.

The following policy fields are required for a safe live canary but are **not**
recognized by RC4 callers today:

```dotenv
PROVIDER_CONNECT_TIMEOUT_SECONDS=<OWNER_POLICY>
PROVIDER_READ_TIMEOUT_SECONDS=<OWNER_POLICY>
PROVIDER_MAX_RETRIES=<OWNER_POLICY>
PROVIDER_RETRY_BACKOFF_SECONDS=<OWNER_POLICY>
PROVIDER_RATE_LIMIT_RPM=<OWNER_POLICY>
PROVIDER_TOKEN_BUDGET_DAILY=<OWNER_POLICY>
PROVIDER_COST_BUDGET_DAILY=<OWNER_POLICY>
PROVIDER_SYNTHETIC_FIXTURE_ENDPOINT=<OWNER_ONLY>
PROVIDER_METRICS_NAMESPACE=mneme_provider
```

Store secrets in the approved external production secret manager, injected at
runtime, or in the existing mode-0600
`/data/soffy/mneme-production/.env.production` mechanism with directory mode
700. The secret manager is preferred. Do not place them in Git, a Dockerfile,
an image layer, Next.js public variables, `/health` responses, metrics labels,
logs, or audit files. `MNEME_LLM`, model names, and non-secret policy values
may be config, but endpoint authorization and secret-bearing configuration must
remain server-side.

## Provider canary assessment and RC boundary

Current RC4 caller behavior is not sufficient for a real provider canary as a
production reliability contract:

- Qwen text timeout is 120 seconds and Qwen VLM timeout is 180 seconds;
- Veya text/VLM and Ollama text callers use 300 seconds;
- caller-level retry/backoff, circuit breaking, bounded concurrency, rate
  limiting, and cost/token budgets are absent;
- the existing metrics provide aggregate request/error/latency and
  `llm_failures_total`, but not provider request count, provider error class,
  timeout count, provider latency, input/output token usage, or cost series;
- existing failure fallback was verified offline (56 tests passed), but no live
  provider connectivity, timeout, retry, malformed-response, or rate-limit
  fixture was run.

Therefore:

`LLM_PROVIDER_REQUIRED=YES` before an LLM-dependent production canary;
`VLM_PROVIDER_REQUIRED=YES` before enabling any immersive/VLM path (it is not
needed for the current global-off core smoke); `PROVIDER_ACTIVATED=NO`;
`PROVIDER_OBSERVABILITY=INSUFFICIENT`; and
`RUNTIME_CODE_CHANGE_REQUIRED_BEFORE_CANARY=YES`.

The minimum runtime work is a new RC (`RC5_REQUIRED`): configurable bounded
connect/read deadlines, bounded retries only for explicitly idempotent calls
with exponential backoff, circuit breaker/bulkhead, rate and token/cost
budgets, graceful malformed/timeout/provider-error handling, and aggregate
provider metrics for request/error/latency/timeout/token usage/cost with no
user/email/phone labels. The frontend API-base artifact issue above also needs
an explicitly rebuilt/qualified frontend image if `api-prod.sxueji.com` is used.
No such runtime or image change was made in this turn.

Owner completion required before Codex can resume: approve and create the two
hostnames, install the tunnel ingress, apply and validate the Aegis/edge route,
confirm TLS/proxy limits, resolve the frontend API-base choice, select and
provision a live provider secret/model/endpoint and its policy/fixture, and
provide owner evidence that the changes are live. Codex can then automatically
run route identity proof, public health/readiness/frontend checks, public core
smoke, immersive denial, demo/staging preservation checks, provider fixture
tests, and the 30-minute public-route soak. If runtime changes are required,
Codex must stop at `NEW_RC_REQUIRED` and not reuse RC4.

This turn changed documentation only. `RC4_TAG_UNCHANGED=YES`,
`PRODUCTION_DEPLOYED=NO`, `PUBLIC_ROUTING_READY=NO`, and the recommended next
gate is `FIX BLOCKERS` in the order: owner routing action → frontend artifact/
RC5 decision → public routing verification.
