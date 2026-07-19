# W4-PREWORK-INVENTORY-001

**类型**：只读盘点，不动代码
**范围**：W4 六模式（Solve / Research / Animator / Visualize / Notebook / Co-Writer）前置查证
**方法**：DeepTutor（github.com/HKUDS/DeepTutor）真实上游源码逐一读取（非猜测）+ Mneme 本仓库
现有沙箱/可复用基建盘点 + apps/mneme-studio 壳现状

---

## 0. 一句话结论：六模式порtingComplexity 由简到难

**Solve < Co-Writer < Notebook < Visualize < Animator < Research**

- **Solve**：DeepTutor 里根本不是独立 pipeline——就是聊天循环的一个状态机包装，
  Mneme 已有的 7 个 `solve_*.py` 确定性内核比 DeepTutor 这条路径更扎实。
- **Research**：DeepTutor 单一 `pipeline.py` 就 2800 行/107KB，四阶段агентic
  系统，比 Book Engine 还大，且依赖 arXiv 论文检索（K-12 数学场景基本用不上，
  同 W3 的 Stratum 替换成 Knowledge Hub 是同一类"整体替换外部依赖"工作）。
- **Animator**：硬依赖 Manim（`if importlib.util.find_spec("manim") is None:
  raise RuntimeError`）——子进程跑生成的 Python 代码渲染视频，本仓库**没有**
  与之相当的沙箱/进程隔离能力（见下方§2）。这是六模式里唯一"明确基建缺口"
  最大的一个。
- **Visualize**：DeepTutor 自己拆成两条分支——非 Manim 分支（SVG/Chart.js/
  Mermaid/HTML）零执行风险、前端渲染，Manim 分支直接调用 Animator 模块（同一
  个基建缺口）。W4 spec 可以只做前者，价值仍然真实。

---

## 1. DeepTutor 六模式源码盘点

DeepTutor 把这六个不是放在同一层级："Loop capability"（Solve，挂在聊天循环
上的轻量扩展）vs "独立 Agent capability"（Research/Animator/Visualize，
`deeptutor/runtime/bootstrap/builtin_capabilities.py` 里按类路径注册）vs
"横切服务"（Notebook，JSON 文件存储 + 两个小 agent，不是一个 turn capability）
vs "顶层独立包"（Co-Writer，`deeptutor/co_writer/`，不在 capabilities/ 或
agents/ 下）。

### Solve
`deeptutor/capabilities/solve/`（~21.5KB，4 个文件，无 pipeline.py）。
`DeepSolveCapability.run()` 只是标记 `solve_mode=True`，走标准
`AgenticChatPipeline`；唯一专属逻辑是三个工具（`solve_plan`/
`solve_finish_step`/`solve_replan`）+ 内存态 `SolveSession`（步骤计划、
完成标记、重规划计数上限 256 会话/12 步）。不自己执行代码，只走标准聊天
循环的工具调用。**最简单——本质是"计划状态机"，不是求解引擎**。Mneme 已有
的确定性 `solve_*` 内核比这条路径更值得作为"求解"的真正实现，DeepTutor 这
部分主要能借鉴的是"分步计划+可重规划"的交互态设计，不是求解算法本身。

### Research
`deeptutor/agents/research/`：`pipeline.py`（**2800 行/107KB**）+
`citation_manager.py`（33.3KB）+ `data_structures.py`（19.3KB）+
`mode_strategy.py`/`request_config.py`。四阶段：
**Rephrase**（最多 3 轮澄清对话）→**Decompose**（一次 LLM 调用拆子主题，
用户需确认大纲）→**Research blocks**（`DynamicTopicQueue`，每个 block 自己
的 THINK/TOOL/APPEND/FINISH 循环，工具含 `rag`/`web_search`/`paper_search`/
`code_execution`，可并行调度）→**Reporting**（大纲→引言→逐 section→结论，
从 `CitationManager` 取证据做行内引用）。四种报告模式（notes/report/
comparison/learning_path）各自子主题数/分节长度阈值/结构校验器不同。
**最复杂——单文件比 Book Engine 整个 B3 还大**，且依赖 arXiv 论文检索（K-12
数学场景基本不适用，需要整体替换检索后端，同 W3 Knowledge Hub 替换 Stratum
是同一类工作）。

### Animator（math_animator）
`deeptutor/agents/math_animator/`（~50KB）：6 阶段
concept_analysis→concept_design→code_generation→code_retry（渲染）→
summary→render_output。前几阶段各是一次 LLM 调用产出结构化对象（分析→
设计→生成 Manim Python 代码），`ManimRenderService` **用 subprocess 真的
跑 `python -m manim`** 渲染视频/PNG，`CodeRetryManager` 把渲染失败反馈给
代码 agent 最多重试 4 次，可选一个"看渲染帧"的视觉审核 agent。
**硬依赖 Manim**（`math_animator/capability.py` 启动即检查 `find_spec
("manim")`，没装直接 raise）——Manim 需要 FFmpeg/LaTeX/Cairo 系统包，且这
是"让 LLM 生成的任意 Python 代码跑子进程"，比 Mneme 现有的 sympy 沙箱（AST
白名单+fork+超时 kill）复杂得多、风险高得多。**本仓库没有与之相当的沙箱
能力**——这是六模式里唯一一个"基建缺口"最实打实的。

### Visualize
`deeptutor/agents/visualize/`（~35KB）：**analyze**（一次 LLM 调用从 6 种
`render_type` 里选：svg/chartjs/mermaid/html/manim_video/manim_image）→
**generate**（一次 LLM 调用产出对应代码）→**review**（先本地确定性校验——
XML 良构/JSON 严格解析/mermaid lint/HTML 合理性检查，零 LLM 成本；校验不过
才升级成一次针对性修复调用；HTML 失败直接退化成模板，不修复）。若
analyze 选中 manim_video/manim_image，直接调用 Animator 模块——继承同一个
基建缺口。**非 Manim 分支自成一体，纯前端渲染（不需要服务端执行/沙箱），
与 Mneme"渲染不入主库"的 3O 红线天然契合（Mafs/Three.js 可以是渲染目标）**
——W4 spec 完全可以先只做这条分支，砍掉 Manim render-type，仍然是真实可用
的功能。

### Notebook
`deeptutor/services/notebook/service.py`（14.3KB，`NotebookManager`）+
`deeptutor/agents/notebook/`（analysis_agent.py 14.1KB + summarize_agent.py
4.3KB）。**不在 capability 注册表里**，不是独立 turn 能力。纯 JSON 文件
CRUD（`Notebook`含`NotebookRecord`列表，按 RecordType: SOLVE/QUESTION/
RESEARCH/CHAT/CO_WRITER/TUTORBOT 打标签）；`NotebookSummarizeAgent`
记录保存时跑一次流式 LLM 摘要；`NotebookAnalysisAgent`
（thinking→acting选记录→observing 三阶段）在新一轮对话挂了
`notebook_references` 时，把历史记录当轻量跨会话 RAG 素材。**后端体量
小，但横切**——Solve/Research/Chat/Co-Writer 全都往里写、也都能读。对
Mneme 更自然的落点是"既有永久档案（护城河）哲学的延伸"，不是一个独立
"模式"——工作重点是决定 Mneme 现有产出（哪些内容）该有存/取语义，不是
移植一条 pipeline。

### Co-Writer
`deeptutor/co_writer/`（顶层独立包，不在 capabilities/或 agents/下）：
`edit_agent.py`（13.3KB）+ `storage.py`（8KB）。`EditAgent.process()`每次
编辑动作（rewrite/shorten/expand）一次 LLM 调用，可选一次 `rag_search`
或 `web_search` 取上下文（二选一，失败退化成纯编辑）；`auto_mark()`一次
LLM 调用加标注标签。每次操作追加进有上限（200 条）的 JSON 历史文件做审计。
`storage.py`是纯文档清单 JSON CRUD（原子写入+标题从首个 markdown 标题
自动推断）。**后端简单——没有 pipeline、没有代码执行、没有沙箱**。DeepTutor
真正的复杂度在它自己 web app 的富文本编辑器 UI（本次未调研，超出后端
移植范围）——Mneme 若要做这个模式，mneme-web 需要一个对应的富文本编辑
界面，这块前端目前完全没有。

---

## 2. Mneme 沙箱现状

**`vendor/obase/sympy_runtime.py`（925 行，obase v0.13.0）真实存在且扎实**：
- 隔离：AST 白名单校验先行（`_SafeVisitor` 拒绝 import/exec/eval/open/私有
  属性访问/循环/lambda/函数定义），受限命名空间（`eval(code,
  {"__builtins__": {}}, ns)`，只暴露白名单 sympy 名字）。
- 超时：`_run_with_timeout` fork 子进程（`multiprocessing.get_context
  ("fork")`），轮询结果队列到 deadline，超时先 `terminate()`再
  `kill()`（SIGKILL）——**真的操作系统级杀进程**，不是协作式超时。非
  fork 平台退化到尽力而为的 `SIGALRM`（文档明确写只在主线程有效）。
- 内存：`RuntimeConfig.max_memory_bytes`（默认 64MB）**只是声明的配置项，
  代码里没有任何实际执行的地方**（没有 `resource.setrlimit`/`RLIMIT_AS`
  调用）——文档写了但没强制。
- 默认 `timeout_seconds=5.0`、`max_expression_depth=50`、
  `max_string_length=10000`。
- **测试**：`tests/test_sympy_sandbox_timeout.py` 直接验证红线——(1)
  `time.sleep(5)`配 0.3s 超时，断言 fork+kill 机制真的在约 2s 内杀掉（不是
  拖满 5s）；(2) 80 次多项式喂给 `solve_function`，断言有界返回时间+优雅
  `solvable=False`+错误信息含"timeout"，不是挂死/500。测试文件自己的
  docstring 承认这条红线**加这个文件之前是零覆盖**。

**缺口**：7 个 `solve_*.py` 里只有 5 个（function/conic/derivative/trig/
sequence）走 `SymPyRuntime`；**`solve_geometry3d.py`和`solve_probability.py`
直接调原生 sympy/math，完全绕过沙箱超时**——W4 若"Solve"模式要统一覆盖所有
题型，这个不一致得先补。

**其他执行/沙箱基建**：不存在。没有任意 Python 执行沙箱（repo 全文搜不到
RestrictedPython/pyodide/gVisor/firecracker/Docker-in-docker 的引用），
没有 Jupyter/notebook 内核基建（`requirements.txt`和全仓库都没有
nbformat/nbconvert/ipykernel），没有 JS 生成/执行沙箱给交互式可视化用。
`vendor/obase/docker/client.py`存在但**mneme 自己代码零处 import**——是
不相关产品的通用 vendor 库代码，没接进来。

**限流**：`vendor/obase/rate_limit.py`（异步滑动窗口）存在但**同样零处
被 mneme 使用**。真正生产在用的是`services/ratelimit.py`（Redis 固定
窗口，按 (scope, client_IP)），已经在保护 `/v1/solve` 和 LLM 端点（超限
429）——docstring 明说是因为"匿名 /v1/solve 和 LLM 端点可能被刷爆算力/
配额"，这条已有的限流约定（`rate_limit(limit=, window_seconds=,
scope=)` FastAPI 依赖）直接是 W4 Solve/Research 防滥用该复用的模式。

---

## 3. Mneme 既有可复用building blocks

**CLAUDE.md 列的三个文件逐一核实**：
- **`solve_*.py`**：存在，但是**七个独立文件**而非一个：
  `solve_function.py`/`solve_conic.py`/`solve_derivative.py`/
  `solve_trig.py`/`solve_sequence.py`/`solve_geometry3d.py`/
  `solve_probability.py`（均在 `vendor/oprim/`）。每个都是纯确定性
  dataclass-in/dataclass-out 内核（如 `solve_function(FunctionSolveInput)
  -> SolveResult`，覆盖 zeros/evaluate/domain/monotonicity/parity/
  compose/inverse 等任务）。合起来覆盖函数/圆锥曲线/导数/三角/数列/
  立体几何/概率组合——广东高中数学大部分题型的求解基础已经有了。
- **`kernel_viz.py`**：**不是单一文件**，但文档说的功能
  （`kernel_to_plot2d`/`kernel_to_three`）真实存在，拆成
  `vendor/oprim/kernel_to_plot2d.py`（采样 f(x)，找过零点）和
  `vendor/oprim/kernel_to_three.py`（采样 z=f(x,y) 曲面网格）。另有
  `vendor/oprim/generate_svg_diagram.py`直接把 Plot2DData/Three3DData
  渲成 SVG 字符串（2D 原生，3D 用等距投影）——**这是一条现成的"后端产出
  数据→前端渲染"路径**，可以直接喂给 Visualize 模式的非 Manim 分支，且
  与 Mafs/Three.js 前端栈天然契合。
- **`llm_oprims.py`**：存在但只实现了 CLAUDE.md 列的 5 个里的 3 个
  （ocr/grade/profiler）——`ocr_paper`/`grade_question`/
  `profiler_analyze`。**`socratic_turn`和 svg 生成不在这个文件里**：
  `socratic_turn`实际独立在 `vendor/oprim/socratic_turn.py`；"svg"由前面
  提到的确定性 `generate_svg_diagram.py`覆盖（根本不是 LLM oprim，和
  注释归类的不一样）。

**其他可复用**：`vendor/oprim/_arxiv_search.py`/`_gutenberg_search.py`/
`_oapen_search.py`/`_citation_formatter.py`（APA/MLA/Chicago）、
`vendor/oskill/web_research.py`/`researcher_workflow.py`（search→fetch→
extract→synthesize 组合）存在于共享 vendor 库——通用、领域无关，**非
mneme 编写/测试过**，但结构上与 Research/Co-Writer 相关。数学可视化专属
的动画能力不存在（`_animation_types.py`/`_face_animation.py`是通用视频
产品 vendor 代码，与数学可视化无关）。

**Provider**：`services/providers/qwenvl_caller.py`
（`QwenTextCaller`/`QwenVLCaller`）+ `ollama_caller.py`
（`OllamaCaller`）都实现 `obase.provider_registry` 的
`LLMCaller`/`VLMCaller` Protocol（`async __call__(*, messages,
max_tokens, tools, response_format, system)`），经
`ProviderRegistry.get().llm()/.vlm()`注册——**这是唯一现成、该被六模式
全部复用的调用约定，不要重新发明**。

**`requirements.txt`**：没有 PDF 生成、动画/视频、notebook 执行相关的库
——这些若要做，是需要先改 Master 的新依赖（CLAUDE.md 硬规则）。

---

## 4. studio 壳现状（apps/mneme-studio，B4 实战经验）

独立 Next.js 16/React 19 app（`basePath: "/studio"`，standalone 生产构建，
同源复用 mneme-web 登录）。

**已就绪，六模式可直接复用**：
- 路由：`app/<name>/page.tsx`扁平结构（`learn/`/`quiz/`/`chat`/`book/`，
  后两个是占位壳），加新模式=加新目录，零侵入。**当前没有共享导航/侧边栏
  组件**，四页互不知道对方存在。
- 数据通道：`lib/mcp.ts`一个 `call<T>(tool, payload)`泛型封装+具名方法，
  FC-5 零 DB 从建立起就是约束，不是 W3 才加。
- 鉴权：`localStorage.mneme_token`/`mneme_user`，同源复用 mneme-web 登录，
  **studio 没有自己的登录页**。
- KaTeX：`components/MathText.tsx`纯 katex 直渲染（非
  `@helios/blocks`的`OMarkdownRenderer`，那个在 Next16/React19 下有已知
  崩溃 bug）。
- **⭐ 3D 渲染栈已装好但零处使用**：`package.json`已有
  `@react-three/fiber`/`@react-three/drei`/`three`，但 grep 全
  app/components 目录**零 import 命中**——明显是为 Visualize/Animator 类
  可视化预先埋好的依赖，只差后端产出数据这一环（对应上面 §3 的
  `kernel_to_plot2d`/`kernel_to_three`）。
- e2e：Playwright 已配置（`e2e/`已有 3 个真实浏览器测试范式可以照抄）。

**明显缺失，六模式要新建**：
- 无共享导航壳（若要同时上线多模式，需要决定加真正导航还是继续"各自
  URL 靠外部链接跳转"）。
- 无富文本编辑组件（Notebook/Co-Writer 若要真文档编辑体验，不是现成的，
  `@helios/blocks`只有`OTextInput`级别）。
- 无代码执行/Jupyter 风格 cell 编辑器/代码高亮编辑器（Notebook 若要"写
  代码跑代码"，前端这块从零开始）。

---

## 5. 给 W4 spec 的几个直接推论（不是决定，仅供参考）

- Solve：Mneme 已有的确定性 `solve_*` 内核比 DeepTutor 那套"计划状态机"
  更扎实，W4 更可能是"补 solve_geometry3d/solve_probability 的沙箱覆盖 +
  加交互式分步计划 UI"，不是从头搬 DeepTutor 的 pipeline。
  R2/R2- 限流模式（`services/ratelimit.py`）已经在保护 `/v1/solve`，直接
  复用。
- Visualize：非 Manim 分支（svg/chartjs/mermaid/html）+ 已有的
  `kernel_to_plot2d`/`kernel_to_three`/`generate_svg_diagram` + 已装好
  但未用的 R3F/Three.js 前端栈——这条路径成本最低、最快能出真实可用功能。
- Animator：Manim 依赖是本仓库唯一"基建缺口"最实打实的一项——若要做，
  需要先决定是站起一个真正沙箱化的 Manim 渲染服务，还是用更轻量的替代
  方案；这个决定本身建议单独定，不要和 Visualize/Solve 混在一次 spec
  决策里。
- Research：K-12 数学场景基本用不上 arXiv 检索，若要做需要整体替换检索
  后端（同 W3 用 Knowledge Hub 替换 Stratum 是同一类工作）——且 DeepTutor
  这部分体量比 Book Engine 整个 W3 Part B 还大，值得单独评估是否要在 W4
  一次性做完，还是拆更小的阶段。
- Notebook：更适合当"Mneme 现有护城河档案"的延伸能力，不是六个并列模式
  之一——工作重点是"哪些既有产出该有存/取语义"，不是移植 DeepTutor 的
  JSON 存储机制本身（那部分很薄，不值得整体搬）。
- Co-Writer：后端简单，但前端（富文本编辑器）目前完全没有，是这个模式
  的真正工作量所在，不在后端。
