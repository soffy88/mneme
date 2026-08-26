# Real-World Validation

Mneme 当前状态：

**PILOT ENGINEERING READY**

这表示工程上具备安全开始真实用户验证的基础设施：protocol-versioned enrollment、
assignment、consent gate、污染隔离、delayed windows、endpoint null semantics、
analysis manifest/replay、artifact-backed evidence registry、privacy/purge/export 和
默认关闭的 rollout controls。

这不表示已有真实世界证据。当前不能声称：

- 已有真实学生 pilot 结果；
- 已经证明 retention、transfer 或 RMG/AM 改善；
- 已经有 RCT 因果结果；
- 已经有 commercial traction 或 unit economics。

合法的下一步是 owner 批准 protocol/consent/cohort，随后在受控生产窗口收集真实
LearningEvents，再使用固定 code SHA、protocol snapshot、event cutoff 和 analysis
version 生成可重放报告。没有数据的 endpoint 必须保持 `null` 并明确
`PENDING` / `INSUFFICIENT_EVIDENCE` / `WINDOW_NOT_REACHED`。
