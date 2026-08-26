# Policy decision trace

The policy loop is:

```text
CognitiveState + EvidenceRefs → PolicyDecision → action/event → new evidence
```

`services.policy_trace.PolicyDecision` records decision ID, student, timestamp,
candidate actions, selected action, reason codes, state version, policy
version, evidence refs, constraints, expected utility, exploration flag,
fallback reason, evidence level, and `trace_id`.

The persisted `policy_decisions` table is an operational projection. Policy
code has no mastery write capability; only `kc_mastery`'s existing cognitive
kernel path can change mastery.

Policy v2 uses the centralized uncertainty contract. When explicit evidence is
insufficient or epistemic uncertainty is high, diagnostic/information-gain
actions are favored when available. A state with the same point estimate but
different evidence counts therefore does not receive the same policy context.

`replay_policy_decision` invokes the deterministic `mneme-core` engine without
database writes. The route persists the trace and returns it to the caller.
