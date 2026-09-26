# Mneme project adapters inside `vendor/`

`vendor/oprim`, `vendor/oskill`, `vendor/omodul`, and `vendor/obase` are
canonical 3O roots by default.  The exact files listed below are the first
canonical-closure exception: they are Mneme-specific orchestration or storage
adapters retained at their historical import paths for compatibility.

They are **not** shared 3O authority.  They may depend on `services` or
`mneme_core`, but no other file under the shared roots may do so.  The exact
allowlist is enforced by `scripts/architecture_gate.py` and its unit gate.
Moving these adapters to a project package is a follow-up migration once
external import compatibility can be changed safely.

Allowlisted adapters:

- `oskill/{visualize_dispatch,solve_dispatch,socratic_loop,partner_dispatch,paper_grading}.py`
- `omodul/{book_compile,visualize_concept,solve_problem,analyze_paper,paper}.py`
- `obase/{cognitive_store,prior_provider}.py`
- `oprim/{answer_policy,retrieve_chunks,check_partner_review_due,learner_profile_summary}.py`

The production cognitive authority remains `oprim._cognitive` and
`oprim.fsrs_engine`; adapters must not introduce a second algorithm.
