# v0.1.0-rc4 isolated staging canary audit

Date: 2026-08-30 UTC
Artifact SHA: `a359877676a39fc2627a6f429adea77b0ed41311`
Exposure: loopback-only isolated staging; no public or production route
Test data: two synthetic staging principals; no demo learner data

## Gate matrix

| Configuration / action | Result |
|---|---|
| Global OFF + empty allowlist; A status | 200, enabled=false |
| Global OFF + empty allowlist; B status | 200, enabled=false |
| Global OFF + allowlist A; A status | 200, enabled=true |
| Global OFF + allowlist A; B status | 200, enabled=false |
| B token on A-owned URL | 403 authorization deny |
| Global OFF + allowlist A; B media/session/practice/telemetry | feature-disabled deny |
| Global OFF + allowlist A; B Learn Now | no immersive candidate |
| Global ON; A and B status | both enabled=true |
| Restored final state | Global OFF + allowlist A |
| Unauthenticated status | 401; no canary data disclosed |

The status response is user-aware and contains no allowlist contents or other
user IDs. All immersive API routes call the same server-side gate after
principal authentication and URL-user authorization.

## Golden path and regressions

Synthetic canary A completed media upload, transcript/segments, session and
continuity, telemetry, dictation/listening/comprehension/recall practice,
behavioral event, policy, and explain through the real API. The browser path
also passed with A enabled and B disabled.

Telemetry non-advancement passed: the telemetry-event count increased by one,
while LearningEvent, mastery snapshots, KC mastery, memory claims, policy
decisions, and interaction-event counts remained unchanged; no performance
Evidence or FSRS advancement was produced. Existing Mneme FSRS duplicate
guard and purge/idempotency regression passed against the exact artifact SHA.

## Soak

Global OFF + allowlist A was held for 30 minutes using 30 continuous
60-second API/frontend health samples. API/frontend 5xx: **0**; container
restarts: **0**; gate errors: **0**; cognitive projection errors: **0**;
FSRS errors: **0**. Final containers remained running and the final gate state
was A enabled / B disabled.

Production was not deployed and immersive remained disabled globally.
