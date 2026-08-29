# ADR-0012：媒体证据强度与误判禁令

- 状态：Accepted
- 日期：2026-08-29
- 范围：Immersive 信号如何升格为 Evidence 及其默认强度

## 决策

证据强度默认：

| 信号 | 强度 | 可暗示 | 不可暗示 |
|------|------|--------|----------|
| 复听 ×N / A–B 循环 | weak behavioral | 可能吃力 → 仅作 scaffold 提示 | **≠** `did_not_understand=true` |
| 揭示翻译 / 调脚手架 | weak behavioral | 依赖脚手架 / help-seeking | ≠ 词汇未知 / 能力判定 |
| Vocab / phrase lookup | weak | 下次可加 scaffold；Memory Router **候选** | **≠** 掌握；**不得**自动建 FSRS item |
| 无字幕听力答错 / 听写错 | **strong performance** | 听力/拼写缺口 | — |
| 跨视频 transfer 正确 | **strong performance** | 模式学会，非单句死记 | — |
| 低置信 ASR 发音分 | 封顶（如 ≤0.4） | 可存档 | 不得驱动强掌握写入 |

只有 **performance** 类默认可标 strong；behavioral / self-report 保持弱。
Derived（聚合）证据必须单独版本化，不得静默升为 performance。

污染（答案已暴露、未标记的 AI 辅助等）→ Evidence 打标，**不写**掌握度路径。

## 不变的红线

- **replay ≠ misunderstanding**（不得自动写“没听懂”事实）。
- **lookup ≠ mastery**（查词不是学会；也不是自动进 FSRS）。
- 低置信 ASR **永不**当高置信掌握证据。

## 验证

`VOCAB_LOOKUP` alone → Memory Router `no_fsrs_item`；
`SEGMENT_REPLAYED` → 不得产生 `did_not_understand=true`；
ASR confidence < 阈值 → evidence strength 封顶。
