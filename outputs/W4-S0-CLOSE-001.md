# W4 S0 关闭记录（W4-S0-CLOSE-001）

**日期**：2026-07-19
**范围**：`MNEME-W4-IMPL-SPEC-001.md` §1 S0（sympy 沙箱加固，Solve 前置）
**状态**：S0 三项验收（S0-1/S0-2/S0-3）全绿。**实际发现的绕过面比 spec 原文
估计大得多**——本记录的重点之一就是把这个落差钉清楚，不让"S0 完成"盖过
"绕过面原来比想的严重"这个事实。

---

## 一句话结论

Spec 原文只报告了 2 个绕过（solve_geometry3d/solve_probability）。真正动手
按 S0-1 写结构性测试后发现：**7 个内核里，加固前只有 1 个（solve_function）
部分接了沙箱，其余 6 个要么完全绕过、要么部分绕过**。多数是"import 了
SymPyRuntime 但从没调用"的半成品迁移状态——这比"忘了加沙箱"更隐蔽，因为
表面上看起来像是已经接了（毕竟 import 语句在那儿）。

同时，加固内存限制的第一版实现本身有一个严重设计缺陷（`RLIMIT_AS` 用错了
资源指标），如果没测就上线，会让生产环境里**所有**沙箱调用（不只是病态
输入）瞬间全部失败——这是这次 S0 加固过程本身最大的一个坑，细节见下。

---

## 发现清单：绕过面比 spec 估计的严重

| 内核 | spec 原文说法 | 实际状态（加固前） |
|---|---|---|
| solve_geometry3d | 完全绕过（纯数值，无字符串） | 确认，纯数值 DoS 风险 |
| solve_probability | 完全绕过（纯数值，无字符串） | 确认，纯数值 DoS 风险 |
| solve_sequence | spec 未提及，视为已接沙箱 | **实为绕过**：import 了 SymPyRuntime，从未调用，甚至连 sympy 本身都没 import——纯 Python 数值运算，死 import |
| solve_conic | spec 未提及，视为已接沙箱 | **实为绕过**：import 了 SymPyRuntime/SymPyRuntimeError，从未调用；两处裸 `sp.sympify()` 直接吃调用方字符串，零 AST 校验 |
| solve_derivative | spec 未提及，视为已接沙箱 | **实为绕过**：同上模式，一处裸 `sp.sympify()` |
| solve_trig | spec 未提及，视为已接沙箱 | **实为绕过**：同上模式，两处裸 `sp.sympify()`（expression + rhs） |
| solve_function | spec 未提及，视为已接沙箱 | **部分绕过**：7 个任务分支里只有 3 个（zeros/evaluate/simplify）真的走 `rt.solve_equation()`/`rt.evaluate()`/`rt.simplify_expr()`；另外 4 个分支（parity/compose/monotonicity/inverse）各自内联一段 `sp.sympify()` 裸调用，零沙箱 |

**为什么盘点会漏掉这些**：早前 W4 前置查证只 grep 了 import 语句
（`from obase.sympy_runtime import ...`），没有验证"import 了是否真的被
调用"。这次写 S0-1 结构性测试时，第一版测试同样只查 import，第一次跑
全绿；把断言收紧到"真的调用了 AST 校验入口"之后，才逐一暴露出上面这 4+1
个真绕过。**结构性测试的价值就在这——它逼着你验证"用了"而不是"提到过"。**

---

## S0-1：7 内核全经沙箱，0 绕过

**修复**：
- `solve_geometry3d.py` / `solve_probability.py`：接入沙箱新增的
  `SymPyRuntime.run_isolated(func, timeout=)`——纯数值内核没有表达式字符串
  可做 AST 校验，真正需要的是 fork+timeout+内存上限这三重 DoS 防护，不需要
  白名单。
- `solve_sequence.py`：同上接入 `run_isolated`（风险等级低于前两者——数值
  溢出走 IEEE-754 float 上溢，不是任意精度大整数爆内存，但为了"0 绕过"的
  结构一致性，同样接入，去掉死 import）。
- `solve_conic.py` / `solve_derivative.py` / `solve_trig.py`：裸
  `sp.sympify()` 替换为 `SymPyRuntime.evaluate()`（AST 白名单 + fork +
  timeout + 内存上限），解析出的已验证 SymPy 对象再做后续结构操作（`expand`/
  `diff`/`solve`/`trigsimp` 等，这些是安全的，因为已经不是在对原始字符串
  做二次求值）。
- `solve_function.py`：`parity`/`compose`/`monotonicity`/`inverse` 四个
  分支同样改用 `rt.evaluate()` 解析，`zeros`/`evaluate`/`simplify` 三个
  分支本来就是对的，未改动。
- `solve_conic.py` 额外发现并修复一个真实的兼容性坑：`SymPyRuntime.evaluate()`
  走纯 Python `ast.parse`/`eval`，`^` 是按位异或；而原来的 `sp.sympify()`
  会自动把 `^` 转乘方。solve_conic 的既有测试
  （`tests/test_new_routes.py::test_solve_conic`）真实传入了 `"x^2 + y^2 = 25"`
  这种记法——如果直接切换会静默解析错误。加了 `_normalize_caret_power()`
  在进沙箱前把 `^` 换成 `**`，保住既有输入格式的兼容性。

**验收**（`tests/test_sandbox_zero_bypass.py`，4 个测试）：
- 固定 7 内核基线，防未来清单漂移。
- 3 个纯数值内核（geometry3d/probability/sequence）必须调用 `run_isolated`。
- 4 个字符串求值内核（function/conic/derivative/trig）必须调用某个 AST
  校验入口（`evaluate`/`solve_equation`/`differentiate`/`integrate_expr`/
  `simplify_expr`/`to_latex`）。
- 4 个字符串求值内核不得再残留裸 `sp.sympify()` 调用。

---

## S0-2：内存上限真正 enforce（且第一版实现本身有严重设计缺陷）

**加固前**：`RuntimeConfig.max_memory_bytes` 声明了但从未被任何
`setrlimit`/cgroup 机制真正落地——64MB 上限是纸面数字，子进程能吃多少内存
就吃多少，唯一兜底只有 timeout。

**第一次尝试（有严重 bug，已发现并推翻重做）**：子进程 fork 后
`setrlimit(RLIMIT_AS, (max_memory_bytes, max_memory_bytes))`（连同 hard
limit 一起下调）。手动验证时发现两个连环真实问题：

1. **限了硬上限就再也回不去了**：POSIX 规定非特权进程不能上调自己的
   hard limit——把 soft 和 hard 一起设到 32MB 后，即使之后想恢复也恢复不了，
   子进程被永久焊死在这个上限上（包括之后想给 Queue 的 feeder 线程
   分配内存来回报 MemoryError 本身都会失败——"can't start new thread"，
   真正的错误被这个连环失败吞掉，暴露成一个更莫名其妙的
   `SymPyRuntimeError: subprocess terminated without a result`）。
2. **`RLIMIT_AS` 限的是虚拟地址空间，不是常驻内存**：实测生产 `uvicorn`
   进程本身的 VmSize 已经 ~1.6GB（FastAPI+SQLAlchemy+全部依赖装载后的正常
   现象）。fork 出的子进程立刻继承父进程整个虚拟地址空间——64MB 这种上限
   在真实生产进程里意味着**任何一次沙箱调用，包括最简单的 `x+1`，都会
   立刻失败**，不只是病态输入。这个 bug 如果没测出来直接上线，等于让整个
   Solve/Visualize 功能在生产环境里彻底不可用。

**最终实现**：改为父进程侧轮询子进程的**常驻内存**增量
（`/proc/<pid>/status` 的 `VmRSS`，减去 fork 刚结束时的基线值），复用既有
0.05s 轮询间隔（与 timeout 检测同一个循环），超过 `max_memory_bytes` 就
按既有 timeout 一样的方式 terminate/kill。这个指标只反映"这次计算相对于
刚 fork 出来时，自己新增长了多少常驻内存"，与宿主进程本身多大完全无关。

**验收**（`tests/test_sympy_sandbox_memory_limit.py`，3 个测试）：
- 人造 500MB bytearray 分配在 32MB 上限下被真实杀掉，且在 2s 内返回（不是
  等到 5s timeout 才杀，证明是内存墙而非超时墙）。
- 32MB 上限下，一个远小于上限的正常计算不受影响（负向对照，防误伤）。
- 真实内核端到端（`solve_probability` 的 combinations 任务，经沙箱加固前
  完全绕过）：`math.comb(2_000_000, 1_000_000)` 实测原始耗时 ~12.6s——大
  n/k 组合数是 CPU-bound（大数乘法链长），不是内存-bound（结果本身只有
  ~240KB，远不到 64MB）。这条测试如实撞的是超时墙不是内存墙——两道墙哪个
  先触发取决于具体输入的资源消耗模式，测试断言接受两者之一，不强行归因。

---

## S0-3：恶意 LLM 输出被 AST 白名单拦截

**加固前**：全仓库对 `_SafeVisitor`（AST 白名单本体）零测试覆盖——白名单
代码本身看起来写得对，但从未有测试验证过它真的能拦住典型沙箱逃逸手法。

**验收**（`tests/test_sympy_sandbox_security.py`，20 个测试）：
- 14 种常见沙箱逃逸手法参数化测试：`__import__`/`os.system`/`open`/
  `exec`/`eval`/`compile`/`().__class__.__bases__...__subclasses__()`
  这类经典对象内省逃逸/`globals()`/`locals()`/`vars()`/
  `getattr(__builtins__, 'exec')`/裸 `import os` 语句——全部确认被
  `SymPyRestrictedError` 拦截。
- 一条对 `__builtins__` 裸引用的专门澄清：这个名字本身不在
  `forbidden_names` 里，会通过 AST 校验，但**不是漏洞**——
  `evaluate()` 的 `eval(code, {"__builtins__": {}}, ns)` 本身就把
  `__builtins__` 显式替换成空字典，所以拿到的永远无害，不是真的 builtins
  模块。这是比 AST 白名单更底层的一道硬防线，测试把它显式钉住，防止未来
  "优化"掉这个空字典替换时没人意识到那也是安全边界的一部分。
- 3 条端到端测试，通过真实内核（solve_conic/solve_derivative/
  solve_function 全部四个曾经绕过的分支）验证恶意输入优雅降级为
  `solvable=False`，不是抛未捕获异常，更不是真的执行。
- 1 条负向对照：确认白名单没有严到把合法数学表达式也误杀。

---

## 回归状态

- 新增/修改测试：`test_sandbox_zero_bypass.py`（4）+
  `test_sympy_sandbox_memory_limit.py`（3）+
  `test_sympy_sandbox_security.py`（20）+ 更新
  `test_sympy_sandbox_timeout.py` 的既有断言（原断言只认"timeout"，加固后
  内存墙也是真的了，改为接受两道墙之一，不是弱化红线——两道墙都是"病态输入
  必须被杀"这同一条红线的体现）。
- 根仓 `pytest`：727 过 / 4 败（同一 4 个既有失败，
  `test_daily_plan.py`×3 + `test_dod_e2e.py`×1，与 S0 改动无关，S0 前后
  交叉验证一致）/ 3 跳。700（S0 前基线）+ 27（本次新增）= 727，吻合。
- `packages/mneme-core`：114 过，与 S0 前一致（S0 不触碰 mneme-core）。
- `packages/mneme-agent`：14 过，与 S0 前一致。
- ruff/mypy：`vendor/`（本次改动的 7 个内核文件 + sympy_runtime.py）和
  `tests/`（本次新增测试）按项目既有约定都不在 lint/型检查范围内
  （`pyproject.toml` 显式 exclude，vendor 有自己的上游 CI）；在真正受检的
  范围内（`services/`/`tasks/`/其余 `tests/` 外文件）跑 `ruff check .`
  确认零新增问题，本次改动前后一致。

---

## S0 验收表（对照 spec 原文）

| # | 项 | 结论 |
|---|---|---|
| S0-1 | 7 内核全经沙箱，0 绕过 | ✅（含额外发现并修复的 solve_conic/derivative/trig/function 四个分支 + solve_sequence 死 import，总计比 spec 估计多修了 5 个绕过点） |
| S0-2 | 内存超限实际被杀（非纸面） | ✅（含推翻重做一次——第一版 RLIMIT_AS 实现本身有生产级 bug，改为父进程侧 RSS 增量轮询） |
| S0-3 | 恶意 LLM 输出被 AST 白名单拦截 | ✅（含对 `__builtins__` 裸引用为何无害的专门澄清） |

**S0 全绿，可以进 Solve。**
