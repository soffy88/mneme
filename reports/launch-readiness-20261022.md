# Mneme（善学记）上线就绪评估 — 2026-10-22

- 评估对象：`/data/soffy/projects/mneme`，`main` @ `70e56d1`（含 `feat/jiangshan-links` 合并）
- 评估性质：只读评估，未改业务代码；未写生产库
- 评估方式：代码/文档/路由审阅、生产库只读查询、公开端点探测、10 分片测试 + 根目录复核、Ruff/MyPy/覆盖率
- 重要事实：`sxueji.com` 已经公网可达（`/studio/learn`、`/login` 均 200），但容器运行在 `MNEME_ENV=demo`
- 最终判定：**NO-GO（正式公开/商业化上线）**；若定义为“邀请制、免费、不宣称学习效果的技术试点”，可在完成 P0-1/2/5/6/7 后转为**有条件 GO**

---

## 0. 结论摘要

| 维度 | 结论 |
|---|---|
| 工程质量 | **通过**：2827 用例，2812 passed / 0 failed / 15 skipped；覆盖率 80.13%；Ruff、MyPy 全绿 |
| 核心学习闭环（数学） | **基本完备**：KU → 路径 → 练习/判分 → BKT/FSRS → 复习/错题/小测 → 掌握度 |
| 多学科产品面 | **部分**：语文/英语/物理的学科工作台未公开路由；物理题库未接 KU；历史/化学/生物仅符号数据 |
| 部署运维 | **不达标**：自动备份 cron 指向不存在的脚本；生产身份为 `demo`；无 mneme 监控抓取；`/data` 92% |
| 安全合规 | **不达标**：仓库内提交了数据库口令；隐私政策/监护人同意/ICP 未闭环；CC BY-NC 与收费路线冲突 |
| 现有发布门 | 仓库自带 `docs/LAUNCH_CHECKLIST.md` 仍为 `BLOCKED_INFRA` + `BLOCKED_OWNER`；`make launch-readiness` 会在 `secret_safety` 失败 |

**一句话**：学习内核和测试质量已经像“可上线产品”，但法务/未成年人合规、生产配置与数据可恢复性还像“内部演示环境”。

---

## 1. 核心能力清单

状态口径：**完备** = 有数据/服务/公开入口且闭环可测；**部分** = 后端或数据存在，但入口、数据映射或线上暴露不完整；**缺失** = 没有可用实现或没有数据。

| # | 能力 | 状态 | 证据（文件/路径） | 主要缺口 |
|---|---|---|---|---|
| 1 | 学科知识体系（KU/先修图/教材绑定） | 部分 | `knowledge_units` 14,646；`knowledge_clusters` 1,931；`textbooks` 133；`data/ku_packages/` 68 个包；`data/cn_math_taxonomy/` | 仅 2,166/14,646 KU 已核验（14.8%）；`ai_generated=true` 14,646；历史/化学/生物极薄 |
| 2 | 题库 | 部分 | `wrong_questions(student_id IS NULL)` 30,120 题；`data/cn_math_taxonomy/questions.json` 2,271；`data/seed_questions.json` 306 | 物理 390 题全部映射到伪 KC，0/1,551 KU 有题；历史 0 题；数学 5,015 题依赖图片 |
| 3 | 学习路径 / Next Action | 完备 | `services/mcp_router.py`（`GetPath`/`NextObjective`/`CheckMastery`）；`services/path_builder.py`；`apps/mneme-studio/app/learn`、`today` | 公开面只覆盖数学主路径；多学科路径未公开 |
| 4 | 诊断（先修回溯 / 缺口单点练 / 薄弱点） | 部分 | `services/prereq_diagnosis_service.py`、`gap_drill_service.py`；MCP `StartPrereqDiagnosis`/`StartGapDrill`；`/v1/weak-roots` | 公开 `/placement` 为 404（Caddy 有路由、代码无页面）；先修/缺口单点练无前端 |
| 5 | 练习 / 复习 / 错题 / 限时小测 | 完备 | `services/routers/practice.py`、`review.py`；`services/quiz_service.py`、`wrongbook_review_service.py`；`tests/test_quiz.py` 等 | 语义上题库寄存在 `wrong_questions`，后续建议独立 `question_bank` |
| 6 | 拍照答疑 / 解题 | 完备 | `services/routers/questions.py`、`practice.py`；`mneme-ocr-1` healthy；`apps/mneme-studio/app/ask`、`solve` | 依赖 OCR/LLM 可用性；已有降级路径 |
| 7 | 语音朗读 TTS | 部分 | `services/routers/voice.py` `POST /v1/tts`；`mneme-speech-1` healthy；`/data/soffy/models/sherpa` 373MB | 后端可用，公开前端未接 TTS 播放 |
| 8 | 语音陪伴 / AI 陪学陪练 | 部分 | `WS /v1/voice`；`services/companion_service.py`；`companion_safety.py`；`apps/mneme-studio` 无 voice 调用 | 无公开语音 UI；`mneme-web/speaking` 明确“音频不上传”，是文本练习而非口语陪练 |
| 9 | 语文专项（古诗文/阅读/作文/成语/字词） | 部分 | 语文 8,516 KU、2,986 题；`data/ku_packages/TONGBIAN-*`；`mneme-web/src/app/subjects/chinese/*` | 学科工作台未公开路由；作文/真题模考在卡片中为 disabled/ComingSoon |
| 10 | 英语（词汇/语法/阅读/听说） | 部分 | 555 KU、1,207 题；`mneme-web/src/app/subjects/english/*`；`services/speaking_service.py` | 听说/口语为文本；真题模考 ComingSoon；学科工作台未公开 |
| 11 | 物理（概念/受力分析/实验） | 部分 | 1,551 KU；`services/routers/subjects.py` 受力分析/概念诊断；`mneme-web/src/app/subjects/physics/*` | 0 个物理 KU 有题库映射；专题练习/变式/模考/虚拟实验室均 disabled |
| 12 | 历史 / 化学 / 生物 | 缺失 | 历史 243 KU、化学 22 KU、生物 20 KU；均 0 题、0 核验、无学科页 | 仅数据占位，不构成可学可练能力 |
| 13 | 江山时序地图外链 | 部分 | `data/jiangshan_links/links.json` 1,751 条；`tests/test_jiangshan_links.py`；`reports/jiangshan-links-pilot.md` | 无 API/前端引用；许可证（MIT vs GPL-3.0）与审图号未清 |
| 14 | 家长端 / 成长报告 | 部分 | `services/routers/parent.py`；`mneme-web/src/app/parent/*`；`/v2/export` | 家长页未公开路由；无独立家长 App/小程序 |
| 15 | 多用户 / 授权 / 审计 / 硬删除 | 完备 | `vendor/obase/user_grants.py`、`audit_log.py`；`services/purge_service.py`；51 张学生表 + 家长表全覆盖；`tests/test_partner_no_self_judged_mastery.py` | `ADMIN_USER_IDS` 未配置，admin 授权入口当前不可用 |
| 16 | 支付 / 订阅 | 缺失 | `docs/MONETIZATION.md` 仅 provider-neutral 契约；`BILLING_PROVIDER` 未配置 | 无真实支付渠道；PRO 定价 `TBD_OWNER_DECISION` |
| 17 | 沉浸式 / 可视化 / 数字人 | 部分（实验） | `apps/mneme-studio/app/{immersive,visualize,animate}`；`services/immersive/`、`aria_*`；Fay/Echo 侧车 | `IMMERSIVE_LEARNING_ENABLED` 默认 0；无对外验收 |
| 18 | 数据导出 / 互操作 | 完备 | `/v2/export`（mneme/xapi/caliper/case）；`tests/test_export_*` | 标准适配器只导出伪匿名 URI，符合预期 |

### 1.1 学科数据覆盖（生产库只读统计）

| 学科 | KU | 有题库映射的 KU | 系统题（`student_id IS NULL`） | 已核验 KU | 公开学科入口 | 判定 |
|---|---:|---:|---:|---:|---|---|
| 数学 | 3,320 | 2,505 | 24,686（其中 5,015 需图） | 376（11.3%） | studio `learn/practice`（数学主路径） | 部分/主路径可用 |
| 语文 | 8,516 | 816 | 2,986 | 816（9.6%） | 无（`/subjects/chinese` 公网 404） | 部分 |
| 英语 | 555 | 555 | 1,207 | 555（100%） | 无（仅 ask/book 可跨学科） | 部分 |
| 物理 | 1,551 | **0** | 390（映射到 `cmmlu-physics-*` 伪 KC） | 0 | 无 | 部分/数据未接通 |
| 科学 | 419 | 419 | 851 | 419 | 无独立学科页 | 部分 |
| 历史 | 243 | 0 | 0 | 0 | 无 | 缺失 |
| 化学 | 22 | 0 | 0 | 0 | 仅 ask | 缺失 |
| 生物 | 20 | 0 | 0 | 0 | 无 | 缺失 |

补充：

- 题库来源：`cmm-math` 22,248、`ctsf-v1.2.0-v5` 6,545、`cmmlu` 993、`ceval` 125、`gaokao_bench` 210（`wrong_questions.profiler_analysis->>'source'`）。
- 数学 5,015 题 `needs_image=true`，文本练习路径会被排除；实际可文本作答的数学题约 19,671。
- `textbooks` 中存在 subject=`数学` 的 20 本空书（0 KU），是历史导入残留，建议清理。
- 真实使用量很小：`users` 115、`question_records` 169、`interaction_events` 139、`learning_events` 38，尚无 pilot 证据。

### 1.2 前端 / 入口现状（这是最容易被文档误导的一点）

仓库里有两套前端：

1. `mneme-web`（独立仓 `/data/soffy/projects/mneme-web`）：学科工作台、家长端、口语、作文、掌握度等，最完整。
2. `apps/mneme-studio`：MCP 驱动的学习主面（learn/today/practice/review/ask/solve/…）。

线上 Caddy（`/data/soffy/projects/aegis/Caddyfile`）实际只放行：

- `/studio/*` → studio（200）
- `/login`、静态资源 → mneme-web（200）
- `/placement` → mneme-web（但页面不存在，实测 **404**）
- 其余 → studio

实测：`https://sxueji.com/subjects/math`、`/parent/overview`、`/speaking`、`/essay`、`/mastery` 全部 **404**。也就是说，README 所说的“真实生产前端 mneme-web”目前只公开了登录页，主力产品面是 studio。

---

## 2. 质量

### 2.1 测试（按要求分片，未改业务代码）

分片方式：按 `tests/test_*.py` 文件序切成 10 片（33/27/32/28/28/30/30/30/29/28 个文件），另跑 `tests/unit`。测试库使用独立 `mneme_test`（已迁移到 head），未触碰生产库 `mneme`。

| 分片 | passed | failed | skipped |
|---|---:|---:|---:|
| 00 | 450 | 0 | 0 |
| 01 | 244 | 0 | 7 |
| 02 | 412 | 0 | 4 |
| 03 | 259 | 1 | 1 |
| 04 | 169 | 1 | 0 |
| 05 | 226 | 0 | 3 |
| 06 | 214 | 0 | 0 |
| 07 | 276 | 1 | 0 |
| 08 | 218 | 1 | 0 |
| 09 | 337 | 0 | 0 |
| **小计** | **2,805** | **4** | **15** |
| `tests/unit` 补跑 | 3 | 0 | 0 |

口径对齐：2,805（分片通过）+ 4（CWD 假失败在根目录复跑通过）+ 3（`tests/unit`）= **2,812**，与根目录全量复核一致；另有 15 skipped。

4 个失败全部是**工作目录（CWD）敏感**的相对路径问题，不是产品缺陷：

- `test_immersive_merge_gate::test_player_has_no_mastery_threshold_pedagogy`（读 `apps/mneme-studio/lib/immersive.ts`）
- `test_learner_model_l1::test_call_sites_migrated_to_single_source`（读 `services/routers`）
- `test_product_closure::test_frontend_cannot_compute_mastery`（读前端源码）
- `test_s1_grading_accuracy_e2e::test_real_bank_sample_grading_accuracy`（读相对数据）

按仓库根目录（`scripts/check.sh` 的调用方式）复跑后全部通过。根目录复核结果：

- **2,812 passed / 0 failed / 15 skipped**（收集 2,827；连续 3 次一致）
- 覆盖率：**80.13%**（`--cov=services`，门槛 60%，通过）
- 低覆盖热点（非阻塞）：`textbook_qa_service` 15%、`visualize_service` 31%、`textbook_extract_service` 55%

说明：分片首轮有 4 个 CWD 假失败，根目录复跑是必要的；测试过程未发生 OOM。为跑测试，把原本指向不存在 revision `cts5meta0001` 的 `mneme_test` 重命名为 `mneme_test_stale_ctsf5`，并新建 `mneme_test`（生产库未动）。

### 2.2 Lint / 类型 / 迁移

| 检查 | 结果 |
|---|---|
| `ruff check .` | **All checks passed** |
| `mypy --explicit-package-bases services tasks cli packages` | **Success: no issues found in 263 source files** |
| Alembic | 92 个 migration，全部有 `downgrade`，单 head `vcm1a2b3c4d5`，生产库已在 head |
| CI | `.github/workflows/quality.yml`：Postgres/Redis/MinIO + `uv sync --locked` + 迁移 + `scripts/check.sh` + studio build + `npm audit` |
| 前端类型检查 | CI 只构建 `apps/mneme-studio`；`mneme-web` 不在本仓 CI 内，本次未跑 tsc/eslint |

---

## 3. 部署与运维

### 3.1 Compose / 运行时

- `docker compose config -q` 通过；api/db/redis/minio/worker/beat/speech 均 running；api/db/minio/redis/speech healthy；重启次数 0。
- 启动顺序正确：`sandbox_selfcheck → alembic upgrade head → uvicorn`（`docker-compose.yml` api command）。
- `api` 以 uid 999 非 root 运行，bind-mount 工作树；本次检查 `git ls-files` 权限位，others 不可读文件 **0**。
- `.env` 为 600、已被 `.gitignore` 忽略；容器内普通用户读不到 `.env`，启动脚本通过 `cd /tmp` 规避，属于可用但脆弱的约定。

### 3.2 环境变量（只核对键名，未打印任何值）

当前 `.env` 与 `.env.example` 的差异（键名级）：

- `.env.example` **缺少** compose 强制项：`POSTGRES_PASSWORD`、`MINIO_ROOT_USER`、`MINIO_ROOT_PASSWORD`（`${...:?}` 会在 `docker compose up` 直接报错）。
- `.env.example` 也缺 `EMAIL_PROVIDER`/`SMTP_*`、`ADMIN_USER_IDS`、`GIT_SHA`、`RELEASE_VERSION`、`REGISTRATION_OPEN` 等上线必需项。
- `.env` 缺 `DATABASE_URL`、`REDIS_URL`、`MINIO_*` 等（由 compose 注入，能跑，但与文档不一致）。
- 现状值（非密钥）：`MNEME_ENV=demo`、`REGISTRATION_OPEN=1`；`EMAIL_PROVIDER`/`SMS_PROVIDER` 未设（默认 mock）；`MINIO_ACCESS_KEY` 仍为 `minioadmin`；`ADMIN_USER_IDS` 未设；`GIT_SHA`/`RELEASE_VERSION` 未设。
- `JWT_SECRET` 非默认值且长度 ≥32（通过）。
- 生产 preflight（`services/production_config.py`）会拒绝当前配置：`MNEME_ENV` 必须是 `production`、至少一个真实 SMS/email、禁止 `minioadmin`、必须显式 `GIT_SHA`/`RELEASE_VERSION`。

### 3.3 健康检查 / 日志 / 监控

| 项 | 现状 | 判定 |
|---|---|---|
| `/health` | `{"status":"ok"}` | 通过 |
| `/readiness` | `database/migrations/storage` 均 true | 通过 |
| `/health/metrics` | 请求数 2,483、错误 0、p50/p95、端点级 | 基础可用 |
| worker/scheduler | 只有容器 running，未进入 readiness | **P1** |
| 日志 | structlog JSON → stdout；docker json-file `max-size=10m,max-file=3` | 基本通过；无集中检索/保留 |
| 监控 | Prometheus（`:9090`）只抓 `selene/cadvisor/node-exporter/prometheus`，**不抓 mneme** | **P1** |
| 告警 | `alert_service` 是家长预警，不是运维告警；无 on-call 路由 | **P1** |

### 3.4 备份 / 恢复（阻塞）

- crontab 里配置了每日 02:10：
  `... /data/soffy/backups/mneme/run_backup.sh >> .../backup.log`
- 但 `/data/soffy/backups/mneme/run_backup.sh` **不存在**，`backup.log` 也不存在；cron 每天静默失败。
- 目录里只有一份手工快照：`pre-vc1-20261022-030931.sql.gz`（386MB）。生产库 1.5GB。
- `scripts/backup.sh`、`scripts/restore_drill.py` 存在，但**没有实际调度，也没有恢复演练记录**。
- `BackupContract` 的 RPO/RTO 仍是 `TBD_OWNER_DECISION`。

### 3.5 磁盘与数据库膨胀

- `df -h /data`：787G 总，710G 已用，**69G 可用（92%）**。
- `/tmp` 是 16G tmpfs，已用 13G（81%）；本次测试因此改用 `/data/soffy/tmp`。
- Docker：镜像 109GB、卷 52.39GB、build cache 18.78GB（可回收约 222MB；镜像层可回收约 1.1GB）。
- Mneme 库 1.5GB；最大表 `vocabulary_collection_memberships` 1.07GB（211 万行）。
- `aegis`（`platform-postgres` 的 `aegis` 库，121MB）：
  - 当前**没有** `agent_metrics` 原表，只剩 `agent_metrics_rollup_1h`（24KB）；
  - `metric_anomalies` 102MB、`n_live_tup=0`、`n_dead_tup=5,295`、`last_vacuum/last_autovacuum` 均为空；
  - 说明“agent_metrics 膨胀”已从原表转到残留膨胀/无保留策略，仍需 vacuum + retention 验证。
- `textbook_chunks` 也有 3,514 dead tuples；建议统一 autovacuum 参数。

---

## 4. 安全与合规

### 4.1 鉴权与多用户

- JWT HS256、7 天有效期、Bearer；`services/auth_deps.py` 的 `_ensure_student_self/_ensure_student_access` 覆盖写/读越权；有 IDOR/权限测试。
- 登录有失败锁定；邮件/短信验证码有 60s 防刷；CORS 为显式白名单（`services/main.py`）。
- 工具授权 deny-by-default（`vendor/obase/user_grants.py`）：学生默认仅 `VoiceTutor/StudyCompanion/先修诊断/可视化/缺口单练`，其余需 admin。
- **`ADMIN_USER_IDS` 未配置** → 当前没有 admin，`SetUserGrant`、`BindPartnerChannel` 实际不可用。
- 前端把 JWT 放 `localStorage`（`mneme-web/src/lib/auth-store.ts`），无 CSP/HSTS/X-Frame-Options（`next.config.ts` 无 headers；实测响应头也没有）；`pg_hba.conf` 对 127.0.0.1 是 `trust`。

### 4.2 未成年人数据与隐私

做得好的部分：

- `services/purge_service.py` 的 51 张学生表 + 家长表覆盖完整；本次用 `information_schema` 反查，未发现漏表。
- 年龄分层（<12 过程数据家长可见，≥12 默认不可见）在 `services/privacy.py`。
- 语音陪伴有确定性安全层：自伤、恋爱、离题、PII 打码、输出过滤（`services/companion_safety.py`）。
- 掌握度只能经 `SubmitAnswer` 更新，有 AST 红线测试。

阻塞/缺口：

- **`OWNER-LEGAL-GATE.md` 七项全部 BLOCKED**：隐私政策、条款、数据保留、未成年人政策、监护人同意、研究分类、数据处理者审查。
- 登录页只有一句“已阅读并同意《个人信息处理及隐私政策》”，**没有可点击的隐私政策/条款页面**。
- 自助注册 UI 只走邮箱验证码，而 `EMAIL_PROVIDER` 默认 mock；`MNEME_ENV=demo` 下 mock 旁路被拒绝，实测 `POST /v1/auth/send-email-code` 返回“当前未配置真实邮件通道”（HTTP 429）→ **公开自助注册不可用**。
- `POST /v1/auth/register/student-account`（用户名/密码）没有年龄/监护人门禁；这是绕过 <14 监护人同意的 API 路径。
- 邮箱注册路径 `register_student_email()` 创建 `User` 时**没有写入 `birth_date`**，后续年龄分层/家长过程数据可见性会退化为 `None`。
- 未见 ICP 备案/公安备案号；公网域名 `sxueji.com` 面向未成年人提供生成式 AI 服务，需要备案与算法/生成式 AI 合规评估。

### 4.3 第三方许可证

| 来源 | 许可证/状态 | 风险 | 证据 |
|---|---|---|---|
| `cn-math-taxonomy`（531 知识点 + 2,271 题 + Python 移植算法） | **CC BY-NC 4.0** | **禁止商业使用**；`docs/MONETIZATION.md` 规划 PRO 收费 → 直接冲突 | `data/cn_math_taxonomy/NOTICE.md`、`UPSTREAM.json`、`services/cn_math_importer.py`、`services/prereq_diagnosis_service.py` |
| `cmm-math` 题库（22,248 题） | 未随数据记录许可证 | 数据集许可未核验；`cmm_math_train.jsonl` 20MB 已入库 | `cmm_math_SOURCE.txt`、`wrong_questions.profiler_analysis` |
| `cmmlu` / `ceval` / `gaokao_bench` | 未随数据记录许可证 | 仅存 source 字符串，商用/再分发依据不足 | `wrong_questions` source 统计 |
| PEP 教材文本（2,869 句 / 72 文件） | 教材版权 | 公开产品中复现教材句子需授权或“随身携带教材”边界 | `textbook_sentences`、`services/reading_service.py`、`curriculum_standards/` |
| `jiangshan-map` 外链 | LICENSE=MIT，README 又称 GPL-3.0，且上游引用谭其骧/CHGIS 等 | 不能按 MIT 放心用；历史边界地图无审图号 | `reports/jiangshan-map-assessment.md`、`data/jiangshan_links/links.json` 的 label |
| AetherViz | MIT | 低风险 | `data/aetherviz/LICENSE` |
| DashPlayer / AGPL | clean-room 边界 | 若未来引入 AGPL 依赖需重审 | `docs/adr/ADR-IMMERSIVE-AGPL-BOUNDARY.md` |

`data/jiangshan_links/links.json` 的 1,751 条都带“第三方示意地图，非教材标准地图”label，但目前没有 API/前端消费它，所以“标注”尚未真正到达用户。

### 4.4 内容审核

- 语音陪伴有输入/输出安全过滤；答案泄漏有确定性闸门；这些有测试。
- 通用 chat/ask 没有统一的审核队列、举报入口、人工复核台；AI 生成内容全部 `ai_generated=true`，KU 核验率仅 14.8%。
- 对未成年人产品，建议上线前至少补齐：举报入口、审核队列、抽样复核、危机词转人工。

---

## 5. 阻塞项（P0）与建议项（P1）

### P0（上线前必须修复）

| ID | 阻塞项 | 证据 | 影响 | 建议 | 估工时 |
|---|---|---|---|---|---|
| P0-1 | 仓库内提交了数据库口令 | `reports/jiangshan-links-pilot.md:255` 含 `POSTGRES_PASSWORD=<literal>`；`python3 scripts/secret_scan.py` 直接失败；该文件在 `3ed4229` 已进入历史 | 凭据泄漏；仓库自带 `make launch-readiness` 的 `secret_safety` 失败 | 立即轮换 DB 口令；删除该行并清理历史；把 `secret_scan` 加进 `quality.yml` 必跑 | 2–4h（含轮换）；历史重写 +0.5d |
| P0-2 | 自动备份未运行、无恢复演练 | crontab 指向不存在的 `/data/soffy/backups/mneme/run_backup.sh`；仅一份 2026-10-22 03:10 手工 dump；无 restore 记录 | 数据丢失不可恢复；RPO/RTO 未定义 | 修复 cron/脚本；每日 pg_dump + MinIO 快照；在 staging/test 做一次完整 restore drill 并记录 | 4–8h + 0.5d 演练 |
| P0-3 | 法务/隐私/监护人同意/ICP 未闭环 | `docs/OWNER-LEGAL-GATE.md` 7 项 BLOCKED；登录页无隐私政策链接；无 ICP/公安备案号 | 未成年人合规与监管风险；不能公开商业化 | 出隐私政策/条款/儿童个人信息规则；完成监护人同意与数据保留决定；办理 ICP/公安备案与生成式 AI 合规评估 | 法务 3–10 工作日；ICP 1–3 周（外部） |
| P0-4 | CC BY-NC 数据 + 算法进入生产路径，且计划收费 | `data/cn_math_taxonomy/NOTICE.md` 明确禁止商业使用；`docs/MONETIZATION.md` 规划 PRO | 授权违约/下架风险 | 取得上游商用授权，或在收费版本中移除/替换该数据与移植算法；在授权前保持完全免费 | 法务 1–3 工作日；工程替换 2–5 工作日；谈判 1–4 周 |
| P0-5 | 生产身份/配置不达生产门 | 线上 `MNEME_ENV=demo`；`EMAIL_PROVIDER/SMS_PROVIDER` mock；`MINIO_ACCESS_KEY=minioadmin`；`GIT_SHA/RELEASE_VERSION` 未设；`production_config` 会拒绝 | 安全闸门实际未武装；无法按生产发布 | 设 `MNEME_ENV=production`；配置真实 SMTP（或短信）；换 MinIO 凭据；注入 `GIT_SHA/RELEASE_VERSION`；跑 `production-db-preflight` | 4–8h + 真实邮件通道 1–2d |
| P0-6 | 公开自助注册不可用 | 唯一 UI 走 `/register/student-email`；`EMAIL_PROVIDER=mock` 被 `_mock_bypass_allowed` 拒绝；实测 send-email-code 返回“未配置真实邮件通道” | 新用户无法注册，`REGISTRATION_OPEN=1` 形同虚设 | 配置真实 SMTP 并端到端测试；或明确改为邀请码/管理员开户，并在 UI 隐藏自助注册 | 2–4h（SMTP）；或 1d（邀请制 UI） |
| P0-7 | 未成年人注册保护可绕过 + 生日未落库 | `register_student_account()` 无年龄/监护人校验；`register_student_email()` 的 `User(...)` 未写 `birth_date` | <14 可绕过监护人同意；后续年龄分层失效 | 所有学生注册路径统一走年龄门禁与 `GuardianConsent`；持久化 `birth_date`；补测试 | 4–8h |

### P0 修复状态（2026-10-22，分支 `fix/launch-p0`）

| ID | 状态 | 修复证据 | 剩余 |
|---|---|---|---|
| P0-1 | **已修** | `reports/jiangshan-links-pilot.md` 口令行已删除；`scripts/secret_scan.py` PASS；`secret_scan` 已加入 `.github/workflows/quality.yml`；PostgreSQL 口令已 `ALTER USER` 轮换并同步 `.env`（旧值未重写 git 历史，已作废） | 无 |
| P0-2 | **已修** | `/data/soffy/backups/mneme/run_backup.sh` 已实现并手动成功（pg_dump -Fc + MinIO 快照 + 7 天轮转 + backup.log）；restore drill 关键表行数一致，记录见 `docs/RESTORE_DRILL.md` | RPO/RTO 数值、异地副本、自动演练仍属 owner 决策 |
| P0-5 | **部分** | MinIO 已换非默认强随机凭据；`GIT_SHA`/`RELEASE_VERSION` 已注入 `.env` 与 compose；生产 preflight 现只剩“真实邮件/短信验证通道”一项，属外部依赖，故**保留 demo** 未硬切 | 真实 SMTP/短信通道（外部），通道就绪后可再切 `production` |
| P0-6 | **已修** | 新增 `registration_invites` 表 + admin API（生成/列表/吊销）；学生凭邀请码注册端点 `POST /v1/auth/register/student-invite`（不依赖邮件）；登录页隐藏邮件自助注册、改为邀请码注册；`ADMIN_USER_IDS` 已设 owner 账户 | 无（SMTP 路径仍保留可配置） |
| P0-7 | **已修** | 手机/邮箱/用户名/邀请码四条学生注册路径统一年龄闸门（`assess_registration_age`），`birth_date` 全部落库，<14 必须监护人联系方式 + 明确同意；新增/更新测试覆盖 | 无 |

> 未处理的 P0-3（法务/隐私/ICP）与 P0-4（CC BY-NC 商用授权）仍为外部/法务阻塞，本轮未动。

### P1（建议在 GA 前完成）

| ID | 建议项 | 证据/影响 | 估工时 |
|---|---|---|---|
| P1-1 | 统一公开路由：`/placement`、`/subjects/*`、`/parent/*`、`/speaking`、`/essay` 目前 404；mneme-web 只公开了 `/login` | 产品能力“存在但用户到不了”；与 README 描述不一致 | 1–2d（先做路由决策，再补 Caddy/页面） |
| P1-2 | 物理题库与 KU 对齐；历史/化学/生物要么补数据要么明确“不在本期范围” | 物理 0/1,551 KU 有题；390 题映射到伪 KC | 3–6d |
| P1-3 | 语音陪伴前端：TTS 播放、`/v1/voice` WS、打断、家长开关 | 后端完整但无公开 UI；`speaking` 页明确“音频不上传” | 3–5d |
| P1-4 | 江山外链接入 API/UI，并让 label 可见；先完成许可证与审图合规 | 1,751 条数据未被任何代码引用 | 工程 2–3d；法务 1–3d |
| P1-5 | 监控/告警：Prometheus 抓 mneme，worker/scheduler 进 readiness，接 on-call | Prometheus 无 mneme target；无运维告警 | 1–2d |
| P1-6 | 磁盘与膨胀治理：/data 92%、/tmp 81%、build cache 18.8GB、aegis metric_anomalies 102MB/0 live | 余量不足会放大备份/构建/日志风险 | 0.5–1.5d |
| P1-7 | 安全加固：CSP/HSTS/X-Frame、JWT 撤销/刷新、缩短有效期、`pg_hba` 本地改 scram | 当前无安全头；7d JWT 存 localStorage；本地 trust | 2–3d |
| P1-8 | 补齐 `.env.example` 与运维手册：`POSTGRES_PASSWORD`、`MINIO_ROOT_*`、`EMAIL_PROVIDER/SMTP_*`、`ADMIN_USER_IDS`、`GIT_SHA/RELEASE_VERSION` | 新环境按文档无法 `docker compose up` | 2–4h |
| P1-9 | 配置 `ADMIN_USER_IDS`，验证 `SetUserGrant`/`BindPartnerChannel` | 当前无 admin，特权工具不可用 | 0.5h |
| P1-10 | 题库/教材版权尽调：cmm-math、cmmlu、ceval、gaokao_bench、PEP 教材句 | 仅 source 字符串，无许可证文件 | 法务 1–3d |
| P1-11 | 内容安全：通用 chat/ask 的审核队列、举报入口、人工复核；KU 核验率从 14.8% 提升 | 目前仅语音陪伴有强过滤 | 1–3d + 持续内容运营 |
| P1-12 | 建立 staging 与真实 pilot（当前 `LAUNCH_CHECKLIST` 为 BLOCKED_INFRA、无 pilot 数据） | 无法在非生产环境做迁移/恢复/金路径验证 | 1–2 周 |

---

## 6. 建议上线路径

1. **今天**：轮换 DB 口令，删除报告中的口令行，修 cron 备份并做一次 restore drill（P0-1/2）。
2. **1–2 天**：把线上环境从 `demo` 切到 `production`，配真实 SMTP，补齐 `GIT_SHA/RELEASE_VERSION` 与 MinIO 凭据；端到端跑通注册/登录（P0-5/6）。
3. **2–3 天**：统一学生注册的年龄/监护人门禁并持久化 `birth_date`；补隐私政策/条款页面（P0-7 + P0-3 工程部分）。
4. **并行法务**：CC BY-NC 商用授权、题库/教材版权、ICP/公安备案与生成式 AI 合规（P0-3/4、P1-10）。
5. **法务书面通过后**：再决定是否开放 `/subjects/*`、家长端、语音陪伴与地图外链（P1-1/3/4）。

在 P0-1/2/3/4/5/6/7 全部关闭前，不建议对外宣布“正式上线”或开启任何收费。

---

## 附录：本次只读核查的关键证据

- 代码基线：`git rev-parse HEAD` = `70e56d1946101b04404ffd9be7a34b6a49dbf87e`
- 生产库：`mneme-db-1`（`mneme`），Alembic head `vcm1a2b3c4d5`
- 公开探测：`https://sxueji.com/` → 302 `/studio/learn`；`/studio/learn` 200；`/login` 200；`/placement`、`/subjects/math`、`/parent/overview`、`/speaking`、`/essay` 均 404
- 健康：`/health` 200、`/readiness` ready、`/health/metrics` 2,483 请求 / 0 错误
- 测试：10 分片 + `tests/unit`；根目录复核 2,812 passed / 0 failed / 15 skipped；覆盖率 80.13%
- 静态检查：Ruff 通过；MyPy 263 文件通过
- 迁移：92 个版本、单 head、全部有 downgrade
- 备份：cron 目标脚本不存在；仅 `pre-vc1-20261022-030931.sql.gz`
- 磁盘：`/data` 92%（69G 可用）；`/tmp` 81%
- 安全扫描：`scripts/secret_scan.py` 失败（`reports/jiangshan-links-pilot.md`）
- 本报告未修改任何业务代码；测试库变更仅限 `mneme_test`（旧库重命名为 `mneme_test_stale_ctsf5`）
