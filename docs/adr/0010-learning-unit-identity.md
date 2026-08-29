# ADR-0010：LearningUnit 身份与跨语境出现

- 状态：Accepted
- 日期：2026-08-29
- 范围：媒体学习中稳定学习目标身份及其 occurrence 链接

## 决策

LearningUnit 是多态学习目标，身份**跨媒体语境稳定**：

`segment` | `sentence` | `word` | `phrase` | `concept` | `grammar_pattern` | `listening_feature`

媒体/片段是 **context**，不是身份本身。例：句子
`"You should've told me earlier."` 可挂多个 LU（`should have`、过去分词、
`should've`、弱读、regret 语用等），并通过 occurrence 指向 Media A / Segment 42；
日后在 Media B 的 `"You should've called."` 做 near/far transfer 时仍是同一
pattern LU。

CognitiveStateV2 **不**另起第二套 learner state；语言面向用 `knowledge_ref`
命名空间表达（`vocab-{id}`、`phrase-{id}`、`grammar-{id}`、`listening-{skill}`、
`listening_feature-{id}`、`pron-{id}` 等）。未支持维度保持 `null`。

复习不得只能回放原视频：same-context / near-transfer / far-transfer 复用既有
EvaluationPhase 与 transfer 投影。

## 不变的红线

- LearningUnit id 不以单次字幕切分为唯一来源。
- 禁止为视频学习 fork 平行 CognitiveState 存储。
- 掌握度仍只经既有写路径（SubmitAnswer / process_interaction 族）与 Memory
  Router 资格进入 FSRS，Agent/播放器不得自编掌握度。

## 验证

跨媒体 transfer 事件携带 `source_context` / `target_context` / `distance`；
同一 LU 的多 occurrence 可解释“为何相信会/不会”；schema 最小缺口是 LU registry
+ occurrence edges + media 表，而非新状态库。
