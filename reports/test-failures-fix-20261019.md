# Test failure repair — 2026-10-19

## Result

- Baseline source: `main` / `origin/main` at `37eba4b824274edb4767646f57881e87c77053d5`.
- Baseline collection: 2,641 tests. The one-shot run reached 77% and hit the 10-minute command limit; all tests were then completed in 10 ordered shards. `OOMKilled=false`. The API container was restarting because its DB pointed at missing Alembic revision `vlc1a2b3c4d5`, not because of memory exhaustion.
- Baseline summary: **2,610 passed / 18 failed / 22 skipped**, plus **61 teardown errors**. Pytest reports some teardown errors in addition to their test body's pass/fail result.
- Final full run: **2,624 passed / 0 failed / 17 skipped**, 2,641 collected, all 10 shards exited 0. No skip/xfail was added and no test was removed.
- Full-run logs: `/tmp/full_before.txt` and `/tmp/full_after.txt`. Final validation used a disposable migrated PostgreSQL database, Redis, and MinIO on the Compose network. Cornell content fixtures were mounted read-only from the main workspace; no content data was committed.

## Baseline FAILED cases

| Test | Root cause | Changed file(s) | Before → after |
|---|---|---|---|
| `tests/test_aria_director.py::test_direct_falls_back_to_heuristic_without_key` | The test cleared only Qwen/DashScope keys while the runner selected a configured Veya/InternAI caller. | `tests/test_aria_director.py` | failed (`source=llm`) → passed |
| `tests/test_aria_director.py::test_direct_falls_back_with_key_invalid_placeholder` | Same provider-environment leak; the placeholder Qwen key did not mask the configured caller. | `tests/test_aria_director.py` | failed (`source=llm`) → passed |
| `tests/test_calibration_flywheel.py::test_calibration_moves_slip_and_sets_n` | Calibration reports a cohort-wide count; the test incorrectly assumed no other KC had eligible data. It now asserts the seeded KC's prior changed. | `tests/test_calibration_flywheel.py` | failed (`4 != 1`) → passed |
| `tests/test_calibration_flywheel.py::test_insufficient_warm_samples_skipped` | Same global-count assumption. It now asserts the seeded KC's prior stayed unchanged. | `tests/test_calibration_flywheel.py` | failed (`3 != 0`) → passed |
| `tests/test_daily_plan.py::test_p4_new_learn_no_prereqs` | The test student was unbound and therefore eligible for all math textbooks; unrelated persisted KUs changed P4 recommendations. | `tests/test_daily_plan.py` | failed → passed |
| `tests/test_daily_plan.py::test_p4_prerequisite_unlocks_after_mastery` | Same global textbook candidate leak. | `tests/test_daily_plan.py` | failed → passed |
| `tests/test_daily_plan.py::test_p4_chained_prerequisites` | Same global textbook candidate leak. | `tests/test_daily_plan.py` | failed → passed |
| `tests/test_dod_e2e.py::test_dod_full_loop_reaches_complete_all_mastered` | MCP writes use independent sessions, but the test user was only flushed and not committed, so those sessions could not see it. | `tests/test_dod_e2e.py` | failed to converge; question-record FK errors → passed |
| `tests/test_fsrs_optimize.py::test_fit_gate_blocks_massed_logs` | Cohort history included unrelated test events. The test now creates a sufficient same-day sequence for one student and passes that student ID to the fitter. | `tests/test_fsrs_optimize.py` | failed (`51 != 0` spaced reviews) → passed |
| `tests/test_knowledge_hub_backfill.py::test_backfill_then_match_is_fill_only_and_idempotent` | `oprim.embed_chunks` resolves to the package re-exported function, not the submodule. The monkeypatch targeted the wrong object. | `tests/test_knowledge_hub_backfill.py` | `AttributeError` → passed |
| `tests/test_learning_metrics.py::test_learning_metrics_shape` | The test assumed a globally empty cohort and asserted the transfer note was absent even though the service always returns it. | `tests/test_learning_metrics.py` | failed on persisted transfer rows → passed |
| `tests/test_nce_importer.py::test_get_vid_reuses_k12_namespace` | Importing a pure ID helper eagerly imported optional `openpyxl` through workbook modules. | `scripts/vocab_importer/schema_detector.py`, `scripts/vocab_importer/parser.py` | `ModuleNotFoundError` → passed |
| `tests/test_oprim_llm.py::test_ocr_paper_mock` | The test registered the legacy mock registry; `ocr_paper` calls the current `ProviderRegistry`. The supposedly mocked call reached the external provider and returned HTTP 5xx. | `tests/test_oprim_llm.py` | provider 5xx → passed with the actual provider boundary mocked |
| `tests/test_prod_safety_gate.py::test_prod_with_default_jwt_secret_and_mock_channels_refuses_to_start` | Container `JWT_SECRET` masked the test's patched settings value, so the intended default-secret condition was not exercised deterministically. | `tests/test_prod_safety_gate.py` | failed assertion → passed |
| `tests/test_provider_setup_y4.py::test_veya_registers_local_text_and_vision` | The test expected Veya callers without setting a Veya key or clearing the InternAI key, producing a fallback caller instead. | `tests/test_provider_setup_y4.py` | fallback type mismatch → passed |
| `tests/test_quiz.py::test_submit_correct_updates_bkt_and_scores` | Fixed KC IDs allowed old wrong-question rows from earlier test runs to be selected. | `tests/test_quiz.py` | score `0.0` instead of `1.0` → passed |
| `tests/test_retention_probe.py::test_retention_metrics_values` | A JSONB `null` card is SQL-non-null but decodes to Python `None`; the service called `.get()` on it. | `services/retention_service.py`, `tests/test_retention_probe.py` | `AttributeError` → passed |
| `tests/test_retention_probe.py::test_retention_metrics_endpoint_auth` | Same JSONB-null card defect on the aggregate endpoint. | `services/retention_service.py`, `tests/test_retention_probe.py` | `AttributeError` → passed |

## Baseline ERROR cases

All 61 were caused by test teardown deleting a user while its append-only `learning_events` rows still referenced that user. The application event stream remains append-only; tests now delete only rows belonging to their own test students before deleting those users. `tests/db_test_helpers.py` holds the shared cleanup helper.

| Test | Root cause / changed file | Before → after |
|---|---|---|
| `tests/test_api.py::test_api_interaction_and_mastery` | Missing event cleanup in student fixture; `tests/test_api.py` | ERROR → passed |
| `tests/test_api.py::test_api_review_queue` | Same; `tests/test_api.py` | ERROR → passed |
| `tests/test_cognitive_service.py::test_process_interaction_writes_kc_mastery` | Same; `tests/test_cognitive_service.py` | ERROR → passed |
| `tests/test_cognitive_service.py::test_interaction_events_append_only` | Same; `tests/test_cognitive_service.py` | ERROR → passed |
| `tests/test_cognitive_service.py::test_mastery_snapshot_upserted` | Same; `tests/test_cognitive_service.py` | ERROR → passed |
| `tests/test_cognitive_service.py::test_mastery_overview_sorted_ascending` | Same; `tests/test_cognitive_service.py` | ERROR → passed |
| `tests/test_cognitive_service.py::test_mastery_overview_has_peer_percentile` | Same; `tests/test_cognitive_service.py` | ERROR → passed |
| `tests/test_cognitive_service.py::test_phase2_difficulty_autolookup_from_ku` | Same; `tests/test_cognitive_service.py` | ERROR → passed |
| `tests/test_cognitive_service.py::test_effortful_gain_recorded_on_struggled_correct` | Same; `tests/test_cognitive_service.py` | ERROR → passed |
| `tests/test_cognitive_service.py::test_effortful_gains_endpoint` | Same; `tests/test_cognitive_service.py` | ERROR → passed |
| `tests/test_cognitive_service.py::test_weakness_roots_surfaces_weak_prereq` | Same; `tests/test_cognitive_service.py` | ERROR → passed |
| `tests/test_cognitive_service.py::test_jol_predicted_confidence_and_calibration` | Same; `tests/test_cognitive_service.py` | ERROR → passed |
| `tests/test_cognitive_service.py::test_weekly_digest_streak` | Same; `tests/test_cognitive_service.py` | ERROR → passed |
| `tests/test_cognitive_service.py::test_daily_report` | Same; `tests/test_cognitive_service.py` | ERROR → passed |
| `tests/test_feature_flags.py::test_self_explanation_disabled_is_not_persisted` | Missing event cleanup; `tests/test_feature_flags.py` | ERROR → passed |
| `tests/test_feature_flags.py::test_self_explanation_enabled_by_default_is_persisted` | Same; `tests/test_feature_flags.py` | ERROR → passed |
| `tests/test_feature_flags.py::test_growth_feedback_disabled_is_none` | Same; `tests/test_feature_flags.py` | ERROR → passed |
| `tests/test_feature_flags.py::test_growth_feedback_enabled_by_default` | Same; `tests/test_feature_flags.py` | ERROR → passed |
| `tests/test_feature_flags.py::test_fine_feedback_disabled_skips_step_analysis` | Same; `tests/test_feature_flags.py` | ERROR → passed |
| `tests/test_fire_credit.py::test_fire_postpones_verified_prereq_only_due` | Missing event cleanup rolled back fixture cleanup; `tests/test_fire_credit.py` | ERROR → passed |
| `tests/test_fire_credit.py::test_fire_no_cascade_to_grandparent` | Same; `tests/test_fire_credit.py` | ERROR → passed |
| `tests/test_fire_credit.py::test_fire_not_triggered_on_wrong_answer` | Same; `tests/test_fire_credit.py` | ERROR → passed |
| `tests/test_fire_credit.py::test_fire_debounced_massed_practice_not_retrieval` | Same; `tests/test_fire_credit.py` | ERROR → passed |
| `tests/test_fire_credit.py::test_fire_disabled_by_default` | Same; `tests/test_fire_credit.py` | ERROR → passed |
| `tests/test_guide_services.py::test_force_analysis_end_confirms_when_equation_ready` | Missing event cleanup; `tests/test_guide_services.py` | ERROR → passed |
| `tests/test_guide_services.py::test_force_analysis_end_api` | Same; `tests/test_guide_services.py` | ERROR → passed |
| `tests/test_guide_services.py::test_reading_guide_end_confirms_when_located_passage` | Same; `tests/test_guide_services.py` | ERROR → passed |
| `tests/test_guide_services.py::test_reading_guide_end_api` | Same; `tests/test_guide_services.py` | ERROR → passed |
| `tests/test_lesson_practice.py::test_practice_submit_correct_no_wrong_question_created` | Missing event cleanup; `tests/test_lesson_practice.py` | ERROR → passed |
| `tests/test_lesson_practice.py::test_practice_submit_duplicate_event_id_does_not_double_update` | Same; `tests/test_lesson_practice.py` | ERROR → passed |
| `tests/test_lesson_practice.py::test_practice_submit_wrong_creates_student_record_not_bank` | Same; `tests/test_lesson_practice.py` | ERROR → passed |
| `tests/test_mastery_concurrency.py::test_concurrent_process_interaction_preserves_both_updates` | Missing event cleanup; `tests/test_mastery_concurrency.py` | ERROR → passed |
| `tests/test_new_routes.py::test_patterns_with_interactions` | Missing event cleanup; `tests/test_new_routes.py` | ERROR → passed |
| `tests/test_quiz.py::test_submit_wrong_moves_fsrs_due_closer` | Missing event cleanup; `tests/test_quiz.py` | ERROR → passed |
| `tests/test_quiz.py::test_quiz_due_and_submit_api` | Same; `tests/test_quiz.py` | ERROR → passed |
| `tests/test_retention_probe.py::test_probe_submit_records_predicted_r_and_updates_fsrs` | Missing event cleanup; `tests/test_retention_probe.py` | ERROR → passed |
| `tests/test_retention_probe.py::test_due_card_submit_stays_review_source` | Same; `tests/test_retention_probe.py` | ERROR → passed |
| `tests/test_review_retrieval_gate.py::test_reveal_records_fsrs_again` | Missing event cleanup; `tests/test_review_retrieval_gate.py` | ERROR → passed |
| `tests/test_review_retrieval_gate.py::test_submit_correct_records_and_returns_answer` | Same; `tests/test_review_retrieval_gate.py` | ERROR → passed |
| `tests/test_review_retrieval_gate.py::test_unverified_variant_degrades_to_original_and_judges_consistently` | Same; `tests/test_review_retrieval_gate.py` | ERROR → passed |
| `tests/test_review_retrieval_gate.py::test_kernel_verified_variant_shown_and_judged_by_its_own_answer` | Same; `tests/test_review_retrieval_gate.py` | ERROR → passed |
| `tests/test_routes_b3.py::test_interaction_returns_findings` | Missing event cleanup; `tests/test_routes_b3.py` | ERROR → passed |
| `tests/test_routes_b3.py::test_interaction_state_persists` | Same; `tests/test_routes_b3.py` | ERROR → passed |
| `tests/test_routes_b3.py::test_mastery_overview_sorted` | Same; `tests/test_routes_b3.py` | ERROR → passed |
| `tests/test_routes_b3.py::test_mastery_curve_empty_then_filled` | Same; `tests/test_routes_b3.py` | ERROR → passed |
| `tests/test_routes_b3.py::test_review_queue_after_wrong` | Same; `tests/test_routes_b3.py` | ERROR → passed |
| `tests/test_self_explanation.py::test_self_explanation_persisted` | Missing event cleanup; `tests/test_self_explanation.py` | ERROR → passed |
| `tests/test_self_explanation.py::test_no_self_explanation_leaves_null` | Same; `tests/test_self_explanation.py` | ERROR → passed |
| `tests/test_socratic_end_session.py::test_end_session_success_writes_kc_mastery` | Missing event cleanup; `tests/test_socratic_end_session.py` | ERROR → passed |
| `tests/test_socratic_end_session.py::test_end_session_failed_writes_incorrect_event` | Same; `tests/test_socratic_end_session.py` | ERROR → passed |
| `tests/test_socratic_outcome_integrity.py::test_verified_success_credits` | Missing event cleanup; `tests/test_socratic_outcome_integrity.py` | ERROR → passed |
| `tests/test_socratic_outcome_integrity.py::test_verified_overrides_client_partial` | Same; `tests/test_socratic_outcome_integrity.py` | ERROR → passed |
| `tests/test_speaking_practice.py::test_speaking_with_ku_id_updates_mastery` | Missing event cleanup; `tests/test_speaking_practice.py` | ERROR → passed |
| `tests/test_transfer_probe.py::test_end_to_end_due_queue_and_grading` | Missing event cleanup; `tests/test_transfer_probe.py` | ERROR → passed |
| `tests/test_transfer_probe.py::test_learning_metrics_reflects_transfer_probe_accuracy` | Same; `tests/test_transfer_probe.py` | ERROR → passed |
| `tests/test_vocab_and_graded_reading.py::test_submit_vocab_review_updates_mastery` | Missing event cleanup; `tests/test_vocab_and_graded_reading.py` | ERROR → passed |
| `tests/test_vocab_and_graded_reading.py::test_due_vocab_reviews_surfaces_due_card` | Same; `tests/test_vocab_and_graded_reading.py` | ERROR → passed |
| `tests/test_vocab_and_graded_reading.py::test_estimate_reading_level_rises_with_mastery` | Same; `tests/test_vocab_and_graded_reading.py` | ERROR → passed |
| `tests/test_vocab_and_graded_reading.py::test_vocab_review_api` | Same; `tests/test_vocab_and_graded_reading.py` | ERROR → passed |
| `tests/test_vocab_memory_fsrs_single_state.py::test_one_word_yields_exactly_one_kc_row_across_many_reviews` | Missing event cleanup; `tests/test_vocab_memory_fsrs_single_state.py` | ERROR → passed |
| `tests/test_vocab_memory_fsrs_single_state.py::test_staged_reveal_advances_with_the_single_card` | Same; `tests/test_vocab_memory_fsrs_single_state.py` | ERROR → passed |

## Additional isolated-run checks

The clean-run pass surfaced an environment-dependent concept-diagnosis route test and production-preflight happy-path tests that had relied on ambient provider settings. Those tests now inject a deterministic workflow or explicit preflight environment. The final 2,641-case run includes them and is green.

No user data, production API container, production database, or production service was changed by final verification. The initial baseline was run against the designated `mneme_test` database; subsequent validation used disposable services because the local Compose API is the live production container and was already failing startup migration.
