# Product Learning Loop

`First Value → Learn Now → LearningEvent → CognitiveState → PolicyDecision → Action → Evidence → Session Summary → Return Reason`

First value begins at real content/session readiness and completes only after a
real learning attempt has produced a cognitive-state projection and a policy
recommendation. Synthetic/demo events cannot advance it. The reducer is
resumable and retains start/completion timestamps.

- Learn Now delegates selection to the existing Policy Engine.
- Today is a policy-ordered queue; an empty queue says `You're caught up`.
- Memory and Weak Areas are evidence-backed projections.
- Session summaries describe observed evidence, uncertainty, fading, repair,
  and the next policy action.
- Return reasons exist only for real due work: review, fading memory,
  unfinished session, transfer, misconception repair, or delayed measurement.

Notifications are a disabled-by-default contract. This repository does not
enable email, push, or random engagement reminders.
