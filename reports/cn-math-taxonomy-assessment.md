# `cn-math-taxonomy` 与 `mneme` 数学知识体系评估报告

> **结论摘要**
> `cn-math-taxonomy`（xiaoyang111222/cn-math-taxonomy）是一套基于 2022 年版数学新课标与人教版 2024 审定版教材、完全采用 Marble 格式（`topics.json` + `dependencies.json`）构建的初中数学（七至九年级）有向无环图知识图谱（包含 315 个正式知识点、18 个小学先修节点及 616 条先修边），并配有课标对齐（157 条）、多选题库（1407 题）和静态诊断引擎。
> **与 mneme 关系**：mneme 现有体系聚焦于广东高中数学 KC 字典及细颗粒度 KU（Knowledge Units，含丰富正文、确定性求解内核与多维矩阵），对于初中阶段尚缺少一套结构清晰、符合最新人教版目录且具备明确先修边（hard/soft）的初中数学知识网。
> **集成评估**：若要集成，建议作为 mneme 初中数学知识体系的**顶层结构基线（Knowledge Units / Curriculum Topology Reference）**引入，通过知识点 ID 对齐或将其包装为 `ku_packages` 导入 mneme 的 `knowledge_units` 表；工作量约 2–3 人日（格式转换与双向映射脚本编写）；主要风险在于 AI 初稿未经过一线初中教师人工审核，部分先修边和九下目录为第三方推定，需在入库前通过教研进行二次校准。

---

## 一、 `cn-math-taxonomy` 仓库深度解析

### 1. 内容与结构
该仓库由开发者 `xiaoyang111222` 于 2026 年初开源，旨在建立一个覆盖中国初中数学（七年级上册至九年级下册）的机器可读知识图谱。其核心文件分布在 `data/` 目录下：
- **`topics.json`**：共 333 个节点（315 个正式初中知识点 + 18 个小学外部先修节点）。每个节点包含 `id`（`cnm_NNN`）、`name`、`domain`（数与代数、图形与几何、统计与概率、综合与实践）、`grade`（7-9 / 小学）、`semester`、`chapter`（人教版 2024 新版章节）、`type`（conceptual, procedural, reasoning, application, modeling）、`description`、`mastery_criteria`、`diagnostic_question`、`standards`（课标条目映射）等。
- **`dependencies.json`**：共 616 条有向依赖边，采用 `{ "topicId": "A", "prerequisiteId": "B", "strength": "hard"/"soft", "reason": "..." }` 格式。明确区分了硬先修（hard）与软先修（soft），并通过传递约简剔除了冗余边。
- **`cn-curriculum-standards.json`**：收录了教育部《义务教育数学课程标准（2022年版）》第四学段（7–9年级）的 157 条内容要求。
- **`questions.json`**：扩展题库，给 315 个正式知识点各配 4–5 道题，共 1407 题，涵盖 basic、standard、advanced 难度，以及 numeric、choice、short、self 题型。
- **`diagnose/`**：一套自适应诊断单页面应用，支持基于先修关系拓扑的自适应追问。

### 2. 数据规模与分布
- **正式知识点总数**：315 个
- **领域分布**：数与代数 142 个，图形与几何 117 个，统计与概率 43 个，综合与实践 13 个。
- **册次分布**：七上 61，七下 58，八上 57，八下 57，九上 49，九下 33。
- **边密度**：616 条先修边（平均每个正式知识点 1.92 条先修），末端节点 63 个。

### 3. 许可证
该项目明确采用 **CC BY-NC 4.0（知识共享 署名-非商业性使用 4.0 国际许可协议）** 授权。
- **允许**：免费用于个人学习、教学、研究，修改和再分发（需署名并注明来源）。
- **禁止**：不得用于任何商业用途（如付费课程、付费 App、机构收费服务、售卖题库等）。如需商业化，需联系原作者获取单独授权。

---

## 二、 `mneme` 现有数学知识体系审视

根据 `mneme` 仓库（特别是 `MNEME_MASTER_DESIGN.md`、`data/guangdong_math_kc.py` 及 `data/ku_packages/`）的现状：
1. **高中聚焦与初中空白**：mneme 核心是以广东高考/高中数学为主要阵营，拥有精细的高中 KC 字典（`guangdong_math_kc.py`）及约 2395 个高中数学 KU（Knowledge Units）。然而，对于初中数学（衔接 K-12 全周期、作为中考及长线学习档案基础的初中段），现有代码库中缺乏一套系统、结构化、具备严密前置依赖关系的初中知识图谱。
2. **三层设计契合度**：mneme 的 3O 范式（oprim, oskill, omodul）以及 KU/KC 双层体系（KC 负责 BKT 掌握度建模，KU 负责内容组织与呈现）与 `cn-math-taxonomy` 的节点-边设计天然契合。`cn-math-taxonomy` 的节点可以无缝映射为 mneme 体系中的初中段 KU / KC 骨架。

---

## 三、 两者关系分析：补齐、重叠与冲突

| 维度 | 分析说明 | 评估结论 |
| :--- | :--- | :--- |
| **互补（能补什么）** | `cn-math-taxonomy` 提供了高密度的**初中数学知识网、先修依赖边（hard/soft）、2024 新版人教版章节目录、课标第四学段对齐（157条）及 1407 道诊断/练习题库**。mneme 正好以此补齐 K-12 初中段的图谱基础。 | **强补齐**：直接填补初中段知识结构与题库空白。 |
| **重叠（重叠什么）** | 两者均采用 JSON/结构化数据形式表达知识单元，均强调与中国现行课程标准（2022版）及人教版教材对齐。格式上，Marble 规范与 mneme 的 `ku_packages` 存在语义映射空间。 | **低代码冲突**：属于不同学段（初中 vs 高中）或不同数据源的合并，无底层架构冲突。 |
| **冲突/风险（冲突什么）** | 1. **审核状态**：`cn-math-taxonomy` 是纯 AI 生成的初稿，未经一线教师人工审核，部分九下目录为第三方推定。<br>2. **许可证限制**：CC BY-NC 4.0 属于**非商业授权**。如果 mneme 未来进行商业化部署（如收费版、企业服务），直接内嵌该仓库的代码/数据将触发许可证合规风险。<br>3. **粒度差异**：图谱的 `cnm_NNN` 粒度偏向概念/小节，而 mneme 的 KU 体系包含更丰富的富文本 (`rich_content`) 与确定性求解内核。 | **合规与教研风险**：需隔离商业使用边界，并安排教研复核。 |

---

## 四、 具体集成方案与实施规划

若决定将 `cn-math-taxonomy` 的价值引入 mneme（在遵守 CC BY-NC 4.0 非商业条款前提下），建议采取**“离线转换、按需挂载、教研校验”**的方案：

### 1. 映射方式与入库位置
- **转换脚本**：编写 `scripts/import_cn_math_taxonomy.py`（仅作为内部工具或开源工具链扩展），将 `cn-math-taxonomy` 的 `topics.json` 与 `dependencies.json` 转换为 mneme 标准的 `ku_packages` 格式。
- **入库位置**：
  - 正式知识点存入 `knowledge_units` 表（或扩展独立的初中数学 KU 包，如 `RENJIAO-JUNIOR-MATH`）。
  - 先修边写入 `knowledge_units` 的前置依赖字段或构建对应的图邻接表，供 `path_builder.py` 和前置门控（Gate）使用。
  - 题库部分导入 `seed_question_bank.json` 或 `question_records` 供初中自测使用。

### 2. 工作量评估
- **数据格式对齐与编写转换脚本**：0.5 人日
- **批量导入与数据库验证（运行 `validate.py` 与迁移测试）**：0.5 人日
- **教研抽样校准（针对关键 Hard 边与九下目录）**：1.0 - 2.0 人日
- **总计工作量**：约 **2 至 3 人日**。

### 3. 风险防范
1. **许可证隔离**：在仓库文档与代码声明中明确标注初中数学图谱源自 `cn-math-taxonomy` 且受 CC BY-NC 4.0 约束，设置构建或打包门禁，确保商业发布版本（Commercial Build）中自动剥离或替换该部分非商业数据。
2. **确定性优先与教研兜底**：由于初中图谱为 AI 生成初稿，mneme 的核心求解内核（如 sympy 运行沙箱）及确定性规则依然是判题与步骤校验的唯一真相源，不依赖图谱自带的粗颗粒度答案。

---
*报告生成完毕。按照指令，已将本报告保存至 `/data/soffy/projects/mneme/reports/cn-math-taxonomy-assessment.md`，且未修改 mneme 仓库中除此报告之外的任何其他文件。*
