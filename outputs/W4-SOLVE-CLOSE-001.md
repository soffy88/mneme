# W4 Solve 模式关闭记录（W4-SOLVE-CLOSE-001）

**日期**：2026-07-19
**范围**：`MNEME-W4-IMPL-SPEC-001.md` §2 Solve（S0 已绿，gate 通过后进入）
**状态**：Solve 模式 SV-1..SV-5 全绿。

---

## 架构

三段流水线，标准 omodul 编排（`vendor/omodul/solve_problem.py`）：

1. **`plan_solve_task`**（`packages/mneme-core` 私有 oskill，LLM）：自然语言
   题目 → `{kernel, task, params, restated_problem}`。kernel/task 只能是
   `SOLVE_KERNEL_TASKS`（单源注册表，`mneme_core/oprim/models.py`）里真实
   存在的值——LLM 编造/选错一律拒绝，不猜测硬凑。
2. **`solve_dispatch`**（`vendor/oskill`，纯确定性，零 LLM）：调用对应的
   真实 `solve_*` 内核（全部经 S0 加固的沙箱）。
3. **`narrate_solve_steps`**（`packages/mneme-core` 私有 oskill，LLM）：内核
   真实 `answer`/`steps` → 自然语言讲解，纯附加字段，绝不覆盖前者。

命名上刻意避开 `understand_problem`——`vendor/oprim/understand_problem.py`
已经是既有"Deep Solve"模式的不同用途元素（产出 problem_type/required_kus
供 RAG 方法检索，不产出可调用的内核/task/参数），两者互不相关，同名会
造成混淆。

---

## SV 验收表

| # | 项 | 结论 |
|---|---|---|
| SV-1 | 7 类题各求解正确 | ✅ `tests/test_solve_dispatch.py`（12 测试），7 个内核逐一通过 solve_dispatch 求解，加恶意/缺参数入参的优雅降级测试 |
| SV-2 | 步骤来自内核真实输出，非 LLM 编造 | ✅ `tests/test_solve_problem_omodul.py::test_narration_cannot_override_kernel_answer_or_steps`：讲解阶段 LLM 刻意编造错误答案（"x=100"），断言最终 `answer`/`steps` 仍是内核真实输出 `zeros: [-2, 2]`，narration 存在但不影响权威字段 |
| SV-3 | 求解全程经沙箱，Solve 包装不引入新绕过 | ✅ 复用 S0-1 的零绕过结构断言手法：`test_solve_dispatch.py::test_solve_dispatch_introduces_no_new_bypass_path` grep 确认 `solve_dispatch.py` 无裸 `sympify`/`eval`/`exec`；7 个 solve_* 内核本身的沙箱覆盖仍由 S0 的 `test_sandbox_zero_bypass.py` 持续把关 |
| SV-4 | LLM 讲解不改求解结果/判分 | ✅ 同 SV-2 那条测试；另加 `narrate_solve_steps` 自身单测（`packages/mneme-core/tests/test_narrate_solve_steps.py`）确认讲解失败时兜底为"逐步直读内核步骤"，不编造 |
| SV-5 | 若接教学循环，掌握度经 guard 回流 | 本轮 Solve **未接**教学循环（无 `kc_id`/学生上下文，纯解题工具）——spec §2 "若接入教学循环"是条件从句，本次场景不满足前提，不适用；留待后续如需要"解题即练习"再接 |

---

## 实测发现（比脚本化 fake caller 测试更狠的坑，均已修复）

1. **真实 LLM 输出不总是严格 JSON**：`plan_solve_task._parse()` 原始实现
   只做裸 `json.loads()`，本地 fake caller 测试永远输出干净 JSON，不会
   暴露问题；接真实 provider 后实测偶发输出被 ` ```json ... ``` ` 包裹或
   前后带解释性文字。修复：加两层兜底（剥离 code fence → 提取 `{...}`
   子串），并补两个真实复现该问题的回归测试。
2. **LLM 会为了"看起来合法"而编造占位内核**：喂一句"今天天气怎么样"，
   LLM 自己在 `restated_problem` 里正确写出"非数学题目、无可用内核"，
   却仍然编了一个 `kernel=function, expression="0"` 的假计划，导致系统
   把"f(0)=0"当成正经答案展示给用户——技术上不违反 SV-2/SV-4（内核输出
   本身是真的），但会给学生一个文不对题的误导性答案。修复：system prompt
   显式加"非数学题/无适用内核时留空 kernel，不要编造占位参数"的指令；
   e2e 测试（`e2e/solve.spec.ts`）用这个真实场景（天气问题）验证优雅降级。
3. **真实两次 LLM 调用耗时 ~35-40s**：调整 Playwright 全局超时
   40s→90s，并把 solve.spec.ts 的成功路径测试改为"最多重试 3 次提交"，
   而不是断言单次调用必然成功——真实外部 LLM 输出质量本身是概率性的，
   这条测试要验证的是"整条链路能走通"，不是"每次单次调用零失败率"。

---

## 生产环境发现并处理：vendor/ 此前对生产完全不生效

写完全部代码后，端到端验证时发现：`mneme-api-1`/`worker`/`beat` 的
`PYTHONPATH` 一直不含 `/app/vendor`，`import oprim/oskill/omodul/obase`
实际解析到站点包（site-packages）里的旧副本，不是本仓 `vendor/`——这意味着
**本会话 S0 的全部沙箱加固、以及 Solve 模式的全部新代码，在真实 HTTP 请求下
此前都不会生效**（会 500 或者走没加固的旧内核）。这不是本次改动引入的新
问题，是这个仓库一直存在、此前没人触碰到的既有状态（`docker-compose.yml`
自己的注释也写着"现经 PYTHONPATH 验证整条链；稳定后再固化为 Dockerfile
pip install"，说明这本来就是计划内但尚未执行的步骤）。

**已向用户确认后处理**：`docker-compose.yml` + `docker-compose.override.yml`
的 `PYTHONPATH` 都加了 `/app/vendor` 到最前面，`api`/`worker`/`beat` 三个
容器已重启生效（api.sxueji.com 有几秒中断）。切换前逐项核对了
`vendor/` 与站点包之间的差异面（`diff -rq` 全量比对 oprim/oskill/omodul/
obase 四个包）：

- 站点包独有、vendor 没有的模块（`_essay_assessment.py`、
  `adaptive_quiz_session.py`、`grade_paper_workflow.py`、
  `register_ku_ontology.py` 等一批）——全仓 grep 确认零处引用，是
  platform/3O 共享包服务于其他项目的能力面，Mneme 从未用过，切换不受影响。
- 内容有差异的公共文件（`obase/db.py`、`obase/config.py` 等）——抽查确认
  差异要么是纯格式/无关紧要（如 import 顺序），要么是站点包多出、但同样
  未被 Mneme 引用的功能（如通用 YAML config loader）。
- 切换后跑了全部既有 Playwright e2e（书单/阅读器/三态标注/Book→learn
  交接/人在环连续作答）——5/5 全过，证明真实用户路径（`GetPath`/
  `NextObjective`/`RequestQuestion`/`SubmitAnswer`/`ListBooks`/`GetBook`）
  切换后行为不变。

**结论**：这次切换让 S0 加固和 Solve 模式第一次在生产环境真正生效，也顺带
把这个"vendor 从不生效"的既有隐患解决了——但值得记录：这类"改了代码、
没人意识到部署路径没跟上"的坑，本会话之前已经撞过两次（`async_session_
factory` 潜伏 12 小时、`pymupdf4llm` 镜像未 rebuild），这是第三次，模式
相同：本地改动 ≠ 生产生效，需要显式核对部署路径。

---

## 事后加固 1：生产自检（防"vendor 从不生效"这类坑再次悄悄发生）

前一节记录的"vendor 从不生效"事故，根因就是**没有任何东西在生产环境验证过
S0 加固真的生效**——测试环境（pytest 的 vendor-first pythonpath）一直是绿的，
掩盖了生产环境根本没生效这件事。这是一个纯粹的"验证盲区"问题，只补代码不
补验证机制，同一类坑还会以别的形式再发生一次。

**新增 `vendor/obase/sandbox_selfcheck.py`**：把 S0-1"零绕过"结构断言 +
"沙箱确实是加固版本、不是旧副本"的能力/来源检查，包成一份单源定义：

- `_check_resolves_to_vendor_not_site_packages()`：直接检查
  `obase.sympy_runtime` 的真实解析路径，含"site-packages"字样就判定失败——
  这正是这次事故的直接症状，最有效的一道检测。
- `_check_hardened_version_loaded()`：检查 `SymPyRuntime` 是否有
  `run_isolated` 方法——防止"vendor 生效了，但恰好是 S0 之前的旧版本"这种
  更隐蔽的假阳性（比如未来有人在 vendor 里做了一次不完整的回退）。
- `_check_zero_bypass()`：S0-1 的 7 内核零绕过检查本体，从
  `tests/test_sandbox_zero_bypass.py` 抽出来，两处现在共用同一份
  `EXPECTED_KERNELS`/`NUMERIC_ONLY_KERNELS`/`STRING_EVAL_KERNELS` 定义
  （单源，不再各自维护一份副本）。
- `check_or_die()`：任何一项不过直接抛异常，供容器启动时调用。

**接进容器启动命令**（`docker-compose.yml`，`api`/`worker`/`beat` 三个容器），
同 2026-07-09 那次"迁移失败则不对外提供服务"的处置原则完全一致：

```
command: sh -c "python -m obase.sandbox_selfcheck && alembic upgrade head && uvicorn ..."
```

自检不过，容器直接启动失败，不会带着未加固/装错版本的沙箱对外提供服务——
不再可能只在 pytest 里验证过、生产里从没验证过。

**验证自检本身有牙齿，不是摆设**（`tests/test_sandbox_selfcheck.py`，7 个
测试）：分别用 mock/临时目录复现了这次事故本身遇到的三类真实故障——
`obase.sympy_runtime` 解析到 site-packages、加载到没有 `run_isolated` 的
旧版本、内核本身绕过沙箱（数值内核缺 `run_isolated`/字符串内核残留裸
`sympify`/内核清单本身对不上）——确认每一类都会被正确拦下来，不是只在
"当前环境凑巧是好的"这一种情况下显得有用。同时实际重启了
`api`/`worker`/`beat` 三个容器，日志确认自检输出（"S0 沙箱加固自检通过：
vendor/ 生效，7 内核零绕过"）真的排在 alembic/uvicorn/celery 之前执行，
容器 `/health` 确认健康，重启前后完整 e2e 套件（7/7）交叉验证零回归。

---

## 事后加固 2：回填验证——裸奔窗口有没有被利用

**问题**：从 S0 push（`b1b433d`，2026-07-19 11:29）到 PYTHONPATH 修复
（同日 ~12:00 前后，同一会话内）之间，生产是否有真实流量打到那 7 个
（原本以为已加固、实际仍是站点包旧副本的）内核？

**能确认的**：

- 该"裸奔"状态本身**不是这次改动引入的新窗口**——`docker-compose.yml`
  自己的既有注释（"现经 PYTHONPATH 验证整条链；稳定后再固化为 Dockerfile
  pip install"）说明 vendor 从未在生产生效这件事，从这次改动之前就一直
  成立，S0 push 前后风险水平没有变化，只是 S0 push 之后我曾经**误以为**
  它已经生效。
- 数据库里全部 56 个 `users` 记录，手机号字段全部匹配本会话历次
  e2e/回归测试脚本生成的模式（`t<hex>` 或形如 `137.../139...` 的合成号码），
  创建时间全部落在 2026-07-03～2026-07-19（本开发会话的活跃时间跨度内），
  没有任何一条像是真实外部注册——与"Mneme 至今零真实学习者"这一既有事实
  一致。
- Redis 里 `/v1/solve` 的限流 key（scope="solve"）当前查询为空——但这项
  本身**不构成证据**：限流计数器有 TTL（60s 窗口），不管过去有没有真实
  被打过，现在查都会是空，这条线索不能证明也不能证伪。

**不能确认的（诚实说明这个证据缺口）**：

- 容器级 HTTP 访问日志无法回溯——本次为切 PYTHONPATH 对 `api`/`worker`/
  `beat` 做了两次 `docker compose up -d`（配置变更触发 Recreate），旧容器
  实例连同其 `json-file` 日志已被移除，**无法直接查到那个具体窗口期内
  `/v1/solve` 端点收到过什么请求**。这是一个真实的证据缺口，不是"查过了
  确认没事"，而是"这条证据链本身已经不存在了"。

**结论（给出评估，不隐瞒缺口）**：综合"零真实学习者"这一贯穿全会话的
既有事实、窗口本身很短（同一天、同一次会话内的一到两小时）、且没有任何
外部渠道曾经宣传/引流到这个环境——真实外部流量在这个窗口命中的概率
判断为极低。但这不是一个能用日志证明的"零流量"断言，只是在证据缺失情况下
给出的合理评估，如实告知：证明材料在容器重建时已经不可挽回地丢失了。

**经验记录**：以后任何"改 PYTHONPATH/换部署路径"级别的操作，重启前应先
导出一份容器日志快照（`docker compose logs <service> > snapshot.log`），
避免这类事后取证缺口再次出现——这次没有提前做这一步。

---

## 回归状态（2026-07-19，Solve 模式 + 生产自检收口时）

- 根仓 `pytest`：753 过（Solve 收口时基线 746 + 本次新增 7：
  `test_sandbox_selfcheck.py`）/ 4 败（同一 4 个既有失败，
  `test_daily_plan.py`×3 + `test_dod_e2e.py`×1，S0/Solve 前后交叉验证一致）/
  3 跳。
- `packages/mneme-core`：127 过，无变化（新增测试在根仓 tests/，不在
  mneme-core）。
- `packages/mneme-agent`：14 过，无变化。
- 三套合计：894（753+127+14）。
- ruff：真实受检范围零新增问题，既有 6 处与本次改动无关（同前）。
- `apps/mneme-studio`：`next build` 通过；7 个 Playwright e2e 全过——
  两次分别在"切 PYTHONPATH 后"和"接入自检命令重启后"各跑了一遍全量 e2e，
  确认两次生产级容器操作都没有引入回归。
- 生产容器：`mneme-api-1`/`worker`/`beat` 已切换 PYTHONPATH + 接入
  `sandbox_selfcheck` 启动检查，两次重启，`/health` 均确认健康，启动日志
  确认自检输出排在 alembic/uvicorn/celery 之前正确执行。

---

## 明确不做（本轮未接的部分）

- SV-5（掌握度回流）：Solve 本轮是独立解题工具，未接 `kc_id`/学生教学
  上下文，不适用；如后续要做"解题即练习"，需要额外设计（例如显式传入
  `kc_id` + 复用既有 `process_interaction`+guard），不在本次范围内。
- Solve 结果的 `solution_latex`（内核已产出但本轮 API/前端未透传）——
  当前前端展示纯文本表达式，未接 KaTeX 渲染；可作为后续小优化，非本轮
  必须项。

---

**Solve 全绿，可以进 Visualize。**
