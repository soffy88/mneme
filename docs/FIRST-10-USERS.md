# First 10 Users: Controlled Early Access

This runbook defines a controlled first-user stage, not an open launch. Maximum cohort size is `10`; access is restricted to an owner-approved allowlist. `EARLY_ACCESS_MODE` remains closed by default and must not be enabled without the production configuration and owner approval.

## Purpose

The first users are used to verify activation, time to first learning value (TTFLV), the Learn Now core loop, return behavior, data quality, evidence quality, user-facing blockers, and operational reliability. This stage is not intended to prove product-market fit, an RCT, commercial scale, or a learning effect.

## Entry gates

- The frozen release candidate is deployed to a verified production-like environment.
- The owner has completed the legal/consent decisions in `docs/OWNER-LEGAL-GATE.md`.
- The owner has supplied the explicit allowlist and support/on-call contact.
- Pilot protocol, measurement windows, and contamination rules are frozen.
- Pilot, notification, and billing flags are independently reviewed; no flag is enabled by this document.

## Per-user sequence

1. Add the test/approved user to the allowlist without storing unnecessary PII.
2. Record the required consent status and protocol version; do not infer consent.
3. Record baseline evidence before treatment or practice where the protocol requires it.
4. Observe first value: a real learning interaction produces `LearningEvent` → `CognitiveState` → `PolicyDecision` and an explained next action.
5. Observe the normal learning period and return behavior.
6. Collect immediate, delayed, transfer, and independent measurements only in their eligible windows and with contamination rules applied.
7. Review data quality, usable-evidence rate, trace coverage, and P0 incidents.
8. Keep retention, transfer, and independent outcomes as `PENDING` until the required window and evidence threshold are reached.

## Success observations

- Activation: the user completes First Value.
- TTFLV: record the real event-derived duration; do not predeclare a successful value.
- Core loop: Learn Now completes through event ingestion, state projection, policy decision, and next action.
- Return: record D1/D7/D30 behavior when those windows occur; no missing window is treated as failure or success without protocol rules.
- Evidence: monitor `usable_evidence_rate`, contamination, ordering, and provenance.
- Reliability: record P0 incidents and stop early access for integrity, privacy, isolation, purge, or state-corruption failures.
- Learning: calculate retention, transfer, and independent evidence only after their measurement windows are reached.

## Evidence boundary

Every record must preserve the source distinction `REAL`, `DEMO`, `TEST`, or `SYNTHETIC`. Only `REAL` records from approved users may enter product retention, pilot evidence, commercial evidence, or model evaluation. Observational evidence is not randomized evidence, and neither is automatically causal.
