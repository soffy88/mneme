# ADR-0007：Media Learning Engine 定位与边界

- 状态：Accepted
- 日期：2026-08-29
- 范围：Immersive Learning 产品面下的媒体学习引擎分层与首个垂直

## 决策

**Immersive Learning** 是产品面；其底层引擎名为 **Media Learning Engine**，
语言无关（language-agnostic），覆盖 video / audio / podcast / course / lecture。
**English 是首个垂直**，不是引擎的硬编码范围。

模块边界：

```text
Immersive Learning
├── Media          # 资产摄入、存储引用、播放会话、续播位置
├── Transcript     # 来源、归一化、切分、provenance
├── Segment        # 定时导航/循环单元
├── Language Scaffold  # L0–L5 呈现与查词 UX
├── Practice       # 听力/听写/回忆/迁移任务
└── Mneme Core Integration  # 发 LearningEvent；调 Evidence/Policy/Memory Router/FSRS
```

引擎**不**自建掌握度、**不**自建第二套 FSRS/调度器、**不**在播放器内嵌
`if replay>3 then quiz` 类策略。媒体/转写 worker 落 oprim/oskill；会话编排在
`services/`；播放器在 `mneme-web`。

路径固定为：

```text
Media → Transcript → Segment / LearningUnit
  → LearningEvent → Evidence → CognitiveStateV2
  → Policy → FSRS → Delayed Review → Transfer Evaluation
```

## 不变的红线

- Media / Segment 不得发明 CognitiveState；Practice 不得自判掌握度。
- `position_ms` 只属于播放连续性，不属于 CognitiveState。
- 不得为英语另起平行 learner-state；语言维度用 `knowledge_ref` 命名空间扩展
  （`vocab-*` / `grammar-*` / `listening-*` 等）。

## 验证

架构对照：`outputs/IMMERSIVE-LEARNING-ARCHITECTURE.md` §2–3、§14；实现时由契约
测试锁定“无第二调度器 / 无播放器内嵌策略规则”。
