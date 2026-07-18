# W2C 关闭记录（W2C-CLOSE-001）

**日期**：2026-07-18
**状态**：W2C **收口**。C1–C5 五项全部落地（含 C4：先判 C4-0 不可达推后，
用户拍板重启网络/注册服务账号后解除阻塞、补齐）。
**收口性质**：五项均有对应可运行代码 + 通过测试；C4 的检索**管道**验证通过，
**不等于**检索**可用**（见下方 caveat）——如实标注，不因"管道通了"夸大结论。

---

## 五项成果 + commit

| 项 | commit | 一句话结果 |
|---|---|---|
| C4-0 | `137c709` | 前置查证：Stratum 确实在跑，但网络不通 + 无服务账号机制 → 按拍定规则推后，不自行搭建/改网络 |
| C2 | `137c709` | 组卷 `quiz_generator`（mneme-core oskill）：`shape_by_difficulty`（3 种难度曲线）+ `is_mastered` 组合选 KC 序列；**不选具体题、不判分**——选中的 KC 仍逐个走既有 RequestQuestion/SubmitAnswer，S1 判分 CI 门约束不变 |
| C3 | `71d9da7` | 教学人格模板：`persona.templates`（3 个人工编写、儿童适龄预设，非用户自建）+ `persona_store` + MCP 工具 `ListPersonas`/`GetPersona`；零门控耦合（见下方红线测试） |
| C1 | `1a6f63a` | Chat 工作区：`intent_router`（mneme-core，单 LLM 调用判"自由问答/转 Mastery Path"）+ `chat_loop`（复用既有 `tutor_loop`，禁另起循环）+ `POST /v1/chat/turn`；顺手修了 AA.1 遗留的 agent 侧 401（`tutor_loop._mcp()` 从未带 JWT） |
| C5 | `463898a` | 三层 Memory follow-ups：`append_episode`/`recall` 补齐"新增"入口 + MCP 工具 `RecallMemory`/`RememberEpisode`；`merge()` 加可选 LLM 语义合并（对照 DeepTutor `dedup` 策略，非字面照抄其"merge"）；working-memory TTL 清理 Celery 任务 |
| C4 | `d825d23` | Stratum 检索接入：`mneme-api-1` 连 `stratum-net`（声明式持久化进 `docker-compose.yml`）+ 专用服务账号 `mneme-rag-service`；`rag_client.py`（懒登录+检索，fail-safe）+ MCP 工具 `SearchKnowledgeBase`；`tutor_loop` 工具数 8→11（C5 加 2、C4 加 1） |

（`ad9b77c` 不算 W2C 产出——是从 `e25c23d` 拆分出来、C1 提交时意外混进
`services/main.py` 的会话前既有未提交改动，原样保留、未审查，详见该 commit 消息。）

---

## 红线测试：persona / memory / RAG 均不影响门控判定

三处新增的"呈现层"能力（persona 语气、memory 上下文、RAG 检索素材）都可能被
未来的人顺手接进判分/门控逻辑——每处都有**结构性**（不是"目前没有"）的静态断言：

| 模块 | 红线测试文件 | 断言方式 |
|---|---|---|
| persona | `tests/test_persona_no_gating_coupling.py` | AST 解析 `persona_store.py` 实际 import，断言不含 mastery_gate/gate_store/math_grade/verdict_guard/cognitive_service；另断言 `is_mastered`/`next_objective`/`process_interaction` 签名无 persona 参数 |
| memory | `tests/test_memory_no_gating_coupling.py` | 同上 AST 方式对 `services/memory.py`；另断言 `recall` 签名无写入类参数（防被误用成写入口） |
| RAG | `tests/test_rag_no_gating_coupling.py` | 同上 AST 方式对 `services/rag_client.py`；另**直接构造** `is_mastered` 调用前后夹一次"模拟跑了 RAG 检索"，证明返回值无法进入其输入——不是"没连"，是"数据通路不存在" |

用 AST 而非字符串 `in` 匹配，是因为字符串匹配会被模块自己的说明文档字符串
（写着"不得 import mastery_gate"这类话）误判命中——AST 只看真实 import 语句。

---

## FC-6 归属判定（书面记录，逐项）

W2C 每个新元素都过了"该不该进共享 platform/3O 主库"这道判定，结论均为**私有**：

- **C1 intent_router**：带 Mneme 模式假设（"自由问答/转 Mastery Path"是 Mneme
  特有概念，非通用 chat 分类）→ 私有，落 `packages/mneme-core`。
- **C2 quiz_generator**：带 Mneme 题库/掌握度假设（依赖 `is_mastered`/KC 难度）
  → 私有，落 `packages/mneme-core`。
- **C3 persona 模板**：文案带 Mneme 教学假设（面向中国中小学生、儿童适龄措辞）
  → 私有；加载/渲染机制形状虽通用，本轮不迁移进共享库（对照 D3 先例，避免
  不成熟共享包变更）。
- **C4 rag_client**：任务原文写"obase.rag"，但 `obase` 实测是纯 pip 装的跨项目
  共享包（`obase.db.__file__` 落在 `site-packages/obase`，本仓库无本地 `obase/`
  目录）——改共享包需跨项目发布协调；客户端又绑定 Stratum 具体契约（登录/检索
  端点形状、`mode=strict|augmented` 等），非通用抽象 → 落 `services/rag_client.py`
  （Mneme 本地），不进共享 `obase`。
- **C5 memory 四模式**：S3 已判private（agent.* schema 是 Mneme 自己的三层
  Memory 设计），C5 的 LLM merge 升级延续同一判定。

---

## ⚠️ 诚实 caveat：C4 检索管道通了 ≠ 检索可用

**这不是遗留 bug，是 W2C 范围外的独立工作。**

- C4 交付的是**HTTP 客户端接入**（定调原文："HTTP 调既有 Stratum 服务，不把
  Stratum 的栈拉进 Mneme"）——注册账号、连网络、写 `rag_client.py`、接 MCP 工具、
  验证全链路能走通。**这部分已完整验证**：`packages/mneme-agent/tests/
  test_tutor_loop_rag_tool.py` 是真 HTTP（非 mock），走通了
  注册→登录→`/api/search`→经 Mneme `/mcp/SearchKnowledgeBase` 代理 的完整路径。
- 但服务账号 `mneme-rag-service@sxueji.com` 的 Stratum 语料库**目前是空的**——
  零已上传/摄入内容。Stratum 的检索是按账号语料库隔离的（`/api/search` 返回体
  验证过 `{"results": [], "query_used": "函数"}`），所以**在内容填充之前，
  `SearchKnowledgeBase` 工具对任何查询都只会返回空列表**。
- **把 Mneme 教材内容上传/摄入进这个 Stratum 账号**（对应 Stratum 自己的"上传
  文件/URL 抓取/RSS 订阅"能力）是一项独立的内容工程工作，量级和性质都不同于
  "接一个 HTTP 客户端"，**不在 C4 范围内**，留后续 task。
- 换句话说：**C4 验收的是"通路"，不是"效果"**。chat 现在技术上能调用
  `SearchKnowledgeBase`，但在内容填充完成前，得到的永远是空结果——这是已知的、
  设计内的现状，不是需要排查的故障。

---

## 本次范围外（明确不做，非遗漏）

- studio 前端（`apps/mneme-studio/app/chat`）接线——C1/C3 均只交付后端契约，
  真实点击 `/studio/chat` 驱动对话、practice 分支跳转 `/studio/learn`留后续。
- Stratum 语料库内容填充（上述 caveat）。
- `quiz_mimic`（C2 spec 允许推迟到 W4）。
- Z 回测（数据不足，W3 S4 已记录，与本轮无关）。
- IRT 题库参数（题库本身没有，C2 的难度序列退化为 KC 级难度，如实不假装有）。

---

## 回归状态（收口时）

根仓 `pytest` 660 过 / 4 败（4 败为既有失败，`test_daily_plan.py` ×3 + 
`test_dod_e2e.py` ×1，与本次改动无关，S1 阶段已用 `git stash` 验证过与改动前
一致）/ 3 跳；`packages/mneme-core` 103 过；`packages/mneme-agent` 12 过/0 败
（起始 4/8，C1 顺手修复 AA.1 遗留 401 后转全绿）。ruff/mypy 干净（仓库既有
6 处 ruff + 1 处 mypy vendor/omodul 冲突，均经隔离验证为会话前既有问题，与
本次无关，未动）。
