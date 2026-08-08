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

- **测试**：~906 passed（本机缺 mneme_core 包时 19 个 mcp/omodul 文件收集失败、28 个既有环境失败，均非本次引入）/ 11 skipped
- **覆盖率**：88.5%（pyproject.toml 已配 greenlet concurrency）
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
- **Git**：main 领先 origin 若干 commits，近期工作（Aria/康奈尔/题库匹配）+ 本次新增 89 个测试已 `git add` 未提交
- **容器**：api + worker + beat + db + redis + minio；echomimic 侧车宿主机 native（profile=gpu）
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

- 4 个既有测试失败（daily_plan FSRS 排程×3 + dod_e2e 定性 verifier 真 LLM×1）
- 全仓 ruff 4 处 / mypy 1 处既有违规（mcp_client/textbook_qa_service/test_mcp_write_path 未用 import + vendor/omodul 双重模块名）
- 变式题 `_VARIANT_SYSTEM` prompt 硬编码 "math question generator"，物理/语文未调优
- 英语 `knowledge_units` 为空（走独立词汇 FSRS 体系 U.19）
- Stratum 语料库为空（C4 通路已通，内容填充未做）
- PA-2 真实 webhook 推送未验（等用户提供 WeCom/Feishu 群 URL）
- ship-gate 四条仍在（真人 pilot / KU→chunk 精度 / Z 回测 / 测试=生产 CI 收敛）
- C4 部署已生效（2026-08-02）：db `ALTER USER` 新口令 + minio 重建（root 口令随 env 启动生效）
  + api/worker/beat 重建，enrich cron 崩溃（password auth failed）已修复，回归验证通过

---

## 🔄 进行中

（当前无正式进行中的 task。）

**Aria 数字人全链路**（2026-07-31）：
- Phase 1 ✅：3D VRM 默认路径 + Director 骨骼指令 + 2D 代码全删
- Phase 2 ✅：viseme 口型（edge-tts WordBoundary → VRM blendshape）+ MIDI 手指弹琴
- Phase 3 ✅：自写 aria_brain.py 自主行为大脑（后端 asyncio + WebSocket）
- **Fay 大脑接管** ✅：Fay 框架部署为 Docker 容器（Qwen LLM + edge-tts + WebSocket 10002），
  替代自写 aria_brain。前端 `FayAria` 组件 = 照片驱动真人 + Fay WebSocket 接收音频/唇形/动作。
- 63 aria tests green, tsc+build clean。
- 容器：mneme-fay（Flask GUI :5001, WS human :10002, WS web :10003）

## ✅ 近期完成（倒序，仅列最近一批）

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
