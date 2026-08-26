# Evidence Levels

Mneme 只使用以下五级证据：

- `contract`：schema、静态 guard、deterministic contract 和工程测试。
- `offline`：公开/离线数据上的模型或算法评估，不代表真实学生效果。
- `observational`：真实事件的描述性或观察性结果，不代表因果效果。
- `randomized`：满足注册 protocol、有效 assignment 和合格 endpoint 的随机化结果。
- `commercial`：真实产品 funnel、支付、留存、支持或 unit economics 证据。

`PilotEvidenceRegistry` 的 `SUPPORTED` 状态必须关联已持久化的 analysis artifact。
没有 artifact 只能是 `PENDING`、`INCONCLUSIVE` 或其他非支持状态。不能手工把 pending
claim 改成 supported。

当前仓库实现的是 contract/readiness 基础设施；尚无真实学生、RCT 或 commercial
evidence，因此不能声称 Mneme 已证明提高真实学生学习效果。
