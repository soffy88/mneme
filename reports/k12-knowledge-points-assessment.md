# `k12-knowledge-points` 与 `mneme` 集成评估报告

评估对象：<https://github.com/mmlong818/k12-knowledge-points>
评估时间：2026-10-20
评估快照：`main` @ `9e4b493f464cbea8a42c2ba1f995e24e9b83172f`（`split/index.json` 的 `exported_at` = 2026-10-19T12:02:59Z）
对照基线：`reports/cn-math-taxonomy-assessment.md`、mneme 现有 `data/ku_packages/`（47 包 11,646 KU）与已集成的 `data/cn_math_taxonomy/`

---

## 结论摘要

| 问题 | 结论 |
| :--- | :--- |
| 数据本身能用吗 | **不能直接入库**。知识点只有名字，正文/描述 100% 为空，无法支撑 mneme 的 `rich_content`、讲解与判题；粒度过细且重复率高。 |
| 许可证能商用吗 | **不能，连非商业使用也没有授权**。仓库无 `LICENSE` 文件、GitHub API `license: null`、README 与 `meta.json` 均无授权声明 → 默认著作权保留（All rights reserved）。比 `cn-math-taxonomy` 的 CC BY-NC 更严：后者至少允许非商业使用，本仓库连"复制"都没有许可。 |
| 与 cn-math-taxonomy 的关系 | **高度重叠但更差**。初中数学 315 个主题中约 **45%** 在 k12 能按名称匹配到对等点；mneme 自有初中数学 729 个 KU 中约 **33%** 能匹配。cn-math-taxonomy 在结构、内容、课标对齐、题库上全面胜出。 |
| 哪个更适合 `ku_packages` → `knowledge_units` | **cn-math-taxonomy**（已集成）。k12 的字段模型（UUID 主键、无 domain/chapter 落库字段、无 description、关系三分类但无 strength）与 `knowledge_units` 需要的信息量不匹配。 |
| 推荐动作 | **不集成**（NO-GO）。仅把该仓库当作"学科覆盖缺口清单"参考，不复制任何数据；如后续要做多学科扩展，等上游补明确许可证后，只借其**学科/册次清单**，内容自建。 |
| 工作量 | 若强行集成：初中数学单科约 **16.5–21.5 人日**，全量 33,765 KP 约 **330–430 人日**（因为等于从零重写全部内容），且始终卡在许可证上。 |

---

## 一、仓库概况

### 1.1 规模

| 指标 | 数值 | 来源 |
| :--- | ---: | :--- |
| 知识点总数 | **33,765** | `meta.json`、`README.md`、`split/index.json` 三处一致 |
| 关系总数 | **21,536** | 同上 |
| 覆盖学段 | 3（小学 / 初中 / 高中） | `meta.json.grade_bands` |
| 覆盖学科 | **17** | `meta.json.subjects` |
| 覆盖教材 | 347 本（293 本有正文抽取，54 本仅目录标题） | `README.md` |
| 拆分文件 | 39 个（学段×科目） | `split/index.json` |

学段分布（`split/index.json` 逐文件汇总）：

| 学段 | 知识点 | 关系 | 数据量 |
| :--- | ---: | ---: | ---: |
| 小学 | 12,358 | 6,480 | 34.6 MB |
| 初中 | 12,746 | 8,922 | 37.5 MB |
| 高中 | 8,661 | 6,134 | 26.0 MB |
| **合计** | **33,765** | **21,536** | **98.1 MB** |

学科分布（全学段合计）：

| 学科 | 知识点 | 关系 | 学科 | 知识点 | 关系 |
| :--- | ---: | ---: | :--- | ---: | ---: |
| 语文 | 7,843 | 4,650 | 生物 | 1,476 | 1,272 |
| 数学 | 4,607 | 3,701 | 地理 | 1,320 | 1,056 |
| 英语 | 2,936 | 1,191 | 物理 | 1,265 | 1,235 |
| 思政 | 2,867 | 1,833 | 通用 | 1,248 | 683 |
| 音乐 | 2,317 | 59 | 化学 | 1,072 | 948 |
| 美术 | 2,128 | 1,932 | 艺术 | 950 | 968 |
| 体育 | 1,836 | 635 | 日语 | 120 | 182 |
| 历史 | 1,630 | 1,041 | 科学 | 82 | 60 |
| | | | 俄语 | 68 | 90 |

数学分学段：小学 2,201 KP / 1,755 边，初中 1,683 / 1,124，高中 723 / 822。

### 1.2 文件结构

```
README.md              4.1 KB
knowledge_points.json  89.4 MB   # 全量知识点
kp_relations.json      10.0 MB   # 全量关系
meta.json              870 B     # 元信息 + schema 自述
split/                           # 按学段×科目拆分（README 推荐入口）
  index.json                     # 文件清单 + 各组计数
  初中/数学.json  …（39 个文件，单文件 190 KB–6.5 MB）
```

注意：`split/` **仅含知识点与关系两个数组**，不含教材正文、不含题目、不含课标条文。

### 1.3 数据格式

**知识点**（每行一个 JSON 对象，`split/*.json` 的 `knowledge_points[]`）：

| 字段 | 实际观察 | 可用性 |
| :--- | :--- | :--- |
| `id` | UUID（36 字符，如 `1a490048-a341-4677-a345-f7cdc552b8d7`） | 无语义、不可人读、跨版本不稳定 |
| `canonical_name` | 中文名，最长 38 字 | 唯一实质内容 |
| `subject` / `grade_band` / `curriculum_system` | `数学` / `初中` / `pep-cn` | 冗余但一致 |
| `confidence` | 0.25–0.99 | 可用作过滤 |
| `aliases` | JSON **字符串**（需二次 `json.loads`） | 有，1,680/1,683 非空 |
| `annotations` | JSON **字符串**，嵌套 `knowledgeType` / `difficulty` / `learningObjectives` | 有，但含 `labeledAt` 时间戳等冗余 |
| `summary` | **全部为空字符串** | ✗ |
| `title` | 与 `canonical_name` 同值 | 冗余 |
| `grades` | `["七年级"]` 等；**高中 723 条全部为空** | 高中不可用 |
| `textbooks[]` | `textbook_id` / `textbook_title` / `grade` / `volume` / `chapter_node_id` / `chapter_path` | `chapter_path` 是两级数组 `["第十九章 二次根式", "19.1 二次根式及其性质"]` |

**关系**（`relations[]`）：`from_kp_id` / `to_kp_id` / `relation_type` ∈ `{prerequisite, leads-to, related}` / `source_evidence` / 冗余的 `from_name` / `to_name`。

**关键缺陷**：`prerequisite` 没有 `hard` / `soft` 强弱区分——而 mneme 的 `knowledge_units` 恰恰把两者拆成 `prerequisites` 与 `soft_prerequisites` 两个 JSONB 列（见 `services/models.py:1351`）。另外，关系**不跨学科、不跨学段**（README 自己承认），所以小学六年级 → 初一的衔接边天然缺失，而这正是 K-12 学段贯通最需要的那类边。

---

## 二、数据质量抽样

抽样方法：直接下载 `split/小学/数学.json`（2,201 KP / 1,755 边）、`split/初中/数学.json`（1,683 KP / 1,124 边）、`split/高中/数学.json`（723 KP / 822 边）三份全量文件，逐条统计（均为完整 JSON，可全量校验）。选择数学而非随机科目，是因为它是 mneme 目前内容最深、最容易判断"能不能用"的科目——如果数学都不达标，其他科目只会更差（语文/音乐等科目关系数远低于知识点数，如音乐 2,317 KP 只有 59 条边）。三个学段结论高度一致，说明这是**生成管线的系统性问题，不是个别科目的偶然**。

### 2.1 结构完整性：合格

| 检查项 | 小学数学 | 初中数学 | 高中数学 |
| :--- | :--- | :--- | :--- |
| `id` 唯一 | 2,201 / 2,201 ✓ | 1,683 / 1,683 ✓ | 723 / 723 ✓ |
| 关系端点悬空 | 0 | 0 | 0 |
| 自环 | 0 | 0 | 0 |
| 重复关系三元组 | 0 | 0 | 0 |
| `prerequisite + leads-to` 成环 | **0（是 DAG）** | 0 | 0 |
| `source_evidence` 非空 | 100% | 1,124 / 1,124（100%） | 822 / 822 |
| `chapter_path` 非空 | 100% | 1,683 / 1,683（100%） | 100%（模块级） |

图结构本身是干净的：无环、无脏边、边都带一句人写的理由（如"AA 是相似最简判定，自然引出 SAS"）。这是该仓库最值得肯定的部分。

### 2.2 内容完备度：不合格（致命）

| 检查项 | 小学数学 | 初中数学 | 高中数学 |
| :--- | :--- | :--- | :--- |
| `summary` 为空 | **2,201 / 2,201（100%）** | **1,683 / 1,683（100%）** | **723 / 723（100%）** |
| 是否有 `description` 字段 | **无此字段** | 无 |
| 是否有题目/例题 | **无** | 无 |
| 是否有课标条文/代号 | **无** | 无 |
| 是否有掌握标准（mastery criteria） | **无** | 无 |

也就是说，这套数据本质上是**"带先修边的标题列表"**。对比 mneme 的 `knowledge_units`：一个 KU 需要 `description`、`rich_content`（`definition` / `intuition` / `examples` / `key_points` / `common_mistakes` / `counter_examples` 等 9 个字段）、`mastery_levels`、`question_types`、`curriculum_standard`、`source_excerpt`。k12 能填的只有 `name` 一个字段，其余全部要重新生成——**集成成本 ≈ 从零建设成本**。

### 2.3 粒度与重复：不合格

- **粒度过细**：初中数学 1,683 个 KP 对应 6 册教材，平均每册 280 个点；而 mneme 现有同范围是 729 个 KU（`RENJIAO-G7..G9-MATH`），人教版初中数学实际章节知识点约 300–400 个。k12 的粒度是"微技能点"，大量条目是同一个知识点的不同切面。
- **同文件内完全同名**：小学数学 27 组、初中 1 组、高中 3 组，共 **31 组重名**，每组名称完全相同但 UUID 不同（如小学的 `0和任何数相乘都得0` 出现两次、`1～5的数字符号认读与书写` 出现两次）。这说明去重环节按"抽取来源"而非按"语义"工作，连字符串级去重都没做。
- **近重复量化**：按名称归一化（去括号内容、去"的/性质/辨析/应用/概念"等修饰词）后，小学有 **104 组、234 条（10.6%）**、初中有 **63 组、145 条（8.6%）** 落在同一簇内。实例：

  | 同一知识点的多个条目 |
  | :--- |
  | `0作为正负数分界点的特殊地位（非正非负）` / `0的正负归属辨析` / `0的特殊地位（非正非负）` |
  | `多项式的次数（最高次项次数）` / `多项式次数判断` |
  | `二元一次方程组的图象解法` / `二元一次方程组的图象解法与交点意义` |
  | `一元一次不等式组解集的四种情形` / `一元一次不等式组解集的四种标准情形判断` |
  | `三角形外角定理的应用` / `三角形外角定理（外角等于不相邻两内角之和）` / `三角形外角性质定理` |

  README 声称做了"同科目去重合并"，从数据看**合并基本没有生效**。若直接入库，会造成同一知识点的 P(L) 被拆到多个 `kc_id` 上，BKT 掌握度被稀释——这是对 mneme 核心算法最实质的伤害。
- **孤儿节点**：小学数学 **633 个（28.8%）**、初中数学 **407 个（24.2%）**、高中数学 26 个（3.6%）没有任何边。四分之一以上的节点无法进入先修图，等于对推荐/诊断不可见。
- **元知识点混入**：小学 43 条、初中 37 条（2.2%）、高中 34 条（4.7%）是"本章小结""思维导图""全章复习"这类教学组织条目，不是可测的知识点。

### 2.4 置信度与元数据

| 指标 | 小学数学 | 初中数学 | 高中数学 |
| :--- | :--- | :--- | :--- |
| `confidence` 均值 | 0.848 | 0.891 | **0.772** |
| `< 0.6` | 274（12.4%） | 119（7.1%） | **105（14.5%）** |
| `< 0.5` | 262（11.9%） | 116（6.9%） | **93（12.9%）** |
| `knowledgeType` 分布 | procedural 805 / conceptual 725 / metacognitive 85 / factual 68 | conceptual 366 / procedural 297 / factual 34 / metacognitive 26 |
| 抽取模型 | qwen-plus 1,568 + claude-sonnet 115 | claude-sonnet 723 |
| `difficulty` 均值 | 0.44 | 0.51 |

`annotations` 里的 `knowledgeType` / `difficulty` 是 LLM 标注且**自带置信度**，这部分设计思路不错（与 mneme 的 `ai_generated` / `verified` 双标记同构）。但 README 自己写明：54 本教材无正文、仅按目录标题抽取，这类条目置信度系统性偏低——高中数学 14.5% 低于 0.6 就是证据。

### 2.5 抽样结论

| 维度 | 评价 |
| :--- | :--- |
| 图结构（无环、无脏边、边带理由） | ✅ 可用（三个学段均成立） |
| 元数据设计（置信度、类型、来源教材、章节路径） | ✅ 思路正确 |
| 节点内容（讲解、例题、判题依据） | ❌ 零（三个学段 `summary` 均 100% 为空） |
| 粒度与去重 | ❌ 需重做（重名 31 组、近重复 8.6%–10.6%） |
| 字段与 mneme 的匹配度 | ❌ 主键、强弱边、学段贯通、课标代号都缺 |
| 整体 | **只能当"覆盖度清单"用，不能当数据源用** |

---

## 三、许可证风险

### 3.1 事实认定

| 检查 | 结果 |
| :--- | :--- |
| 仓库根目录文件 | `README.md`、`knowledge_points.json`、`kp_relations.json`、`meta.json`、`split/` — **无 `LICENSE` / `COPYING` / `NOTICE`** |
| GitHub API `license` 字段 | `null` |
| README 中的许可/版权/引用章节 | **无**（全文检索"许可/协议/license/商用/版权/引用/cite"零命中） |
| `meta.json` | 只有 `exported_at` / 计数 / `schema`，无任何授权信息 |
| 仓库描述 | 仅"K12全学段知识点数据集（…33,765个知识点+21,536条关系）" |

### 3.2 法律后果

按《伯尔尼公约》与《中华人民共和国著作权法》，作品完成即自动取得著作权，**无许可证 = 默认"保留所有权利"（All rights reserved）**。这意味着：

- ❌ 不能复制进本仓库（连 `data/` 快照都不行）
- ❌ 不能修改、翻译、汇编
- ❌ 不能随产品分发
- ❌ 不能商用
- ❌ 连"非商业使用"都不在授权范围内（这一点比 CC BY-NC 严格）

对比 mneme 现有做法：`data/cn_math_taxonomy/` 是 **CC BY-NC 4.0**——至少明确允许非商业复制与再分发，只需署名并保留许可证全文（项目已按 `UPSTREAM.json`（sha256）+ `NOTICE.md` + `LICENSE` 三件套落地，见 `TASKS.md` CNM-2）。**k12 连这个前提都不成立。**

### 3.3 叠加风险：上游教材版权

README 自述构建链路：**国家中小学智慧教育平台逐页预览图 → OCR → LLM 抽取 → 关系推断**。即便作者日后补发 CC BY 4.0：

1. 教材正文的著作权属于人民教育出版社等出版机构，**平台"可浏览"不等于"可再许可"**；
2. OCR 转录文本属于复制行为，其产物是原作品的演绎物；
3. 作者本人可能并不持有再许可的权利，其授权存在**权利瑕疵（chain of title 断裂）**。

因此本仓库的许可证风险是**双层**的：仓库层（无许可）+ 源头层（教材版权），后者无法通过"联系作者要授权"彻底解决。

### 3.4 风险处置

- 若将来仍要使用：**必须同时**取得 ① 作者书面授权（明确允许商业使用与再分发）② 对教材原文的合法来源说明（或确保数据中不含教材原文，只有自创的名称/结构）。
- 在此之前，**只做阅读与统计，不落盘、不入库、不进 git**。本报告仅引用聚合统计量（计数、分布、比例），未复制任何知识点文本以外的实质内容；报告中出现的少量名称示例属于为说明重复问题所必需的引用，若后续有法务意见要求，应立即删除。

---

## 四、与 `cn-math-taxonomy` 的对比

### 4.1 事实对比

mneme 已集成的 `cn-math-taxonomy`（`data/cn_math_taxonomy/`，快照 commit `3251221`）：

| 维度 | **cn-math-taxonomy**（已集成） | **k12-knowledge-points**（本报告） |
| :--- | :--- | :--- |
| 学段 | 1–9 年级（小学 216 + 初中 315） | **K-12 全段**（小学 12,358 / 初中 12,746 / 高中 8,661） |
| 学科 | **仅数学** | **17 科**（语文/英语/物理/化学/生物/历史/地理/政治/音乐/美术/体育/日语/俄语/科学/艺术/通用/思政） |
| 知识点 | 531 个主题 | 33,765 个 KP |
| 粒度 | 教材小节级（如"勾股定理"） | 微技能级（如"√[n]{a^n}的化简（根式基本性质）"） |
| 关系 | 909 条，**788 hard + 121 soft** | 21,536 条，`prerequisite` / `leads-to` / `related`，**无强弱** |
| 节点正文 | **有 `description` + `mastery_criteria` + `diagnostic_question`** | **无（`summary` 全空）** |
| 题库 | **2,271 题**（basic/standard/advanced；numeric/choice/short/self） | **无** |
| 课标对齐 | **230 条课标原文**（2022 版，含逐条 `verbatim` 与页码策略） | 无课标代号，只有教材章节路径 |
| 主键 | `cnm_xxx` 语义化、稳定、可人读 | UUID，无语义、跨版本不稳 |
| 学段贯通 | 一至九年级同图，跨学段有边 | **不跨学段建边** |
| 去重 | 人工/脚本维护，531 条无近重复簇 | 8.6% 近重复、24.2% 孤儿 |
| 许可证 | **CC BY-NC 4.0**（非商业可用，署名） | **无许可证**（默认保留所有权利） |
| 与 mneme 的接法 | `services/cn_math_importer.py` → `cnmath:*` KU + `prereq_graph`/`prereq_judge`/`prereq_diagnosis` 移植 + 4 个 MCP 工具 + `/v1/placement/prereq/*` | 无 |

### 4.2 重叠量化

方法：字符二元组 Jaccard 相似度做名称匹配（粗略代理，非语义匹配，数字应视为上下界估计）。

| 比对 | 阈值 | 匹配数 | 比例 |
| :--- | :--- | ---: | ---: |
| cn-math-taxonomy 初中 315 主题 → k12 初中数学 | ≥ 0.4 | **142** | **45.1%** |
| mneme 自有初中数学 729 KU → k12 初中数学 | ≥ 0.5 | **239** | **32.8%** |

典型完全同名（相似度 1.0）：`直线与圆的位置关系`、`直接开平方法`、`用正负数表示相反意义的量`、`用坐标表示地理位置`、`点与圆的位置关系`、`正方形的性质与判定`。

未被匹配的主要是 cn-math-taxonomy 的"综合与实践"类主题（如"综合与实践：低碳生活""进位制的认识与探究"）——**k12 缺的不是知识点的另一种说法，而是项目式/跨学科内容**。

### 4.3 互补性

k12 真正独有的价值只有两块：

1. **学科广度**：mneme 目前只有语文（7,700 KU）、数学（2,395）、物理（1,551）三科。化学、生物、历史、地理、政治、英语（作为 KU 体系而非词汇 FSRS）都是空白。k12 是唯一"看起来覆盖全"的公开数据。
2. **高中各科模块清单**：可作为"还缺哪些必修/选择性必修模块"的粗参考——但 README 自述高中部分**未逐科核对模块完整性**，且 `grades` 字段在高中 723 条数学数据中 100% 为空，只能靠 `textbooks[].volume` 的模块名判断，不能当权威清单用。

但这两块都**不能靠导入 k12 数据来补**——因为它没有内容。正确用法是：把 k12 的 `split/index.json` 当成"学科×学段×册次"的**需求矩阵**，逐格判定 mneme 有无覆盖，缺的格子走既有 `ku_packages` 生产线自建。

### 4.4 哪个更适合 `ku_packages` → `knowledge_units`

**cn-math-taxonomy 明显更适合**，逐条对应 `knowledge_units` 的列：

| `knowledge_units` 列 | cn-math-taxonomy | k12 |
| :--- | :--- | :--- |
| `id` (String(100)) | `cnmath:cnm_221`，可读、稳定 | UUID，需额外映射表 |
| `textbook_id` (String(50)) | 统一 `CN-MATH-2024` | 347 本教材 → 347 个 textbook 行，每册还要 `subject/grade/edition/book_name` 四字段，需从 `textbook_title` 反解析 |
| `cluster_id` (String(80)) | `domain`（数与代数/图形与几何/…） | 无 domain 字段，只能用 `chapter_path[0]` 现造 |
| `description` | 有 | **空** |
| `prerequisites` / `soft_prerequisites` | **hard / soft 天然分列** | 只有 `prerequisite`，无强弱 |
| `mastery_levels` | `mastery_criteria` 数组 | 无 |
| `curriculum_standard` | 230 条课标，带 `id`/`confidence` | 无 |
| `rich_content` | 直接承载 `diagnostic_question` + 题库 | 无 |
| `exam_region_tags` | 由 `grade` 推导 | `grade_band` 太粗 |
| `provenance` | 有 `UPSTREAM.json` + commit | 无 commit 级溯源（只有 `exported_at`） |

结论：**k12 的 schema 与 `knowledge_units` 之间不是"字段改名"的距离，而是"缺一半列"的距离。**

---

## 五、集成方案与工作量估算

### 方案 A（推荐）：不集成，仅作覆盖度对照

- 不复制任何数据进仓库。
- 把 `split/index.json` 的 39 个"学段×学科"格子整理成一张**覆盖度矩阵**，与 mneme 现有 47 个 `ku_packages` 对齐，标出空白格（化学/生物/历史/地理/政治/英语等）。
- 空白格的填补走既有生产线：教材 → `book_compile` → `ku_packages` → `import_ku_package.py`。
- 工作量：**0.5 人日**（做矩阵 + 写进 `TASKS.md` 作为后续学科扩展的输入）。
- 风险：无（不复制数据，无许可问题）。

### 方案 B（条件集成，仅在许可证落实后）

触发条件（**必须同时满足**）：① 上游补 `LICENSE`（CC BY 4.0 或明确书面商用授权）② 教材原文来源合法性可解释（或不含教材原文）。

落地步骤与估算（以**初中数学单科**为试点）：

| 步骤 | 内容 | 人日 |
| :--- | :--- | ---: |
| 1 | 快照 + `UPSTREAM.json` + `NOTICE.md`（沿用 cn-math-taxonomy 三件套） | 0.5 |
| 2 | 格式转换脚本 `scripts/import_k12_kp.py`：`split/*.json` → `ku_packages`（UUID→稳定 slug、`chapter_path`→cluster、`textbooks[]`→textbook） | 1.5 |
| 3 | 近重复合并（63 簇 145 条，需人工确认合并方向） | 2.0 |
| 4 | 孤儿节点处理（407 条：补边 or 剔除，逐条判断） | 1.5 |
| 5 | 强弱边拆分（`prerequisite` → hard/soft 需按教学重要性人工标注） | 2.0 |
| 6 | `rich_content` 补齐（1,683 个 KU × 9 字段，LLM 生成 + 抽检） | 5.0–8.0 |
| 7 | 教研校验（一线教师抽检 ≥10%） | 3.0–5.0 |
| 8 | 导入 + `validate.py` + 回归测试 | 1.0 |
| **合计（初中数学单科）** | | **16.5–21.5 人日** |

全量 33,765 KP 按同比例外推 ≈ **330–430 人日**（≈ 1.5–2 人年），且第 6、7 步是纯新增内容生产——**这时候 k12 提供的"边"是否还值得，已经存疑**。

### 方案 C（不推荐）：直接导入标题 + 边，内容留空

- 工作量约 3 人日，能快速得到一张跨 17 科的知识网。
- 但会产生 33,765 条 `rich_content = NULL` 的 KU，直接污染 mneme 的内容层：`retrieve_chunks` 取不到讲解、`book_compile` 视其为空壳、agent 讲解降级、前端出现大量"有名字没内容"的卡片。
- 更严重的是 8.6% 近重复会让同一知识点的 BKT 掌握度分裂到多个 `kc_id`，**破坏"掌握度唯一路径"这条红线**（`AGENTS.md`）。
- 因此**明确否决**。

---

## 六、推荐结论

### 决策：不集成（NO-GO）

三条独立理由，任一条都足以否决：

1. **许可证硬阻断**：无 `LICENSE`、无授权声明、GitHub `license: null` → 默认保留所有权利，连非商业复制都不允许；且源数据来自教材 OCR，存在上游版权瑕疵，作者也无权再许可。这不是"注意一下"的风险，是**法律上不能做**。
2. **内容为零**：`summary` 100% 为空、无描述、无题库、无课标、无掌握标准。集成它等于只拿到一张标题列表，而 `rich_content` 需要从零重写——成本与自建持平，却额外背上许可负担。
3. **重叠且更差**：与已集成的 cn-math-taxonomy 重叠 45%，与 mneme 自有初中数学重叠 33%；同时在粒度（过细 2.3 倍）、去重（8.6% 近重复）、图连通性（24.2% 孤儿）、学段贯通（不跨学段建边）四项上全面落后。

### 保留价值（不落数据）

- 把 `split/index.json` 作为**学科×学段覆盖矩阵**，用于规划 mneme 后续学科扩展（化学/生物/历史/地理/政治/英语）。
- 其 `confidence` + `annotations.knowledgeType/difficulty` 的**带置信度标注**设计，可作为 mneme `ai_generated` / `verified` / `provenance` 三件套的参照。

### 复审触发条件

满足以下**全部**条件后，可重新评估方案 B：

- [ ] 上游仓库出现 `LICENSE` 文件，且 GitHub API `license` 非 `null`
- [ ] 许可证允许商业使用与再分发（CC BY 4.0 / MIT / 作者书面授权）
- [ ] 数据中不含教材原文，或提供教材内容的合法来源说明
- [ ] mneme 明确要开一个新学科，且该学科的 k12 数据经抽样 `summary` 非空率 > 80%

在触发条件满足前，本报告的结论保持有效。

---

## 附：本次评估的复现方式

```bash
# 数据获取（仓库 100 MB，建议按需取 split/，不要整仓 clone）
curl -sL -o meta.json  https://raw.githubusercontent.com/mmlong818/k12-knowledge-points/main/meta.json
curl -sL -o index.json https://raw.githubusercontent.com/mmlong818/k12-knowledge-points/main/split/index.json
curl -sL -o cz.json    "https://raw.githubusercontent.com/mmlong818/k12-knowledge-points/main/split/%E5%88%9D%E4%B8%AD/%E6%95%B0%E5%AD%A6.json"

# 交叉核对 mneme 侧
python3 -c "import json;d=json.load(open('data/cn_math_taxonomy/topics.json'));print(len(d))"
python3 -c "import json;d=json.load(open('data/ku_packages/RENJIAO-G7-MATH-S.json'));print(len(d['units']))"
```

许可证核查：

```bash
curl -s https://api.github.com/repos/mmlong818/k12-knowledge-points | python3 -c "import json,sys;print(json.load(sys.stdin)['license'])"   # → None
curl -s https://api.github.com/repos/mmlong818/k12-knowledge-points/contents/ | python3 -c "import json,sys;print([x['name'] for x in json.load(sys.stdin)])"  # → 无 LICENSE
```
