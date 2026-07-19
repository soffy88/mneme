# MNEME-W4-IMPL-SPEC-001

**类型**：可实施规范（总 spec + 分模块）
**范式**：3O v3.0 + FC-1..FC-7
**范围**：S0 沙箱加固（前置）→ Solve（包装既有内核）→ Visualize（去 Manim）
**推后**：Animator / Research / Notebook / Co-Writer（各有硬理由，§6）
**前置**：`W4-PREWORK-INVENTORY-001`（盘点）

---

## 0. 范围决策（三原则自决，记录理由）

功能至上 ≠ 功能贪多。盘点证明六模式体量/风险差异巨大：

| 模式 | W4 决策 | 理由 |
|---|---|---|
| Solve | 做（包装既有 7 内核，不搬 DeepTutor） | DeepTutor 版比 Mneme 现有弱，搬 = 降级 |
| Visualize | 做（砍 Manim 分支） | 客户端渲染零执行风险，接既有 kernel + 已装 react-three-fiber，最便宜真实赢面 |
| Animator | 推后 | LLM 生成任意 Python 经 subprocess 渲染 = 真沙箱缺口，顺手做 = 安全红线换数量 |
| Research | 推后 | 2800 行单体 + arXiv 依赖，需整个换后端（≥ 整个 Book Engine 工作量） |
| Notebook | 推后 | 横切读写所有模式，更宜作既有归档哲学扩展，非独立模式 |
| Co-Writer | 推后 | 复杂度在富文本编辑器 UI，studio 现无基础 |

**地基声明**：Mneme 至今零真实学习者。W4 同样建在无人使用之上。

---

## 1. S0 —— sympy 沙箱加固（Solve 前置，安全债）

盘点挖出的现存安全洞，W4 Solve 之前先补——包装 Solve 会把这些洞暴露给
更多 LLM 可达入口。

**现状**：sympy 沙箱有 AST 白名单 + fork + OS 级 kill（已测），但：
- `solve_geometry3d` / `solve_probability` 两内核完全绕过沙箱（LLM 可达
  路径无隔离执行）。
- 文档写的 64MB 内存上限从未真正生效（纸面限制）。

**S0 任务**：
1. 两个绕过沙箱的内核纳入统一沙箱路径（AST 白名单 + fork + kill）。
2. 内存上限真正 enforce（`setrlimit` / cgroup，测试验证超限被杀）。
3. 回归测试：7 内核全部经沙箱，无一绕过（结构性断言，防未来新内核再绕）。

**S0 验收**：

| # | 项 | 方法 |
|---|---|---|
| S0-1 | 7 内核全经沙箱，0 绕过 | AST 结构测试 |
| S0-2 | 内存超限实际被杀（非纸面） | 集成测试（喂超限用例，断言 kill） |
| S0-3 | 恶意 LLM 输出（文件读写/网络/import os）被 AST 白名单拦截 | 安全测试 |

**S0 未绿不进 Solve。**

---

## 2. Solve（包装既有 7 内核）

不搬 DeepTutor（其 Solve 是 plan-state-machine bolt-on，比 Mneme 弱）。
Solve 模式 = 给既有确定性求解内核加 studio 面 + 解题步骤展示。

- 求解：既有 7 个 `solve_*` 内核（经 S0 加固后的沙箱）。
- 步骤展示：内核输出的求解步骤结构化呈现（非 LLM 编造过程——确定性求解
  的真实步骤）。
- LLM 角色：仅题面理解 + 步骤转述为自然语言讲解，不参与求解与判分
  （确定性优先）。
- 护栏：Solve 若接入教学循环（解题作为练习），掌握度回流走既有
  `process_interaction` + guard。
- FC-6：Solve 编排带 Mneme 内核假设 → mneme-core 私有。

前端 `/studio/solve`：题面输入 → 求解 → 分步展示 → LLM 讲解。新页面，
原页面零改动。

**Solve 验收**：

| # | 项 | 方法 |
|---|---|---|
| SV-1 | 7 类题各求解正确（复用既有内核测试） | 内核测试 |
| SV-2 | 步骤来自内核真实输出，非 LLM 编造 | 溯源断言 |
| SV-3 | 求解全程经沙箱（S0 保证） | 结构断言 |
| SV-4 | LLM 讲解不改求解结果/判分 | 断言 |
| SV-5 | 若接教学循环，掌握度经 guard 回流 | DB 断言 |

---

## 3. Visualize（去 Manim）

盘点：非 Manim 渲染类型（SVG / Chart.js / Mermaid / 客户端三维）自包含、
客户端渲染、零执行风险，直接接既有 `kernel_to_plot2d` / `kernel_to_three`
/ `generate_svg_diagram` + 已装 `@react-three/fiber`/`three`（现零页面
使用）。

- 渲染类型：SVG 图 / Chart.js 图表 / Mermaid 图 / 客户端三维
  （react-three-fiber）。
- Manim 分支：不做（依赖沙箱，属推后的 Animator）。
- 数据源：既有 kernel 输出（plot2d / three / svg_diagram）。
- LLM 角色：把数学概念/数据转成渲染规格（选类型、填参数），不生成可
  执行代码（客户端声明式渲染，无执行风险）。
- FC-6：渲染规格生成带 Mneme 假设 → 私有；通用渲染适配若无 Mneme 契约
  → 候选主库（CC 判定记录）。

前端 `/studio/visualize`：概念/数据输入 → LLM 出渲染规格 → 客户端渲染。
`react-three-fiber` 首次实际投用。

**Visualize 验收**：

| # | 项 | 方法 |
|---|---|---|
| VZ-1 | 四类渲染各出正确图形 | e2e |
| VZ-2 | 三维经 react-three-fiber 客户端渲染 | e2e |
| VZ-3 | 无任何服务端代码执行（声明式规格，非可执行代码） | 结构断言 |
| VZ-4 | 渲染数据来自既有 kernel | 溯源断言 |
| VZ-5 | FC-5 零 DB（visualize 页） | pg_stat_activity |

---

## 4. 全局不变式（继承，一条不动）

- 掌握度写入唯一路径 + guard。
- studio/agent 零 mneme-DB（FC-5）。
- 门控上游、内容下游——Solve/Visualize 只管"怎么讲/怎么算展示"。
- 确定性判分路由不变；Solve 求解确定性、LLM 不参与。
- 原 mneme 零改动；studio 独立 app。
- 主库元素不可变，改则私有化（FC-6）。
- 不耦合 Stratum。

---

## 5. 顺序

S0 沙箱加固 → S0 验收全绿 → Solve → Visualize → W4 全量验收 → 停

S0 是安全前置，未绿不进 Solve。Solve/Visualize 相对独立，Solve 先
（复用内核、依赖 S0）。

---

## 6. 推后项（各带硬理由，交接后续波次）

| 模式 | 推后理由 | 前置条件 |
|---|---|---|
| Animator | LLM 生成任意 Python subprocess 渲染 = 真安全沙箱缺口 | 需专门建安全代码执行沙箱（独立基建轮） |
| Research | 2800 行单体 + arXiv（K12 中文数学不适用） | 需整个换后端为 Knowledge Hub 检索 |
| Notebook | 横切读写所有模式 | 宜作既有归档哲学扩展重新设计 |
| Co-Writer | 复杂度在富文本编辑器 UI | studio 需先有富文本编辑基础 |

---

## 7. 挂起项（继承 + 新增）

**继承**：3× daily_plan 失败｜oservi assemble 双注册 bug｜blocks
OMarkdownRenderer bug｜image rebuild 债（pymupdf4llm/pypdf）｜main.py
pre-session 簇｜S3-C 真人 pilot（W8–W12 红）——唯一真瓶颈｜KU→chunk
~13% 错配（ship-gate）｜词汇碰撞失败模式｜Stratum 库空

**新增**：
- fallback 无年级上下文（一年级"1-5的认识"生成研究生集合论题）——对真实
  儿童直接伤害，标高严重度，W4 或补丁轮处理。
- Animator 安全沙箱（独立基建轮，Animator 前置）。
- Research 后端换 Knowledge Hub（Research 前置）。

---

## 8. 明确不做

Animator / Research / Notebook / Co-Writer（本波推后）｜Manim（沙箱
缺口）｜pgvector（未过阈值）｜挂接精度提升（ship-gate）｜Z 回测（数据
不足）
