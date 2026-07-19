# Mneme（善学记）学习系统 · 教育效果审计

> 视角：学习科学 + 教育产品。判据是"**学习者能不能真学会 / 记得住 / 理解透**"，循证学习原理是否被真实贯彻，而非功能数量。
> 方法：通读三处真实代码（后端 `mneme/services`、3O 内核 `platform/3O`、前端 `mneme-web`），每条判断标 `文件:行`。读真代码，不臆测。
> 日期：2026-06-30 · 范围：Good Learner Loop + Understanding Agent + Memory Engine（硬件/复合评分不在范围）。

**重要架构事实（审计前置）**：3O 内核（`oprim/oskill/omodul/obase`）**不在 `mneme/` 工作树内**，而是 editable 安装自共享平台仓 `/home/soffy/projects/platform/3O/`（见 `.venv/.../__editable__.mneme-0.1.0.pth`）。"已验证内核"的真实算法源码在该仓，本审计已直接读取，非黑盒。

---

## 第一部分：现状盘点（真实代码）

完成度判定：✅ 完整可用（真实现 + 数据流贯通 + 学习者能真用）／🟡 部分（单边有 / mock / 未接通）／🔴 骨架（空实现 / 占位 / TODO）。

### 1. Good Learner Loop（输入→理解→巩固→回顾→应用）

| 环节 | 接线 | 出处 | 判定 |
|------|------|------|------|
| 输入·试卷 | `papers/upload`→`process_paper.delay`→`analyze_paper_workflow`→OCR→批改+画像→落错题+`cognitive_update` | `main.py:602,639`；`tasks/paper_tasks.py:73`；`analyze_paper.py:74,135-164` | ✅ |
| 输入·教材KU | `textbook-files/upload` **只存PDF**，运行时不抽取；KU 全靠离线脚本 `scripts/extract_*_ku_batch.py` 灌库 | `main.py:1767,1791-1802` | 🔴 孤岛 |
| 理解·讲解 | `lesson/{qid}`→`generate_lesson_page`（确定性内核 + 同源自检） | `main.py:952`；`generate_lesson_page.py:95-124` | ✅ |
| 理解·苏格拉底 | `socratic/start-for-ku`、扣题首问 | `main.py:1253`；`socratic_service.py:63-70` | ✅（见模块2） |
| 巩固 | `practice/submit`→`judge_answer`→`process_interaction`(BKT/FSRS)；苏格拉底 `end_session`→`process_interaction` | `main.py:1166,1225`；`socratic_service.py:281-299` | ✅ |
| 回顾 | `daily-plan` FSRS 到期；`review/due` 变式；`review_queue` 交错 | `daily_plan_service.py:117-138`；`review_service.py:19`；`cognitive_service.py:330-367` | 🟡（见模块3、5） |
| 应用·迁移 | 无独立迁移/应用环节，"应用"塌缩进同题练习/复习 | — | 🟡 薄 |

**结论**：**学生错题闭环已基本贯通**（输入→理解→巩固→回顾真实接通），这是相较 6-28 评估的实质进步；但**课程知识录入是断开的孤岛**——学习者上传自己的教材，系统只存文件、零抽取。

### 2. Understanding Agent（苏格拉底理解引擎）

真实调用链：`socratic_service.py` → `omodul.socratic_session_workflow` → `oskill.socratic_loop` → `oprim.socratic_turn`（单 LLM 调用）。
注意：`oskill/socratic_guide_v2.py`（动态提示升级 hint_level 1→2→3）与 `omodul/socratic_tutor_session.py` 是**死代码**，未被 mneme 调用；docstring 宣传的自适应脚手架**未接入线上**（`socratic_session_workflow.py:27,106` hint_level 恒为 1）。

| 红线/能力 | 判定 | 出处 |
|-----------|------|------|
| 首问扣题（确定性锚定真实题面，非"你怎么想？"） | ✅ | `socratic_service.py:63-70` |
| 不泄露标准答案 | 🟡 有确定性兜底但**仅精确子串匹配**，改写/部分泄露穿透；测试也只查逐字 | `socratic_loop.py:111-125`；`test_remaining.py:138-165` |
| 每次只问一个问题 | 🔴 仅 prompt 约束，无代码计数/拦截 | `socratic_turn.py:54` |
| 错误中间步确定性拦截（非 LLM） | 🟡 `verify_step` 纯 sympy 可靠，但线上 `_try_verify_step` **只拦无变量纯算术**，含变量步（如 x²=4⇒x=3）落给 LLM 判 | `verify_step.py:1-9`；`socratic_service.py:208-212,223-224` |
| 模式按掌握度选 | ✅ 真 BKT 信号（`<0.4`→deep，单阈值粗） | `socratic_service.py:49-51` |
| 多轮对话状态 | 🟡 持久化，但 assistant 历史不回放、每轮从头重算（O(n) LLM 调用） | `socratic_service.py:160-162`；`socratic_session_workflow.py:98-117` |
| 结束→FSRS 评级 | 🟡 已接通，但 `outcome` 由前端/调用方提供、内核未确认是否真解出，可被前端伪报污染掌握度 | `socratic_service.py:256-306`；`socratic_loop.py:53`（`resolved` 恒 False） |

**结论**：扣题首问是真亮点（强制审题）；但首问之后退化为"被要求提问的 LLM"，缺结构化苏格拉底阶梯，且**中间推理由 LLM 判**是最大教学风险。

### 3. Memory Engine（FSRS + BKT 记忆引擎）

| 能力 | 判定 | 出处 |
|------|------|------|
| FSRS 算法 | ✅ 真·官方 `py-fsrs`（Anki FSRS）封装，4 评级齐全，整卡 D/S/R 落 `fsrs_card_json` | `fsrs_engine.py:16,34-40,50-53`；`models.py:188` |
| 复习队列按日期选到期 | ✅ `review_queue_workflow` 真做 `due<=now` | `omodul/cognitive.py:145-154`；`review_service.py:34` |
| BKT 贝叶斯更新 | ✅ forgetting-aware，`p_eff=p_l×R`、slip/guess 后验、学习转移、EMA | `_cognitive.py:42-93` |
| 更新顺序红线 | ✅ R→forgetting-aware BKT→答错 classify→FSRS review→落库+append | `cognitive_state.py:60-97` |
| `effective=long_term×R` / careless·dontknow 比例 | ✅ | `omodul/cognitive.py:140`；`_cognitive.py:104-105` |
| P(L)∈(0,0.97] | 🟡 上界 0.97 显式封顶；下界 >0 仅隐式成立、无 clip | `_cognitive.py:62,81` |
| 个性化（按学生 FSRS 权重/BKT 先验） | 🔴 单一全局 `Scheduler()` 默认权重；先验来自硬编码 `KC_LIST`+静态猜测表，**按 KC×题型、非按学生** | `fsrs_engine.py:18-19`；`seed.py:14-52` |
| 识别维度 p_recognition | 🟡 `cognitive_state.py:86-95` 内联实现真·已落库已展示；但同名 `oprim/recognition_update.py` 是**孤儿**（导出无人调） | `cognitive_state.py:86-95`；`recognition_update.py`（零调用方） |
| 数据飞轮 | 🔴 `interaction_events` 只增、特征丰富，但**无任何代码用它再训 BKT 先验/FSRS 权重**；`BKTPrior.calibrated_from_n` 永远为 0（零写入方） | `cognitive_store.py:161-176`；`models.py:206`（无写入） |

**结论**：内核算法本身扎实（真 FSRS、红线不变量与更新顺序端到端守住）；但**护城河没在转**——飞轮死、调度全局默认、先验静态。另：`process_interaction` 对**每次**答题都发 FSRS `review_card`，把"集中练习/同卷连答"误当"间隔检索"，一张卷内几分钟连对会被 FSRS 推到几天后→生material 被排太远→学了就忘（`cognitive_state.py:80` 每次调用）。

### 4. 知识提取 / 录入（可信度）

| 维度 | 现状 | 出处 | 判定 |
|------|------|------|------|
| 可信抽取流水线（结构分块→LLM抽取→**校验门**→保留 provenance） | 内核**有**正确设计 | `oskill/ku_extract_pipeline.py:41-48` | — |
| 线上是否调用 | 🔴 **未调用**（grep `ku_extract_pipeline/ku_gate_validate/llm_extract_ku` 在 services/tasks 零命中）；实际灌库是 `scripts/extract_math_ku_batch.py` 直连 DeepSeek + 裸 `INSERT`，无校验门、无 provenance | `extract_math_ku_batch.py:236-262,365` | 🔴 |
| 源内容 vs AI 内容分离 | 🔴 `KnowledgeUnit` 无 `provenance/source/ai_generated/verified` 列，LLM 产出即真理 | `models.py:435-451` | 🔴 |
| 语义去重 | 🔴 录入路径无；`unify_ku_naming.py` 只是命名归一 | — | 🔴 |
| 题→KU 匹配 | 🟡 LLM 判，自报约 10% 错配未校验 | `curriculum_standards/数学闭环链路验证报告.txt` | 🟡 |

**结论**：**Mneme 宣称的差异化（可信抽取 / 证据溯源 / 源内容与 AI 分离）在内核里有设计，却被生产路径绕过**——LLM 输出未经校验门直写权威 KU 表，且无溯源列。这是与"防 AI 幻觉污染学习"目标的最大背离。

### 5. 前端 mneme-web（善学记，线上真版）

API 客户端真实（`api-client.ts` 真 `fetch`，`.env.production` 指 `api.sxueji.com` 且 `USE_MOCK=false`）；mock 仅 dev 便利、非生产后门；JWT 鉴权、401 清 token、SSE 流式正确。

| 核心学习面 | 判定 | 出处 |
|------------|------|------|
| 苏格拉底（理解）流式对话 + 逃生舱只给提纲 | ✅ | `socratic/page.tsx`；`api-client.ts:114,159-160` |
| 曲线/复习（记忆·永久档案可视化） | ✅ 真 SVG 纵向曲线 + 月度主错型；复习队列两处入口 | `curve/page.tsx:99,166-170`；`home/page.tsx:62` |
| 掌握 + 错题本（元认知·最强面） | ✅ 复合 4 路真信号：掌握环/形态/校准(JOL努力错觉)/前置断点，并渲染"惰性知识"(effective−recognition>0.2) | `mastery/page.tsx:23,113,172-173,250` |
| 练习（主动回忆） | ✅（数学）：先答后揭、自评防作弊文案；🟡 其他学科"题库建设中" | `subjects/math/practice/page.tsx:292,302,316-321` |
| 主动回忆 UX 强制 | ✅ 提交前禁揭答案、检索练习提示 banner | `subjects/math/practice/page.tsx:261-264,348` |
| 内核图示渲染 | 🟡 lesson 页是 📐 占位（"装 mafs 后渲染"），"内核兜图"护城河在前端不可见 | `lesson/page.tsx:60-77` |
| 学科广度真实度 | 数学≈80% / 语文≈65% / 物理≈45% / 英语≈35%（其余诚实标"即将上线"，非假页） | `SubjectHub.tsx:139-162` |

**结论**：数学端已是生产级、检索/元认知 UX 教科书级正确；**但只有数学闭合完整 input→practice→feedback→review→mastery 闭环**，其余三科只有讲解/卡片/图谱、无评分练习喂飞轮，元认知面对非数学学习者显示"数据不够"。

---

## 第二部分：标杆对标（教育效果视角）

| 能力域 | 标杆基线 | Mneme 现状 | 差距（具体功能点） |
|--------|----------|------------|--------------------|
| **间隔重复调度** | Anki/SuperMemo（SM-2/FSRS），按用户复习日志优化权重 | ✅ 真 py-fsrs（Anki 同款），整卡持久、按日到期 | 🔴 **单一全局默认权重、不按学生优化**（`fsrs_engine.py:18-19`）；每次答题都 review_card，**集中练习被当间隔检索**→shaky 题排太远 |
| **主动回忆（非被动重读）** | Anki cloze / Quizlet：必先检索再揭答 | ✅ 数学练习强制先答后揭、自评防蒙 | 🔴 **复习变式把题+答案同包返回**（`review_service.py:60-66`），可被动读答；**无"看答案=Again"**惩罚 |
| **理解性学习（非死记）** | Khanmigo：结构化苏格拉底、自适应提示升级、步步确定性纠错 | 🟡 扣题首问确定性锚定（真亮点） | 首问后无脚手架阶梯（v2 hint-ramp 死代码）；**含变量中间步由 LLM 判**、非确定性拦截；"只问一个问题"未强制 |
| **知识关联 / 网络** | RemNote/Obsidian 双链、知识图谱 | 🟡 KU 有 prerequisites 前置图、前置断点诊断 | 单向前置链，无双链/概念网络；前置边本身是**未校验 LLM 产物**（`models.py:435-451`） |
| **提取可信度（防 AI 幻觉污染）** | **Mneme 差异化**：证据溯源 + 源/AI 分离 + 校验门 | 🔴 内核**有** `ku_extract_pipeline`（provenance+gate）但**生产未调用** | 实际灌库无校验门、无溯源列、无语义去重；LLM 定义直写权威表——**差异化优势未兑现** |
| **元认知 / 学习反馈** | 自适应平台：弱点定位、信心校准 | ✅ **最强面**：掌握环/遗忘形态/JOL 校准/前置断点/惰性知识，真信号驱动 | 仅数学有数据；非数学学习者全空；缺"该学什么/学了多少"的整体学习地图引导 |
| **个性化（难度/节奏适配）** | Duolingo/SuperMemo：按表现调难度与节奏 | 🟡 题目难度入 IRT、模式按掌握度 | FSRS 权重与 BKT 先验**不按学生**（静态）；难度自适应限于选题，非节奏个性化 |
| **学习动机 / 坚持** | Duolingo streak/连击 | 🟡 有 streak/连续天数、努力收益(desirable difficulty)、家长日报 | 无系统化激励循环（目标/连击/正反馈节律）；动机机制单薄（符合"去冗余"取向，列为低优） |

**对标小结**：Mneme 在**元认知反馈**与**确定性内核护住"算与图"**两域已达到或接近标杆，且"努力收益/识别维度/永久档案曲线"是标杆产品都没有的真实差异点。掉链子集中在三处：**调度个性化缺失**、**复习无检索门**、**理解引擎中间步非确定性纠错**。

---

## 第三部分：差距 + 优化清单

优先级：P0 影响学习效果/可信度（红线级）｜P1 核心学习能力缺失｜P2 体验优化。

| 优先级 | 条目 | 现状 | 目标 | 涉及模块 | 不修的学习后果 |
|--------|------|------|------|----------|----------------|
| **P0** | 试卷批改绕过确定性内核 | `paper_grading.process_single_question` 调 `grade_question` **不传 `solve_result`**，可解题型也落 LLM 判对错 | 可解题型先跑 `solve_*` 再传内核结论，红线"内核兜算"在试卷路径生效 | analyze_paper / paper_grading | LLM 错判→错题信号污染 BKT/FSRS→**掌握度算错、复习排错** |
| **P0** | 知识录入绕过可信校验门 | 生产用脚本直连 LLM 裸 INSERT，`ku_extract_pipeline`/`ku_gate_validate` 零调用；KU 无 provenance/源-AI 分离列 | 录入走校验门 + 加 `provenance/source/verified` 列；幻觉候选进 rejected 不入权威表 | omodul/ku_extract / models / 录入脚本 | **幻觉定义/错前置边静默成为权威**，驱动新学路径→学到错的，差异化优势落空 |
| **P0** | 苏格拉底含变量中间步由 LLM 判 | `_try_verify_step` 只拦无变量纯算术，`x²=4⇒x=3` 落 LLM | 扩 `verify_step` 覆盖含变量代数等式（sympy 已具能力），错误中间步确定性拦截 | socratic_service / verify_step | **错误推理被静默放行/误判**，学生以为被验证，理解性学习失真 |
| **P0** | 复习变式无检索门、答案同包 | `get_due_variants` 题+答案一起返回，无"看答案=Again" | 先只给题面，揭答触发 FSRS `Again`；retrieval-before-answer 强制 | review_service / 前端复习页 | 被动重读冒充复习→**间隔重复的"主动检索"前提被破坏，记不牢** |
| **P1** | FSRS/BKT 飞轮死 | `interaction_events` 只增不学，`calibrated_from_n` 永 0，全局默认权重 | 离线 job 从事件再校准 BKT 先验、按学生/群体优化 FSRS 权重 | tasks / seed / fsrs_engine | 人人吃群体默认间隔、先验永不更新→**护城河不转，记忆引擎天花板被锁死** |
| **P1** | 集中练习被当间隔检索 | 每次答题都 `review_card`，同卷连对几分钟→推到几天后 | 区分"首次练习/集中"与"间隔检索"，仅后者推进 FSRS 调度 | cognitive_state / process_interaction | shaky 新知识被排太远→**到期前已遗忘** |
| **P1** | 教材上传不触发抽取 | `textbook-files/upload` 只存 PDF | 上传→运行时分块→`ku_extract_pipeline`→入候选；productized 录入闭环 | main / omodul / tasks | 学习者上传自己课本=零产出→**自主学习入口形同虚设** |
| **P1** | 每日计划/任务不交错 | `daily_mission`/`daily_plan` 按科分组、无相邻异 KC；`interleave_select` 只用于 review_queue | 让日计划/任务也过 `interleave_select`（算法已现成且可证约束） | daily_plan / daily_mission | 相邻同 KC 集中练习=交错证据警示的反模式→**迁移与长期保持变差** |
| **P1** | 苏格拉底 outcome 前端自报 | `outcome` 由调用方给，内核 `resolved` 恒 False | 由内核/verify_step 判定是否真解出再映射 FSRS 评级 | socratic_service / socratic_loop | 前端伪报 success→**掌握度信号被污染** |
| **P1** | 非数学学科无评分练习闭环 | 仅数学有 question-bank+submit+grade+BKT/FSRS | 把"题库+submit+判分+反馈"扩到物理/英语/语文 | 前后端题库 | 三科元认知面永显"数据不够"→**学习者误判"app 没做好"而流失** |
| **P2** | 苏格拉底自适应脚手架未接入 | `socratic_guide_v2` hint-ramp 是死代码，hint_level 恒 1 | 接入 stuck-count→提示升级，向 Khanmigo 阶梯靠拢 | socratic_session_workflow | 卡住学生得不到渐进支架，引导深度不足（非红线，列 P2） |
| **P2** | 多轮对话每轮从头重算 | assistant 历史不回放、O(n) LLM 调用 | 回放完整历史或增量推进 | socratic_session_workflow | 连贯性近似 + 成本随轮次线性涨（体验/成本，非学习红线） |
| **P2** | 三套"到期"语义分叉 | `due_compute`(缺 due=到期) vs `review_queue_workflow`(缺 due=不到期) | 统一到期判定单源 | review_service / cognitive / daily_plan | 同卡在不同路径"到期"不一致，复习提示混乱 |
| **P2** | 前端内核图示未渲染 | lesson 页 📐 占位 | 接 Mafs/Three.js 渲染内核 plot 数据 | mneme-web lesson | "内核兜图"护城河在前端不可见（入口非主路径，低优） |
| **P2** | P(L) 下界无显式 clip | 仅隐式 >0 | 显式 clip 到 (0,0.97] 防退化输入 | _cognitive | 退化先验/R=0 边界理论暴露（当前不可达，防御性） |

---

## 报告

**产出文件**：`/home/soffy/projects/mneme/MNEME_EDU_AUDIT_20260630.md`

**三个核心结论**：

1. **最影响学习效果的短板 —— 可信度三处破口，让"算得对/记得牢/理解透"的根基漏水**：
   ① 试卷批改可解题型绕过确定性内核、由 LLM 判对错（`paper_grading.py:41-45`）→错信号污染掌握度与复习调度；② 知识录入绕过内核自带的校验门、LLM 定义直写权威 KU 表且无溯源列（`extract_math_ku_batch.py:365`、`models.py:435-451`）→幻觉知识静默成为权威；③ 苏格拉底含变量中间步由 LLM 判而非 `verify_step` 确定性拦截（`socratic_service.py:208-212`）→错误推理被静默放行。三者都直接攻击"确定性内核兜底、LLM 只问只讲"的产品立身之本。

2. **最大差异化优势 —— 元认知反馈面 + 确定性内核护住"算与图"，且有标杆产品都没有的真实机制**：掌握环/遗忘形态/JOL 信心校准（努力错觉）/前置断点/"惰性知识"(effective−recognition>0.2) 是**真信号驱动、已落库已可视化**的最强面（`mastery/page.tsx`、`cognitive_state.py:86-95`）；讲解页同源自检（图示值==答案==末步值，`generate_lesson_page.py:95-124`）、努力收益（desirable difficulty，`cognitive_service.py:194-210`）、永久档案纵向曲线（`curve/page.tsx`）是 Anki/Quizlet/Duolingo 都不具备的差异点。注意：**可信抽取（provenance+校验门）的设计已存在于内核，只是没接线**——这是"已具备、待兑现"的差异化，而非要从零造。

3. **P0 必修项及其学习后果**（红线级，不修即学习效果/可信度失守）：
   - **试卷批改接回内核**：不修→掌握度算错、复习排错。
   - **知识录入走校验门 + 加源/AI 分离列**：不修→幻觉定义驱动新学路径，学到错的。
   - **苏格拉底含变量步确定性拦截**：不修→错误推理被静默放行，理解性学习失真。
   - **复习变式加检索门（看答案=Again）**：不修→被动重读冒充复习，间隔重复前提被破坏、记不牢。

> 边界遵循：未建议恢复已移除的 GLS 复合评分；未引入 Master 未列框架；动机/激励刻意列为低优（符合"去冗余"取向）。所有 P0/P1 均为接通/守红线类修复，非新增臃肿功能。
