# Pilot protocol and evidence boundary

`services.pilot_protocol.PilotProtocol` is the registration contract for a
future real-student pilot. It records the protocol ID/version, registration
time, primary and secondary endpoints, cohort, assignment method, baseline,
treatment, control, evaluation windows, exclusions, and analysis plan.

The supported endpoint names are `retention_7d`, `retention_30d`,
`near_transfer`, `far_transfer`, `independent_no_ai_accuracy`, `jol_calibration`,
and `retained_mastery_gain_per_active_minute` (RMG/AM).

`run_pilot_analysis` accepts only caller-supplied observations. With no approved
real-world input it returns exactly `INSUFFICIENT_REAL_WORLD_EVIDENCE` and an
empty result object. It never falls back to synthetic observations. Supplied
events are labeled observational until a registered design and eligible data
support a narrower evidence level; the runner never emits a causal claim by
itself.

`independent_no_ai` is fail-closed: a LearningEvent must explicitly carry
`ai_assisted=false` and `independent_mode=true`. Practice, hint-heavy,
answer-exposed, or AI-assisted evidence is not independent mastery evidence.
