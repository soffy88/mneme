# ADR-0004：Evaluation OS v2 的 no-AI 与时间切分契约

## 状态

Accepted（2026-08-25）。这是 Blueprint §11 的可在仓库内闭环部分；真实样本、
随机化实验和 delayed holdout 仍需 pilot。

## 决策

Evaluation OS v2 对每个交互保留可选的评估信号：

- `tutor_mode`：本轮教学模式；
- `ai_assisted`：是否使用 AI；
- `independent_mode`：是否处于独立检索/迁移模式；
- `evaluation_phase`：`baseline` 或 `delayed`；
- `received_at`：接收时间，与发生时间分开保存。

历史行统一保持 NULL/未知。只有同时满足 `source=transfer_probe`、
`independent_mode=true`、`ai_assisted=false` 的事件才能进入 `no_ai_transfer`；
没有显式标注的旧迁移事件仍可进入普通 `transfer`，但不能被包装成 no-AI 结果。

`delayed_gain` 只对同一学生同时存在 baseline 和 delayed 的配对计算，缺配对时
返回 null。时间切分在评估前检查 train/eval 窗口不重叠，并按 `as_of` 同时排除
发生时间或接收时间在未来的事件。

`model_registry` 保存 model_id、model_type、code_sha、train/eval 窗口、params、
metrics、status 和 rollback_to。它是 metadata-only 表，管理接口仅允许
`ADMIN_USER_IDS` 中的 admin；`shadow → candidate → production → retired` 必须按
显式状态转换，production 不自动替换同类型旧版本。进入 candidate 或 production 前，
status API 必须提交完整的 `shadow-evaluation/v1` 报告：候选和 baseline 样本对齐、四项
shadow guardrails 均为 false、候选指标完整且至少 30 个 eval events；该 gate 只验证证据
完整性，不自动判断或宣称学习效果。

这些字段只增强事实和评估，不参与 BKT/FSRS 判分或掌握度更新；掌握度仍只能通过
`SubmitAnswer → process_interaction` 产生。

## Shadow comparator

`services/shadow_evaluation.py` 提供与 `model_registry` 时间窗对齐的纯计算比较器。
候选预测必须位于 `[eval_start, eval_end)`，且 `occurred_at` 与可用的 `received_at`
均不得晚于 `as_of`；基线若存在，必须与候选按相同的学生/KC/发生时间键逐事件对齐。
比较器报告 AUC、log-loss、Brier、ECE、calibration slope 和方向明确的 observed predictive difference，
不落库、不控制学习路径，也不把影子差值解释为因果 uplift。真实 shadow→A/B 仍需
独立预测适配器、随机化 pilot 和 admin 发布流程。

`scripts/moat_eval/shadow_registry_eval.py` 是该比较器的 JSONL 离线入口；它要求调用方
显式提供模型 ID、train/eval 窗口和 `as_of`，因此不会把当前时间或数据库中的未知窗口
悄悄当作评估边界。

`services.evaluation_service.reconstruct_kernel_shadow_predictions` 是 production
BKT+FSRS 的只读数据库适配器：只读取声明的 train/eval 窗口，排除 FIRe 记账事件，先
重放 train 状态，再在 eval 事件发生前生成预测，随后才更新状态。窗口之间的 gap 不会
被偷偷当作训练数据；该适配器仍只提供 baseline，不能代表 candidate challenger 已上线。

候选模型使用 `candidate_shadow_predictions` 接入时，只能收到不可变的历史事件序列和
不含 `is_correct` 的当前事件视图。当前真实结果只有在 predictor 返回概率后才进入 history；
概率必须是有限的 `[0, 1]` 数值，违反即 fail-closed。

## 迁移与发布

迁移 `d2e3f4a5b6c7` 为 `interaction_events` 增加 nullable 评估字段，并将历史
`received_at` 回填为 `occurred_at`，避免迁移时间污染 holdout。当前只完成离线 SQL
验证；迁移 `e3f4a5b6c7d8` 新增 metadata-only `model_registry`。应用到活库和重跑
pilot 需要单独发布确认。
