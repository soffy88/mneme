# ADR-0008：Telemetry / LearningEvent / Evidence 三平面

- 状态：Accepted
- 日期：2026-08-29
- 范围：Immersive player 高频信号与 Learning Event v2 / Evidence 的分层

## 决策

Immersive Learning 强制三平面，不得混写：

| 平面 | 用途 | 进入 CognitiveState？ | 保留 |
|------|------|----------------------|------|
| **Telemetry** | 高频播放器信号（timeupdate、buffer、UI chrome） | 否 | 短（小时–天），采样/聚合 |
| **LearningEvent** | 语义上有意义的学习者动作/尝试 | 可能（经 Evidence 资格） | 长；随学生 purge |
| **Evidence** | 可参与认知投影 / FSRS 资格的主张 | 是（合格时） | 长；随学生 purge |

**规则：** 不是每次 UI 点击都是 LearningEvent；不是每条 LearningEvent 都是
Evidence；不是每条 Evidence 都更新 FSRS。

路由示例：

- `timeupdate` / 缓冲 / 音量 / 短于 1s 的 play-pause 刷屏 → **Telemetry only**
- 刻意句级复听 / A–B 循环 / 查词 / 练习 / 迁移 → **LearningEvent**
- 有资格的表现类结果 → **Evidence**（再经 Memory Router 决定是否触 FSRS）

媒体事实仍落在既有 LearningEvent v2 信封（`source`/`action`/`object_*` 等），
不另建第二事件库。taxonomy 见 `outputs/VIDEO-LEARNING-EVENT-TAXONOMY.md`。

## 不变的红线

- 高频 playhead 不得污染 `learning_events`。
- Telemetry 失败不得改变学习请求结果，也不得参与掌握度或策略门控。
- 聚合派生信号须单独版本化，不得静默升格为 performance Evidence。

## 验证

契约测试：10k `timeupdate` → 零 LearningEvent 污染；幂等 `event_id` 不双写
Evidence/FSRS；taxonomy 中标注 `none` 的信号默认不进 Evidence。
