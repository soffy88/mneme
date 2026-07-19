# MNEME-W3-IMPL-SPEC-001

**类型**：可实施规范
**范式**：3O v3.0 + FC-1..FC-7
**范围**：Knowledge Hub（自建，PDF 索引带出处）→ Book Engine（活书）
**关键约束**：Mneme 不耦合 Stratum，Knowledge Hub 自建，以既有中学教材 PDF + KU 为基础
**前置**：`outputs/KNOWLEDGE-HUB-INVENTORY-001.md`（盘点）；C4 Stratum RAG 留作可选外部检索，Book/Hub 零依赖

---

## 0. 地基声明

Mneme 至今零真实学习者（`kc_mastery` 仅 1 个 KC、无重复观测）。W8–W12 红；Z 无数据。W3 建立在无人使用之上——功能补全合理，但不缩小差距。缩小差距唯一动作 = Wiki+孩子跑 `/studio/learn`，CC 做不了。

盘点暴露的三个硬事实（W3 设计依据）：

1. KU（11,646 行）LLM 抽取、零来源链接，无法回溯 PDF 原文 → Book 引用需另建出处。
2. 22 本数学 PDF（G1–G12，有全文层，在 MinIO）从未索引（`textbook_chunks` 零行）；物理/语文 PDF 未上传。
3. 现成 embedding 管道（chunking + numpy 暴力余弦，避开 pgvector）从未跑过，两个 provider 均未配。

---

## 1. 范围与顺序

**Part A：Knowledge Hub（先）→ Part B：Book Engine（后，基于填好的库）**

理由：Book 的内容源是 Hub，空库编不出书（C4 教训：管道通、库空）。

W3 只覆盖数学（22 本 PDF）。物理/语文 PDF 未上传，不在范围——别为没有的数据建管道。

---

## 2. Part A — Knowledge Hub（自建）

### A1. PDF → chunk → 索引管道（复用现成，补配置）

现成资产（uncommitted WIP，盘点确认）：`vendor/oprim/embed_chunks.py` + `retrieve_chunks.py` + `services/textbook_qa_service.py`（段落感知切分 + numpy 暴力余弦）。复用，不重造。

- **embedding provider**：本地 Ollama `qwen3-embedding`（本地优先）。配置补齐（现两 provider 均未配）。
- **检索栈**：numpy 暴力余弦跑通（22 本量级够用，零迁移成本）。pgvector 列**规模化触发项**——数据量过阈值（定：chunk 数 > 5 万 或 检索 P95 > 500ms）再换镜像，W3 不提前换。
- **出处（关键）**：每个 chunk 必带 `{pdf_id, page, char_span, textbook_meta}` —— 这是 Book Engine 引用教材原文的溯源基础，补 KU 缺的来源链接。

### A2. chunk 入库

- 22 本数学 PDF 从 MinIO 取 → 切分 → embedding → 存 `textbook_chunks`（现零行）。
- chunk 表结构含出处字段（A1）；FC-2：若表含 `student_id` 则纳入 purge——`textbook_chunks` 无 `student_id`（是内容非学生数据），书面确认不入 purge、守卫扫过不误报。
- 验证入库真实性：随机抽 N 个 chunk，人工核对文本与原 PDF 页码一致（防"入库了但出处错位"）。

### A3. KU ↔ chunk 挂接

- KU（11,646）与题库 KC 同命名空间（65% 重叠已验证）。
- 挂接策略：KU 经 embedding 检索匹配到相关 chunk（KU 无原生出处，用语义检索补）——匹配是概率的，标注为"推断出处"非"权威出处"，不假装精确。
- 挂接结果供 Book Engine 用（某 KC → 相关教材段落）。

### A4. Knowledge Hub 检索面

- `SearchKnowledgeBase`（Mneme 自建，非 C4 的 Stratum 版）：KC/查询 → 相关 chunk（带出处）。
- MCP 工具，注入 tutor_loop / chat / Book Engine。
- FC-6 分类筛：检索客户端若通用可入主库；带 Mneme chunk 契约 → 私有。CC 判定书面记录。
- 红线：Hub 检索是呈现层素材，不进门控判据（BLUEPRINT P1）。

### A5. Part A 验收

| # | 项 | 方法 |
|---|---|---|
| A-1 | 22 本 PDF 全部索引，`textbook_chunks` 非零 | DB |
| A-2 | 每 chunk 带出处（pdf_id/page/span） | schema + 抽样核对 |
| A-3 | 抽样 chunk 文本与原 PDF 页码一致 | 人工抽验 N 条 |
| A-4 | Ollama embedding 真实产出向量（非空非 mock） | 集成测试 |
| A-5 | SearchKnowledgeBase 返回带出处结果 | e2e |
| A-6 | 检索不影响 is_mastered | 断言 |
| A-7 | textbook_chunks 无 student_id、purge 守卫绿 | CI |

---

## 3. Part B — Book Engine（活书）

精读入口 + 搬运方案：`PORT-PLAN-001`（已产出，DeepTutor `book/` 逐文件映射）。W3 按 3O v3.0 落地，去掉 os-taxonomy 依赖（已废）。

### B1. 五阶段流水线（oskill + omodul）

DeepTutor `book/engine.py` 五阶段：ideation → spine → page_planner → block 编译 → 进度。

- ideation / spine / page_planner：oskill，LLMCaller 注入（qwen），FC-6 私有（带 Mneme 教学假设）。
- spine 前置关系：DeepTutor 让 LLM 生成章节 prerequisites。W3 保持 LLM 生成（os-taxonomy 已废，不引外部前置图）。
- block 编译：omodul（四支柱，cost 必启——DeepTutor 无成本核算）。

### B2. 13 内容块（oskill 注册表）

- 注册表模式（block_type → generator）保留。
- 内容源 = Part A 的 Knowledge Hub（有出处 chunk），非 Stratum。
- quiz 块 → 复用既有题库 + 判分护栏（W2C C2 的组卷链路）。
- flash_cards 块 → 既有 FSRS。
- 图/公式块 → KaTeX（W2 AA.3 已有）。
- Guided Learning 块 → 接门控 `next_objective`。

### B3. omodul.book_compile 四支柱

| 支柱 | 内容 |
|---|---|
| fingerprint | `{KC集合, chunk版本, spine版本}` ——换书/换内容旧缓存失效 |
| decision_trail | 每页选块 + 失败重试分类（DeepTutor `_classify_failure` 直搬） |
| report | 编译进度 + 成书快照（BU for humans） |
| cost | 新增：每本书 LLM/embedding/检索开销（DeepTutor 无，可售定价依据） |

三件套签名 `(config, input_data, output_dir) → dict`；失败不 raise。
async（多块并发编译，C1–C6：ContextVar cost、CancelledError 重抛、shield 落 trail）。

### B4. 前端（studio）

- `/studio/book`：活书阅读器（新页面，原页面零改动）。
- 引用教材处显示出处（Part A 的 chunk provenance）——这是"诚实"原则的体现：书里每段教材内容可溯源。

### B5. Part B 验收

| # | 项 | 方法 |
|---|---|---|
| B-1 | 一本数学书端到端编译（ideation→成书） | e2e |
| B-2 | 书内容来自 Knowledge Hub chunk（非 Stratum、非纯 LLM 编造） | 溯源断言 |
| B-3 | 引用教材段落显示正确出处 | e2e + 抽验 |
| B-4 | quiz 块经既有判分护栏，掌握度回流 | DB 断言 |
| B-5 | book_compile 四支柱齐（cost 非零） | 测试 |
| B-6 | async 并发：cost 累加正确、trail 顺序确定（C5） | 测试 |
| B-7 | FC-6 每元素归属书面记录 | 审读 |
| B-8 | FC-1 测试计数独立审计 | 审读 |

---

## 4. 全局不变式（继承）

- 掌握度写入唯一路径 + guard。
- studio/agent 零 mneme-DB（FC-5）。
- 门控上游、内容下游——Hub/Book 只管"怎么讲"。
- 确定性判分路由不变。
- 原 mneme 零改动；studio 独立 app。
- 主库元素不可变，改则私有化（FC-6）。
- 不耦合 Stratum（本 spec 核心约束）；C4 Stratum RAG 留作可选，Book/Hub 零引用。

---

## 5. 顺序

A1 配置补齐 → A2 入库 → A3 挂接 → A4 检索面 → A5 验收 → B1–B4 → B5 验收

Part A 未绿不进 Part B（空库编不出书）。

---

## 6. 明确不做

物理/语文 PDF（未上传）｜pgvector（未过规模阈值）｜quiz_mimic（W2C 已推）｜os-taxonomy（已废）｜Stratum 耦合｜Solve/Research/Animator/Visualize/Notebook/Co-Writer（W4）｜Partners（W5）｜Z 回测（数据不足）

---

## 7. 挂起项（交接 W4）

3× daily_plan 失败｜oservi assemble 双注册 bug｜blocks OMarkdownRenderer bug｜main.py pre-session 簇｜knowledge_points 漂移未提交｜docker-compose.override.yml｜S3-C 真人 pilot（W8–W12 红）——唯一真瓶颈｜Stratum 内容库为空（若日后用可选外部检索需单独填库）｜Mneme 教材入自建 Hub 后，物理/语文 PDF 上传另议
