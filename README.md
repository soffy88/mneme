# Mneme（善学记）

Personal Learning Memory OS / Cognitive Infrastructure。

Mneme 面向 K-12 学生，长期保存学习事实，持续推断可解释的认知状态，安排下一次最有价值的学习行动，并让每个判断都能回到证据。练习、Tutor、复习、错题、成长报告和家长摘要，都是这套基础设施上的应用视图。

当前仓库是后端与学习内核；真实生产前端在独立仓库 `mneme-web`。首个重点学科是广东数学，但事件、记忆、认知和策略层按跨学科演进设计。

## Memory Loop

```text
Learning Experience
  → immutable Learning Events
  → Evidence / Replay
  → Cognitive State
  → Learning Policy
  → next best learning action
  → new evidence
```

三个不可替代的核心域是：

1. Learning Event & Evidence：发生过什么；
2. Cognitive Engine：学生现在处于什么状态；
3. Learning Policy Engine：下一步最值得做什么。

## 不可妥协的工程原则

- Event 是事实，State 是推断；历史事件只增不改，状态可以从事件重放。
- LLM 负责语义、解释、提问和生成；确定性答案、判分、状态更新、权限和策略约束由内核负责。
- 认知结论必须有证据、模型版本和不确定性，不能只展示一个脱离证据的掌握百分比。
- 掌握、记忆、识别、迁移、误概念和元认知分开建模。
- AI Tutor 不直接制造掌握度；学生自带题和作文遵守答案分级与防泄漏规则。
- 未成年人数据遵守最小化采集、授权隔离、可见、导出、删除和非监控化原则。

完整项目约定见 [CLAUDE.md](CLAUDE.md)，唯一权威设计见 [MNEME_MASTER_DESIGN.md](MNEME_MASTER_DESIGN.md)，执行看板见 [TASKS.md](TASKS.md)。产品与工程路线见 [18/20 Blueprint](docs/Mneme_Personal_Learning_Memory_OS_18of20_Blueprint.docx)。
贡献与发布纪律见 [CONTRIBUTING.md](CONTRIBUTING.md)，证据标签、发布门和待决策项见
[docs/GOVERNANCE.md](docs/GOVERNANCE.md)。

## 运行与质量门

依赖解析以 `pyproject.toml` + `uv.lock` 为准；3O 教育运行时闭包位于 `vendor/`，不依赖宿主机的绝对路径。

```bash
# 安装锁定依赖
uv sync --locked

# 启动本机服务（需先准备 .env 中的数据库/对象存储密钥）
docker compose up -d

# 数据库只通过 Alembic 迁移
alembic upgrade head

# Ruff、3O 教育边界、红线 smoke、MyPy、pytest + coverage
./scripts/check.sh
```

测试必须使用专用数据库 `mneme_test`，不能指向生产库 `mneme`。CI 使用 `.github/workflows/quality.yml`，会启动 PostgreSQL/Redis、应用锁定依赖、执行迁移和质量门。

## 代码边界

```text
services/                 HTTP/MCP 鉴权、编排、持久化装配
                          learning_event_service.py：Event v2 幂等事实写入
oprim/                    单次原子操作
oskill/                   多个 oprim 组合的算法
omodul/                   业务事务
vendor/                   Mneme 锁定的 3O 教育运行时闭包
packages/mneme-core/      Mneme 私有确定性内核
packages/mneme-agent/     只通过 MCP 面调用后端的 Agent 组装参考
packages/event-schema/     Learning Event v2 契约、legacy adapter 与 replay 定序
scripts/moat_eval/        内核、真实序列和策略的可复现实证
tests/                    单元、契约、红线、合规和端到端测试
```

Agent、CLI 和前端都应通过 `services/mcp_router.py` 暴露的 HTTP/MCP 能力边界访问后端；不直连数据库，也不绕过掌握度写路径。

Event v2 双写由 `LEARNING_EVENT_V2_DUAL_WRITE_ENABLED=1` 开启；Compose 在启动时先执行
Alembic，再默认开启双写，裸本地进程仍可显式设为 `0` 进行回滚窗口。旧 BKT/FSRS
投影仍是掌握度唯一路径，v2 只记录同一事实。

历史 `interaction_events` 通过 `scripts/backfill_learning_events.py` 或 Celery task 分批迁入 v2：默认
`dry_run=true`，真正写入还必须显式设置 `LEARNING_EVENT_V2_BACKFILL_ENABLED=1`。
`tasks.replay_learning_events` 只读地从 v2 事实重放 BKT+FSRS，返回
`input_checksum` / `projection_checksum`，不写 `kc_mastery` 或 materialized projection；
两项任务均为手动调用，不加入 Celery beat。

Memory v2 读写边界已接入：`/v2/memory/timeline`、`/v2/memory/claims`、`/v2/memory/evidence/{claim_id}`、
`/v2/learner-state/*`、`/v2/growth/*`、`/v2/events`、`/v2/replay` 和 `/v2/export`。
Claim/Evidence 通过 `memory_claims`、`memory_evidence`、`memory_claim_evidence` 保存，
并随学生硬删除；Learner State 2.0 是只读多维投影，不能替代 SubmitAnswer 掌握度路径。
统一策略入口为 `/v2/policy/next-action/{student_id}`，聚合评估入口为
`/v2/evaluation/os`（D7/D30、near-transfer、观察性 uplift，样本不足返回 null）。
Tutor 控制契约位于 `mneme_core.tutor_control`；`/v1/teaching/policy` 返回
`observe→decide→generate→verify→record` 决策、答案分级和独立模式上下文。Socratic
与 agent 文本在发出前经过确定性答案泄漏闸门。
Evaluation OS v2 额外要求 no-AI transfer 的显式独立标记、delayed baseline/holdout
配对和 train/eval `as_of` 时间切分；历史未标记事件不会被包装成 no-AI 结论。
模型元数据通过 admin-only `/v2/evaluation/models` 注册，生命周期必须显式经过
shadow/candidate/production/retired，不能把同一批训练数据同时当作评估数据；进入
candidate/production 必须提交完整的 `shadow-evaluation/v1` 报告、对齐 baseline、
安全 guardrails 和至少 30 个评估事件，系统不会自动晋升。

`/v2/export` 的 `format` 支持 `mneme`（默认）、`xapi`、`caliper` 和 `case`；标准适配器
只导出伪匿名账号/对象 URI，P2/P3 默认脱敏，CASE 输出能力项与观察关联但不声称掌握。
`/health/metrics` 提供不含 URL 参数、学生 ID 或内容的进程级请求错误率与 p50/p95 延迟，
并通过 `X-Trace-Id` 回传请求关联 ID；`/health/grading` 汇总确定性判分覆盖、纯文本降级
和 verifier 缺失，不记录答案。`teaching_engine_v1` 的真实试验 protocol 见
[docs/PILOT_PROTOCOL.md](docs/PILOT_PROTOCOL.md)，启用前必须有 consent 和真实 cohort。

## 评估与证据

`scripts/moat_eval/` 提供不写数据库的回放实验：

- `exp1_kernel_auc.py`：合成数据上的 BKT+FSRS 判别力回归；
- `exp5_external_auc.py`：ASSISTments 真实序列外部对标；
- `exp6_recognition.py`：识别维度独立验证；
- `exp7_shadow_eval.py`：真实作答序列中，生产内核与 per-KC 因果移动平均基线的影子比较。

注册表对齐的候选比较器位于 `services/shadow_evaluation.py`：按
`[eval_start, eval_end)` 严格校验候选/基线事件，输出 AUC、log-loss、Brier、ECE
calibration slope 和方向明确的 observed predictive difference；它是纯计算，不写库、不控制学习路径，
也不把影子差值包装成因果 uplift。
`services.evaluation_service.reconstruct_kernel_shadow_predictions` 可只读地从
`interaction_events` 重放 production BKT+FSRS baseline；可用
`scripts/moat_eval/shadow_registry_eval.py` 从 JSONL 预测快照复跑同一契约。
候选模型接入使用 `candidate_shadow_predictions`：预测器只收到历史结果和当前事件的
非答案视图，当前事件的真实结果在预测后才追加。

影子评估同时报告 AUC 与 log-loss。学习系统不能只追求排序能力，还必须验证概率校准、留存、迁移、元认知和安全指标。

```bash
python scripts/moat_eval/exp7_shadow_eval.py
MOAT=1 ./scripts/check.sh
```

公开匿名外部数据只用于本地评估，不进入 Mneme 学生数据库。

## 当前路线

近期优先级是：仓库可复现与 CI → Learning Event v2 / Evidence / Replay → 多维 Learner State → Policy Engine → Tutor 防答案泄漏与无 AI 迁移评估。学校/LMS 扩张、跨学科和互操作出口在个人 Memory 核心闭环有真实效果证据后推进。

## 生产纪律

本机容器即生产服务。涉及删除或 purge 数据、数据库 downgrade/drop/truncate、重启活容器、改网络/CORS/tunnel 的操作，必须先确认并保留可恢复快照。
