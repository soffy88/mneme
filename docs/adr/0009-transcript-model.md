# ADR-0009：Transcript 模型（Segment ≠ LearningUnit）

- 状态：Accepted
- 日期：2026-08-29
- 范围：媒体转写、切分与学习目标身份的分离

## 决策

**Transcript** 描述某一媒体上的一份转写产物；**TranscriptSegment** 是带
`start_ms`/`end_ms` 的定时文本行（导航、高亮、循环的原子）。

| 实体 | 是什么 | 不是什么 |
|------|--------|----------|
| Transcript | 来源 + 语言 + 模型版本 + provenance | 掌握度对象 |
| TranscriptSegment | 时间窗内的字幕/ASR 行 | 永久唯一的 LearningUnit |
| LearningUnit | 稳定学习目标（词/句型/语法/听力特征…） | 某条字幕行 ID |

**Occurrence** 边把 LearningUnit 连到具体 `Media` / `TranscriptSegment` 出现处。
同一 lemma/pattern 可跨媒体出现；字幕行身份随切分/重对齐可变，LearningUnit
身份应保持稳定。

转写流水线：

```text
media → transcript source → normalization → segmentation
  → language detection → sentence alignment
  → optional translation → (Phase 2) LU extraction
```

来源：`uploaded_subtitle` | `embedded_subtitle` | `manual` | `asr`。凡生成物须记
`source`、`model/version`、`confidence`、`timestamp`。

## 不变的红线

- **禁止**把字幕行当作永久唯一 LearningUnit / KC 身份。
- `knowledge_refs` 指向 LearningUnit（如 `vocab-…`），不是 raw subtitle row id。
- 低置信 ASR/MT 不得静默升为高置信学习事实。

## 验证

模型/契约测试：Segment 可重切分而不强制重建 LU；occurrence 可指向多媒体；
禁止 API 把 `segment_id` 当作掌握度主键写入。
