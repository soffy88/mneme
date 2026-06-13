# TASKS · Mneme 实施任务看板

> 权威设计 = `MNEME_MASTER_DESIGN.md`｜工作约定 = `CLAUDE.md`。
> Claude Code 按顺序认领。完成后勾选 `[x]` + 写一行「✅ 完成说明」。DoD 见 CLAUDE.md。
> 标记：`[P0]` 关键路径，`[P1]` 重要，`[P2]` 可延后。
> 已实现（禁止重写，只能扩展）：`oprim/bkt.py`、`oprim/fsrs_engine.py`、`oskill/cognitive_state.py`、`data/guangdong_math_kc.py`、`tests/test_engine.py`（AUC≈0.77 长绿）。

---

## 核心闭环（最先打通）

```
0.1→0.2→0.3 → 1.1→1.2→1.3→1.4 → 3.1→3.2→3.3→3.4 → 4.1
= 上传一张广东数学卷 → OCR批改 → 驱动 BKT/FSRS → 看见薄弱点排序
打通后即可真实用户验证（冷启动钩子 = 3.5 共同断点 + 5.1 苏格拉底顿悟）
```

---

## Epic 0 · 基建

- [x] **0.1 [P0]** 3O 骨架与配置：建 `oprim/ oskill/ omodul/ obase/ services/ data/ alembic/ tests/`；迁已实现内核入位；`obase/config.py`(pydantic-settings)、`obase/db.py`(async session)、`pyproject.toml`、`.env.example`。DoD：`pytest tests/test_engine.py` 新结构下通过。 ✅ 骨架已建，内核已迁，测试全绿并已 push。
- [x] **0.2 [P0]** docker-compose（api+postgres16+redis7+minio）。DoD：`docker compose up -d` 全健康。 ✅ docker-compose.yml 已配置，服务已全部健康启动并 push。
- [x] **0.3 [P0]** Alembic async + baseline。DoD：`alembic upgrade head` 成功。 ✅ Alembic 已初始化，环境配置指向 config 中的 db url，baseline 迁移已成功应用并 push。
- [ ] **0.4 [P1]** CI 质量门：pytest+ruff+mypy+覆盖率阈值。DoD：一条命令跑完全检查。

## Epic 1 · 持久化（接已有内核）

- [x] **1.1 [P0]** 全部 SQLAlchemy models（Master §7 全表+枚举）+ autogenerate migration。DoD：建出所有表，字段与 Master 一致。 ✅ 模型已全，数据库已同步。
- [x] **1.2 [P0]** StateStore 抽象 + PgStore（重构 `cognitive_state.py`，保留 InMemoryStore）。DoD：同序列 InMemory 与 Pg 结果一致。 ✅ 已实现 BaseCognitiveStore 协议，支持 InMemoryStore 和 PgStore，通过一致性测试并清理了旧代码。
- [x] **1.3 [P0]** `omodul` 认知落库：`process_interaction` 落 `kc_mastery` + 追加 `interaction_events`（只增不改），严守更新顺序红线。DoD：两表正确写入。 ✅ 已实现 omodul/cognitive.py 业务事务，支持 4 支柱决策轨迹，确保两表持久化及更新顺序。
- [x] **1.4 [P0]** KC 字典 seed → `bkt_priors`（按题型展开）；`get_bkt_prior` 读库带缓存。DoD：priors 行数 = KC×题型。 ✅ 已通过 scripts/seed_priors.py 展开入库（57 条），实现 obase/prior_provider.py 带缓存获取。
- [x] **1.5 [P1]** `/v1/interaction`、`/v1/mastery`、`/v1/review-queue`、`/v1/kc` 走服务层+PG。DoD：契约同 Master §8；重启状态不丢。 ✅ 已实现核心认知 API，通过 tests/test_api.py 端到端验证。

## Epic 2 · 用户与合规

- [x] **2.1 [P0]** 用户模型 + 短信验证码（dev mock）。 ✅ 用户模型已在 1.1 完成，已实现 obase/sms.py mock 逻辑及 /v1/auth/send-code 接口。
- [ ] **2.2 [P0]** 注册/登录 + JWT + `get_current_user`（Master §8 auth）。
- [ ] **2.3 [P0]** 未成年人合规校验：<14 岁强制监护人同意，写 `guardian_consents`，否则 422。DoD：合规红线测试通过。
- [ ] **2.4 [P1]** 多孩子绑定 + `/v1/parent/children`。DoD：一家长绑 2 孩切换。

## Epic 3 · 试卷数据入口

- [x] **3.1 [P0]** `obase.oss` 上传 + `papers(processing)`（MinIO hot）。 ✅ 已实现 obase/oss.py 及 omodul/paper.py 业务流，支持 /v1/papers/upload 接口。
- [ ] **3.2 [P0]** `oprim.ocr_paper`（Claude Vision 结构化）；prompt 入 `obase/llm` prompt 库。
- [ ] **3.3 [P0]** `oprim.grade_question` + 错题入库 + KC 关联（LLM 辅助标注）。
- [ ] **3.4 [P0]** 接内核：每道错题 → `process_interaction(source='paper')`。DoD：上传后 `/v1/mastery` 反映变化，事件累积。
- [ ] **3.5 [P0]** `analyze_paper_workflow` omodul + 共同断点分析（冷启动钩子）。DoD：返回共同断点或诚实"无"，不编造；全 4 支柱产物齐全。
- [ ] **3.6 [P0]** Celery 串链：upload→ocr→grade→profiler→interaction→breakpoint→done，重试3次。DoD：端到端测试通过（LLM 可 mock）。
- [ ] **3.7 [P1]** 单题快速录入 `/v1/papers/quick` → 建 socratic session。

## Epic 4 · 认知应用层

- [ ] **4.1 [P0]** 掌握度总览（按薄弱排序）+ effective。DoD：契约同 Master §8。
- [ ] **4.2 [P1]** 月度快照 + 成长曲线 `/v1/mastery-curve`（Celery 月度写 `mastery_snapshots`）。
- [ ] **4.3 [P1]** `longitudinal_analysis_workflow`：个人模式（confidence>0.6 才输出，不编造）。
- [ ] **4.4 [P0]** `daily_mission_workflow` + Streak（Master §6.5 优先级；晚23点降级）。DoD：`/v1/missions/today` 返回单一目标。

## Epic 5 · 苏格拉底对话

- [ ] **5.1 [P0]** `oprim.socratic_turn` + `oskill.socratic_loop` + `socratic_session_workflow`；SSE 流式；mode 切换。DoD：流式可用；结束映射 FSRS rating 回写内核。
- [ ] **5.2 [P0]** 不泄露答案红线测试（诱导断言不含答案）。
- [ ] **5.3 [P1]** 情绪感知 + 家长预警联动（≥3 次写 `parent_alerts`）。
- [ ] **5.4 [P1]** 逃生出口 `/escape`（记 `used_escape_hatch`，不影响 streak）。

## Epic 6 · 家长端

- [ ] **6.1 [P0]** `/v1/parent/overview` 成长摘要（**不含绝对分数**）。
- [ ] **6.2 [P1]** 微信一句话日报（Celery+LLM≤60字，失败降级短信，写 `daily_reports`）。
- [ ] **6.3 [P1]** 5 类风险预警（emotion/score_drop/task_missing/time_drop/late_night，每类有触发测试）。

## Epic 7 · 前端（最小可用 PWA）

- [ ] **7.1 [P0]** 脚手架 + 鉴权 + API client（Vite+TS+Tailwind+React Query）。
- [ ] **7.2 [P0]** 学生核心流程：今日目标→拍题→苏格拉底(流式)→掌握度/成长曲线。
- [ ] **7.3 [P1]** 家长端：多孩子切换 + 成长摘要 + 预警。

## Epic 8 · 部署与可观测

- [ ] **8.1 [P1]** 生产 compose + 健康检查 + 结构化日志。
- [ ] **8.2 [P2]** 算法监控：定时算线上 AUC，<0.70 告警。

## Epic 9 · 合规收口

- [ ] **9.1 [P0]** `/v1/parent/export` 导出全部档案（JSON+PDF）。
- [ ] **9.2 [P0]** `/v1/parent/delete-request` 软删+异步硬删（含 OSS 归档层）。DoD：删除后不可查询（合规测试）。
- [ ] **9.3 [P1]** 加密 + 儿童信息处理规则页。DoD：Master §10 清单全勾。

## Epic 10 · 确定性求解内核（M-A）

- [ ] **10.1 [P0]** `obase.sympy_runtime` 沙箱（超时/内存/进程隔离）。DoD：病态输入超时被杀。
- [ ] **10.2 [P0]** `oprim.solve_conic / solve_function / solve_derivative`（高频先做）。DoD：每个 ≥10 样题内核自检。
- [ ] **10.3 [P1]** `solve_geometry3d / solve_sequence / solve_trig / solve_probability`。
- [ ] **10.4 [P0]** `oprim.verify_step` + 接入 `socratic_loop`（对话步校验）。DoD：错误中间步被确定性拦截。
- [ ] **10.5 [P1]** `solve_cache` 去重。

## Epic 11 · 可视化生成（M-D/E）

- [ ] **11.1 [P0]** `oprim.kernel_to_plot2d / kernel_to_three`（图示数据，与解题同源）。
- [ ] **11.2 [P0]** 前端 Mafs(2D) 渲染器 + 数据契约。
- [ ] **11.3 [P1]** 前端 Three.js(3D) 渲染器（复用 edulab 思路）。
- [ ] **11.4 [P1]** `oprim.generate_svg_diagram + evaluate_diagram`（LLM 分支+自检+重试≤2+降级）。
- [ ] **11.5 [P0]** `oskill.solve_and_visualize` + `omodul.generate_lesson_page`。DoD：三处一致自检通过；不合格图不展示。

## Epic 12 · 学习科学机制（M-B/C/F/G）

- [ ] **12.1 [P0]** `oprim.recognition_update` + `cognitive_update` 扩展双维度。DoD：「专项对但混合错」可被识别为 recognition 弱。
- [ ] **12.2 [P0]** `oskill.interleave_select` + 易混淆 KC 对配置表。DoD：相邻题 KC 不同。
- [ ] **12.3 [P0]** `daily_mission_workflow` 整合交错 + 检索约束。DoD：回顾未作答不可见答案，看答案=Again。
- [ ] **12.4 [P1]** 服务层 `InterleaveSchedulerEngine`（配置驱动调度/节流）。
- [ ] **12.5 [P1]** `oprim.compute_effortful_gain` + 前端努力错觉看板。
- [ ] **12.6 [P1]** 前端检索练习交互（遮答案/自评/计时）。

---

## 进度总览

```
MVP（Epic 0-5 核心 + 选做）：打通"上传卷→内核→薄弱排序→苏格拉底顿悟"
Phase 2（Epic 6-12）：家长端/前端/合规收口/确定性内核/可视化/学习科学机制
依赖：0→1→3→4 优先；Epic 10 是 11/12 部分前置。
保持 tests/test_engine.py 长绿；每完成一个 task 回来勾选并记录。
```
