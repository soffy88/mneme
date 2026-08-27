# Mneme JTBD Contract

## Core job

> When I am learning something over days, weeks, or months, help me know what I
> actually know, what I am forgetting, what I misunderstand, and exactly what I
> should do next, so that I can retain and transfer knowledge without managing
> the learning system myself.

The product answers five questions:

1. What should I learn now?
2. What am I forgetting?
3. What do I actually know?
4. What am I misunderstanding?
5. Am I genuinely improving?

Learner-facing vocabulary is `Learn Now`, `Today`, `Memory`, `Weak Areas`,
`Progress`, and `Why this?`. BKT, FSRS, IRT, Policy Engine, and Evidence Graph
remain infrastructure terms.

## Acceptance contract

- Learn Now reads a server PolicyDecision; the frontend does not rank or infer
  mastery.
- Memory is a label projection (`Strong`, `Learning`, `Fading`, `Unknown`);
  advanced views may show model values with uncertainty.
- Weak Areas contain only evidence-backed misconception claims. Insufficient
  evidence is labelled `Possible misconception`.
- Progress separates activity progress from retention, transfer, independent
  performance, and JOL calibration.
- `Why this?` exposes policy reason codes and existing evidence refs; prose
  cannot create evidence or decisions.
- No real data produces `NO DATA`, `You're caught up`, or `not measured yet`,
  rather than a fabricated zero or urgency.
