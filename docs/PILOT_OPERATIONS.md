# Pilot Operations

Mneme 的 pilot 是受控的测量层，不是另一条学习路径。默认配置为关闭：

- `PILOT_MODE=0`
- `PILOT_ENABLED=0`
- `PILOT_POLICY_EXPERIMENT_ENABLED=0`
- `PILOT_INDEPENDENT_EVAL_ENABLED=0`
- `PILOT_KILL_SWITCH=0`（设为 1 可立即关闭 pilot-specific behavior）
- `PILOT_COHORT_ALLOWLIST` 为空时没有 cohort 获准运行

只有 `PILOT_MODE=1`、`PILOT_ENABLED=1`、protocol id/version 已配置且 cohort 在
allowlist 中时，pilot metadata、assignment、measurement scheduling 和 aggregate
telemetry 才会运行。普通 `LearningEvent`、CognitiveState 和 Policy 路径不受绕过。

技术入口：

- `GET /v2/pilot/config`：admin-only，返回非敏感开关摘要。
- `POST /v2/pilot/enrollment/{student_id}`：显式 enrollment；需要 protocol 要求的
  `GRANTED` consent。
- `POST /v2/pilot/measurement/{student_id}`：为已 enrollment 学生生成幂等 schedule。
- `POST /v2/pilot/consent/revoke/{student_id}`：撤回同意并使未完成 measurement
  invalidated。
- `GET /v2/pilot/export/{student_id}`：只导出 enrollment、assignment、schedule
  metadata，不导出 raw answer 或 P2/P3 process signals。
- `GET /v2/pilot/dashboard`：admin-only aggregate surface；无真实证据时显示
  `NO REAL-WORLD EVIDENCE YET`。

运行前必须由 owner 完成法律、监护人同意、cohort 定义、protocol 注册和 rollout 审批。
本仓库不会自动招募学生、自动启用 flags 或触碰生产环境。
