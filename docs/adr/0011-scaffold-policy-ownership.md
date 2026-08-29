# ADR-0011：Scaffold L0–L5 策略所有权

- 状态：Accepted
- 日期：2026-08-29
- 范围：语言脚手架级别由谁决定、播放器可做什么

## 决策

脚手架级别 **L0–L5** 由 **Policy Engine** 拥有与推荐；播放器只负责**渲染**与
**用户覆盖（override）**，不内嵌学习策略规则。

| Level | 呈现 |
|-------|------|
| L0 | 双语字幕 |
| L1 | 仅目标语字幕 |
| L2 | 关键词提示 |
| L3 | 无字幕 |
| L4 | 主动回忆提示 |
| L5 | 延迟 / 迁移任务 |

- Policy 输入：相关 LU 的 CognitiveStateV2、EvidenceRefs、到期 FSRS、会话脚手架
  历史、uncertainty。
- Policy 输出：推荐 scaffold、是否暂停练习、是否揭示翻译、是否生成复习/迁移、
  是否停止介入；经既有 `PolicyDecision` + reason_codes + evidence_refs 留痕。
- 用户 override → LearningEvent `SCAFFOLD_LEVEL_CHANGED`（behavioral），**不是**
  能力证据；须写入 PolicyTrace。

Learn Now 继续消费服务端 `PolicyDecision`；新增候选动作类型（如
`VIDEO_SEGMENT_TASK` / `DICTATION_TASK` / `TRANSFER_TASK`）仍由同一策略面产出，
不另建 Video recommendation engine。

## 不变的红线

- 播放器 **禁止** 编码 `if replay > 3 then quiz` 或同类启发式权威。
- 手动调低/调高脚手架 ≠ 掌握度变化。
- AI 可解释/生成练习，但不得取代 Policy / 掌握 / FSRS 权威。

## 验证

契约：手动 override 只改 PolicyTrace / 事件，CognitiveState mastery 不变；
应用的 scaffold 决策可追溯到 `decision_id`。
