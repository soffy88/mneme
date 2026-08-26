# Pilot Metrics

所有 pilot endpoint 使用既有 `services/evaluation_os.py` 的 observation contract，
并由 `EvidenceContaminationClassifier` 统一筛选。结果字段包含：

`value`、`confidence_interval`（样本允许时）、`n_students`、`n_events`、
`missingness`、`exclusion_count`、`contamination_count`、`protocol_version`、
`data_cutoff`、`evidence_level` 和 `status`。

## Endpoint definitions

- `retention_7d` / `retention_30d`：cohort anchor 后的明确 horizon window；window 未
  到返回 `WINDOW_NOT_REACHED`，没有可用 anchor 返回 `INSUFFICIENT_EVIDENCE`。
- `near_transfer` / `far_transfer`：只消费明确 phase 且 clean 的 transfer evidence。
- `independent_no_ai_accuracy`：只消费 `independent_mode=true` 且
  `ai_assisted=false` 的 clean events。
- `jol_calibration`：JOL 必须有显式 `jol_at`，且早于 `outcome_revealed_at`；输出
  `calibration_error`、`overconfidence_rate`、`underconfidence_rate` 和
  `brier_like_score`。
- `retained_mastery_gain_per_active_minute`（RMG/AM）：只使用显式
  `active_learning_seconds` 或显式 active minutes；不使用 session wall-clock。
  idle、background、upload、AI latency 和 system wait 被排除。缺失活动证据时返回
  `INSUFFICIENT_ACTIVITY_EVIDENCE`。

RMG/AM 的基本定义是：

`sum(retained mastery gain) / sum(net active learning minutes)`。

没有真实事件、没有有效窗口或数据质量失败时，value 为 `null`，不填充 synthetic
result，也不把 observational difference 写成 causal effect。
