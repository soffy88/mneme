# STATUS.md · Mneme（善学记）项目状态快照

> **维护协议**：每次非平凡任务开始时先读本文件；工作中更新「🔄 进行中」；
> 完成后移入「✅ 近期完成」并更新「当前状态」里的数字；遇到无法自行决定的
> 事项写入「🚨 需人决策」。本文件是**浓缩全景**，不是 TASKS.md 的副本——
> 只记"新会话需要立刻知道的事"，细节查 TASKS.md / MNEME_MASTER_DESIGN.md。

---

## 这是什么

Mneme（对外名**善学记**）：K-12 学生学习成长档案 + 自主学习工具。
核心 = **BKT(知识追踪) + FSRS(间隔重复)** 算法内核，先做广东数学，已扩物理/语文/英语。

⚠️ **本机即生产**。`mneme-api-1` + `mneme-db-1` 是 `api.sxueji.com` / `sxueji.com`
的活后端。破坏性操作（删数据/downgrade/重启活容器/改 tunnel）必先确认。

## 架构速览

| 层 | 位置 | 说明 |
|----|------|------|
| oprim | `platform/3O/oprim`（pip -e）+ `vendor/oprim`（冻结副本） | 单次原子操作（bkt/fsrs/solve_*/ocr/grade/verify_step…） |
| oskill | `platform/3O/oskill` + `vendor/oskill` | ≥2 oprim 组合（cognitive_update/socratic_loop/interleave_select…） |
| omodul | `platform/3O/omodul` + `vendor/omodul` | 业务事务，标准签名 `(config,input,output_dir)→dict` |
| obase | `platform/3O/obase`（pip -e） | 基础设施（db/auth/oss/sympy_runtime/cost_tracker…） |
| services | `services/` | Layer 4 装配：鉴权→调 3O→持久化→返响应，**零业务逻辑** |
| mneme-core | `packages/mneme-core` | 私有内核（mastery_gate/quiz_selection/intent_router/progress_assembler） |
| mneme-agent | `packages/mneme-agent` | AgenticLoop/tutor_loop/chat_loop，**零 DB 红线**，经 `/mcp/*` HTTP |
| mneme-studio | `apps/mneme-studio` | Next.js pilot 学习界面（sxueji.com/studio） |
| mneme-web | 独立仓库 `/data/soffy/projects/mneme-web` | 真前端（Next.js PWA），本仓不含前端 |

**依赖方向**：omodul→oskill→oprim 单向；obase 平行不被反向依赖；omodul 不互调。

**技术栈**：Python 3.12 / FastAPI async / SQLAlchemy 2.0 async / Alembic /
PostgreSQL 16 / Redis 7 / Celery / 阿里云 Qwen（文本 qwen3.7-plus / 视觉 qwen-vl-max，
MaaS 专属部署 OpenAI 兼容端点）/ Docker Compose / pytest。

## 关键文件地图

| 找什么 | 看哪里 |
|--------|--------|
| 唯一权威设计 | `MNEME_MASTER_DESIGN.md` |
| 执行看板（2500+ 行） | `TASKS.md` |
| 工作约定/红线 | `CLAUDE.md` |
| Agent 架构说明 | `AGENTS.md` |
| API/MCP 工具全集 | `services/mcp_router.py` |
| 主路由（60+ 端点） | `services/main.py` |
| 鉴权/IDOR 防护 | `services/auth_deps.py` |
| 认知状态更新 | `services/cognitive_service.py` |
| 掌握度单源阈值 | `services/learner_model.py`（GATE=0.6/MASTERED=0.7/GREEN=0.75/YELLOW=0.40） |
| 每日计划规则引擎 | `services/daily_plan_service.py` |
| 判分主链路 | `services/math_grade.py` |
| 定性判分 | `services/qualitative_verify.py` |
| 沙箱 sympy | `vendor/obase/sympy_runtime.py` + `vendor/obase/sandbox_ast_audit.py` |
| 数据合规/硬删除 | `services/purge_service.py` |
| Provider 注册 | `services/providers/setup.py` |
| 三层 Memory | `services/memory.py`（agent schema） |
| Partners 渠道 | `services/partner_channels.py` + `tasks/partner_heartbeat.py` |
| 多用户授权/审计 | `vendor/obase/user_grants.py` / `vendor/obase/audit_log.py` |
| CLI | `cli/mneme_cli.py`（文档见 `SKILL.md`） |
| 康奈尔笔记 | `services/cornell_service.py` + `data/cornell_topics/` |
| Aria 数字人 | `services/aria_director.py` / `services/aria_media.py` / `services/aria_perception.py` |
| 教材 PDF **离线源**（未接入流水线） | [TapXWorld/ChinaTextbook](https://github.com/TapXWorld/ChinaTextbook) — 小初高/大学 PDF 聚合；>50MB 分片需 tools 合并；**勿整仓 submodule**；入库仍走 `scripts/import_textbooks.py` + 本地/挂载 books |

## 当前状态

- **测试**（2026-08-16，宿主 pytest → `mneme_test`，约 3 min）：1100 passed / 26 failed / 4 skipped / 2 errors。失败全为环境/数据（ollama embed、CLI vs 活服务、book compile、knowledge hub、MCP rubric、provider 顺序、echo/hand、s1 grading、error_journal 运行时表、mcp_request_question 缺种子题）——已用 stash 对照 HEAD~1 验证**零回归**（HEAD~1 为 1099/27/4/2，失败集完全一致）。`check.sh` smoke 44 passed。
- **覆盖率**：83%（services，greenlet concurrency；`fail_under=60`）
- **mypy**：第一方代码 0 错误（docker/scratch 外部/实验目录排除；旧“vendor 双重模块名”已随 vendor.* import 统一为 oprim.* 消解）
- **代码审查图（CRG）**：code-review-graph 已接入 opencode（`opencode.jsonc` MCP + 全局 crg-plugin 钩子），
  `.code-review-graph/` 已入 .gitignore；**本地 CRG 已取消默认忽略 `**/vendor/**`**（mneme vendor=3O 内核），
  项目 `.code-review-graphignore` 排除 studio node_modules / fay / PDF；全量图 ~9.8k 节点
- **P0–P3 加固（2026-08-07）**：
  1. `PgStore.get_or_create` 对 `(student_id,kc)` **SELECT FOR UPDATE**（并发掌握度不丢更新）
  2. vendor 裁剪金融子树 + `EDU_BOUNDARY.md` + `test_vendor_edu_boundary`
  3. `ErrorType` 下沉 `obase.domain_enums`；learner_profile 改 ProviderRegistry（断 oprim→services）
  4. 双 BKT 写路径守卫 `test_mastery_write_path_guards`
  5. lifespan 强制 `sandbox_selfcheck.check_or_die`（`MNEME_SKIP_SANDBOX_SELFCHECK=1` 可跳）
  6. `cognitive_update` 纯单测 + 并发写路径测试
  7. main 拆出 `services/routers/{health,cornell}`；CLAUDE 服务层措辞对齐现实
- **LLM**：阿里云 MaaS 专属部署（`QWEN_BASE_URL`/`QWEN_API_KEY` 在 .env），已实测通
- **注册**：邮箱（Z.2），SMS 仍 mock，注册闸门 `REGISTRATION_OPEN=0`
- **环境**：`MNEME_ENV=demo`（非 prod）
- **Ruff**：默认缺陷集 E4/E7/E9/F = 0（`[tool.ruff.lint] select` 钉死，防版本漂移扩成上千条风格规则）
- **Git**：分支 `chore/test-pythonpath-fix`；质量可复现包已提交（db_guard 钉 `mneme_test` + ruff 清零 + smoke/edu-closure）；第二轮 vendor 裁剪 + mypy 清零待提交
- **容器**：api + worker + beat + db + redis + minio；echomimic 侧车宿主机 native（profile=gpu）
- **待应用迁移**：`8ad19eb4ab90`（wrong_questions.item_difficulty，nullable 补列）已应用
  到 mneme_test；活库 `mneme` 待 api 容器下次重启时 alembic 自动应用（代码已 getattr
  防御，重启前不会 500）
- **前端**：mneme-web 独立仓库，旧 `frontend/` 已删（tag `archive/frontend-legacy`）

## 红线（违反 = task 未完成）

1. **确定性优先**：有 `solve_*` 覆盖的题型，数值结论必来自内核，LLM 不得改写
2. **答案分级**：学生自带题/作文永不给可抄答案；系统教学同构新知可给完整样例
3. **掌握度唯一路径**：P(L) 只经 `SubmitAnswer`→内核更新，任何 agent/Partner/CLI 不得自行判定
4. **多用户 deny-by-default**：`ADMIN_USER_IDS` 环境变量判 admin，非 admin 需 `SetUserGrant` 显式授权
5. **未成年合规**：<14 无监护人同意注册必失败；删除后数据不可查询；新表同 PR 入 purge 清单
6. **沙箱**：病态 sympy 输入必须超时被杀；全仓 AST 扫描零绕过（`sandbox_selfcheck.check_or_die()`）
7. **3O 层级**：omodul 不互调（含包装模式）；obase 不反向依赖 3O；服务层零业务逻辑
8. **同源自检**：lesson_page 图示值==答案==末步值，三处不一致不交付
9. **交错/检索**：相邻题 KC 不同；回顾未作答不可见答案，看答案=Again
10. **指纹/轨迹禁真实 PII**：`_fingerprint_fields`/decision_trail 不含真实 user_id

## 已知技术债 / 遗留

- 全量 26 fail + 2 error（环境/数据，见「当前状态」；已与 HEAD~1 对照确认零回归）
- 变式题 `_VARIANT_SYSTEM` prompt 硬编码 "math question generator"，物理/语文未调优
- 英语 `knowledge_units` 为空（走独立词汇 FSRS 体系 U.19）
- Stratum 语料库为空（C4 通路已通，内容填充未做）
- PA-2 真实 webhook 推送未验（等用户提供 WeCom/Feishu 群 URL）
- ship-gate 四条仍在（真人 pilot / KU→chunk 精度 / Z 回测 / 测试=生产 CI 收敛）
- C4 部署已生效（2026-08-02）：db `ALTER USER` 新口令 + minio 重建（root 口令随 env 启动生效）
  + api/worker/beat 重建，enrich cron 崩溃（password auth failed）已修复，回归验证通过

---

## 🔄 进行中

**Aria 数字人全链路**（2026-07-31）：
- Phase 1 ✅：3D VRM 默认路径 + Director 骨骼指令 + 2D 代码全删
- Phase 2 ✅：viseme 口型（edge-tts WordBoundary → VRM blendshape）+ MIDI 手指弹琴
- Phase 3 ✅：自写 aria_brain.py 自主行为大脑（后端 asyncio + WebSocket）
- **Fay 大脑接管** ✅：Fay 框架部署为 Docker 容器（Qwen LLM + edge-tts + WebSocket 10002），
  替代自写 aria_brain。前端 `FayAria` 组件 = 照片驱动真人 + Fay WebSocket 接收音频/唇形/动作。
- 63 aria tests green, tsc+build clean。
- 容器：mneme-fay（Flask GUI :5001, WS human :10002, WS web :10003）

## ✅ 近期完成（倒序，仅列最近一批）

- **vendor 第二轮裁剪 + mypy 清零**（2026-08-16）：删 113 个未引用金融/量化/支付文件
  （alipay/stripe/okx/stat_arb/macro_*/risk_*/llm_agent 多空/ohlcv_store/price_store/
  crypto 交易族/backtest 族 + autoheal_cycle/backup_app_data/generative_video_pipeline），
  `vendor_edu_closure.py --check` 升级为**文件存在性守卫**（防整仓 dump 回流，白名单仅
  合法密码学/DB 事务设施）；`vendor.oprim.*` 历史导入风格统一为 `oprim.*`（消解 mypy
  双重模块名）；mypy 第一方 15 处真实类型错误清零（aria 循环变量遮蔽、KCState
  datetime→unix ts、mastery_map 泛型等）；**修复真实运行时 bug**：question-bank ZPD 排序
  引用不存在的 `WrongQuestion.item_difficulty`（迁移 8ad19eb4ab90 补列 + getattr 防御）；
  check.sh 加 ruff/mypy 缓存目录不可写回退；清理 mneme_test 历史污染行（JSON 'null'
  fsrs_card_json、test-* fixture KU）后 daily_plan/retention/review 恢复确定性。
  对照 HEAD~1 全量验证零回归。
- **质量数字可复现**（2026-08-16）：宿主 pytest 经 `tests/db_guard.py` 钉 `mneme_test` + `.env` 现口令（fail-closed，禁打活库 `mneme`）；ruff 钉 E4/E7/E9/F 并清零；`check.sh` 加 smoke（44）+ `vendor_edu_closure --check`；L1 单源自检改扫 routers；`PgStore.get_or_create(for_update=)` 写路径显式加锁。全量 1095/29/6/2、cov 83%。未写 `DATABASE_URL` 进 `.env`（compose 活库用 `/mneme`）。oservi/chat 见「需人决策」。
- **CRG 审查闭环**（2026-08-04）：接入 code-review-graph（opencode MCP + 插件 + AGENTS.md 指引），
  修复高/中风险缺口 —— 新增 89 个测试（prod 禁 mock 旁路红线 19 测 / SMS+Email fail-closed /
  aria viseme+Director 回退 / paper_tasks retry / match_questions 纯函数 / _trim_plot_data /
  _table_exists / _check_lockout/_register_failure 直调），风险分 0.85→0.75，关闭 17 个缺口；
  剩余缺口多为 CRG 工件（测试辅助类/HTTP 路由/Pydantic 模型）或环境依赖项（视频管线/LLM 匹配）
- **C4 部署落地**（2026-08-02）：db ALTER USER 新口令 / minio 重建轮换 root 口令 /
  api+worker+beat 重建吃新 env；enrich cron 修复（旧口令认证失败→退出码 0）；
  验证：api /health 200、db 新旧口令（新 OK 旧拒）、minio 新旧凭据（新 OK 旧拒、
  137 对象完好）、worker/beat DB 连接全通
- **C 审查修复**（2026-08-01）：C1 purge FK 顺序（lesson_pages→wrong_questions 反查、
  parent 双列清、运行时表 to_regclass 兜底，7/7 回归）+ C2 验证码暴力锁（连错 5 次
  锁 15min，mock 码仅 demo/dev 生效）+ C3 上传 50MB 上限 + 平台教材注入改 admin 白名单 +
  C4 compose 口令注入/端口 127.0.0.1 + C5 Celery retry/acks_late + MinIO 孤儿 blob 清理 +
  FK 热点列索引迁移（19 列）+ 脚本口令环境变量化
- **Aria 数字人全链路**（2026-07-29）：Director LLM 指挥 / 3D VRM 身体 / EchoMimic V2 侧车 /
  感知层 VLM / 手势 MIDI+SVG / 口型 / TTS edge-tts / Ken Burns film loop / 独立数字人图层 /
  侧车部署 E2E / P1–P3 集成。110 tests。
- **康奈尔笔记 Phase B+C**（2026-07-28）：交互式检索笔记 + 云同步（cornell_progress 表）
- **CMM 真题→人教 KU 匹配**（2026-07-28）：G7–G9 共 3019 条挂 RENJIAO KU
- **全仓可信试用包**（2026-07-28）：Y.4 复检（LLM/VLM 已通）+ pilot 清单 + provider 加固
- **W5 全量验收关闭**（Partners + 多用户 + CLI）
- **前端合二为一**（2026-07-22）：收敛到 mneme-web，旧 frontend/ 删除
- **AF W2 欠账清偿**：quiz_generator / persona / Stratum RAG / chat 工作区 / Memory follow-ups
- **AA Studio pilot**：一套登录 / 定性 verifier / KaTeX / 题库清洗 / 判分准确率 10%→92%
- **AB 判分 CI 门**：真题库 fixture + ≥90% 准确率回归
- 更早的 A–AE 全部完成，详见 TASKS.md

## 🚨 需人决策

- **oservi / chat 未挂载（线上）**：活 `mneme-api-1` 的 `import oservi` 失败（`cannot import name 'IDaemon_Bus' from 'obase'`，vendor/obase 无此符号）。`services/main.py` 吞 ImportError，线上 OpenAPI 24 个 `/mcp`、**0 个 chat**。`tutor_loop`/`chat_loop` 硬 `from oservi.agentic_loop import AgenticLoop`；oservi 仅 `docker-compose.override.yml` 挂 `/opt/oservi_pkg`（dev）。选项：A) vendor/obase 补 `IDaemon_Bus` 并在活容器挂 oservi（**会重启 api，需确认**）；B) chat 改成不依赖 oservi 的可选装配；C) 接受 chat 仅本机 dev、线上不提供。本包只把 chat 测试改成 `importorskip("oservi")`，未改活容器。
- **阿里云短信报备**：完成前勿开公网注册（当前邮箱注册可用）
- **MNEME_ENV=prod**：设 prod 后 `_assert_prod_safety` 强制真实验证通道（SMS aliyun 或 SMTP 邮箱二选一）
- **PA-2 真实 webhook**：需提供 WeCom/Feishu 群 webhook URL 才能验证
- **真实学生数据**：0.77 AUC 验证 / FSRS 权重拟合启用 / FIRe 上线 A/B 均以此为前提
- **U.21 课标标注量产**：需更强模型（当前 qwen2.5vl:7b 错误率 ~5-8%，骨架可接受但量产不够）
- **ship-gate 四条**：真人 pilot / KU→chunk 精度 / Z 回测 / 测试=生产 CI 收敛

---

## 里程碑总览（A → Aria，~90 个 task 全部完成）

| 阶段 | 内容 | 状态 |
|------|------|------|
| A–F | 核心闭环：注册→拍卷→Celery 批改→掌握度→今日目标→苏格拉底 | ✅ |
| G–L | 家长端/求解可视化/变式题/纵向分析/合规/部署 | ✅ |
| M | 3O 增强：随手拍/元认知/物理受力/阅读理解/英语口语 | ✅ |
| N–Q | 四层知识体系/教材阅读器(119 PDF)/知识点讲解+练习 | ✅ |
| R(17项) | 数学单科前端闭环：BKT+IRT/补救阶梯/JOL/留存/交错/错题本/美化 | ✅ |
| S–T | 教育审计修复 + 登顶路线（AUC 守卫/FIRe/步骤批改/小测/考期感知） | ✅ |
| U(24项) | 教育架构重排（门控/CAT/RCT/语文双轨/UDL/feature-flag/课标标注） | ✅ |
| V–W | 每日计划闭环修复 + 外部数据集审计 + 软前置 | ✅ |
| X–Y | 项目体检（coverage/同源/沙箱/孤儿）+ 上线就绪体检 | ✅ |
| Z | 云模型(阿里云 Qwen) + 邮箱注册 | ✅ |
| AA | Studio pilot：登录/定性 verifier/KaTeX/题库清洗/判分 92% | ✅ |
| AB–AF | 判分 CI 门/mastery_path/三层 Memory/Z 回测/W2 清偿 | ✅ |
| W5(A–C) | Partners 渠道+心跳 / 多用户授权审计 / CLI+Agent-native | ✅ |
| Cornell | 交互式康奈尔笔记（本地+云同步） | ✅ |
| Aria | 数字人全链路（Director/3D/VRM/EchoMimic/感知/手势/口型） | ✅ |
