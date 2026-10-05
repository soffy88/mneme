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
PostgreSQL 16 / Redis 7 / Celery / 本机 Veya gateway（文本 veya1.2-128K / 视觉
veya1.2-vl，OpenAI 兼容端点；Qwen 为显式云端 fallback）/ Docker Compose / pytest。

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
| 三层 Memory / Evidence Graph | `services/memory.py`、`services/evidence_graph.py`、`services/routers/memory.py` |
| Partners 渠道 | `services/partner_channels.py` + `tasks/partner_heartbeat.py` |
| 多用户授权/审计 | `vendor/obase/user_grants.py` / `vendor/obase/audit_log.py` |
| CLI | `cli/mneme_cli.py`（文档见 `SKILL.md`） |
| 康奈尔笔记 | `services/cornell_service.py` + `data/cornell_topics/` |
| Aria 数字人 | `services/aria_director.py` / `services/aria_media.py` / `services/aria_perception.py` |
| 教材 PDF **离线源**（未接入流水线） | [TapXWorld/ChinaTextbook](https://github.com/TapXWorld/ChinaTextbook) — 小初高/大学 PDF 聚合；>50MB 分片需 tools 合并；**勿整仓 submodule**；入库仍走 `scripts/import_textbooks.py` + 本地/挂载 books |

## 当前状态

- **测试**（2026-08-25，宿主 pytest → `mneme_test`，Alembic 迁移后）：`1229 passed / 14 skipped`，`coverage=82.23%`；`./scripts/check.sh` 完整质量门干净通过。
- **质量门**：Ruff 0、vendor edu closure 98 项、红线 smoke 44 项、Mypy `157 source files` 0 错误；迁移只对 `mneme_test` fail-closed 执行。
- **前端**：`apps/mneme-studio` 的 `npm ci && npm run build` 已通过；`npm audit --audit-level=moderate` 当前为 0 vulnerabilities，审计已加入 CI。
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
- **LLM**：本机 Veya 已部署；文本 `veya1.2-128K`、视觉 `veya1.2-vl`，API `/health`
  healthy，`VeyaTextCaller/VeyaVLCaller` 均为非 mock；Qwen 仅作显式 fallback。
- **注册**：邮箱（Z.2），SMS 仍 mock，注册闸门 `REGISTRATION_OPEN=0`
- **环境**：`MNEME_ENV=demo`（非 prod）
- **Ruff**：默认缺陷集 E4/E7/E9/F = 0（`[tool.ruff.lint] select` 钉死，防版本漂移扩成上千条风格规则）
- **Git**：分支 `chore/test-pythonpath-fix`；质量可复现包已提交（db_guard 钉 `mneme_test` + ruff 清零 + smoke/edu-closure）；第二轮 vendor 裁剪 + mypy 清零待提交
- **容器**：api + worker + beat + db + redis + minio；echomimic 侧车宿主机 native（profile=gpu）
- **迁移**：`b8c0d1e2f3a4`（Learning Events）、`c1d2e3f4a5b6`（Evidence Graph）、
  `d2e3f4a5b6c7`（evaluation signals）和 `e3f4a5b6c7d8`（ModelRegistry）已在迁移链；
  测试库已由质量门自动升级，活库发布仍需单独执行。
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

- 变式题 `_VARIANT_SYSTEM` prompt 硬编码 "math question generator"，物理/语文未调优
- 英语 `knowledge_units` 为空（走独立词汇 FSRS 体系 U.19）
- Stratum 语料库为空（C4 通路已通，内容填充未做）
- PA-2 真实 webhook 推送未验（等用户提供 WeCom/Feishu 群 URL）
- Blueprint 外部证据仍在：真人 pilot、far-transfer/no-AI delayed holdout、随机 A/B/RCT、真实留存/迁移/付费指标；代码与评估契约不能替代这些证据。
- ship-gate 四条仍在（真人 pilot / KU→chunk 精度 / Z 回测 / 测试=生产 CI 收敛）
- C4 部署已生效（2026-08-02）：db `ALTER USER` 新口令 + minio 重建（root 口令随 env 启动生效）
  + api/worker/beat 重建，enrich cron 崩溃（password auth failed）已修复，回归验证通过

---

## 🔄 进行中

**词汇记忆引擎 P0（2026-10-03 启动，工程规格 `MNEME_CORE3000_MEMORY_ENGINE_P0_SPEC.md`）**

按「VOCABULARY MEMORY ENGINE SPEC v1.0」实现之前先做了生产实测，因为那份 spec
按字面实现会产出**一批进不了产品链的数据**。四处前提与仓库现实不符：

| spec 主张 | 实测 | 处置 |
|---|---|---|
| Context Priority 第 1/2 层「当前教材句/Lesson 句」 | 559 lesson **全 NCE**；`lessons.book_id ∩ books` = **0**；`reading_passages` 仅 **41** 行 | 保留 tier 接口但**显式标 unavailable + 原因**，不静默降级 |
| 第 4 层「高质量公共语料」 | 无库 | 同上 |
| `IMAGE_COVERAGE≥80%` / `ANIMATION≥10%` | 图片 provider 集成 = **0**，无生图模型 | 改为 `IMAGE_PROMPT_COVERAGE`，图片生成另开 epic |
| §8 影视片段 | 2026-10-02 已因未成年+版权**被人决策否决** | **不建 media 列**（不复活） |
| 核心 3000 词 | 3,369 = **2,761 单词 + 608 短语** | 验收分母 = 2,761，单词口径 |

✅ **已交付（P0.0–P0.7）**：`vocabulary_memory_nodes`（alembic `e6f7a8b9c0d2`）、
Context Retriever（`services/vocab_context.py`）、生成 oprim
（`vendor/oprim/_vocab_memory_generate.py`）、**11** 条质量门禁
（`services/vocab_memory.py`）、FSRS 复习阶梯、`/mcp/GenerateMemoryNode` +
`/mcp/GetMemoryNode`、试跑 runner（默认 dry-run）、**50 项测试 + 6 处变异验证**。

四个值得记住的设计决定（都偏离原 spec，理由在 spec §1.3）：

1. **LLM 契约里没有 etymology 字段** → 结构上不可能编造词源。词源读既有
   `vocabulary_affixes.etymology_status` 三档。比跑 `ETYMOLOGY_CONFIRMED` 门禁强。
2. **MemoryNode 只存联想层**，不复制词源/词根/搭配（单源红线）—— 复制即多一份会
   漂移的第二来源，且会把「可当词源讲」与「只是记忆联想」抹平。
3. **每词 1 张卡**，四级阶梯是卡内分阶段揭示而非 4 张卡；按人决策**首次全展开不做
   下拉折叠**（第一次最重要，目标是完全理解），`expanded` 可多看一层但不改调度。
4. **无语境记 `DEGRADED_NO_CONTEXT` + `verified=false`，绝不记 PASS** —— 假绿会让
   「教材优先」这条产品承诺静默消失。

**输入侧审计已实跑**（`--audit-only`，纯确定性，不依赖模型）：全量 2,761 单词
tier **A=1,050 / B=1,016 / C=695**、语境覆盖 **74.83%**、平均 2.06 句/词；
100 词样本（seed=20261003）tier A=37/B=33/C=30、语境覆盖 70%（≈总体，代表性好）。

**🚨 P0.8 已不再是「无模型」阻塞 —— 根因是模型名退役（§2.9）**

`.env` 的 `VEYA_MODEL=veya1.2-128K` 是网关注释里写明的**已退役别名**（「§11 要求废弃
拼写仍可解析 —— 现在解析到 `veya-free`」），而 `veya-free` 的上游 `gpt-5.6-luna` 与
全部 `opencode-go/*` **配额耗尽**（HTTP 429）。实测 **`veya1.2` 可用**（真实补全返回
正常），`veya1.1` / `veya-deepseek-v4-flash-nv` 亦可用。

**探针设计教训（已修）**：网关会用 **HTTP 200** 把上游故障当正文返回
（`{"content":"gpt-5.6-luna 兜底失败"}`）。第一版 `/health/providers` 探针只判
「有没有抛异常」，于是把**调不通报成健康**。现在分两层：默认 ~3s 端点探活；
`?deep=1` 真发一次最小补全并**检查返回内容**是否命中 `_GATEWAY_ERROR_MARKERS`。
实测：退役别名 `reachable=true / usable=false`；`veya1.2` `usable=true`。

⚠️ **但生产仍调不通**：Veya 只 bind 宿主 `127.0.0.1:8791`，api 容器内
`host.docker.internal:8791` connection refused。按人决策**不改生产 listener**，
故容器侧可达性需另决（compose `network_mode: host` 或独立网络方案）。

**⚠️ CME-P0.8 100 词真实试跑（dry-run，报告
`reports/vocab_memory_p0/trial_100_seed20261003_dryrun.json`）**

**下面这组数字已过时**，不要当现状引用（2026-10-05 更正）：

- 当时：模型 `veya1.2`、**9** 道门禁、通过 **89/100**、调用错误 0。
- 之后三件事让它失效：① 2026-10-03 加了第 10 道 `MEANING_AUTHORITY`；
  ② 主端点换成 `Agents-A1`（`veya1.2` 已退役）；③ Veya 侧 28 个上游只剩 2 个可用。
- 同 seed（20261004）、10 道门禁、`Agents-A1` 的**重测实测：94 词跑完，
  OK 77 = 82%**，拒收 7（`FAMILY_TRACEABLE` 6 + `HAS_RECALL_HOOK` 1），
  **调用失败 10**。`FAMILY_TRACEABLE` 已由 `7b3295f` 修（把库内真实同族候选
  喂给模型，**不放宽门禁**），修后同 seed 重跑尚未完成。

**`vocabulary_memory_nodes` 至今 0 行** —— 所有生成只在 dry-run 验证过，从未落库。
「引擎可用」与「数据已生产」是两件事，别混。

**✅ 20 词人工抽查完成，四个发现**（详见 spec §3.4）：
1. `HAS_ONE_CORE_IMAGE` 下限 8 **误杀**（4/4 全是 7 字好画面）→ **已修**（下限 5），
   重跑该 4 词 4/4 全过，已加回归测试 + 变异验证。
2. **`meaning_cn` 系统性只截首个义项**：`blind`→百叶窗（漏「盲的」）、`wet`→雨天
   （漏「潮湿」）、`fine`→罚款（漏「好的」）。实测 **1,288** 词多义项，
   **1,190** 词的 `meaning_cn` 不足 canonical 一半；另 **490** 词 `pos` 与首义项不符。
   → 修它等于改「学生看到的权威释义」，**需人决策**（`CME-P1.6`），未动。
3. **画面可能与语境句不是同一义项**：`blind` 的 NCE 句是动词义，画面是名词义。
   无机制强制对齐 → 多义词上第 1 层与第 4 层讲两个意思（P1 需加义项对齐门）。
4. **无权威释义仍可 verified**：`title` 的 canonical 是纯音标 → `unusable`，
   节点仍 `verified=true`。9 条门禁里没有一条要求「输入释义可信」→ **需人决策**
   加不加 `MEANING_AUTHORITY`。

**另修两处工程缺陷**：① `resolve_stage` 按字符串 state + `card["reps"]` 写，
而 py-fsrs 的 Card **没有 reps**、state 是 **int** → 接真卡即 `AttributeError`；
测试夹具已全换成生产真卡形状。② 试跑 runner 一次 LLM 超时就中断整轮
（100 词跑到第 38 个崩，前面结果全丢）→ 已加逐词隔离 + `-u` 实时输出。

⚠️ **迁移发布注意（2026-10-05 复现并加强）**：活库与测试库都要到 head，且
**不要单独对活库跑 alembic**。

`EXPECTED_MIGRATION_HEAD`（`services/routers/health.py:13`）是**硬编码常量**，
`/readiness` 靠 `revision == EXPECTED_MIGRATION_HEAD` 判定。加迁移时若只加文件、
忘了改这个常量，就会出现 **alembic 报「upgrade 成功」而 `/readiness` 503**
—— 迁移本身是对的，红的是健康检查。这不是臆想的坑：加
`f2a8b4c6d8e1`（confusable_words）时当场撞到。

正确顺序：**改代码 → 改 `EXPECTED_MIGRATION_HEAD` → 发布重启**（容器启动命令自带
`alembic upgrade head`，迁移自动应用后新代码期望值正好对上）。
测试库 `mneme_test` 与活库 `mneme` 是**两个库**，都要升到 head，否则
`tests/test_vocab_memory_db.py` 会报 `column ... does not exist`。

⚠️ 另注：`mneme_test` 是手工补列出来的（`alembic upgrade head` 被既有漂移
`vocabulary_items.language` 挡住），**NCE 三表 `lessons`/`timed_sentences`/
`sentence_vocabulary_occurrences` 在测试库里不存在**。本次为此在
`tests/test_vocab_memory_db.py` 里幂等补建这三张表，没去「修」整个漂移（独立 epic）。

🚨 **Needs Human（2026-10-03）`./scripts/check.sh` 的 ruff / mypy 步骤在 HEAD 上
已经红了**（非本次改动引入，已用 `git stash` 确认那些文件与 HEAD 一致）：ruff 95 项
（其中 27 项来自未跟踪的 `.veya/` 工作树目录），mypy 20 项集中在
`services/learning_engine.py` 与 `services/routers/learning.py`。按「不drive-by 改
adjacent 代码」未动它们 —— 但这意味着**当前不能声称质量门全绿**。

**Vocab Enrichment（2026-10-02 启动）**：拟增「词汇增强层」（图片/动画/语境）。
调研后**未按原提案开工**，先纠三处前提（实测库，非推测）：

| 提案假设 | 实测 |
|---|---|
| 词库已具备基础词义 | `meaning_cn` 非空仅 **298/24681 = 1.2%** |
| 已具备逐词 FSRS 状态 | 机制**已实现**(U.19 `knowledge_point=vocab-{id}` 复用 KCMastery)，但 **vocab-* 卡片 = 0** |
| 标准发音已有 | `phonetic_*` 非空 = **0** |

- 外部图片 provider 集成 = 0；图片生成模型 = 无（仅 VLM 可做排序/描述）。
- `vendor/oskill/asset_reference_inject.py` 是 hevi 视频 `shot_spec`，**与词汇无关**，无现成挂载点。
- **已否决**：§4 影视片段（`license_status` 是字段不是授权；给未成年人分发版权片段
  无授权依据）→ 改为 NCE 真实语境句，已获人决策同意。

**P0 卡点（新发现，原提案未提）**：`backfill_vocab_glosses.py` 无法直接跑 ——
24,383 个待回填词里 **24,381 没有 example_sentence**，脚本会退化成
`example_sentence=word`（无上下文），违反 `_vocab_gloss_generate.py` 自述契约
（「例句由语料库确定性抽取，不是 LLM 编的」）。
另该脚本 `UPDATE ... WHERE word=%s`，而 `word` **不唯一**（240 个重复词），
按词更新会把一个义项的释义覆盖到同名的其它行。

**改序后的 P0（待批）**：先从既有语料确定性挖例句 ——
`timed_sentences` 13,017 条双语句（`english_text`+`chinese_text`+lesson+时间轴）
经 `sentence_vocabulary_occurrences` 覆盖 **9,809** 个待回填词
（`bank` 河岸/银行双义均在句中）→ 喂既有生成器（此时才有真上下文）
→ 同一批句子即 spec §4 获批的「NCE 真实语境」层。剩余 ~14,574 词待定。

**P0.1 ✅（2026-10-02）**：`scripts/backfill_vocab_glosses.py` 两处静默数据损坏已修 ——
(a) `WHERE word=%s` → `WHERE id=%s`（word 不唯一，240 词重复，按词更新会跨行覆盖）；
(b) 无 `example_sentence` 的词不再 `ex or w` 拿词本身当例句（违反生成器契约，
    多义词必错），改为跳过并打印跳过数。写入逻辑抽出 `apply_gloss_batch()` 以便单测，
新增 `tests/test_backfill_vocab_glosses.py` 6 项，**变异验证**：改回 `WHERE word` → 4 败；
恢复「只在有 meaning_cn 时对齐」→ 位置错位测试失败。均可复现。

**P0.2 范围待批（关键）**：spec 公式「中考 ∪ 高考 ∪ 教材」实测 = **20,173** 词，
与 spec 预期「3000~4000」差 6 倍。命中预期区间的是**交集** ∩ = **3,369**。
且 ∩ 的语境覆盖显著更好：

| 范围 | 词数 | 有 `timed_sentences` 语境 |
|---|---|---|
| ∪（spec 写的公式） | 20,173 | 5,601（27.8%） |
| ∩（spec 的目标数字） |  3,369 | 2,308（**68.5%**） |

`frequency_band` 对 ∩ 内 3,369 词**全部等于 5**，无法用于 Level A/B/C 分层
（1000/2000/500），需另找判别维度。另：∩ 内 `meaning_cn` 已填充 = 0，全部待生成。

**P0.2 ✅（2026-10-02）**：`scripts/freeze_core_exam_vocab.py` 固化
`CORE_EXAM_VOCAB_SCOPE = ZHONGKAO ∩ GAOKAO ∩ K12_SYNC` = **3,369** 词，产出
collection `core-exam-zhongkao-gaokao-k12`（kind=DERIVED / scope=CORE_EXAM /
stage=UNKNOWN，跨学段）+ 3,369 条 memberships（uuid5 确定性 id + ON CONFLICT
DO NOTHING）。已上生产并复跑验证幂等：collection=1 / memberships=3369 / dup=0 /
orphan=0。dry-run 默认，不加 `--apply` 不写库。

**P0.3a ✅（2026-10-02）**：`scripts/extract_vocab_examples.py` 从
`timed_sentences` 确定性挖掘例句 → **2,308 词**已有 `example_sentence`
（tier0=2234 / tier1=52 / tier2=22），1,061 词无语境按约定跳过。复跑幂等。
只写 `example_sentence` 为空的行，按 **id** 更新（word 不唯一）。
**与原 spec 偏差**：spec 要求「中考/高考教材优先」排序，但实测 559 个 lesson
**全部是 NCE**（`lesson_key` 形如 `001&002.Excuse Me`）且 `lessons.book_id` 与
`books` 表**零交集**，故无任何句子带中考/高考来源标注，该优先级无法实现；
改为按句长分层(30–119 最佳) → occurrence_index → sentence_id 排序。

**核心范围质量发现**：3,369 里有 **598 条是多词短语**（`a bit of` / `according to` /
`agree with sb.`），真正单词/专名 **2,771**。「核心 3000 词」这个口径需要说明，
否则验收数字会虚高 17.8%。

**P0.3b 音标（待人决策格式）**：CMUdict 已取得（`data/external/cmudict.dict`，
3.6MB / 135,166 词，许可明示「research or commercial purpose is completely
unrestricted」，需致谢）。覆盖核心范围 **2,753/3,369 = 81.7%**；
616 未命中中 598 是多词短语、18 个是英式拼写(`aeroplane/colourful/maths`)或
缩略词(`P.E./VCD`)。**格式未定**：现有 `phonetic_*` 列由教材词表填 **IPA**
（`/ˈæpl/`），而 CMUdict 是 **ARPAbet**（`AE1 P AH0 L`），混写会让同一列出现
两种记音体系；且前端目前**零处**渲染 phonetic（无消费面）。`phonetic_uk` 应保持
NULL —— CMUdict 只有美音，编造英音是错的。

**P0.3b ✅（2026-10-02）**：新增 `vocabulary_items.phonetic_arpabet VARCHAR(100)`
（alembic `a7b8c9d0e1f2`），存 CMUdict **原始 ARPAbet**。**不复用** `phonetic_us`：
那三列装教材词表的 IPA，混写会出现两套记音体系；`phonetic_uk`/`generic` 保持 NULL
（CMUdict 只有北美音，编造英音是错的）。`scripts/backfill_vocab_phonetics.py`
回填核心范围 **2,757/3,369 = 81.8%**（直接 2,753 + 英式变体 4），复跑幂等。
英式变体用**显式映射表**（不模糊匹配，映射错就是给孩子看错发音），命中自报
`variant:airplane` 便于审计。612 未命中里绝大多数是多词短语（`hurry up`/`a bit of`）。

⚠️ **过程中我自己踩了一个静默 bug**：CMUdict 解析写成 `rsplit(' ',1)`（按最后
一个空格切），音标被截到只剩最后一个音素，表现为「核心词几乎全查不到」
（0.1% 而非 81.7%）。若不复核极易误判成「词典覆盖不了核心词」而放弃这步。
已加 `tests/test_vocab_phonetics.py` 12 项钉住（变异验证：改回 rsplit → 6 败）。

⚠️ **每次加迁移要改 3 处**（第三个是这次才发现的漂移来源）：
`services/routers/health.py:13 EXPECTED_MIGRATION_HEAD`（不改 → `/readiness` 503
→ 容器 unhealthy）、`tests/test_nce_import_db.py:502` 的 head 断言、以及给
`mneme_test` 补列（`alembic upgrade head` 在测试库上被既有漂移
`vocabulary_items.language` 挡住，只能单独 ALTER）。建议后续把前两处改成
「唯一来源」以消除这个重复维护点。

**核心范围当前进度（生产实测）**：3,369 词 / 有例句 2,308 / 有音标 2,757 /
**有 meaning_cn 仍为 0** → 下一步 P0.4。

**P0.4a ✅（2026-10-02，重大发现改变了 P0.4 做法）**：调查中发现
`vocabulary_items.canonical_meaning` 已存着**教材词表原文照搬**的多义中文释义
（来源可追溯：`import_english_k12_vocab.py:169 canonical_meaning=e.definition_raw`
← `parser.py:50` ← 教材 workbook 单元格；`source=k12_sync`）。样例：

    bank   => "n. 银行；岸；浅滩；储库\nvt. 将…存入银行；倾斜转弯\nvi. 堆积；倾斜转弯"
    protect=> "vt. 保护，防卫；警戒"

这比「1 条 NCE 例句让 LLM 猜释义」更权威（词典原文 vs 推断）且免费、确定、无幻觉。
故新增 `scripts/derive_meaning_from_canonical.py`（纯确定性派生，零 LLM），
**已回填 2,200 词 meaning_cn**，复跑幂等。
注意 `ai_generated=true` 在这些行上**不是**幻觉标记 —— 那是列默认值且从未被维护
（核心范围 3,008 条 canonical_meaning 全部 true，0 条 false），别据此判断来源可信度。

- `pos` **默认不写**（需 `--fill-pos`）：pos 是我从词性标签**推断**的，对专名/一词
  多性明显出错（实测 `Tuesday → "n."`、`cool` 释义混了形容词义却标 `n.`）。
  `meaning_cn` 是原文照搬可追溯，`pos` 是推断值，不把推断塞进展示字段。
- 该列 **零消费面**（只有 importer 写、无人读），所以此前一直"沉睡"，本次首次启用。
- 15 项单测钉住三类静默错误：IPA 被当释义、占位符被当释义、光秃词性标签（`n.`）
  被当释义——最后一条是写测试时**当场发现**的真实 bug。

**核心范围当前真实完成度（生产实测，务必按维度分开看）**：

| 维度 | 词数 | 占 3,369 |
|---|---|---|
| meaning_cn 有值 | 2,200 | 65.3% |
| NCE 例句有值 | 2,308 | 68.5% |
| ARPAbet 音标有值 | 2,757 | 81.8% |
| **释义 + 例句 齐全** | **1,715** | **50.9%** |
| **释义 + 例句 + 音标 三者齐全** | **1,604** | **47.6%** |
| 缺释义但有例句 → 可 LLM 生成 | 593 | 17.6% |
| 缺释义且无例句 → 本阶段无解 | 576 | 17.1% |

⚠️ 单看「音标 81.8%」会严重高估整体完成度，**三者齐全只有 47.6%**。
好消息：原计划要 LLM 生成的规模从 2,308 缩到 **593**（4× 缩减）。
807 条 canonical 是 IPA 而非释义（`escape`/`freedom`/`survive` 等，说明那些教材
表把音标放进了释义列 —— 导入时的列错位，独立数据质量问题，未修）。

**词汇源材料实测（2026-10-02，gdrive `考研成人/英语词汇书`）**：
用户称 17 份，**实际只存在 14 份**。缺失 6 份含全部考研 5500 系列与
`100个英语句子背完2000个中考单词` —— 恰好是能补例句缺口的那批。

| 文件 | 文本层 | ∩ 核心 3,369 | 结论 |
|---|---|---|---|
| 威威GPT单词本 **.epub** | ✅ 7,948 词条 | **2,517 (74.7%)** | 覆盖率最高，但**内容是 LLM 生成**（其前言自述 ChatGPT），与 P0.4a「教材原文优先」原则冲突 |
| (英译汉)1600词汇默写版 | ✅ | **1,120 (33.3%)** | 可补 pos，无幻觉风险 |
| 2022版课标新增词汇 | ❌ 扫描件(10页/610字符) | ? | 含**用法搭配**（当前完全缺失的能力），需 OCR |
| 1600单词默写（音标词性中文） | ❌ 扫描件(40页/40字符) | ? | 需 OCR |
| DK×3 / EvI×3 (260MB) | 未测 | 大概率≈0 | 高级 ESL，与中考范围不重叠 |
| 词根合集 (340页) | ✅ | — | 教学指南非词表 |

⚠️ **opencode 历史会话无词汇内容**：`ses_f0942195effeIUeFTyOiIFL1cy` 就是当前这个
会话（"sxueji.com首页空白无法进入"）。全库 390 个 session **0 个**标题含
英语/词汇/单词/音标；含「词根分析/词缀分析」的仅 2 条、含「例句」的 15 条中
**13 条在当前会话内**，另 2 条是 NCE 任务规格文档。无任何词汇图片资产。

**OCR 已装并可用**（`rapidocr-onnxruntime` pip，无需系统包）。课标 PDF 实测
10 页/829 文本块/conf 中位数 0.795。但有两个必须先解决的问题：
1. **多栏表格版式** —— 朴素「先 y 后 x」聚类会把不同栏混到同一行（已实证）；
2. **OCR 恰好破坏我们要入库的字段** —— `.煮沸;烧开` 丢了 `v`、`adi.成年的`
   应为 `adj.`、`biologylab` 少空格、`n．& .帮助;援助` 乱码。词性字段出错
   会直接被学生背下来，属高危。

**词根词缀（用户要求卡片面按 前缀·词根·后缀 显示）**：唯一来源是威威GPT 的
`词根分析`/`词缀分析` 字段，但那是**自由散文且自相矛盾**（`discover` 先说
root=`dis-`+`cooperire`，紧接着又说「该单词没有前缀和后缀。中缀是 -ver」），
需要再做一次结构化抽取 = 多一层 LLM 误差面。

**P1 ✅（2026-10-02）词性回填**：从 `(英译汉)1600词汇单词默写版.pdf`（人工编排的
固定词表，`pos` 是表里显式标注而非推断，无幻觉风险）确定性回填核心范围
**1,568 词 pos (46.5%)**，复跑幂等。`scripts/import_pos_from_dictation.py`。
源表用中文教材缩写 `a`(形容词)/`ad`(副词)，已归一化为 `adj`/`adv`。
用 **pymupdf** 抽取而非 `pdftotext -layout` —— API 镜像无 poppler，而 pymupdf
已是 requirements 声明依赖。括号屈折标注 `bad (worse, worst) a` 会额外按裸词
`bad` 索引一份，否则查 `vocabulary_items.word` 永远 miss。

⚠️ 解析器踩坑两次，都已加测试：第一版用「尾部正则匹配词性」被贪婪匹配吃掉
单词一部分（`ability n` → pos=`ity n`），解析率只有 **36/1600**；改成逐 token
摘除后 1484/1600。`&`/`,` 作连接符时须透明摘除，否则 `prep & ad` 只认到 `ad`。

**P2 ✅（2026-10-02）`vocabulary_affixes` 表已建**（alembic `f2a3b4c5d6e7`，
已上生产；index `ix_vocab_affix_root` / `ix_vocab_affix_suffix`）：
`prefix`/`root`/`suffix` 三列**分开存**（可按词根反查同根派生词 —— 独立表才建得起
索引），展示串 `前缀·词根·后缀` 由 `services/vocab_affixes.format_affix_chain()`
生成、**不落库**。分隔符契约：半角 `·` 两侧各一空格，**缺段不留空占位**
（`pre · dict ·` 是错的，会在卡片上多出空格子）。15 项测试钉死。
每词一条（UNIQUE），避免渲染歧义。合规：全局参考数据非学生 PII，FK 带
ON DELETE CASCADE，故不进 purge 清单（同 vocabulary_items）。
⚠️ 表已建但**尚无数据** —— 唯一来源是威威GPT 的自由散文词根分析且自相矛盾
（`discover` 先说 root=`dis-`+`cooperire`，紧接又说「没有前缀和后缀。中缀 -ver」），
需要再做一次结构化抽取，未做。15 项 affix 测试全绿。

**核心范围当前完成度（生产实测，四维）**：

| 维度 | 词数 | 占 3,369 |
|---|---|---|
| meaning_cn | 2,200 | 65.3% |
| pos | 1,568 | 46.5% |
| NCE 例句 | 2,308 | 68.5% |
| ARPAbet 音标 | 2,757 | 81.8% |
| **释义+词性+例句+音标 四者齐全** | **1,252** | **37.2%** |

（单看任一维度都会高估；四者齐全 37.2% 才是真实完成度。）

**P3 🔶（2026-10-02）课标「用法搭配」抽取器已建，但产出是复核队列、未入库**：
`scripts/extract_curriculum_collocation.py`。**关键技术决定**：不能用「按 y 聚类
猜行」—— 第一版这么做，产出 76 条「通过校验」的记录，但**词与释义整体错位**
（`196 pressure→王子`、`197 prince→公主`、`11 aid→闹钟`），这不是 OCR 噪声而是行
对齐错误（实测同一记录内 word/meaning/搭配 三块 y 坐标不同：attack y=411 而
U.攻击 y=384、序号 y=413）。改为**从 PDF 矢量表格线建精确单元格网格**
（40 水平线 / 12 垂直线，去重后 5 列×约 20 行/页），OCR 块按中心点投影到单元格，
对齐由表格结构保证。修正后配对正确：`accident→交通事故;意外遭遇`、`account→账户`、
`breath→（呼吸的)空气;吸气`。

当前产出（10 页）：通过机械校验 **74 条**，提取搭配 **31 条**。拒绝分布：
`no_chinese_meaning: 81`（列下标硬编码 col==2，部分行错列，**主要剩余缺口**）、
`pos_not_in_whitelist: 29`、`no_word: 7`、`ocr_junk_in_meaning: 4`。

⚠️ **不进展示层的硬理由**：OCR 中文会出**形近错字**且机械校验拦不住 ——
`v.攻击;袭击` 被识别成 `U.攻击;秤击`，`adj.` 成 `adi.`。词义单元格还会被塞进
杂散记号（`n.＆.疼痛`、`& .帮助;援助`），已按「拒绝而非启发式清洗」处理
（脏数据进复核队列，不静默修补）。给 K-12 学生背的释义错一字就是错的，故
**必须人工过一遍**才能入库。复核队列：
`data/external/vocab_src/curriculum_collocations_review.json`。

**P3 ✅（2026-10-02）课标「用法搭配」已入库**（alembic `c8d9e0f1a2b3`，
表 `vocabulary_collocations`，含 `phrase_en` 反查索引）。66 条搭配 / 59 个词，复跑幂等。

三个静默错误全部定位并钉测试（`tests/test_curriculum_collocation.py` 16 项）：
1. **行对齐用 y 聚类 → 词义整体错位**（`196 pressure→王子`、`197 prince→公主`）。
   同一记录三块 y 坐标不同（attack y=411 / U.攻击 y=384 / 序号 y=413）。改为
   **从 PDF 矢量表格线建单元格**（40 水平线 + 12 垂直线 → 5 列×约 20 行/页），
   对齐由表格结构保证。
2. **列下标硬编码 col==2 → 81 行找不到词义**。实测词义列在 c2/c3/c4 之间跳
   （p1=c2 p2=c4 p4=c3 p5=c2 p6=c3…），因为某些页多检测到一条竖线。改为
   `profile_columns()` 按**内容特征**判定列角色（数字=序号 / 英文=单词 /
   首个中文占比过半=词义 / 其右=搭配）。修正后 74→**148 条**，该类拒绝归零。
3. **一个单元格含多条搭配时只在第一个汉字切** → 第二条的英文混进第一条中文
   （`traffic accident` 的 phrase_cn 里塞了 `by accident`）。改为拉丁/中文交替切分。

**入库门控（关键）**：OCR 不可全信，但**可用教材词表原文（可追溯）交叉验证**。
对同一词比对汉字重合度，`<0.30` 不加载进 review 分区。实测 67 条可比对，
平均覆盖 75.1%，仅 4 条无共同汉字，逐条判读**全部是义项选择差异而非错配**
（`novel` 课标=长篇小说/教材=新奇的：课标教名词义项；`master` 课标给名词义、
教材给动词义）。故 OCR 质量**足以入库**。

词义**不覆盖** meaning_cn：课标是「适合该学段的精简义项」，教材是详尽词典释义，
粒度不同而非冲突（`accident` 课标=交通事故;意外遭遇 / 教材=事故；意外；意外事件；机遇）。

**已知残余**：63 条 `pos_not_in_whitelist` 被拒 —— 正是它们拦住了 OCR 噪声
（`attack` 的 pos 被读成 `u`、释义 `袭击`→`秤击`）。`u`/`c` 已从词性白名单移除，
因为它们是语法记号且会放过 `v.` 的误读。

**P4 ✅（2026-10-02）词根词缀分解已入库**（alembic `b9c8d7e6f5a4`，
`scripts/import_vocab_affixes.py`）。核心范围 3,369 词 → **379 条分解**，复跑幂等。

1. **`root` 改可空**（迁移 `b9c8d7e6f5a4`）。原迁移 `f2a3b4c5d6e7` 把 `root` 定为
   NOT NULL，隐含假设「每个可入门的词都必有词根」。该假设不成立：只被讲清
   「前缀+后缀」的词（`careless` = care+less，其 care 被质量门判为平凡而落空）
   会让整个事务**原子失败**（实测 0 行写入）。`format_affix_chain` 本就支持
   缺失段位，NOT NULL 与之矛盾。
2. **形态校验挡住 295 条幻觉**：词缀段必须真实重建原词（`pre` 在首 / `able` 在尾 /
   `fact` 在内），否则 `discover` 的 `cooperire` 这类会被拒。
3. **一条自己写的过度拒绝规则，已修**：「词根位于词末即判为后缀」会砍掉大批真
   拉丁词根 —— `predict→dict`、`factory→fact`、`conduct→duct`、`reject→ject`、
   `inspect→spect`。已移除，只保留「平凡词根」过滤（等于整词/相差≤2），
   并用 `test_predict_root_dict_is_kept` 钉住防回退。
4. **归一化去掉连字符**：SEG 允许尾连字符但不允许首连字符，直接存会出现
   `pre-` 与 `dict` 并存的不一致形态。连字符是书写习惯，由
   `format_affix_chain` 按位置决定，不混进数据。

留空 2,993 词，原因分布：`explicit_no_affix` 961（散文明确写无词缀）/
`morphology_mismatch` 295（形态对不上）/ `nothing_extracted` 882 / `no_affix_section` 5。

⚠️ **待处理（诚实标注，非词源）**：这 379 条的权威来源是散文里
「词根/前缀/后缀」的**标注**，不是历史语言学。散文自身就常把词干/后缀写成
「词根」（`careless→less`、`chinese→ese`、`colour→col`）。按「单词深度记忆引擎
V2」自己的标准（*"如果所谓'词根记忆法'只是人为联想，必须明确这是'记忆联想'，
不是历史词源"*），这些属于**记忆联想**，须与已校验词源分层 —— 见下方
🚨 Needs Human。

✅ **词源/联想分层已落地**（2026-10-02，alembic `a3b4c5d6e7f8`，
`services/vocab_affixes.py`）：`vocabulary_affixes.etymology_status` 三档
`reference_confirmed` 67 / `mnemonic_association` 288 / `disputed` 24。
展示层契约：`is_source_bearing()` 决定能否当词源讲，`disputed` 默认**不展示**，
`affix_payload` 不传档位时按最保守档处理。

参考表（新东方词根词缀大全，`scripts/crossvalidate_affixes.py`）实测价值主要是
**补全**而非判对错，40 条靠它补上漏段位：`arrive` ar·∅→ar·rive、
`protect` pro·∅→pro·tect、`technology` ∅·∅·logy→techn·∅·logy。
`disputed` 24 条**不自动采信任何一方**。注意 `reference_confirmed` 是
**教学参考级**权威，不是学术词源（OED/etymonline）。

✅ **前后端已接线**（2026-10-02）：`tool_get_word_enrichment` +
`POST /mcp/GetWordEnrichment`（mneme `1820693`）；词表页展开时调该接口并渲染分档
（mneme-web `dbb969c`，`WordEnrichmentPanel.tsx`）。

展示层把 epistemic status 真的渲染出区别，而不只是多传字段：
`reference_confirmed` 实线边框正常字重；`mnemonic_association` 虚线琥珀边框 +
「记忆联想」角标 + 一行「别当词源背」；`disputed` **整块不展示**。
象形侧同样降级：音标标注「近似读音」（粗 ASCII 转写，非标准 IPA），
`ownership_verified=false` 加「归属待校对」角标（多为 OCR 形近字误读）。

🚨 **Needs Human（2026-10-02）V2「单词深度记忆引擎」的定位**

🚨 **Needs Human（2026-10-02）V2「单词深度记忆引擎」的定位**：它是**设计规格**
而非数据源 —— 记忆电影、声音钩子、拼写钩子都是生成式联想，不是事实。落地需先定
schema（`verified_etymology` / `disputed` / `mnemonic_only`），并让生成走
`services/mcp_router.py` 这一唯一入口（AGENTS.md 红线），而非本地脚本。
规模上只应把 §七「长期记忆卡」喂进 FSRS（每词 1 个 KC：释义↔拼写），
长文本按需查阅，不作复习材料。**此项未动，等用户定。**

**象形9000 ✅（2026-10-02）已入库**（alembic `c5d6e7f8a9b0`，表
`vocabulary_xiangxing`，`scripts/parse_xingxing9000.py`）。六册 OCR 976 页 →
5,605 候选 → **核心范围命中 1,219（36.2%）**，归属经例句验证 **1,169（95.9%）**，
复跑幂等。

- 6 册 PDF 是**纯位图扫描**（600 DPI CCITT G4，**零文本层**），第一册下另有
  .docx 文本版（不走 OCR）。
- OCR 实测可用：RapidOCR 8.5s/页，置信度 0.85–0.94，8 进程约 20 分钟。
- **归属解析是必须的一步**：象形体把**形近/音近词分组**，组头列多个词、其下
  只有一条详情块，行相邻会**静默错配**（`absent` 拿到了 `solitary` 的音标释义，
  `admire` 拿到了 `recognize` 的）。归属由**例句中出现哪个词**判定，判不出就
  标 `ownership_verified=false` 留人工复核（宁缺勿错）。
- 三道门控**均为「拒绝」而非启发式清洗**：同列 120px 内锚不到词行即丢
  （1,005 条，最大拒因）、词性白名单挡 OCR 形近（`u.` `adi.`）、归属须例句验证。
- 验证器覆盖 OCR 行末连字符（`atten- tion`）、丢空格（`Ihave faiththat`）、
  英语形态丢字母（`ride`→`riding`、`carry`→`carries`），否则会把正确归属
  误判为存疑。**但不做形近字容错** —— `physicai`/`yeliow` 必须留在待复核里，
  放宽会把真实错配一起掩盖。
- 独立表 + `ipa_ascii` 独立字段：象形音标是**粗 ASCII 转写**（`['erb]`），
  不是标准 IPA，与已有 2,757 条 ARPAbet 不能混用。释义**不覆盖**
  `meaning_cn`：象形给详尽义项，课标给精简义项，粒度不同而非冲突。
- 人工抽检 24 条已验证 + 6 条未验证：已验证全部正确；未验证的 6 条**全是 OCR
  形近字**（`physicai`/`yeliow`/`vaiuable`），无真实错配。
- 复核队列：`data/external/vocab_src/xingxing9000_review.json`。

⚠️ **这批填不满核心范围**：剩余 2,150 词（63.8%）象形9000 压根没收录 —— 它按
自身词表编，不是按我们的核心范围编。1,219 是**增量补充**，不是全覆盖。

**Aria 数字人全链路**（2026-07-31）：
- Phase 1 ✅：3D VRM 默认路径 + Director 骨骼指令 + 2D 代码全删
- Phase 2 ✅：viseme 口型（edge-tts WordBoundary → VRM blendshape）+ MIDI 手指弹琴
- Phase 3 ✅：自写 aria_brain.py 自主行为大脑（后端 asyncio + WebSocket）
- **Fay 大脑接管** ✅：Fay 框架部署为 Docker 容器（Qwen LLM + edge-tts + WebSocket 10002），
  替代自写 aria_brain。前端 `FayAria` 组件 = 照片驱动真人 + Fay WebSocket 接收音频/唇形/动作。
- 63 aria tests green, tsc+build clean。
- 容器：mneme-fay（Flask GUI :5001, WS human :10002, WS web :10003）

**✅ 收口项 7 部署完成（2026-10-04）**

commit `af0d35f` / `5316fb9` / `a18303a` / `66bc3a5`；部署走既有 `docker compose up -d`
路径，**未手工跑 alembic**（启动命令自带 `alembic upgrade head`，迁移自动进）。
活库 `alembic_version = e6f7a8b9c0d2`、`vocabulary_memory_nodes` 已建、
`/readiness` 200（database/migrations/storage 全 true）、`/mcp/*MemoryNode` 路由已上线、
未鉴权调用返回 401。全量 1751 passed / 14 skipped / cov 80.45%。

**✅ 「API 实际生成 1 个 MemoryNode」由失败转为通过** —— 这是收口项 7 唯一原本不过的
一步。根因**有四层**，前一层修完才露出下一层：

1. **模型名退役**：`.env` 的 `veya1.2-128K` 是网关注释写明的已退役别名。
2. **容器连不上宿主 loopback**：网关只 bind `127.0.0.1:8791` → 新增
   `scripts/veya_relay.py`（纯 stdlib，**只 bind docker bridge 172.22.0.1**，
   脚本 + systemd 单元双重拒绝 `0.0.0.0`，局域网/公网不可达）+ `systemd --user`
   单元 `veya-relay.service`（`systemctl --user disable --now` 可一键回滚）。
   按人决策**未改 Veya 自身 listener**。
3. **`docker-compose.override.yml` 硬编码遮蔽 `.env`** ← 「改了 .env 没生效」的真凶：
   override 优先级高于 `docker-compose.yml` 的 `${...}` 插值，容器里一直是退役别名 +
   连不上的地址。改为从 `.env` 插值，恢复单一来源。
4. **可用模型会漂移**：同一分钟内 `veya1.2` 一度「兜底失败」、稍后恢复。
   `VEYA_MODEL` 改为**逗号分隔按序回退名单**；回退必须**检查返回内容**（网关的故障是
   HTTP 200 + 正文错误串，只判状态码则回退永不触发）。

⚠️ **宿主侧附带坑**：`VEYA_BASE_URL` 改成 bridge 地址后不在默认 `no_proxy` 里 →
httpx 会走 `127.0.0.1:7890` 代理 → 502。且 **httpx 的 `NO_PROXY` 不支持 CIDR**
（curl 支持），必须写**字面 IP** `172.22.0.1`。容器内无 proxy 变量，不受影响。
生产实测：`/health/providers?deep=1` 由 `reachable=false, usable=false` → `true/true`；
容器内真实生成 `advice` → 核心画面「老医生把处方塞进病人手心」、answer=advice、
quality=1.0、0 条门禁失败、语境证据 `That's very good advice!`。

**✅ CME-P1.6 义项截断已修（派生，不落库）** + **✅ 加第 10 条门禁 `MEANING_AUTHORITY`**

`meaning_cn` 常只截 `canonical_meaning` 的首个义项 → 记忆画面照**冷门义项**生成
（`blind`→百叶窗、`wet`→雨天、`fine`→罚款）。修法是**读时纯函数**
（`services/vocab_senses.py`）：不建表不写库（完整义项本就在 canonical 里，建表只会
多一份会漂移的第二来源）；用 `pos` 列（默写表的**策展值**）选主义项。
**`meaning_cn` 本身不改写** —— 它是「教材原文可追溯」的载体；测试钉住 DB 原值不动。
音标守卫复用 P1.5 的唯一源（不挡会把 `[ˈtaɪt(ə)l` 当义项 —— `title` 就是这样）。

⚠️ **过程中踩到一次「变异没被抓住」**：把 `MEANING_AUTHORITY` 的第一支短路掉时
54 项测试全绿 —— 因为另两支（unusable / 无来源列）各自挡住了当时的用例，掩盖了
「tier 写着 canonical 但 gloss 为空」这个漏洞。补了该结构防御用例后才钉住。

**📉 加第 10 条门禁 + 义项选择后的同种子重测（100 词，可直接对比）**

| 指标 | 修前（9 门禁） | 修后（10 门禁） |
|---|---|---|
| verified | 89/100 | **73/100** |
| `HAS_ONE_CORE_IMAGE` 拒收 | 4 | **0** ← 我那个下限误杀修好了 |
| `MEANING_AUTHORITY` 拒收 | —（门禁不存在） | **16** |
| `FAMILY_TRACEABLE` 拒收 | 6 | 6 |
| 生成成功 / 调用错误 | 99 / 0 | 95 / 2 |

**通过率下降不是质量回归，是把一个静默漏洞变成了可见的计数。** 那 16 个词的
`canonical_meaning` 是**纯音标**（`[ˈdaɪət]`、`[ɪˈlektrɪk]`、`[kəˈmɪtmənt]`）、
`meaning_cn` 为空 —— 修前它们照样 `verified=true`，但卡片里的中文释义是**模型编的、
无教材出处**。第 10 条门禁正是为此而加，现在它们被如实拒收。

**可回收量已量化**：核心范围里「**有 NCE 真实句 + 无中文释义**」= **461 词**
（其中 459 的 canonical 就是纯音标），「无语境 + 无释义」= 315 词。
这 461 词**有真实语境句**，正好满足既有 `oprim._vocab_gloss_generate` 的契约
（「例句由语料库确定性抽取，不是 LLM 编的」）→ 走既有生成器补释义即可，
零编造、可复现。这是下一步最有价值的一步（`CME-P1.12`），能把大部分这 16 个拒收转成通过。

**📌 素材实测结论（用户已授权入库）**：`gdrive:英语优先/`
- **100句**（新东方）：99 句 / 1,127 去重词（「7000」是营销口径）→ 命中核心 2,761
  仅 492（17.8%），救到 695 无语境词只 31（4.5%）。**建议不接**：句中位 22 词、
  雅思语域，给中考学生是负收益。
- **OPD 牛津图解词典3rd**：⚠️ **我先前报的 36.3% 是含噪声的高估，已纠正为 13.4%。**
  换用正规解析器（`scripts/parse_opd_topic_anchors.py`，抽 `N. word` 编号词条 +
  主题面板标题）后：**1,906 词 / 129 个主题面板**，命中核心单词 **369（13.4%）**、
  救到 109 个无语境词、命中 99 个无释义词。之前那 36.3% 里混进了 `a`/`an`/`and`
  这类功能词（粗糙正则的产物），已加测试钉住真实口径。
  **结论翻转：不建 OPD 入库表。** 理由是它**解决不了义项对齐** ——
  义项问题最严重的 `blind`/`wet`/`fine`/`deer`/`credit`/`type` **一个都不在 OPD**
  （它是入门级图解词典，覆盖的是 bedroom/kitchen/bus stop 这类基础具体名词）；
  而它确实收录 `blind` 的形式是 **`mini-blinds`（主题 A Bedroom）** ——
  按它选义项会把 `blind` **钉死在「百叶窗」这个冷门义项上**，比现状更糟。
  解析器保留（是一次可复现的测量工具，且负面结论有用测试钉住）。

## 🚨 上游 LLM 全线失效（2026-10-04 完整诊断）—— 需充值/换 key，我无法从代码侧修复

`GET /v1/free-pool`（网关自带诊断端点）实测：**28 个已知上游只剩 2 个 active**。

| provider | 错误 | 性质 | 谁能修 |
|---|---|---|---|
| opencode-go 计量池 | HTTP **429** `GoUsageLimitError` | workspace **月度配额耗尽** | 充值/等下月 |
| opencode-go 大部分 `-free` | HTTP **403** Forbidden | **key 权限范围不足** | 换 key |
| `gmi-serving` | HTTP **402** Payment Required | **余额耗尽** | 充值 |
| `bai`（×4） | ConnectTimeout | 服务不可达 | 换供应商 |
| `nvidia-nim`（全部） | 超时 / 10ms 立即失败 | 别名与凭据均不可用 | 查 NIM key 轮换 |
| `openrouter` | 18 unhealthy / 2 healthy | 部分可用 | — |

逐一实测 `-free` 家族后：**只有 `opencode-go/space-bunny-free` 能回**（≈2s，且仍间歇失败），
其余 `big-pickle`/`nemotron-3.5-lightning-free`/`mimo-*`/`ling-*`/`muse-spark-*`/
`longcat-*`/`fledge-alpha-free` 全部 **403**。`.veya/model-state.json`（machine-maintained，
`updated_at 2026-09-26`）列了 33 个 healthy，但那是 8 天前的快照，与实测不符 ——
**该文件不能当现状用**。

### 已做的（代码侧能做的都做了）

1. **`VEYA_MODEL` 名单回退**（`VeyaTextCaller`）：按序尝试、**检查返回内容**才判定失败
   （网关的故障是 HTTP 200 + 正文错误串）、全失败时抛异常并带每个候选的原因。
2. **`/health/providers?deep=1` 现在报 `llm_model_serving`** —— 单点可用时这是最关键的
   一条信息（此前只能说「不可用」，说不出是谁在服务）。生产实测：
   `llm_reachable=true, llm_usable=true, llm_model_serving=opencode-go/space-bunny-free`。
3. **LLM 不可用时快速失败并说清缺什么**：新增 `services.errors.LlmUnavailableError`
   （503），`/mcp/GenerateMemoryNode` 映射成 503 + 候选名单 + 处置指引，
   不再抛栈里的 `LLMOprimError` 让人以为是代码 bug。503 与 500 处置完全不同。
4. `.env` 的 `VEYA_MODEL` 改为以实测可用的模型打头。

### 我做不了的（需要你）

按性价比排序：

1. **配 `QWEN_API_KEY`** —— 最快最省。DashScope 有便宜额度，且国内直连，
   `.env` 里 `MNEME_LLM=qwen` 已接好（`configure_llm_providers` 的 qwen 分支现成）。
   当前 `QWEN_API_KEY` 为空、`DASHSCOPE_API_KEY` 未设，这是**唯一一条代码侧已就绪、
   只差一个 key** 的路。
2. **给 gmi-serving 充值**（402）。
3. **换 opencode-go 的 key**（403 权限范围）或等月度配额重置（429）。
4. 恢复后只需把更可靠的模型加到 `VEYA_MODEL` 名单**前面**，无需改代码。

⚠️ 在恢复之前，**记忆引擎的批量生成基本不可用**（`CME-P1.12` 的 453 词补齐因此只完成 8）。
单点 `space-bunny-free` 不足以支撑批量作业。

## 📍 「用本地的 veya-nim」—— 查证结论：本机没有可用的本地 NIM，本地 LLM 也不可用

按要求查了「本地 veya-nim」，结论是**这条路走不通**，证据如下（全部实测，非推断）。

### 1. 没有本地 NIM

- 网关里 `veya-nim` / `veya-*-nv` 这 5 个别名代理的是
  **`https://integrate.api.nvidia.com/v1/chat/completions`** —— NVIDIA **云端**，
  不是本地（`veya/obase/llm.py:250`）。
- **本机没有 NIM 凭据**：`veya-backend` 的 `NVIDIA_NIM_API_KEY=` **为空**；
  它指向的 `VEYA_NVIDIA_NIM_KEYS_FILE=/home/soffy/projects/stratum/aii/.pipeline_keys.json`
  里是 **stratum/aii 的其它 pipeline key**（`econ`/`math_en`/`advmath_*`/`learning`…），
  **不是 NIM key**。
- **mneme 实际对话的那个网关进程**（宿主 pid 2983）**完全没有** `NIM_KEY_POOL` /
  `NIM_KEYS_FILE` / `NIM_API_KEY` 环境变量 —— 这是所有 `-nv` 别名全挂的直接原因。
- 本地**无** NIM / vLLM / triton 镜像（`docker images` 无命中），也没有 NIM 容器。

### 2. 本地确实有真模型，但**只有 CPU，且慢到不可用**

Ollama 在跑 `qwen2.5:7b`（4.7GB）、`qwen2.5vl:3b`、`qwen2.5:0.5b` —— 是真模型不是
mock，而且 `OllamaCaller` 代码路径现成（其 docstring 原文就是「如 DeepSeek 余额不足时」）。
但实测：

| 模型 | 实测 | 结论 |
|---|---|---|
| `qwen2.5:7b` | 38 tok / **208s**、51 tok / **199s**（≈4 tok/s，热机同样慢） | 记忆契约每词需 400~800 tok → **20~70 分钟/词**，批量与交互都不可行 |
| `qwen2.5:0.5b` | 28s，但让它「数到20」输出**「四十二」** | 连基本指令都做不到，质量不足以用于教学内容 |

### 3. 根因是 GPU 掉卡（硬件层）

`/dev/nvidia0` 节点存在、驱动已加载（595.91.07，RTX 3080），但：

    $ nvidia-smi -L
    Unable to determine the device handle for gpu 0000:05:00.0: Unknown Error
    No devices were found

`/proc/driver/nvidia/gpus/0000:05:00.0/power` 显示 `Runtime D3 status: Disabled by default`
—— 典型的「掉卡」状态，于是 Ollama 全部 **CPU-only**（`/api/ps` 的 `size_vram: 0`）。

**经典修复（我没有执行 —— 生产机 + 需 root + 会打断 GPU 上的 echomimic 等负载）**：

```bash
rmmod nvidia_uvm && modprobe nvidia_uvm          # 最小改动，先试这个
# 不行再：rmmod nvidia_uvm nvidia_drm nvidia_modeset nvidia && modprobe nvidia
nvidia-smi -L                                     # 验证
```

GPU 恢复后：Ollama 会自动 GPU offload，`qwen2.5:7b` 速度提升约两个数量级。

### 4. 已做好的准备工作（GPU 一恢复就能一键切换）

- 新增 `systemd --user` 单元 **`ollama-relay.service`**（桥接 `172.22.0.1:11435`
  → `127.0.0.1:11434`，与 `veya-relay` 同构，只绑 bridge 不对外）。
  已验证 **容器 → relay → ollama：HTTP 200**，看得到三个模型。
- `.env` 里留了注释：GPU 恢复后把 `OLLAMA_BASE_URL` 改成 relay 地址、
  `MNEME_LLM=ollama` 即可，**无需改代码**。
- **当前不切**：`MNEME_LLM` 保持 `veya`（`space-bunny-free` 至少能回），
  切到 ollama 只会把 2s 的调用变成 200s 的超时。

## ✅ 近期完成（倒序，仅列最近一批）

- **Blueprint 仓内实现收口**（2026-08-25）：Event v2 双写默认部署开关、fail-closed
  历史回填脚本、xAPI/Caliper/CASE 导出适配器、P2/P3 默认脱敏、`X-Trace-Id` 与隐私安全
  请求观测、Studio 生产构建门已完成；新增 ADR-0005 与互操作/观测契约测试。完整质量门
  `1229 passed / 14 skipped / 82.23%` 通过。真实学生实验、因果效果和商业指标仍不宣称完成。
- **安全与治理收口**（2026-08-25）：Next 16.3.2/Mermaid 11.17.1、DOMPurify 3.4.14、
  nanoid 3.3.18 已锁定，npm audit 为 0；新增 [CONTRIBUTING.md](CONTRIBUTING.md)、
  [docs/GOVERNANCE.md](docs/GOVERNANCE.md)，并把前端 audit 加入 GitHub quality workflow。
- **Memory claims 列表**（2026-08-25）：新增 `/v2/memory/claims`，只读返回带 evidence_count
  的证据绑定 claim，并沿用学生/家长过程数据授权与 P2/P3 脱敏。
- **判分与试验验收契约**（2026-08-25）：新增 `/health/grading` 聚合确定性覆盖/降级/分歧
  指标；数学判分返回内部路径分类但不改变 bool API；`teaching_engine_v1` 增加冻结的
  protocol 元数据与 [PILOT_PROTOCOL.md](docs/PILOT_PROTOCOL.md)，仍保持 protocol_only。
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
- **质量数字可复现**（2026-08-16）：宿主 pytest 经 `tests/db_guard.py` 钉 `mneme_test` + `.env` 现口令（fail-closed，禁打活库 `mneme`）；ruff 钉 E4/E7/E9/F 并清零；`check.sh` 加 smoke（44）+ `vendor_edu_closure --check`；L1 单源自检改扫 routers；`PgStore.get_or_create(for_update=)` 写路径显式加锁。全量 1095/29/6/2、cov 83%。未写 `DATABASE_URL` 进 `.env`（compose 活库用 `/mneme`）。
- **GH-4 chat 断链修复**（2026-08-24）：采用方案 B，新增无 oservi 依赖的 `LocalAgenticLoop`；chat 保留 intent 分流、persona、MCP HTTP 工具和学生 token 转发。Docker/compose 已把 `packages/mneme-agent` 纳入运行时 PYTHONPATH，并移除 oservi dev 挂载；未重启活容器。
- **本机 Veya LLM/VLM 接入并部署**（2026-08-24）：`MNEME_LLM=veya` 默认使用文本
  `veya1.2-128K`、视觉 `veya1.2-vl`；聊天、出题、定性判定、教材问答和 Aria
  Director 均已接到该 provider。宿主 `127.0.0.1:8791` 文本/视觉探针均返回 200；
  `api/worker/beat` 已重建，API `/health` healthy，线上 provider 状态为非 mock 的
  `VeyaTextCaller/VeyaVLCaller`。
- **Blueprint P1–P3 + Evaluation groundwork**（2026-08-24）：Evidence Graph + Memory v2 API、
  Learner State 2.0、统一 Policy Engine、Evaluation OS 已落代码；ADR-0002、迁移、
  hard-delete 清单和契约测试同步补齐。全量双写/真实 far-transfer/RCT 仍待 pilot。
- **Blueprint P4 Tutor Guardrails**（2026-08-25）：ADR-0003 与纯确定性
  `tutor_control` 契约已落地；教学策略接口返回控制决策，Socratic/Agent 输出默认
  经过答案片段和显式答案标记闸门；独立模式与 5–10 次 no-AI 检查 cadence 已可重放。
  真实 no-AI transfer 不以代码测试代替，仍待独立检索事件与 delayed holdout。
- **Blueprint P5 Evaluation OS v2 groundwork**（2026-08-25）：ADR-0004、评估信号
  字段和迁移 `d2e3f4a5b6c7` 已完成；no-AI transfer 只认显式独立标记，delayed gain
  按同学生配对，time split 同时防发生时间/接收时间未来泄漏。迁移仅完成 offline SQL
  验证，尚未应用活库。
- **Blueprint P5 ModelRegistry**（2026-08-25）：metadata-only 注册表、时间窗校验、
  shadow/candidate/production/retired 生命周期和 admin-only API 已完成；迁移
  `e3f4a5b6c7d8` 仅完成 offline SQL 验证，尚未应用活库。
- **Blueprint P5 promotion evidence gate**（2026-08-25）：ModelRegistry 进入
  `candidate/production` 前必须提交完整 `shadow-evaluation/v1` 报告，包含同样本 baseline、
  四项安全 guardrail、AUC/log-loss/Brier/ECE/calibration slope 和至少 30 个 eval events；
  缺证据、未来/非 shadow 报告或模型 ID 不匹配均拒绝。24 项 ModelRegistry/路由/影子契约
  测试、Ruff、Mypy 已通过；不自动晋升，活库迁移仍未执行。
- **Blueprint P5 registry-aligned shadow comparison**（2026-08-25）：新增纯计算
  `services/shadow_evaluation.py`，对候选/基线使用相同 eval event keys，拒绝越窗、
  未来发生/接收时间，报告 AUC、log-loss、Brier、ECE 与方向明确差值；明确 shadow-only、
  不写库、不控制学习路径、不宣称因果 uplift；`shadow_registry_eval.py` 可从 JSONL
  快照离线复跑；`evaluation_service` 新增只读 production BKT+FSRS baseline 重放适配器。
  `candidate_shadow_predictions` 冻结了候选预测器不得读取当前真实结果的接入契约。
  新增无 sklearn 的 calibration slope 与距理想斜率 1 的比较；19 项影子/重放契约测试、
  Ruff、Mypy 已通过；具体 DKT/Hybrid predictor、pilot/A-B
  和活库迁移仍未启动。
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

- **生产发布**：GH-4 + Veya 代码已按确认重建 `mneme-api-1`、`mneme-worker-1`、
  `mneme-beat-1`；启动命令同时修复了 vendor 优先路径，API `/health` 已 healthy。
- **Pilot smoke 尚未重跑（2026-08-24）**：本机 Veya 文本/视觉 provider 探针已通过，
  但 Memory Graph 新迁移尚未应用到活库；需要单独发布后，再隔离到 `mneme_test` 重跑
  pilot smoke 与 `/v2` 端点验证。
- **阿里云短信报备**：完成前勿开公网注册（当前邮箱注册可用）
- **MNEME_ENV=prod**：设 prod 后 `_assert_prod_safety` 强制真实验证通道（SMS aliyun 或 SMTP 邮箱二选一）
- **PA-2 真实 webhook**：需提供 WeCom/Feishu 群 webhook URL 才能验证
- **真实学生数据**：0.77 AUC 验证 / FSRS 权重拟合启用 / FIRe 上线 A/B 均以此为前提
- **Tutor 真实效果**：当前已完成控制契约与泄漏红线，尚未有真人 no-AI transfer、
  answer-dependency 或 D7/D30 delayed holdout 样本，不能据此宣称学习增益
- **Evaluation OS v2 发布**：`d2e3f4a5b6c7` 尚未应用到活库；需要发布后重新跑
  pilot smoke，再积累独立检索和 delayed baseline/holdout 数据
- **ModelRegistry 发布**：`e3f4a5b6c7d8` 尚未应用到活库；真实 shadow→A/B→production
  切换仍需 admin 发布流程和实验数据
- **仓库许可证**：尚未选定法律许可证；不能由 agent 擅自添加 SPDX/许可证文本。
- **U.21 课标标注量产**：需更强模型（当前 qwen2.5vl:7b 错误率 ~5-8%，骨架可接受但量产不够）
- **ship-gate 四条**：真人 pilot / KU→chunk 精度 / Z 回测 / 测试=生产 CI 收敛
- **Vocab Enrichment 剩余 ~14,574 词无语境源**：9,809 词可从 `timed_sentences`
  确定性挖例句；其余需决定扩语料 / 降级为无义项释义 / 暂不覆盖。**不能**用无上下文
  的 LLM 猜义（`bank` 这类多义词会直接出错）。
- **Vocab 图片 provider 法务**：Unsplash/Pixabay 等是否允许「持久化 URL + 面向
  未成年人产品展示」需逐 provider 审 license；`license` 列不等于授权。
- **CORE_EXAM_VOCAB_SCOPE 取 ∪ 还是 ∩**：spec 公式写 ∪（实测 20,173），目标数字
  是 ∩（3,369）。二者差 6 倍，需人明确后才能固化范围脚本。
- **`vendor/oprim` 无法扩展**（阻塞 spec P0.4/P0.5）：`_vocab_gloss_generate.py` 已进
  `3o-replication-lock.json`（`scripts/check.sh` 会卡），且 `/data/soffy/projects/platform`
  **不是 git 仓库**，AGENTS.md 要求的「canonical 仓提交 → sync_3o_from_platform」路径
  当前不可执行。故 senses/confidence 版生成器只能新写（`scripts/`），不能改 vendor。

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

---

## 词汇记忆引擎 V2 spec 完成度审核 + 补齐（2026-10-05）

审核对象：`单词深度记忆引擎 V2`（7 个连接 / 事实准确性 / 频率 / 输出结构 /
主动回忆 / 长期卡 / 质量控制 / 特殊规则）。

### 审核结论

**做得比 spec 强**：§三 事实准确性（契约里**根本没有 etymology 字段** →
物理上不可能编造词源；`etymology_status` 三档；`disputed` 不进展示面）、
§八 质量控制（spec 是人工自检清单，实现是 **11 道可执行门禁** + 变异验证）。

**最实质的缺口（已修）**：spec §二 的 7 个连接里，**3 个「生成了、存了、
API 也返回，但不在 `LAYER_ORDER` 里」** —— `sound_hook` / `spelling_hook` /
`family_network`，学生永远看不到，而 spec 明说要形成
「单词→声音→画面→故事→词根→词族→含义」这条链。`ac0c5a2` 已补齐，
并因此把层数从 4 增到 8。

**完全未实现**：⚠️易混点（`CONFUSABLES_GROUNDED` 已补，见下）、🎯意义演化、
🧩词缀价值+高频例词、🧩最终记忆压缩 5 项、频率等级 🔴🔵⚪（**有意否决**：
`frequency_band` 实测核心范围内恒等于 5，无区分度）、§九「用户说记不住/易混
→ 提升为最高优先级」（`learner_confused_with` 已补）、「模板是工具不是格式牢笼」
的弹性输出。

### 已补：⚠️易混词（第 11 道门禁）

**问题与 `FAMILY_TRACEABLE` 同源**：模型不知道库里有哪些词，会编「其实不混淆」
的对照词，而学生会把那条规则记一辈子。

- 候选由**确定性判据**算出：长度差 ≤1 且**编辑距离 ≤2**。实测
  `affect→effect`、`adapt→adopt`、`desert→dessert` 全部命中；`abandon`/`wet`
  正确返回空。
- 门禁 `CONFUSABLES_GROUNDED` **只查「给出的都查得到」，不查「该有的都找到了」**
  —— 判据只有形近，音近/近义抓不到，拿缺漏去拒收一个可能有价值的节点是本末倒置。
- 空候选是合法结果：prompt 明确要求输出 `[]`，**宁可空也不硬凑**。
- `learner_confused_with`（spec §九）进 `llm_entry`，prompt 要求排在易混清单
  第一位，且**不受候选限制**（那是学生自己的经验）。

### 本轮撞到的三个工程坑（都已修 + 都有测试钉住）

1. **`_upsert_memory_node` 漏 `json.dumps`**：新增 JSONB 列时不在那里加一行，
   导入期不报错，等到真落库才抛 asyncpg `'list' object has no attribute 'encode'`。
2. **`EXPECTED_MIGRATION_HEAD` 忘了改** → alembic 成功而 `/readiness` 503（见上）。
3. **门禁里 `allowed` 直接 `str(dict)`**：候选是 `{"word": ...}`，
   `str()` 得到 `"{'word': 'effect'}"`，于是**每个**候选都判不通过。
   测试没先跑全就会漏。

### 教辅 PDF 资源实测（2026-10-05）

`gdrive:K12教育/{小学,初中,其他}` 英语学科 198/120/52 个文件（17 GB）+
`gdrive:考研成人/英语词汇书`。**先测文本层再谈用量**，结论：

| 资源 | 文本层 | 实测价值 |
|---|---|---|
| **21 个《21天搞定中考英语1600词》PDF**（2.2 MiB 合计） | **有** | 搭配 **+162 条**（已入库）；pos 仅 +29 |
| 6 册象形9000 PDF（216 MB） | **0** | 只有那份 1.9 MB docx 可用 |
| OPD 中英文版（1.83 GB） | **0** | 不可用 |
| `1600单词默写（音标、词性、中文对照）.pdf` | **0** | 名字写着「词性」却是扫描件 |
| 其余 370 个教辅/试卷（17 GB） | 未测 | **不建议**逐本下 —— 期望收益低 |

`vocabulary_collections` 66 → **228 行**（`scripts/import_collocations_from_k12.py`，
确定性、零 LLM、`ON CONFLICT DO NOTHING` 幂等）。这些搭配经 `word_origin` 层
**直接渲染给学生**（spec §五「📌实用搭配」），是该层最薄的一块。

**已知残留风险**：源书有个别**翻译错误**（`a lot of 大多数`，实为「许多」），
确定性方法修不了，只能靠 20 词人工审查抓。

### 100 词重测结果（seed 20261004，11 门禁，`Agents-A1`，dry-run）

生成成功 88（3 词未满足契约、9 次调用失败）→ **verified 87**。
quality 均值 **0.999**（87/88 满分，最低 0.91）。失败明细：
**内容拒收仅 1 次**（`HAS_RECALL_HOOK`），其余 9 次全是端点抖动。

| | 修复前 | 本次 |
|---|---|---|
| 通过 | 77/94 = 82% | **87/100 = 87%** |
| `FAMILY_TRACEABLE` 拒收 | 6 | **0** |
| 调用失败 | 10 | 9 |

**两处据实测数据收紧**（本条 commit）：

1. `HAS_RECALL_HOOK` 只认 `？`/`?` 结尾 → 漏问号的好问题被拒（`spread`
   的「把画卷向两边拉展的动作叫什么」）。**门禁在测标点格式，不是在测记忆质量**
   —— 与 `HAS_ONE_CORE_IMAGE` 下限 8（4/4 误杀）是同一类错误，第二次出现。
   改为「问号 **或含**疑问词」。放弃只看结尾的写法：实测「这是哪一步」
   「这是什么步骤」都是问句但结尾是「步」「骤」。
2. 易混候选 `_CONFUSABLE_MAX_EDIT` **2 → 1**。依据是那轮 115 条易混对按距离
   拆开：距离=1 的实测 **100% 是真易混**（`chance/change`、`honour/honor`、
   `valley/alley`、`gold/cold`、`beer/bee`、`prevent/present`、`shake/shade`），
   距离≥2 的多数是噪声（`offer/coffee`、`boss/Boys`、`Paris/parish`、
   `influence/influenza`）。收紧后剩 63 条，其中**同词变形噪声 6 条**
   （`effort/efforts`、`drug/drugs`…）→ **精度约 90%**。

### 诚实边界

- 易混候选判据**只有形近**：音近（`affect`/`effect` 靠 -ect 同尾侥幸命中）、
  同义近义、跨词性混淆**抓不到**。
- `vocabulary_memory_nodes` **仍 0 行**；P0 **仍 NOT QUALIFIED**（需
  10/11 门禁下的 100 词重跑 + 20 词人工审查）。
