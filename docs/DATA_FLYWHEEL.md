# Learning Data Flywheel

`Interaction → LearningEvent → Evidence → CognitiveState → PolicyDecision → Action → Outcome → Evaluation → ModelRegistry → Policy improvement`

`PolicyOutcomeLink` attributes an action event to an outcome event.
`LearningOutcomeLedger` is a query projection of those links and events, not a
second event store.

`FlywheelHealthReport` covers event, state, policy, outcome, independent,
delayed, contamination, and model-evaluation coverage. The key measure is
`usable_evidence_rate`: real, knowledge-linked, outcome-bearing, clean evidence
divided by real interactions. Event volume alone is not flywheel health.

Synthetic/demo events are excluded. Empty input is `NO_DATA`; missing evidence
never becomes a quality claim. Candidate evaluation is temporally and
student-isolated, contamination-filtered, protocol-aware, and shadow-only until
an explicit ModelRegistry promotion gate is satisfied.
