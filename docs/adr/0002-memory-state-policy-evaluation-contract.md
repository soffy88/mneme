# ADR-0002：Memory Graph、Learner State 2.0、Policy 与 Evaluation OS

- 状态：Accepted
- 日期：2026-08-24
- 范围：Blueprint 1–4（Evidence Graph / Memory API、Learner State 2.0、统一策略、评估 OS）

## 决策

Mneme 将个人学习 Memory Loop 固定为：

```text
LearningEvent v2（事实）
  → MemoryEvidence（证据节点）
  → MemoryClaim（带证据的解释投影）
  → Learner State 2.0（读模型）
  → Policy candidate ranking（纯函数）
  → 新的学习事件
```

1. `learning_events` 是事实源，只增不改；`memory_claims`、
   `memory_evidence` 和 `memory_claim_evidence` 是可重建的解释投影。Claim
   必须挂同一学生的 Evidence，不能写入或替代 `kc_mastery`。
2. Learner State 2.0 统一返回 mastery、memory/retrievability、recognition、
   transfer、error profile、metacognition、uncertainty 和 evidence refs。
   它是只读组合，不改变 `SubmitAnswer → cognitive kernel` 唯一路径。
3. Policy Engine 只接收显式 candidate/state/context，按可解释的
   `expected_learning_gain_per_minute` 排序；动态 ZPD、到期紧迫性、迁移缺口、
   考期和学生选择是加权因素。策略不判定掌握、不写状态。
4. Evaluation OS 对 retention、near-transfer 和 observed arm difference 使用
   时间边界、Wilson 区间和样本不足返回 null。两臂差异默认只是观察性 uplift，
   不称为因果结论。

## API 边界

- `GET /v2/memory/timeline?student_id=&from=&to=`
- `GET /v2/memory/evidence/{claim_id}`
- `POST /v2/events`
- `POST /v2/replay`
- `POST /v2/export`
- `GET /v2/learner-state/{student_id}`
- `GET /v2/learner-state/{student_id}/ku/{ku_id}`
- `GET /v2/growth/{student_id}/period/{term}`
- `GET /v2/policy/next-action/{student_id}`
- `GET /v2/evaluation/os`

学生写入事件仅允许学生本人；Memory/State/Growth 读接口使用既有学生本人或
绑定家长授权。家长未获学生过程数据分享时，timeline/export/evidence 会做过程
字段脱敏。

## 尚未宣称完成的部分

- 现有 legacy `InteractionEvent` 仍是兼容读路径；全量双写/历史回填需要单独
  开启 feature flag 并做 pilot 验证。
- 当前 transfer 指同 KU 新实例的 near-transfer；far-transfer 题池仍需教研定义。
- uplift 只有在真实随机化、预注册终点和足量样本后才能用于因果结论。
- 本 ADR 对应迁移脚本已提交，活库应用与 API 重启属于单独发布动作。
