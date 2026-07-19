# Knowledge Hub 技术栈盘点（KNOWLEDGE-HUB-INVENTORY-001）

**日期**：2026-07-18
**性质**：只读盘点，未动任何代码。全部数据经真实生产库查询 + 代码库读取，非猜测。
**用途**：供 W3 spec 定"Knowledge Hub 自建"的技术栈决策参考。

---

## 1. 既有中学教材：存在哪、格式、是否已解析/入库、覆盖哪些学科年级

**两套独立的"教材"概念，容易混淆，先分清：**

| | KU 课程字典（`textbooks`+`knowledge_units`） | 教材原文 QA（`textbook_files`+`textbook_chunks`） |
|---|---|---|
| 性质 | LLM 从源材料批量抽取的知识点结构化字典 | 原始 PDF 全文，供逐字检索/问答 |
| 覆盖 | 数学 G1-G12 全学段 + 物理 G8-G12 + 语文 G7-G12（`textbooks` 表 43 行） | **仅数学 G1-G12（22 个 PDF）**，物理/语文教材**未上传** |
| 入库状态 | 已完成（见 §2） | **文件已存（MinIO 实测有字节）+ DB 行已建，但 0 行 `textbook_chunks`、22/22 `index_status='pending'`——从未真正跑过分块/嵌入** |
| 来源 | `scripts/extract_*_ku_batch.py` 系列一次性脚本（LLM 抽取，无原文逐字保留） | 用户/系统上传的官方教材 PDF（人教版），`owner_student_id` 均为空——是系统级教材，非个人上传 |

**教材原文格式细节**（`textbook_files` 实测）：
- 22 个 PDF，全部 `file_type='pdf'`、`has_text_layer=true`（原生文本层，非扫描图片，**不需要 OCR**）。
- 文件名规律：`G{年级}_{序号}_{学科}{年级}册.pdf`，如 `G10_19_高中数学必修一（A版）.pdf`。
- 大小 9MB–54MB 不等（22 个文件总计约 400MB）。
- 已确认存在 MinIO（`mc ls local/mneme/curriculum_standards/` 实测有文件），不是只有 DB 行没有实体。

**结论**：数学教材原文"人在等跑"——文件已就位、表已建好，**只差真正跑一次分块+嵌入的批处理**（见 §3 关于嵌入 provider 现状为何目前跑不通）。物理/语文教材连文件都还没传。

---

## 2. KU 现状：总量、结构、与教材的挂接关系、与 kc_mastery 是否同一套 KC

**总量**：`knowledge_units` 表 **11,646 行**，按 `textbook_id` 分布（节选，完整见附表）：
- 数学 G1-G12：36～363 条/册不等（如 `renjiao-math-g10-a` 165 条）
- 物理 G8-G12：113～210 条/册
- 语文 G7-G12（`TONGBIAN-*`）：428～1002 条/册（语文 KU 密度明显更高）
- 高考语文专项：50 条

**结构**（`knowledge_units` 20 列）：`id`/`textbook_id`/`cluster_id`（挂 `knowledge_clusters`，1853 行，即"章节"）/`name`/`description`/`prerequisites`（jsonb 硬前置）/`soft_prerequisites`（W.2 新增）/`difficulty`/`ku_type`/`question_types`/`mastery_levels`/`rich_content`/`provenance`/`source_excerpt`/`ai_generated`/`verified`/`exam_region_tags`。

**与教材的挂接**：`knowledge_units.textbook_id` 外键指向 `textbooks.id`，`cluster_id` 外键指向 `knowledge_clusters.id`（章节，有 `display_order`）——挂接关系完整、有 FK 约束。**但挂接是"属于哪本教材/哪章"的元数据级关联，不是"来自教材第几页第几段"的原文级关联**：实测 `renjiao-math-g10-a` 的 KU **100% `provenance` 为空、`ai_generated=true`、`verified=false`**（全库 11,646 条同此状态，无一例外）——KU 内容是 LLM 一次性批量抽取所得，**没有保留到原文的可追溯锚点**。这意味着"KU ↔ 教材原文 chunk"目前是两套彼此独立的数据，没有天然的双向定位能力（无法从一个 KU 直接跳转到教材原文的对应段落，反之亦然）。

**与 `kc_mastery` 是否同一套 KC**：**是同一套命名体系，但当前几乎零重叠使用**。
- 验证：`wrong_questions.knowledge_points`（题库的 KC 关联字段）的 2677 个去重 KC key 里，1736 个（65%）能在 `knowledge_units.id` 里找到匹配——证明题库确实在用 KU 的 ID 命名体系。
- 但 `kc_mastery.knowledge_point`（学生实际掌握度记录）当前全表仅 4 行，去重后**只有 1 个值：`GDMATH-SET-01`**——这不是 `knowledge_units.id` 的命名格式（对比 `renjiao-math-g10-a-ku004`），是更早期/测试阶段遗留的旧命名，**与 `knowledge_units.id` 零匹配**。
- 结论：设计上是同一套 KC 空间（`progress_assembler.py` 等生产代码路径也是这么假设的），但**目前真实写入 `kc_mastery` 的数据几乎为零**（与 S4 的"零真实学习者"结论一致），这条"KU↔kc_mastery 是否同一套"的问题目前更多是"理论上是，实测上无数据可验证"。

---

## 3. Mneme 现有 Postgres 是否有 pgvector / 既有 embedding 能力

**pgvector：未安装，且当前镜像不可用。**
- `SELECT * FROM pg_extension` 实测只有 `plpgsql`。
- `SELECT * FROM pg_available_extensions WHERE name ILIKE '%vector%'` **零行**——`pgvector` 扩展在当前 `postgres:16-alpine` 镜像里**连可安装列表都没有**（不是"装了但没建"，是镜像本身没打包这个扩展）。若要用 pgvector，需要换成打包了该扩展的镜像（如 `pgvector/pgvector:pg16`），不是简单一句 `CREATE EXTENSION`。

**已有一套完整但未跑通的 embedding 管线**（全部是本 session 之前已存在、尚未提交的工作，我读了源码确认）：

| 组件 | 文件 | 关键事实 |
|---|---|---|
| 分块 | `vendor/oprim/embed_chunks.py` | 按段落边界切（非定长/非按页），800 字上限+100 字重叠，超长段落强制切分；保留 `page_number`/`section_title`（用 PyMuPDF 字号≥14 启发式判章节标题） |
| 嵌入 | 同上 `embed_text()` | **优先 OpenAI `text-embedding-3-small`**（1536 维，需 `OPENAI_API_KEY`），**兜底 Ollama `nomic-embed-text`**（本地）；两者都失败时返回 `None`，不报错，降级为纯关键词检索 |
| 存储 | `textbook_chunks.embedding` | `postgresql.ARRAY(Float(8))`——**明确不用 pgvector**，migration 注释直接写"不依赖 pgvector；向量以 Python list[float] 返回，存入 ARRAY(FLOAT8)" |
| 检索 | `vendor/oprim/retrieve_chunks.py` | **暴力法**：查出某文件全部 chunk，Python/numpy 逐条算 cosine，`min_score=0.3` 过滤后取 top_k——**没有任何 SQL 侧向量算子**（不是 `<=>`，就是全表拉回 Python 算），没有索引加速；还会拼一段知识图谱前置关系上下文（`KnowledgeUnit.prerequisites`），不是纯向量 RAG |
| 业务串联 | `services/textbook_qa_service.py` | `index_textbook_file()` 调分块+嵌入写入 `textbook_chunks`；`textbook_qa_stream()` 调检索+丢给 LLM（同样优先 OpenAI `gpt-4o-mini`，兜底 Ollama）流式回答；复用既有 `SocraticSession` 表存会话，没建新会话表 |

**当前环境下这条管线实际跑不通**：实测 `OPENAI_API_KEY` 未配置、Ollama（`ollama:11434`）不可达——两个 embedding provider 都用不了。若现在触发 `index_textbook_file()`，每个 chunk 的 `embed_text()` 都会返回 `None`，写入的是**无嵌入的 chunk**，检索会静默退化成纯关键词匹配，不是语义检索。**这不是代码 bug，是环境未配置**——管线本身逻辑完整、有兜底降级设计，只是两个 provider 选项在这台机器上都没打通（Mneme 其余部分统一用 qwen/DashScope，这条管线目前完全没接 qwen）。

**成熟度评估**：端到端逻辑完整（PDF→分块→嵌入→存储→检索→LLM 回答+引用），有状态跟踪（`index_status`）和错误处理，但**零测试覆盖**，无重试/批处理优化（chunk 间只有 0.05s 睡眠节流），且从未在任何环境真正跑通过一次（`textbook_chunks` 实测 0 行）。定性：**可用的一稿骨架，非生产就绪**。

---

## 4. C4 接入的 Stratum RAG 若拆除，影响面

**全文 grep `rag_client`/`SearchKnowledgeBase`/`search_knowledge_base`，命中面很窄，8 个文件，无一触及核心判分/门控路径：**

| 文件 | 性质 | 拆除需做什么 |
|---|---|---|
| `services/rag_client.py` | 客户端本体 | 整个删除 |
| `services/mcp_router.py` | `tool_search_knowledge_base` 函数 + `SearchKnowledgeBaseReq` + `/mcp/SearchKnowledgeBase` 端点 | 删这三处 |
| `packages/mneme-agent/mneme_agent/assembly/tutor_loop.py` | `search_knowledge_base` 闭包 + 对应 `ToolSpec`（11 个工具中的 1 个） | 删这个工具，`build_tools()` 退回 10 个工具，docstring 工具数说明同步改 |
| `tests/test_rag_client.py`、`tests/test_rag_no_gating_coupling.py`、`tests/test_mcp_search_knowledge_base.py`、`packages/mneme-agent/tests/test_tutor_loop_rag_tool.py`、`packages/mneme-agent/tests/test_tutor_loop_memory_tools.py`（仅工具计数断言 11→10 那一行） | 测试 | 前 4 个整个删除；最后一个改一行断言 |

**`chat_loop.py` 不在上述列表里但功能上间接受影响**：它不直接引用 `rag_client`/`SearchKnowledgeBase` 字符串，只是调用 `build_tutor_loop()` 拿到"当前 `build_tools()` 返回的全部工具"——如果上面删了，`chat_loop.py` 不需要改一行代码，自动少一个可用工具。

**基础设施层面**（不是代码引用，但拆除完整性要考虑）：
- `docker-compose.yml` 的 `stratum-net` 外部网络声明 + `api` 服务的 `STRATUM_*` 三个环境变量透传（纯声明，删不删不影响其他功能，留着也无副作用——没有凭据时 `rag_client` 本就静默返回空列表）。
- `.env` 里的 `STRATUM_SERVICE_EMAIL`/`STRATUM_SERVICE_PASSWORD`/`STRATUM_BASE_URL`（本地文件，未提交）。
- `mneme-api-1` 对 `stratum-net` 的 docker 网络连接（纯网络拓扑，无数据依赖）。
- Stratum 侧的 `mneme-rag-service@sxueji.com` 账号本身不受影响（是 Stratum 自己的用户，Mneme 这边清理跟它无关）。

**结论**：拆除面小而干净——本来就是按"呈现层、可插拔、缺失不阻断"设计的（fail-safe 是刻意为之），红线测试也提前验证过它和门控判定之间没有数据通路。真要拆，是一次**低风险、范围明确**的删除，不会牵连判分/掌握度任何逻辑。

---

## 附：现成可复用 vs 需要新建的对照速览

| 能力需求 | 现成可复用 | 现状 |
|---|---|---|
| 教材原文（数学） | ✅ 22 个 PDF，MinIO 已存，文本层完整 | 直接可用 |
| 教材原文（物理/语文） | ❌ | 未上传 |
| PDF 分块 | ✅ `vendor/oprim/embed_chunks.py` 的段落感知分块 | 代码存在，未提交，未测试 |
| 嵌入生成 | ⚠️ 代码支持 OpenAI/Ollama，**两者当前环境都未配置**；未接 Mneme 已在用的 qwen/DashScope | 需要选一个 provider 并配置，或改接 qwen |
| 向量存储 | ⚠️ 有表结构（`ARRAY(FLOAT8)`），**非 pgvector** | 若走当前设计→现成；若要 pgvector→需换库镜像+改 schema+改检索代码 |
| 向量检索 | ⚠️ 有暴力 cosine 实现，无索引加速 | 小规模能用，量大会慢（全量拉回 Python 算） |
| 外部检索服务 | ✅ Stratum（C4 已接通） | 通路验证过，**内容库为空**（同一批教材若不导入 Stratum，两条路都没内容） |
| KC 命名体系 | ✅ KU 与题库 65% 重叠验证过是同一套 | 可直接复用于任何新检索功能的元数据关联 |
