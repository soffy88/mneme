# ADR-0003：Tutor 控制回路与答案泄漏契约

## 状态

Accepted（2026-08-25）。本 ADR 覆盖 Blueprint §8 的仓库内确定性边界；真人
pilot、延迟迁移结果和 provider 级 benchmark 仍是后续发布条件。

## 决策

Tutor 采用可重放的五段式控制回路：

`observe → decide → generate → verify → record`

`packages/mneme-core/mneme_core/tutor_control.py` 负责 Observe/Decide 的纯函数
契约和输出闸门：

- pedagogical move 只允许 `ask / hint / contrast / worked_example / retrieval /
  reflect`；
- `own_homework`、`writing`、独立模式和已看答案状态优先级高于 feature flag，
  不允许完整答案；
- system-taught 的 `worked_example` 仅在明确授权的样例阶段允许完整样例；
- 默认每 5 次高强度 Tutor session 插入一次独立检索检查，cadence 可显式设为
  5–10，不使用随机隐式干预；
- 输出闸门只比对可信题目/内核提供的答案片段，并拦截显式“答案是/最终答案”交接，
  不让 LLM 自己判断是否泄漏。

旧的 `oprim.answer_policy` 入口保留为兼容导出，实际规则只有
`mneme_core.tutor_control.answer_policy` 一份。Socratic loop 和 agent loop 在向
学生发出文本前执行闸门；闸门失败时返回中性的下一步提示，并记录泄漏状态。

## 不变的红线

- Tutor 不写 `kc_mastery`，不生成掌握度，不绕过 `SubmitAnswer`；
- `/mcp/*` 的服务端鉴权、答案分级和确定性判分仍是最终权威；
- generated exercise 的答案验证仍由确定性 kernel/rubric 负责，本 ADR 不把 LLM
  输出变成真相源；
- no-AI transfer 的真实效果不能由本地契约测试宣称，必须在独立检索事件和 delayed
  holdout 上评估。

## 验证

契约测试覆盖：完整样例授权、看过答案后的降级、独立模式、5–10 次 cadence、空格
混淆、显式答案标记、Socratic 二次拦截和 agent 发出前过滤。
