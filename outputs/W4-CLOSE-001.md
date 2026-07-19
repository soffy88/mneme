# W4 关闭记录（W4-CLOSE-001）

**日期**：2026-07-19
**范围**：`MNEME-W4-IMPL-SPEC-001.md` 全部（S0 沙箱加固 → Solve → Visualize）
**状态**：三个模块全绿，W4 收口。详细验收记录分别见
`outputs/W4-S0-CLOSE-001.md`、`outputs/W4-SOLVE-CLOSE-001.md`、
`outputs/W4-VISUALIZE-CLOSE-001.md`——本记录是三份的汇总索引 + 全量验收，
不重复展开每一条的过程细节。

---

## 一句话结论

三个模块（S0/Solve/Visualize）验收表全绿，但过程中发现的真实缺口比 spec
原文估计的多得多——S0 从"2 个已知绕过"变成"6 个真绕过 + 1 处生产从不生效
的部署缺口"；Visualize 又追加发现 2 个既有可视化内核的同类绕过。这些都是
在"按 spec 施工"的过程中，靠**结构性测试 + 真实 LLM 联调 + 生产级验证**
逐一挖出来的，不是纸面审查能看到的。W4 收口的价值，一半在"三个模块都能
跑通"，另一半在"经过这轮，S0 加固覆盖面比 spec 写下的更完整、且第一次在
生产环境验证过真的生效"。

---

## S0 沙箱加固（详见 W4-S0-CLOSE-001.md + W4-VISUALIZE-CLOSE-001.md 追加发现）

| # | 项 | 结论 |
|---|---|---|
| S0-1 | 7 内核全经沙箱，0 绕过 | ✅（实际修了 5 个绕过，比 spec 估计的 2 个多；Visualize 阶段又追加修了 2 个可视化内核的同类绕过，共 7 个真绕过点） |
| S0-2 | 内存超限实际被杀（非纸面） | ✅（含推翻重做一次——RLIMIT_AS 方案本身有生产级 bug，改为父进程侧 RSS 增量轮询） |
| S0-3 | 恶意 LLM 输出被 AST 白名单拦截 | ✅ |
| 追加 | 生产自检（防"vendor 从不生效"再犯） | ✅ `obase.sandbox_selfcheck` 接入 `api`/`worker`/`beat` 启动命令，检查不过拒绝对外提供服务 |

**最重要的一条发现**：S0 代码 push 之后，`mneme-api-1`/`worker`/`beat` 的
`PYTHONPATH` 一直不含 `/app/vendor`，生产实际装配的是站点包
（site-packages）里未加固的旧内核——这个洞不是本轮改动引入的，是这个仓库
一直存在、没人验证过的既有状态，本轮把它连带修了（已获用户确认后切换
PYTHONPATH 并重启，切前切后各跑满回归/e2e 确认零回归）。

---

## Solve（详见 W4-SOLVE-CLOSE-001.md）

| # | 项 | 结论 |
|---|---|---|
| SV-1 | 7 类题各求解正确 | ✅ |
| SV-2 | 步骤来自内核真实输出，非 LLM 编造 | ✅（用"讲解阶段 LLM 故意编造错误答案"的测试硬证明） |
| SV-3 | 求解全程经沙箱，Solve 包装不引入新绕过 | ✅ |
| SV-4 | LLM 讲解不改求解结果/判分 | ✅ |
| SV-5 | 若接教学循环，掌握度经 guard 回流 | 不适用（本轮 Solve 是独立解题工具，未接教学上下文） |

真实 provider 联调揪出两个 fake-caller 测试测不出的坑：LLM 输出偶发被
markdown fence 包裹/带解释性文字（解析器加两层兜底）；LLM 会为了凑合法
JSON 而给非数学问题编造占位内核（system prompt 加"留空不编造"指令）。

---

## Visualize（详见 W4-VISUALIZE-CLOSE-001.md）

| # | 项 | 结论 |
|---|---|---|
| VZ-1 | 四类渲染各出正确图形 | ✅ |
| VZ-2 | 三维经 react-three-fiber 客户端渲染 | ✅（这个依赖在仓库里第一次被真正用到） |
| VZ-3 | 无任何服务端代码执行 | ✅ |
| VZ-4 | 渲染数据来自既有 kernel（mermaid 除外，诚实标注为 LLM 内容） | ✅ |
| VZ-5 | FC-5 零 DB | ✅ |

---

## 回归状态（2026-07-19，W4 收口时，累计）

- 根仓 `pytest`：777 过 / 4 败（同一 4 个既有失败——`test_daily_plan.py`×3
  + `test_dod_e2e.py`×1——贯穿 S0/Solve/Visualize 全程未变）/ 3 跳。
- `packages/mneme-core`：134 过 / 0 败。
- `packages/mneme-agent`：14 过 / 0 败。
- 三套合计：925。W4 全程（S0 起点 727 → 收口 925）新增约 198 个测试。
- ruff/mypy：真实受检范围零新增问题；既有 6 处 ruff 问题与本轮改动无关
  （交接自会话更早阶段）。
- `apps/mneme-studio`：`next build` 通过；10 个 Playwright e2e 全过
  （5 W3 既有 + 2 Solve 新增 + 3 Visualize 新增），其中 4 条对真实 LLM
  provider 跑（非 mock）。
- 生产容器：`mneme-api-1`/`worker`/`beat` 已切换 PYTHONPATH（vendor/ 优先）
  + 接入 `sandbox_selfcheck` 启动自检，三次重启（S0 切换、Solve 部署新
  路由、Visualize 部署新路由+内核修复），每次重启前后都跑满 e2e 套件
  交叉验证零回归。

---

## W4 明确推后（spec §6，未变）

| 模式 | 推后理由 |
|---|---|
| Animator | LLM 生成任意 Python subprocess 渲染 = 真安全沙箱缺口，需专门建安全代码执行沙箱 |
| Research | 2800 行单体 + arXiv 依赖，需整个换后端为 Knowledge Hub 检索 |
| Notebook | 横切读写所有模式，宜作既有归档哲学扩展重新设计 |
| Co-Writer | 复杂度在富文本编辑器 UI，studio 需先有富文本编辑基础 |

---

## 挂起项（继承 + 本轮新增，均未处理，如实记录不遗漏）

**继承自 W3（未变，见 outputs/W3-PENDING-ITEMS.md）**：KU→chunk ~13% 错配
ship-gate、image rebuild 债、人工校订未开始等——均与 W4 无关，未在本轮
触碰。

**继承自 W3、spec §7 点名"W4 或补丁轮处理"，2026-07-19 补丁轮已修**：
`_llm_generate_question`（既有 W2C 兜底出题逻辑）不传年级上下文的 bug
（一年级 KC 生成研究生集合论题）。W4 三个模块（S0/Solve/Visualize）收口
时确实没有触碰这个函数——收口后作为独立补丁轮处理：`tool_request_
question` 的取名查询改联表拿 `Textbook.grade`，传给
`_llm_generate_question(kc_name, grade=...)`，prompt 用真实学段替换硬编码
"适合中学生"。真实 qwen provider 验证：G1 KC 现在生成"数一数几个苹果"
这种真实符合学段的题，不再是集合论。详见
`outputs/W3-PENDING-ITEMS.md`。

**本轮新增，已处理但记录取证缺口**：S0 push 到 PYTHONPATH 修复之间，
生产是否有真实流量打到未加固内核——容器级访问日志已因重启丢失，无法
直接验证，现有证据（零真实学习者、全部测试账号可追溯）支持"未被利用"的
评估，但这是评估不是日志证明，详见 W4-SOLVE-CLOSE-001.md 对应小节。

**本轮新增，Visualize 明确不做的小项**：chart 的 sequence 模式不做外推
更多项（避免解析 `solve_sequence.answer` 字符串的脆弱实现）；mermaid 的
FC-6 候选主库判定留待未来重新评估。

**🔴 本轮新增，W5 前必须处理，不能再靠"发现一个补一个"**：
"未沙箱化 sympify/eval/exec 处理外部输入" 是**跨命名空间的模式性漏洞**，
不是 solve_* 或 kernel_to_* 这几个文件独有——本轮实际发现顺序就是证据：
S0 一开始只知道 2 个绕过（geometry3d/probability），结构性测试挖出
solve_conic/derivative/trig/sequence 4 个更多，之后 solve_function 自己
7 个任务分支里还有 4 个绕过没被同一轮扫到，Visualize 阶段又在
kernel_to_plot2d/kernel_to_three 这两个不在 `solve_*` 命名下的文件里发现
同一个模式。每次都是"接一个新模式才顺带扫到"，不是主动查过全仓。

**处置**：W5 开工前，对全仓（含 `vendor/`、`packages/mneme-core/`、
`scripts/`、`tasks/`）做一次 `sympify(`/`eval(`/`exec(`/`compile(` 的全量
grep，逐个确认调用点是否处理外部（用户/LLM）输入、是否经过沙箱
（`obase.sympy_runtime.SymPyRuntime` 的 AST 校验入口或
`run_isolated()`）。不要等下一个新模式（Animator/Research/Notebook/
Co-Writer 任何一个）接线时再顺带撞见——那还是"发现一个补一个"，不是根治。
`obase/sandbox_selfcheck.py` 目前只覆盖已知的 `EXPECTED_KERNELS` +
`VISUALIZATION_KERNELS` 两组白名单，这次全仓 grep 的结果应该反过来验证/
扩充这份白名单是否已经穷尽，而不是继续假设"没被点名的文件都是安全的"。

---

**W4 全部三个模块（S0/Solve/Visualize）收口。**
