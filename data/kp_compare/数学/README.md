# 数学 · k12-knowledge-points 对照数据（仅内部比对）

本目录是 **一次性对照审计** 的产物，不是可入库的知识点数据。

## 为什么不能入库

上游仓库 <https://github.com/mmlong818/k12-knowledge-points> **没有 LICENSE**
（GitHub API `license: null`，README/meta.json 也没有授权声明），按著作权法默认
“保留所有权利”；其数据来自教材页面 OCR，还存在上游教材版权瑕疵。因此：

- 本目录只保存 **名称、章节归属、类型、难度** 等比对所需的字段；
- **不复制** 上游的 `summary` / `learningObjectives` / `misconceptions` 等正文；
- **不导入** `knowledge_units`，不参与 `rich_content`、判题、掌握度计算；
- 结论只用于回答“mneme 还缺哪些考点”，缺口内容一律自建。

`knowledge_units` 的唯一合法来源仍是 `data/ku_packages/`（自建）与
`data/cn_math_taxonomy/`（CC BY-NC 4.0）。

## 文件

| 文件 | 行数 | 说明 |
| :--- | ---: | :--- |
| `k12_names.csv` | 4,599 | 数学三学段知识点名称，按学段/年级/册/章节排序，已按 `(学段,年级,册,名称)` 去重 |
| `compare.csv` | 155 | 逐章比对：教材章节 × 考点 × k12 × mneme KU |
| `compare_points.csv` | 857 | 逐考点明细：每个考点的 k12 对应名称/匹配分、mneme 对应 KU/匹配分 |

### `k12_names.csv` 字段

`学段, 年级, 册, 章节, 知识点名称, 知识类型, 难度, 置信度, 别名, 来源教材, 合并来源数`

- 知识类型：上游 `annotations.knowledgeType.value`（conceptual / procedural / factual / metacognitive）
- 难度：上游 `annotations.difficulty.value`（0–1，LLM 标注）
- 章节：同一知识点在旧版/新版教材中出现的全部章节，`；` 分隔
- 合并来源数：同一 `(学段,年级,册,名称)` 合并了多少条上游记录（旧版/新版重复）

### `compare.csv` 字段

| 字段 | 口径 |
| :--- | :--- |
| 教材节数 | 该章在教材目录中的节数（小学为单元内栏目数） |
| 考点数 | 对照锚点总数 = 教材节 + 课标内容要求（cn_math_taxonomy 主题）+ 中考/高考高频考点 |
| 考点清单 | 每个考点后标注来源：`[课标]` / `[教材]` / `[考频]` |
| k12知识点数 | 落到该章的 k12 知识点（去重后） |
| k12严格覆盖考点数 / 严格覆盖率 | 名称归一 + 术语/二元组匹配 ≥0.55 视为覆盖 |
| 表述差异数 | 字符串未命中、但人工复核确认 k12 以子点/同义表述覆盖的考点 |
| 移位覆盖数 | 该考点在 k12 同章没有，但在同册/同学段其他章有 |
| 复核后覆盖率 | (严格覆盖 + 表述差异 + 移位覆盖) / 考点数 |
| 覆盖判定 | 复核后覆盖率 ≥90% 且无真缺口 = 覆盖；≥65% = 基本覆盖；<65% = 部分覆盖；“不适用”为综合与实践/总复习/活动课 |
| 真缺口清单 | 复核后仍无 k12 对应的考点（本表最重要的一列） |
| 多余/过细数 | 在本章找不到直接对应考点的 k12 点数（含细分展开、跨章重复、版本差异） |
| 版本差异点数 | 教材章节名对不上当前 PDF 目录的 k12 点（旧版/其他版本教材） |
| mneme对应KU数 / 覆盖考点数 / 覆盖率 | mneme 现有数学 KU 与本章考点的匹配 |
| 学段/册错位数 | k12 点在全库最相似考点落在其他学段，或章节归属跨册 |

### `compare_points.csv` 字段

`学段, 年级, 册, 章, 考点, 考点来源, k12对应名称, 匹配分, 判定, mneme对应KU, 匹配分`

判定：`覆盖` / `已覆盖(表述差异)` / `非考点` / `缺口`。

## 方法

1. **k12 侧**：读取 `split/{小学,初中,高中}/数学.json`，解析
   `canonical_name`、`grades`、`textbooks[].grade/volume/chapter_path`、
   `annotations.knowledgeType/difficulty`、`confidence`；按
   `(学段,年级,册,名称)` 去重，合并别名与章节。
2. **教材基线**：仓库内 23 册人教版教材 PDF 的目录页
   （`curriculum_standards/G*_*_数学*.pdf`，`pdftotext -layout` 抽取第 5–7 页），
   人工整理为 155 章/单元；人教A版必修第二册无本地 PDF，用
   `data/ku_packages/RENJIAO-G10-MATH-BX2.json` 的 clusters 与 k12
   `chapter_path` 互核。
3. **考点**：
   - 小学/初中：`data/cn_math_taxonomy/topics.json` 的 531 个主题（其中 460 个能映射到当前目录，课标 2022 版对齐）
     + 教材节 + 中考高频考点（教研归纳）；
   - 高中：教材节 + `curriculum_standards/高中_数学_KU.json`（课标 2017 版 2020 修订）
     + 高考高频考点（教研归纳）。
4. **匹配**：NFKC 归一 → 去括号（保留 SSS/SAS/HL 等符号）→ 数字区间归一
   （1～5 = 1-5 = 1到5）→ 别名表 → 包含关系 → 字二元组 Dice → 术语命中。
   阈值 0.55。聚合型考点（如“集合的基本运算”“全等判定”）按组件覆盖
   （交集/并集/补集、SSS/SAS/ASA/AAS/HL）。
5. **人工复核**：对全部字符串判为缺口的考点逐条检查 k12 同章/同学段知识点的
   实际表述，把“同义改写/子点拆分/移位覆盖”与“真缺口”分开。
   生成时内置复核表 `GAP_REVIEW`（56 条判定），复核表不随数据入库。

## 已知局限

- 名称匹配无法理解语义，严格覆盖率是**下界**；复核后覆盖率仍可能有 ±3–5% 误差。
- k12 混用 2011/2022/2024 版人教教材（如小学 1–2 年级 2024 版、3–6 年级旧版；
  初中 7–8 年级 2024 版、九年级 2011 版），章节名与当前 PDF 目录不完全一致，
  已单列“版本差异点数”。
- 中考/高考没有官方“考点大纲”，考频项来自教研归纳，不是教育部条文。
- 高中必修第二册目录未从 PDF 抽取（仓库无该册 PDF），以 KU 包 clusters 与 k12
  章节路径互核。

## 来源

| 用途 | URL / 路径 |
| :--- | :--- |
| 义务教育数学课程标准（2022 年版） | <http://www.moe.gov.cn/srcsite/A26/s8001/202204/t20220420_619921.html> |
| 课标 PDF | <http://www.moe.gov.cn/srcsite/A26/s8001/202204/W020220510531636118932.pdf> |
| 普通高中数学课程标准（2017 年版 2020 年修订） | <http://www.moe.gov.cn/srcsite/A26/s8001/202006/t20200603_462199.html> |
| 人教社教材电子版（目录核对入口） | <https://jc.pep.com.cn/> |
| 教材 PDF 快照（23 册） | `curriculum_standards/G*_*_数学*.pdf` |
| 高中课标 KU | `curriculum_standards/高中_数学_KU.json` |
| 义教课标条目 | `data/cn_math_taxonomy/cn-curriculum-standards.json` |
| k12 上游 | <https://github.com/mmlong818/k12-knowledge-points>（无许可证） |

数据快照：k12 `exported_at=2026-10-19T12:02:57Z`；mneme 比对基线
`data/ku_packages/`（数学 2,389 KU）；审计日期 2026-10-20。
