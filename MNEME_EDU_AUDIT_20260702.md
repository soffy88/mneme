# Mneme（善学记）教育专家全面审计 · 2026-07-02（v2 修正版）

> 视角：国内外教育专家（学习科学 + 教育产品）。判据："**每个功能模块是否可用、好用、学生愿意用**"。
> 方法：6 路并行代码级审查——① 6-30 审计 15 条整改逐条核验（每条 `文件:行`）；② 后端 services/tasks 全模块盘点；③ **善学记真前端 `mneme-web`** 全页面学生体验审查（tsc 零错验证）；④ 容器内实跑质量门（pytest/ruff/mypy）；⑤ 2025-2026 国内外标杆网络调研。
> **v2 说明**：v1 误将 `mneme/frontend`（废弃旧版"学鉴"Vite SPA）当作产品前端审计，前端结论全部作废并按 `/data/soffy/projects/mneme-web` 重审；旧目录已标记 DEPRECATED（`frontend/README.md`），CLAUDE.md 品牌名已更正。mneme-web 经核实是旧前端功能的严格超集与事实继任者。
> 前一次审计：`MNEME_EDU_AUDIT_20260630.md`。

---

## 0. 总评（一段话）

**善学记的数学主闭环已经"可用、好用、学生会愿意用"：选题→凭记忆作答→秒判→错题入本→答错一键问AI（只引导不给答案）→到期复习过检索门（看答案=没记住），这条链路真实、快速、反馈即时，且学习科学红线（主动回忆、检索门、交错、努力收益、防泄答、防伪报）在前后端都有真实现和绿色测试。** 6-30 审计后的整改是实打实的：数据飞轮（BKT 每日校准 + FSRS 每周 per-student 拟合 + AUC 每周实证）三条 celery 链真接通，203 个测试全绿（含全部红线/合规测试）。当前真正拦在"发布/增长"面前的是四件事：**后端核心写接口无鉴权（档案可伪造）、家长链路完全断裂（无注册 UI/无邀请码展示/无入口，付费与监督场景归零）、中文输入法 Enter 误发送污染所有对话体验、非数学学科纵深不足**。修复前两项工作量小、回报极高。

---

## 1. 6-30 审计 15 条整改核验（宣称 vs 真实）

内核/后端侧证据来自 mneme 仓库，前端侧已按 mneme-web 更正。

| 条目 | 当前状态 | 关键证据 | 残留 |
|---|---|---|---|
| P0-1 试卷批改接回内核 | 🟡 部分 | `vendor/oskill/paper_grading.py:41-57` judge_answer 确定性优先，unsure 才落 LLM | 修法偏离目标：靠 OCR 出的 correct_answer 比对，`solve_*` 在试卷路径仍零调用；correct_answer 本身无内核复核 |
| P0-2 KU 录入校验门 | 🟡 部分 | `services/models.py:472-475` 溯源列；`tasks/textbook_tasks.py:43-52`→`ku_ingest_service.py:84-101` 过门；`scripts/backfill_ku_provenance.py` 存量回填 | ① 批量脚本（`extract_physics_ku_batch.py:439` 等）仍裸 INSERT 绕门；② **verified 列无任何学习路径消费**，可信分离只是数据标记 |
| P0-3 苏格拉底含变量步拦截 | ✅ 已修 | `socratic_service.py:221-281` `_verify_assignments` sympy 代回前序方程，x²=4⇒x=3 被拦；`test_socratic_step_verify.py` 绿 | 孤立多变量等式刻意不拦（宁不拦不误伤，可接受） |
| P0-4 复习检索门 | ✅ 已修（前后端） | 后端 `review_service.py:68-79` due 只发题面、`:110-126` reveal→Again；前端 `mneme-web review/page.tsx` 调 `/v1/review/due\|submit\|reveal`（`api-client.ts:234-243`），揭答显示"👀 看了答案 · 已按「没记住」重排复习"（:138），无字段断链 | v1 报告的"揭答空白"是旧前端问题，真前端不存在 |
| P1-1 FSRS/BKT 飞轮 | ✅ 已修 | `tasks/celery_app.py:22-37` 三 beat；`calibration_service.py:31-106` 写 calibrated_from_n→`vendor/obase/prior_provider.py:21` 消费；`fsrs_optimize_service.py:153-186` scipy 拟合→`cognitive_service.py:158-159` 热路径加载 | 闭环全接通，测试绿。评估结果只进日志不落表 |
| P1-2 集中练习≠间隔检索 | ✅ 已修 | `vendor/oskill/cognitive_state.py:34-38` 去抖；`cognitive_service.py:32` 20h 启用 | — |
| P1-3 教材上传触发抽取 | ✅ 已修 | `main.py:1857-1865`→`textbook_tasks.py:42-52` 抽取+过门 | 仅平台教材；学生自传 skip（防污染，by design） |
| P1-4 日计划交错 | 🟡 部分 | daily_plan ✅ `daily_plan_service.py:249-286` 过 interleave_select | daily_mission 🔴 `daily_mission_workflow.py:88` 仍直接拼接无异 KC 约束；前端复习页为顺序 due 列表 |
| P1-5 outcome 防伪报 | ✅ 已修 | `socratic_service.py:338-390` 服务端 judge_answer 核实，未核实 success 降级 partial | 无答案钥匙时仍信客户端（注释已承认） |
| P1-6 非数学练习闭环 | 🟡 部分 | 后端通道学科无关（`main.py:1016-1064,1179-1240`）；mneme-web 练习页有学科快切（`practice/page.tsx:55-67`），空题库时诚实降级 | 缺的是**非数学题库内容**与判分适配，不是架构/UI；物理仍只有受力分析对话 |
| P2 hint-ramp | 🟡 | `socratic_session_workflow.py:111-120` 轮次型升级 | stuck-count 版仍未进主链 |
| P2 对话历史回放 | ✅ | `socratic_service.py:160-178` O(1) 增量 | — |
| P2 到期语义统一 | ✅ | `vendor/oprim/due_compute.py:22-30` 单源，三路径消费 | — |
| P2 前端内核图示 | 🟡 实现真、入口死 | mneme-web 已装 Mafs 0.18.8 且真用（`KernelPlot.tsx`）；lesson 页渲染内核 SVG/Mafs+同源自检警示（`lesson/page.tsx:63-81`） | **`/lesson` 是孤儿页**：全仓无任何入口链接到它——"内核兜图"护城河做了但学生看不到 |
| P2 P(L) 下界 clip | ✅ | `vendor/oprim/_cognitive.py:22-23,84-86` | — |

**小计：9 ✅ / 6 🟡 / 0 🔴。** 内核与后端整改真实且有测试；前端（善学记）比 v1 误判的旧前端先进一代。
vendored 内核与 platform/3O `feat/edu-audit-fixes` tip 逐字节一致；启动自检（`main.py:124-129`）防静默回退。

---

## 2. 功能模块完成度全景

### 2.1 学科 × 学习闭环矩阵（后端∣前端=mneme-web）

| 学科 | 输入 | 讲解/引导 | 练习判分 | BKT/FSRS | 复习 | 元认知 |
|---|---|---|---|---|---|---|
| 数学 | ✅∣✅ 拍卷/题库/教材阅读器 | ✅∣✅ 苏格拉底（嵌入答错时机）+lesson 同源自检（孤儿页） | ✅∣✅ **真闭环：秒判+错题入本+问AI** | ✅∣✅ | ✅∣✅ 检索门完整（看答案=Again） | ✅∣🟡 掌握环/惰性知识/努力看板真；**JOL 无采集通道，校准卡永远空** |
| 物理 | 🟡 贴文本 | ✅ 受力分析引导 | 🔴 无题库内容（UI 通道已备） | 🔴 不更新 | 🔴 无 | 🟡 |
| 语文 | 🟡 贴文本 | ✅ 阅读引导+作文 rubric | 🔴（静态成语/文言内容页） | 🔴 | 🔴 | 🟡 |
| 英语 | 🟡 | ✅ 阅读引导；口语页评分为"示例"占位（诚实标注） | 🟡 单词 SRS 为本地静态 | 🔴 | 🔴 | 🟡 |

后端形态 = "数学单科全闭环 + 三科对话式外挂"；非数学缺的是**题库内容**与认知接线，不是架构。

### 2.2 后端模块（services/ + tasks/，75 条路由）

✅ 完整可用：auth（含 <14 岁监护人同意红线 + prod 密钥闸门）、cognitive、daily_plan、mission、review、socratic（红线最厚）、textbook_extract、ku_ingest、calibration、fsrs_optimize、evaluation、kernel_selfcheck、anon、seed、storage、paper/textbook/三条 beat celery 任务。
🟡 部分：physics/reading_guide/speaking（对话真、不接认知状态；ASR/TTS 无条件 Mock）、alert（5 类预警逻辑真但**无定时触发**，家长手动 POST 才响）、sms（阿里云 provider 是 NotImplementedError 框架，生产短信未通——连带登录页"验证码固定 123456"公开万能码风险）、providers（启动期择一降级，非运行时故障转移；服务层不聚合 cost）、instant_solve（后端真、无 VLM key 时 Mock 返空；**前端未接**）。

### 2.3 前端 = 善学记 mneme-web（Next.js App Router PWA，tsc 零错，54 个 API 路径与后端逐一比对无断链）

✅ 好用：`/home`（冷启动引导卡+今日目标+到期复习+全科任务全部可点）、`/practice` 选题（学科快切/记住上次/按学段分组）、`/subjects/math/practice` **做题真闭环**（进度条/检索提示/秒判/解析/答错问AI/离线入队）、`/review` 检索门复习、`/error-journal`（错因分布/答案对比/问问AI/举一反三）、`/mastery`（KC 人名化+掌握环+惰性知识）、`/curve`、`/upload` 拍卷、`/library`+`/reader`（PDF/EPUB+高亮笔记+KU 面板拉苏格拉底）。
🟡：`/socratic`（SSE 流式真、但 IME Enter 误发送；endSocratic 从未调用）、`/essay`（真接口，年级默认"高三"与初二用户错位）、四科 hub 子页多为本地静态内容、`/parent/*`（页面真但新家长进不来）。
🔴：`/lesson` 孤儿页（实现完整无入口）、`/speaking`（评分"示例"占位，价值≈0）、家长注册（`registerParent` 定义零调用，提交 4958fc8 宣称"家长注册"经 `git show --stat` 核实**未包含注册 UI**——宣称与实现不符）。
PWA：manifest+手写 sw.js（策略合理）+localStorage 离线提交队列真实现；缺 PNG/maskable 图标（iOS 主屏残缺）、background sync。死重：Three.js 三个包装了零使用。

### 2.4 质量门实证（容器内实跑）

- **pytest：203 passed / 3 skipped / 0 failed，覆盖率 70.6%（gate 60%）**。全部红线测试绿：合规（13 岁无监护→422、软删后不可登录）、苏格拉底诱导不泄露、P(L) 边界、交错相邻异 KC、确定性优先、检索门。前端 mneme-web `tsc --noEmit` 零错。
- ruff 1347 错 / mypy 606 错——**99% 来自 vendor/ 未被 lint 配置排除**（vendor 还混入量化交易/视频等非教育域代码）；第一方仅 ruff 1 错、mypy 11 错。
- mypy 的 11 个第一方错误（fsrs `parameters` 等"不存在"）与运行时矛盾（测试绿、vendor 里参数真实存在）→ **mypy 解析到了非 vendor 旧内核副本，环境存在内核双源**；运行时由启动自检兜底，但类型检查形同虚设。
- `scripts/check.sh` 依赖宿主 `.venv`（不存在），一条命令的质量门在宿主跑不通；实际环境在 docker（5 服务健康，alembic 到 head）。
- **全新库一键起已修复**（9ac0adc），但 KU（原 12573 条）与公共题库**不在迁移/种子里**，全新部署两表为 0——练习与知识点页面会是空的。
- vendor/ 内核自身零测试；CLAUDE.md 要求的 `test_*_single_source` 单源守卫测试不存在。

---

## 3. 标杆对标（2025-2026 实时调研）

| 能力域 | 标杆最新状态 | 善学记现状 | 差距 |
|---|---|---|---|
| 间隔重复 | Anki/RemNote 已 FSRS-6（21 参数、w20 个性化遗忘曲线、同日复习建模、per-user optimizer + simulator 产品化）；FSRS-7 已出 benchmark（暂不必追） | ✅ 真 py-fsrs + **per-student scipy 拟合已接通** | 核对 py-fsrs 版本是否 ≥6（API 变更影响 R 取值路径）；simulator 未进调度变更守卫 |
| 知识图谱×复习 | **Math Academy FIRe**：综合题成功复习按比例回写全部前置主题日程；30-45min 诊断定位知识前沿；连对 2 题才前进 + 每 150 XP 限时小测 | 有 KC 前置图 + BKT，复习与图谱不融合；无掌握门槛、无周期小测 | FIRe 思路可直接嫁接（命中多 KC 的题按权重回写各 KC 卡片）；缺强制检索检查点 |
| 苏格拉底辅导 | Khanmigo 2025 重建：辅导**嵌入做错/卡壳时机**；锚定已审校内容；graduated hints；教师在环 | ✅ 扣题首问+sympy 拦截+防伪报，**且入口已嵌入答错时机（练习/复习/错题本三处）**——机制上已对齐 | hint-ramp 是轮次型非卡壳型；IME bug 污染体验 |
| 批改可信 | 松鼠AI"稿纸解题过程识别"（定位错误步骤）；国内批改准确率均为厂商口径 | verify_step + careless/dontknow 分类是同问题更强解法 | 试卷路径 solve_* 零调用、OCR 答案无复核——**可宣传的差异化没做完** |
| 错题闭环 | 豆包爱学：批改→收录→遗忘曲线复习→**同 KC 变式推荐→一键打印** | 前三步齐 + 错题本"举一反三"已有 | 无打印/导出（国内家长刚需） |
| 动机 | Duolingo 2025 弃 Hearts 改 Energy（奖励正确、连对返还）；streak 7 天→留存 3.6×；Math Academy XP=努力分钟数抗刷题 | 有 streak/成就/努力看板，无系统激励循环 | 刻意低优可接受；若做，采用"连对返还/努力货币化"，不做惩罚制 |
| 个性化调度 | Duolingo BirdBrain V2（IRT 同时更新题目难度+学生能力） | ✅ IRT 难度透传 + per-student FSRS 已接 | BKT 先验校准按 KC×题型群体，未按学生（可接受的下一步） |

**对标结论**：调度个性化与"辅导嵌入做错时机"两项 6-30 差距已实质追平；元认知反馈面（惰性知识/努力错觉/永久档案曲线）仍是标杆都没有的差异点，但其中 **JOL 校准因前端无采集通道而空转**。落后标杆的集中在产品化末端：lesson 内核图示无入口、错题不能打印、非数学无纵深。

---

## 4. 差距与优化清单（v2 重排）

P0 = 发布/增长阻断级；P1 = 核心学习能力/可信度；P2 = 深化与体验。

### P0（增长/安全阻断，均为小工作量高回报）

| # | 条目 | 现状 | 修法 | 不修后果 |
|---|---|---|---|---|
| 1 | **后端核心写接口无鉴权** | `POST /v1/interaction`(main.py:293)、`/v1/socratic/start`(:867)、`/v1/practice/submit`(:1179)、`/v1/papers/upload`(:611)、`/v1/missions/*/complete`(:747) 匿名可调，student_id 随便填 | 全部挂 JWT + require_student_access（家长端已有同款防护，照抄） | 任何人可伪造任意学生学习记录——**永久档案护城河失信 + 未成年人数据安全事故** |
| 2 | **家长链路断裂**（mneme-web） | `registerParent` 定义零调用（`api-client.ts:73`）；学生邀请码全 App 无处展示；学生端无 /parent 入口；提交 4958fc8 宣称已做与 diff 不符 | 登录页加家长注册 tab；学生"我的"处展示邀请码；ChildBar 绑定流程已现成 | 家长端两页（周报/预警）对新用户不可达——**付费与监督场景归零** |
| 3 | **IME Enter 误发送** | 全仓零处 isComposing：`socratic/page.tsx:147`、`chinese/reading:61`、`english/reading:77`、`force-analysis:60` | onKeyDown 补 `e.nativeEvent.isComposing` 检查（一行×4 处） | 中文学生打字选词即误发——**污染核心"问"体验，必踩** |
| 4 | **生产暴露万能验证码** | 登录页硬编码"dev模式：验证码固定 123456"（`login/page.tsx:191-193`）；后端非 aliyun 模式即万能码（main.py:112 自警）；阿里云 SMS 是 NotImplementedError | 短信通道决策（报备或换通道）；万能码提示仅 dev 显示 | 线上任何人可用 123456 登任意手机号账户 |

### P1（核心能力/可信度）

| # | 条目 |
|---|---|
| 5 | **JOL 采集通道**：练习提交前加一步"你有几成把握？"（`PracticeSubmitReq` 加 predicted_confidence，后端 main.py:855-857 已在等这个字段）——否则元认知差异化卖点之一的校准卡对真实用户永远 n=0 |
| 6 | **/lesson 接入主流程**：练习判分/错题本/知识点地图挂"看讲解"入口——Mafs 内核图示+同源自检已做完，只差一个链接；顺手删 Three.js 死依赖 |
| 7 | 试卷路径接 solve_*：可解题型先内核算再比对，OCR 出的 correct_answer 需内核复核（`paper_grading.py:41-57` 目前只信 OCR 答案钥匙） |
| 8 | verified/provenance 进学习路径：新学/日计划按 verified 过滤或降权（当前零消费）；批量抽取脚本收编进 ku_ingest 校验门（`extract_physics_ku_batch.py:439` 仍裸 INSERT） |
| 9 | 非数学纵深：物理题库灌内容（import 脚本已有题源）→ 练习 UI 通道自动通；物理/阅读/口语会话结果接 process_interaction；口语要么接真 ASR 要么先下线（"示例"评分对学生价值≈0） |
| 10 | 题目 payload 不提前带答案：correct_answer/explanation 随题下发（devtools 可见），检索门被软化——判分后再下发，MC 检测改由后端标记 |
| 11 | daily_mission 过 interleave_select（`daily_mission_workflow.py:88` 仍直拼） |
| 12 | 全新部署内容空洞：KU 12573 条 + 公共题库入种子/一键导入并写进部署文档（当前全新库两表为 0） |
| 13 | 内核双源收口：清理旧 editable 安装让 mypy/运行时同源 vendor；vendor 剔除非教育域代码；ruff/mypy exclude vendor——**让 check.sh 一条命令真绿**（修 .venv 假设） |
| 14 | 预警定时化：alert_service 加 celery beat（现在家长手动 POST 才检查）；家长导出/删除合规能力暴露 UI（后端已有 /v1/parent/report\|export\|delete-request，前端未用） |

### P2（深化/体验）

- FIRe 式前置回写：综合题成功复习按权重回写前置 KC 的 FSRS 日程（Math Academy 验证可大幅压缩复习量）。
- 周期限时小测（每 N 天/任务触发，失败自动生成复习任务）——检索练习的强制检查点。
- 错题本打印/导出（对标豆包爱学，国内家长刚需）。
- py-fsrs 版本核对（≥6 确认 21 参数与 get_retrievability API 变更）；FSRS simulator 进调度变更守卫。
- hint-ramp 换 stuck-count 触发（socratic_guide_v2 已写好未接）；evaluation AUC 落表可视化；socratic 会话显式 end（endSocratic 未调用）。
- 做题页 header 裸 KU id、InterleaveCard 改用后端 kc_name（两处漏网）；essay/speaking 年级默认值随用户年级。
- PWA：PNG/maskable 图标（iOS 主屏）、background sync、离线队列扩到复习提交；USE_MOCK 缺省改 false（`env.ts:7-8` 漏配 env 时静默 mock）。
- 补 test_*_single_source 守卫；vendor 内核补自测；旧 `mneme/frontend` 确认生产不依赖后整目录删除（已标 DEPRECATED）。
- 动机系统若做：连对返还制（Duolingo Energy）+ 努力货币化 XP（Math Academy），不做惩罚制。

---

## 5. "学生愿意用吗"——初二学生视角结论

**会愿意用（数学）。** 注册流程连未满 14 岁的监护人同意都做对了；首页有"从一道题开始"的钩子；做题秒判、错题自动入本、答错一键"让AI一步步引导你"（真的不给答案）、第二天"1 个知识点到了复习时间"且"看答案=没记住"——这套体验的学习科学成色高于豆包爱学/作业帮的错题本，接近 Math Academy 的严肃感。真实流失点只有三个：**打中文按 Enter 半句话被发出去（连发两次就烦了）；想让妈妈看学习报告却找不到任何家长入口；点进物理/英语发现只是公式表和单词本**，和数学那套"越用越懂你"不是一回事。

**给一句话的判断**：内核可信、后端可用、数学端好用；把 P0 四项（一圈 JWT、家长注册 UI、四处 isComposing、短信通道）修掉即可放心开学生试用——它们全是小改动，没有一项需要"新造"。

---

## 附：证据来源

- 整改核验：15 条逐条 `文件:行`（第 1 节），vendored 内核与 platform/3O edu-audit-fixes 分支逐字节 diff 一致。
- 后端：容器内实跑 pytest 203 绿 / ruff / mypy / alembic current / 75 路由烟测。
- 前端：mneme-web 全页面通读 + `tsc --noEmit` 零错 + 54 个 API 路径与后端逐一比对无断链 + `git show 4958fc8 --stat` 核实提交宣称。
- 标杆：blog.khanacademy.org、blog.duolingo.com、expertium.github.io、github.com/open-spaced-repetition（py-fsrs/srs-benchmark）、mathacademy.com、justinmath.com、remnote.com、36kr.com、huxiu.com、21jingji.com、qbitai.com 等（FSRS-7 细节与国内厂商准确率为中低置信度）。
