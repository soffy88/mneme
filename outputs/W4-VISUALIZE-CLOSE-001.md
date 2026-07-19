# W4 Visualize 模式关闭记录（W4-VISUALIZE-CLOSE-001）

**日期**：2026-07-19
**范围**：`MNEME-W4-IMPL-SPEC-001.md` §3 Visualize（去 Manim）
**状态**：Visualize 模式 VZ-1..VZ-5 全绿。

---

## 架构

两段流水线（比 Solve 少一段——Visualize 没有"求解答案对错"这个维度，
`restated_concept` 已足够让前端展示"系统理解了什么"，不需要额外讲解层）：

1. **`plan_visualize_task`**（`packages/mneme-core` 私有 oskill，LLM）：
   自然语言概念/数据描述 → `{render_type, params, restated_concept}`。
   render_type 只能是 `VISUALIZE_RENDER_TYPES`（单源注册表）里真实存在的
   4 种：`svg_plot`/`three`/`chart`/`mermaid`。
2. **`visualize_dispatch`**（`vendor/oskill`，纯确定性除 mermaid 分支外）：
   `svg_plot`/`three`/`chart` 三种类型调用真实内核
   （`kernel_to_plot2d`/`kernel_to_three`/`solve_sequence`）产出渲染数据；
   `mermaid` 是唯一例外——LLM 直接撰写的声明式图示文本，`data_source`
   字段诚实标注为 `"llm_authored"`，不伪装成内核数据（同 Solve 模式
   narration 的诚实标注原则一致）。

前端 `/studio/visualize`：概念输入 → 渲染 spec → 客户端实际渲染。
`react-three-fiber` 在这个仓库首次真实投用（此前 `package.json` 里装了
`@react-three/fiber`/`@react-three/drei`/`three` 但零页面使用）。新增
`chart.js`/`mermaid`/`react-chartjs-2` 三个前端依赖（spec 明确指名的技术，
不是自行引入的新框架）。

---

## 发现并处理：Visualize 前置暴露了 2 个既有内核的同类沙箱绕过

给 Visualize 接线、读 `kernel_to_plot2d.py`/`kernel_to_three.py`（W2 时代
已存在，被既有 `oskill.solve_and_visualize` 使用）时发现：这两个可视化
内核跟 S0 加固前的 `solve_conic`/`derivative`/`trig`/`function` 是**同一类
真实漏洞**——`_safe_eval_at()`/`_safe_eval_z()` 直接对调用方提供的表达式
字符串跑裸 `sp.sympify()`，零 AST 白名单、零 fork/timeout/内存上限。S0 的
范围只覆盖了 7 个 `solve_*` 内核，没扫到这两个不在 `solve_*` 命名下的
可视化内核——Visualize 模式恰好会让 LLM 提供的表达式字符串真正打到这两个
函数，不修就是把这个洞直接暴露给新的 LLM 可达入口。

**已修复**（同 S0 的处置手法）：

- 表达式先经 `SymPyRuntime.evaluate()` 做一次 AST 校验 + 沙箱化解析
  （只解析一次，不是每个采样点都重新解析——`kernel_to_plot2d` 默认采
  200 个点，`kernel_to_three` 默认 20×20=400 个点，每点都重新 fork 解析
  代价太大），解析出的已验证表达式对象再拿去做实际的多点/网格数值求值；
  求值循环本身包一层 `run_isolated`（fork+timeout+内存上限），防止病态
  表达式在 `evalf()` 阶段卡死或吃爆内存。
- 采样点数/网格点数额外做上限裁剪（`_MAX_NUM_POINTS=500`、
  `_MAX_GRID_POINTS=40`）——这两个参数本身也是数值 DoS 面（LLM 可以请求
  任意大的点数），S0 里 `solve_probability` 的 n/k 同理。
- 修复过程中额外抓到一个真 bug：`SymPyRuntime.evaluate()` 对 AST 拦截/
  超时/内存超限是直接抛异常，不是包进 `EvalResult(success=False)`（既有
  约定，同 `solve_conic` 等内核一致）——两个可视化内核最初只判断了
  `parsed.success`，没有 catch 这些异常，导致恶意表达式会让函数抛未捕获
  异常而不是优雅降级。已修复为显式 try/except。

**验证**：`tests/test_visualization_kernel_sandbox.py`（7 测试）——合法
表达式仍正常工作、恶意表达式优雅降级为空数据（不执行、不抛异常）、点数/
网格点数上限生效。`obase/sandbox_selfcheck.py` 扩展了
`VISUALIZATION_KERNELS` 常量，生产启动自检现在也覆盖这两个文件，不止
7 个 `solve_*` 内核。

---

## VZ 验收表

| # | 项 | 结论 |
|---|---|---|
| VZ-1 | 四类渲染各出正确图形 | ✅ 单元测试覆盖全部 4 类（`tests/test_visualize_dispatch.py`），e2e 真实覆盖 svg_plot/three 两类（`e2e/visualize.spec.ts`，对真实 LLM provider 跑） |
| VZ-2 | 三维经 react-three-fiber 客户端渲染 | ✅ e2e 确认 canvas 元素真实渲染出来（`three-canvas`/`canvas` 均可见），这是这个依赖在仓库里第一次被真正用到 |
| VZ-3 | 无任何服务端代码执行（声明式规格，非可执行代码） | ✅ 结构性断言（`test_visualize_dispatch_introduces_no_server_side_code_execution`）确认 `visualize_dispatch.py` 无裸 eval/exec/sympify；mermaid 分支只做字符串透传，真正解析发生在客户端 mermaid.js（`securityLevel:"strict"` 显式声明）+ 关键词黑名单纵深防御（`plan_visualize_task._looks_suspicious`） |
| VZ-4 | 渲染数据来自既有 kernel | ✅ svg_plot/three/chart 三种类型的 `data_source` 字段可追溯到 `kernel_to_plot2d`/`kernel_to_three`/`solve_sequence`；mermaid 诚实标注 `"llm_authored"`，前端也把这个区分做实（图注文案区分"来自内核计算"vs"AI 生成的示意图"） |
| VZ-5 | FC-5 零 DB（visualize 页） | ✅ `package.json` 无 DB 驱动依赖；`mneme-studio` 容器无 DB 环境变量；新增前端文件 grep 确认零 DB 引用（继承自 studio 应用自诞生起的 FC-5 架构，Visualize 没有引入新的例外） |

---

## 回归状态（2026-07-19，Visualize 收口时）

- 根仓 `pytest`：777 过（Solve+生产自检收口时基线 760 + 本次新增 17：
  `test_visualize_dispatch.py` 11 + `test_visualize_concept_omodul.py` 4 +
  `test_mcp_visualize_concept_tool.py` 2；`test_visualization_kernel_
  sandbox.py` 的 7 个已计入 760 基线，是 Visualize 前置修复 kernel_to_
  plot2d/three 时先行提交的）/ 4 败（同一 4 个既有失败不变）/ 3 跳。
- `packages/mneme-core`：134 过（基线 127 + 本次新增 7：
  `test_plan_visualize_task.py`）。
- `packages/mneme-agent`：14 过，无变化（与 mneme-core 分开单独跑——
  两者合并在同一次 pytest 调用里跑会报 collection 冲突，这是既有测试
  基础设施的问题，与本次改动无关，一直靠分开跑规避）。
- 三套合计：925（777+134+14）。
- ruff：真实受检范围零新增问题（新写的 `plan_visualize_task.py` 一处
  未用 `import re` 已修）；既有 6 处与本次改动无关（同前）。
- `apps/mneme-studio`：`next build` 通过；10 个 Playwright e2e 全过
  （7 既有 + 3 新增 `visualize.spec.ts`，其中 svg_plot/three 两条对真实
  LLM provider 跑，含一次真实"无法理解"优雅降级验证）。
- 生产容器：`mneme-api-1` 已重启以加载本轮新代码（`services/
  visualize_service.py`、`mcp_router.py` 的 `/VisualizeConcept` 路由、
  `kernel_to_plot2d`/`kernel_to_three` 修复）——启动自检
  （`obase.sandbox_selfcheck`）确认通过，`/health` 健康，重启前后完整
  e2e 套件（10/10）交叉验证零回归。

---

## 明确不做（本轮未接的部分）

- Manim 渲染分支：spec 明确排除（依赖专门的安全代码执行沙箱，属推后的
  Animator 前置工作）。
- `chart` 类型的 `sequence` 模式目前只展示调用方给定的 terms 本身（不做
  "外推更多项"）——避免解析 `solve_sequence` 的 `answer` 字符串这种脆弱
  实现；如果后续要外推，需要 `solve_sequence` 提供一个返回原始数值（而非
  格式化字符串）的接口，不在本轮范围内。
- mermaid 渲染尚未接入 FC-6 的"是否候选主库"判定——本轮判断为带 Mneme
  假设（"把学生概念映射到 Mneme 自己这 4 种渲染类型"），留 mneme-core
  私有；如果未来 Mermaid 生成本身要抽成通用能力（不带 Mneme 语境），需要
  重新评估。

---

**Visualize 全绿，W4 三个模块（S0/Solve/Visualize）全部完成，进入 W4
全量验收。**
