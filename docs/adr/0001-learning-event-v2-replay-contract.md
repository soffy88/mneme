# ADR-0001：Learning Event v2 与 Replay Contract

- 状态：Accepted
- 日期：2026-08-24
- 范围：Learning Event / Evidence / Cognitive State 的事实层与重放边界

## 背景

Mneme 当前已有 `interaction_events`、`KCMastery`、`MasterySnapshot`、复习和
苏格拉底等数据，但它们还没有统一的跨模型事件契约。若先让页面或 Agent 直接拼接
业务表，后续替换 BKT、扩展 FSRS、加入迁移和元认知状态时，前端与历史数据都会被
实现细节绑死。

Blueprint 将 Memory Loop 定义为：Learning Event → Evidence → Cognitive State →
Policy → 新事件。本 ADR 冻结契约和不变量；数据库迁移、双写、历史回填与只读 replay
由后续独立 task 接入，materialized projection 仍保持可选且可重建。

## 决策

### 1. Learning Event 是事实源

Learning Event v2 的逻辑字段如下。字段可以在物理数据库中拆成列或 JSONB，但 API
和导出必须保持同一语义：

```text
event_id
schema_version              # 当前为 "2"
actor_id / student_id
session_id
occurred_at / received_at
source                      # paper/practice/review/socratic/reading/speaking/...
action                      # attempted/recalled/asked_hint/explained/revised/...
object_type / object_id
content_version
knowledge_refs[]            # KU/KC/strategy/prerequisite
item_features               # difficulty/discrimination/modality/format
response                    # answer/step/speech/selection（按 privacy class 处理）
outcome                     # correctness/partial_credit/verifier/provenance
process_signals             # latency/attempts/hints/steps/interruptions
metacognitive               # JOL/confidence/self_explanation/help_seeking
intervention                # prompt/hint/scaffold/policy decision
provenance                  # OCR/model/provider/kernel/source
privacy_class               # P0/P1/P2/P3
trace_id
```

事件必须能表达“学生做了什么”和“系统提供了什么介入”，但不得把推断出来的
`p_mastery`、`is_mastered` 或策略结论伪装成事实字段。状态属于 Projection，由
模型计算产生。

### 2. 事件只增不改

- `event_id` 是幂等写入键；相同事件重试不得产生第二条事实记录。
- 历史事实不得 `UPDATE` 或物理覆盖。更正使用新事件，并通过
  `supersedes_event_id` / `correction_reason` 表达关系。
- 事件的原始来源、验证器和模型版本写入 `provenance`；低置信度输入不能静默升级
  为高置信度事实。
- `privacy_class` 是契约字段，不由呈现层临时推断；涉及学生的新持久化表必须同步
  纳入 `services/purge_service._STUDENT_TABLES`。

### 3. Replay Contract

Replay 输入是某个学生在指定时间窗口内的 canonical Learning Events；排序键为
`occurred_at ASC, received_at ASC, event_id ASC`。Replay 必须：

1. 只读取事件和明确版本的模型参数；
2. 在每次事件之前生成预测，再应用该事件产生状态转移；
3. 输出 `state_version`、`model_version`、`computed_at`、`evidence_refs` 和投影
   checksum；
4. 对同一事件快照、模型版本和参数，重复运行得到相同输出；
5. 默认只读，不写生产状态。写入 materialized projection 必须是单独、可重建的
   job，并带 projection version。

Replay 不允许依赖当前业务表中的“最后状态”，也不允许读取事件发生时间之后生成
的 projection 作为输入，避免未来信息泄漏。

### 4. Legacy adapter

现有 `InteractionEvent` 继续作为兼容读写入口。迁移期间由 adapter 将旧字段映射
到 v2：旧事件保留原始 ID 和时间，缺失字段保持 `null`/显式 `unknown`，不得补造
元认知、迁移或 verifier 证据。新功能先定义 v2 event，再接 UI；旧字段将在完成
历史回放校验后退役。

## 不采用的方案

- 不把 `KCMastery` 或 `MasterySnapshot` 直接升级为事实表；它们是可重建 projection。
- 不让 LLM 自由生成状态或 Narrative claim；叙事必须由 Claim → Evidence[] →
  Source Event 支撑。
- 不用 xAPI/Caliper 作为内部最小 schema；内部事件做超集，再提供标准 adapter。
- 不在本 ADR 中引入 DKT、深度模型或新的数据库表；challenger 只能在 shadow 轨道
  通过同一 replay 协议验证后再逐步放权。

## 验收与后续工作

后续 Event v2 task 必须至少提供：schema contract tests、幂等 ingest、correction
event、legacy adapter、replay determinism test、projection checksum 和导出样例。

截至 2026-08-24，契约层已落地在 `packages/event-schema/`：

- `LearningEvent` v2 及嵌套 Evidence 字段使用 Pydantic 严格拒绝未知字段，明确禁止把
  `p_mastery` 等投影结果塞入事实事件；
- `legacy_interaction_to_event()` 保留旧 `InteractionEvent` 的 ID、发生时间、题目、
  知识点、作答结果、FSRS rating、过程信号和 FIRe 元数据，缺失的 `received_at` 固定
  回填为 `occurred_at`；
- `canonical_replay_events()` 固定窗口、`as_of` 防未来信息泄漏和
  `occurred_at → received_at → event_id` 全序，`replay_checksum()` 为规范 JSON 的
  SHA-256；
- `tests/test_event_schema.py` 覆盖版本/未知字段、时区、更正关系、legacy 映射、
  定序和校验和。
- `learning_events` Alembic migration 与 `services/learning_event_service.py` 已提供
  独立事实表和幂等 append 边界：同一 `event_id` 同 checksum 是安全重试，不同 payload
  是冲突；新表已加入未成年人数据硬删除清单。
- `process_interaction` 与试卷分析写路径已支持通过
  `LEARNING_EVENT_V2_DUAL_WRITE_ENABLED=1` 在同一事务中把 legacy event 映射到 v2，
  两侧共用同一个 event ID；默认关闭，待 migration 部署后再启用。
- 数据库行可通过 `learning_event_record_to_event()` 重新进入 canonical replay，测试锁定
  legacy→v2→数据库行→v2 的 checksum 等价性。

历史回填与只读 replay job 已接线，但默认不写：回填为手动、分页、dry-run 优先，写入
还需 `LEARNING_EVENT_V2_BACKFILL_ENABLED=1`；replay 返回稳定 input/projection checksum
和按事件 ID 排列的 `evidence_refs`，
不写 `kc_mastery` 或 materialized projection。双写和回填的生产启用仍需独立 rollout
与数据量/延迟观测。
