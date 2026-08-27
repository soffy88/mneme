# Product Analytics Contract

Product analytics derives from real `LearningEvent` rows. Its event vocabulary
includes first value, session start/completion, next-best-action start/completion,
return reason, review completion, and independent-test completion.

Product metrics include TTFLV, D1/D7/D30 return, sessions per user, Learn Now
completion, and review completion. They describe product behavior only.

Learning metrics remain separate: retention, transfer, independent mastery, JOL
calibration, and RMG/AM. `PRODUCT RETENTION` is not learning retention.

Signup, first-value, and learning-start cohorts return `NO REAL USER DATA` with
null values when there are no real users. Demo and synthetic events are excluded
from formal analytics and evaluation.
