# ADR-0013：FSRS 与 Memory Router 资格集成

- 状态：Accepted
- 日期：2026-08-29
- 范围：媒体证据如何进入（或不进入）唯一 FSRS 调度权威

## 决策

Mneme **只有一套 FSRS 调度权威**（既有 `vendor`/`oprim` fsrs 写路径）。Immersive
Learning **引入 Memory Router** 作为显式资格边界：决定
`create` / `update` / `evidence-only` / `no-op`，**不**拥有算法权重，**不**第二套
scheduler。

```text
Video / Practice Evidence
  → Memory Router eligibility
  → FSRS item create/update  或  evidence-only / no-op
```

| 情形 | 动作 |
|------|------|
| 仅 lookup | Evidence only |
| 首次合格的 LU 表现失败 | 可 create FSRS item |
| 合格的间隔回忆 / review 成功 | Update FSRS |
| 同会话 massed replay | Evidence only；**不当** spaced review |
| 污染证据（露答案 / 未标记 AI） | 打标；无 mastery / FSRS 写入 |

今日 FSRS 更新散落在 `process_interaction` / vocab 路径；本 ADR 将“能否碰 FSRS”
收口为命名服务边界，媒体面必须经 Router，禁止播放器或 Partner 直写卡片。

## 不变的红线

- 禁止第二调度器或“视频专用 SRS”。
- Lookup / 弱行为不得自动建卡。
- Massed 同会话复听 ≠ spaced review。
- 掌握度并发与双 BKT 红线（CLAUDE.md）不变：写库仍走既定认知写路径。

## 验证

契约：lookup → `no_fsrs_item`；合格 listening/dictation/transfer result 才可
create/update；同 session massed 计数不推进 FSRS due；重复 `event_id` 不双更新。
