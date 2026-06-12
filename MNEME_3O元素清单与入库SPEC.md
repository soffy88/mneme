# Mneme · 3O 元素清单与主库入库实施 SPEC

> **目的**：列出 Mneme 需要的**全部 3O 元素**，并给出一份让 Claude Code 实施后**入主库**（oprim/oskill/omodul/obase 四个独立包）的规格。
> **关系**：本文档是 `MNEME_MASTER_DESIGN.md` 的入库执行规格；元素的业务语义以 Master 为准，本文档管"入哪个库、叫什么名、对外契约、入库红线"。
> **关键认知**：元素入的是**跨项目资产池**（3O 范式 §1.5）。命名反映"做什么"不反映"谁的"；单项目专属也是资产；不带 `mneme_` 前缀。
> **日期** 2026-06 ｜ **状态** 待实施

---

## 0. 入库前必读：三条铁律（3O 范式）

1. **命名禁项目前缀**：`solve_conic` ✅，`mneme_solve_conic` ❌。元素是跨项目资产，名字说"做什么"。
2. **命名空间扁平**：`from oprim import solve_conic`，不按领域分子模块（obase 例外，可分子模块）。
3. **层级硬约束**：oprim 互不调用；oskill ≥2 不同 oprim 组合、可受限互调（深度≤2）；omodul ≥2 oskill/oprim 组合 + 业务事务 + 不调 sibling omodul；obase 不反向调 3O。

**哪些进主库，哪些留 Mneme（Layer 4）**：

| 进主库（跨项目资产） | 留 Mneme 项目（Layer 4，不入库） |
|---------------------|--------------------------------|
| 所有 oprim / oskill / omodul / obase 元素 | FastAPI 路由、鉴权、多租户、SSE、Celery 调度 |
| 学科无关的算法与业务事务 | 广东数学 KC 字典（领域数据，Mneme 自带）|
| | 前端（Mafs/Three.js/考点地图/检索交互）|
| | InterleaveSchedulerEngine 等服务层引擎 |

> KC 字典是**领域数据**不是 3O 元素，留在 Mneme 项目 `data/`。但**读取 KC 先验的接口**若要通用，可设计成 omodul/oprim 接受外部传入字典（见 §5 注）。

---

## 1. oprim 清单（元实现 · 单次原子操作）

### 1.1 已实现（在 `core/bkt.py`、`core/fsrs_engine.py`，需重构入 oprim 包）

| 入库名 | 当前位置 | 形态 | 入库动作 |
|--------|---------|------|---------|
| `bkt_update` | bkt.py | 纯计算·贝叶斯更新 | 直接迁入，签名规范化（keyword-only） |
| `classify_error` | bkt.py | 纯计算·粗心/不会 | 迁入 |
| `predict_correct` | bkt.py | 纯计算·AUC 预测 | 迁入 |
| `exp_forgetting` | bkt.py | 纯计算·遗忘近似 | 迁入（或并入 fsrs 工具） |
| `fsrs_new_card` | fsrs_engine.new_card | py-fsrs 封装 | 迁入，重命名加 fsrs 前缀避免歧义 |
| `fsrs_review` | fsrs_engine.review | 单算法调用 | 迁入 |
| `fsrs_retrievability` | fsrs_engine.retrievability | 纯计算·R | 迁入 |
| `fsrs_map_rating` | fsrs_engine.map_performance_to_rating | 纯映射 | 迁入 |
| `fsrs_due_date` | fsrs_engine.due_date | 纯计算 | 迁入 |

> `KCState`（dataclass）作为 oprim 包的共享数据结构，放 `oprim/types.py` 或 `obase`。建议放 `oprim` 内，因 BKT 系列共用。

### 1.2 待实现 · 确定性求解内核（M-A）

| 入库名 | 形态 | 依赖 | 优先级 |
|--------|------|------|-------|
| `solve_conic` | sympy 求解·圆锥曲线 | obase.sympy_runtime | P0 |
| `solve_function` | sympy·函数/方程/不等式 | 同上 | P0 |
| `solve_derivative` | sympy·导数 | 同上 | P0 |
| `solve_geometry3d` | sympy·立体几何坐标向量法 | 同上 | P1 |
| `solve_sequence` | sympy·数列 | 同上 | P1 |
| `solve_trig` | sympy·三角/解三角形 | 同上 | P1 |
| `solve_probability` | sympy/numpy·概率统计 | 同上 | P1 |
| `verify_step` | 纯计算·校验某步是否成立 | 各 solve_* | P0 |

### 1.3 待实现 · 可视化数据（M-D/E）

| 入库名 | 形态 | 优先级 |
|--------|------|-------|
| `kernel_to_plot2d` | 纯计算·求解结果→2D 图示数据 JSON | P0 |
| `kernel_to_three` | 纯计算·求解结果→3D 顶点/边数据 | P1 |
| `generate_svg_diagram` | 单 LLM 调用·题意→SVG | P1 |
| `evaluate_diagram` | 单 VLM 调用/确定性校验·图示质量 | P1 |

### 1.4 待实现 · LLM 单调用类（语义任务）

| 入库名 | 形态 | 优先级 |
|--------|------|-------|
| `ocr_paper` | 单 Vision 调用·试卷结构化 | P0 |
| `grade_question` | 单调用·单题批改（确定性优先，无解析解时 LLM） | P0 |
| `profiler_analyze` | 单 LLM 调用·错误细分 | P0 |
| `socratic_turn` | 单 LLM 调用·一轮追问 | P0 |
| `generate_variant` | 单 LLM 调用·按 KC 生成变式题骨架 | P0 |

### 1.5 待实现 · 学习科学 / 价值层（机制 + 重构）

| 入库名 | 形态 | 机制 | 优先级 |
|--------|------|------|-------|
| `recognition_update` | 纯计算·识别维度贝叶斯更新 | M-G | P1 |
| `compute_effortful_gain` | 纯计算·难度×记忆增益 | M-F | P1 |
| `compute_peer_percentile` | 纯计算·掌握度分布百分位 | 社会比较 | P1 |

**oprim 合计：约 30 个**（已实现 9 + 待做 21）。

---

## 2. oskill 清单（元技能 · ≥2 oprim 组合算法）

| 入库名 | 组合的 oprim（≥2 不同） | 状态 | 优先级 |
|--------|------------------------|------|-------|
| `cognitive_update` | `fsrs_retrievability`+`bkt_update`+`classify_error`(+`recognition_update`) | ✅ 已实现于 cognitive_state，需扩展双维度 | P0 |
| `solve_and_visualize` | `solve_*`+`kernel_to_plot2d`/`kernel_to_three`+`evaluate_diagram` | 待做 | P0 |
| `socratic_loop` | `socratic_turn`(循环)+`verify_step`+情绪检测 | 待做 | P0 |
| `interleave_select` | 掌握度查询+`compute_effortful_gain`+混合排程 | 待做 | P0 |
| `generate_practice_set` | `generate_variant`+`solve_*`(验答)+`kernel_to_plot2d` | 待做 | P0 |
| `longitudinal_pattern` | 时间序列统计+单 LLM 解读 | 待做 | P1 |

**oskill 合计：6 个**。

> 注：`cognitive_update` 当前实现在 `cognitive_state.py` 里与存储耦合。入库时**拆分**：纯算法部分（算 R→更新→分类）入 `oskill.cognitive_update`（stateless，不碰 IO）；存储部分（CognitiveStore/process_interaction/mastery_overview/review_queue）属**服务层职责**，留 Mneme 项目，不入主库。

---

## 3. omodul 清单（元功能 · 业务事务，支柱按需）

| 入库名 | 组合 | 启用支柱 | 优先级 |
|--------|------|---------|-------|
| `analyze_paper_workflow` | `ocr_paper`+`grade_question`+`profiler_analyze`+`cognitive_update`+共同断点 | 全 4 支柱 | P0 |
| `generate_lesson_page` | `solve_and_visualize`+讲解组装 | `{fingerprint, report}` | P0 |
| `practice_workflow` | `generate_practice_set` | `{fingerprint, report}` | P0 |
| `socratic_session_workflow` | `socratic_loop`+`cognitive_update`(回写) | `{decision_trail, cost}` | P0 |
| `daily_mission_workflow` | `interleave_select`+检索约束+`compute_effortful_gain` | `{decision_trail}` | P1 |
| `longitudinal_analysis_workflow` | `longitudinal_pattern` | `{decision_trail}` | P1 |

**omodul 合计：6 个**（均为跨产品可复用业务事务；轻业务如注册/导出/通知也可入库，但属通用 SaaS 业务，本期不列）。

> 标准签名（MUST）：`(config: BaseConfig, input_data, output_dir: Path, *, on_step=None) -> dict`，返回含 `status`/`error` + 按 `_enabled_pillars` 的 `fingerprint`/`decision_trail`/`report_path`/`cost_usd`。失败不 raise。

---

## 4. obase 清单（基础设施 · 与 3O 平行）

| 入库名 | 用途 | 子模块 | 优先级 |
|--------|------|-------|-------|
| `ProviderRegistry` | Claude/Vision provider 抽象 | obase 顶层 | P0 |
| `CostTracker` | LLM 成本追踪（ContextVar） | 顶层 | P0 |
| `sha256_hash` / `canonical_json` | fingerprint/dedup | 顶层工具 | P0 |
| `sympy_runtime` | 求解沙箱（超时/内存/进程隔离） | `obase.sympy_runtime` | P0 |
| `auth` | JWT/bcrypt | `obase.auth` | P1 |
| `oss` | S3 兼容对象存储封装 | `obase.oss` | P1 |
| `secrets` / `http` / `fs` | 通用工具 | 各子模块 | P1 |

**obase 合计：约 10 个能力**。

> `sympy_runtime` 是关键新增：所有 `solve_*` 在沙箱内跑 sympy，防病态输入卡死。跨多个 solve_* 共用 → 入 obase（而非某个 oprim 私有）。

---

## 5. 全景汇总

```
oprim   ~30 个（9 已实现 + 21 待做）   单次原子操作
oskill   6 个                          ≥2 oprim 组合算法
omodul   6 个                          业务事务（支柱按需）
obase   ~10 个能力                     基础设施横切
─────────────────────────────────────
留 Mneme（Layer 4，不入库）：
  服务层（FastAPI/鉴权/多租户/SSE/Celery/调度引擎）
  广东数学 KC 字典（领域数据）
  前端（Mafs/Three.js/考点地图/检索交互/努力看板）
  CognitiveStore + process_interaction 等存储编排
```

> **KC 字典的处理**：KC 字典是广东数学的领域数据，留 Mneme。但 BKT 先验、KC 前置链是 `cognitive_update`/`analyze_paper_workflow` 需要的输入——通过**参数注入**传入（omodul 的 config 带 kc_dict 或 prior_provider），保持主库元素学科无关、可被其他学科项目复用。

---

## 6. 入库实施规格

### 6.1 物理结构（四个独立包）

```
oprim/    (PyPI: oprim)   独立 repo · SemVer · __version__ + __manifest__
oskill/   (PyPI: oskill)
omodul/   (PyPI: omodul)
obase/    (PyPI: obase)

Mneme 项目通过 pip install 引入这四个包，作为 Layer 4 调用者。
```

每个包 `__init__.py` 必须暴露（3O 范式 §2.6）：
```python
__version__: str = "X.Y.Z"
__manifest__: dict = {"version": __version__, "updated_at": "ISO",
    "elements": [{"name": "solve_conic", "layer": "oprim", "summary": "..."}, ...]}
```

### 6.2 演进策略（务实，分两阶段）

- **阶段一 · MVP（单 repo 逻辑分层）**：在 Mneme 仓库内按 `oprim/ oskill/ omodul/ obase/` 分目录开发，**先不拆 PyPI 包、不上跨仓治理**。理由：当前最大风险是 PMF 不是工程优雅。但**严格遵守 3O 命名与依赖规则**，使日后拆包零重构。
- **阶段二 · 验证后拆包**：把四个目录"提"成四个独立 PyPI 包 + repo，加 `__manifest__`、SemVer、CI lint。因为阶段一已按规则写，此步几乎只是物理搬迁。

### 6.3 每个元素的入库交付物（DoD）

一个元素算"入库完成"，必须：
1. **签名规范**：oprim keyword-only；返回 Pydantic 或基础类型；完整 docstring（含单行简介、Args、Returns、Raises、Example）。
2. **命名合规**：无项目前缀，扁平命名空间。
3. **层级合规**：oprim 不互调；oskill 列出组合的 oprim（docstring "Internal oprim composition"）；omodul 标准签名 + `_enabled_pillars` + 失败不 raise。
4. **学科无关**：领域数据通过参数注入，元素本身不 hardcode 广东数学。
5. **测试**：单测覆盖；纯计算 oprim 有确定性断言；LLM 类 oprim 可 mock。
6. **进 `__manifest__`**：name/layer/summary 登记。

### 6.4 入库红线（CI 必卡）

- **命名红线**：扫描元素名，含项目前缀（`mneme_`/`gd_` 等）→ block。
- **依赖红线**：oprim 互调 / obase 反向调 3O / omodul 调 omodul → block。
- **组合红线**：标 oskill 但只组合 1 个 oprim → block（复杂≠层级）。
- **学科耦合红线**：主库元素源码出现 "广东"/"GDMATH"/具体 KC 名 → block（领域数据须注入）。
- **确定性优先红线**：`grade_question`/变式题，有 solve_* 覆盖时数值必由内核给。
- **支柱红线**：omodul 未声明 `_enabled_pillars` → block。

### 6.5 实施顺序（新 Epic 14：入库化）

```
Epic 14 · 3O 入库化（在已有 Epic 基础上的重构层）
  14.1 [P0] obase 骨架 + ProviderRegistry + CostTracker + sha256/canonical_json + sympy_runtime
  14.2 [P0] oprim 包：迁入已实现 9 个（bkt/fsrs 系列）+ 签名规范化 + __manifest__
  14.3 [P0] oprim 包：solve_conic/function/derivative + verify_step + kernel_to_plot2d
  14.4 [P0] oprim 包：ocr/grade/profiler/socratic_turn/generate_variant（LLM 类）
  14.5 [P0] oskill 包：cognitive_update（拆出纯算法）+ solve_and_visualize + socratic_loop + interleave_select + generate_practice_set
  14.6 [P0] omodul 包：analyze_paper/generate_lesson_page/practice/socratic_session（标准签名+支柱）
  14.7 [P1] oprim 补全：solve_geometry3d/sequence/trig/probability + recognition_update + compute_effortful_gain + compute_peer_percentile + svg 系列
  14.8 [P1] omodul 补全：daily_mission/longitudinal_analysis
  14.9 [P1] 学科无关化改造：KC 字典/先验全部改参数注入，过学科耦合红线
  14.10 [P2] 拆四个独立 PyPI 包 + CI lint（阶段二，验证后）
DoD：每个元素过 §6.3 + §6.4；__manifest__ 完整；Mneme 项目改为 pip install 调用主库
```

> 依赖：14.1（obase 沙箱）→ 14.3（solve_* 需沙箱）；14.2/14.3/14.4（oprim）→ 14.5（oskill）→ 14.6（omodul）。
> 与 Master 路线图的关系：Epic 14 是把 Epic 0-13 产出的元素**按 3O 入库**的重构层，可与功能开发交织进行（边做功能边按 3O 落位），不必等功能全完成。

### 6.6 给 CC 的实施指令模板

```
读 MNEME_MASTER_DESIGN.md（业务语义）、本文档（入库规格）、CLAUDE.md（3O 约定）。
从 TASKS.md 的 Epic 14 认领第一个未完成 task。
严格遵守 §6.3 DoD 和 §6.4 入库红线：命名无项目前缀、层级合规、学科无关（领域数据注入）、登记 __manifest__、带测试。
完成后跑 pytest + 入库红线检查，在 TASKS 勾选并写说明，停下等确认。
```

---

## 7. 关键设计决策记录

1. **cognitive_update 拆分**：纯算法入 oskill（stateless），存储编排留服务层。这是 3O 的核心边界——算法可复用，存储是项目特定的。
2. **KC 字典不入主库**：它是广东数学领域数据。主库元素通过参数注入接受任意学科的 KC 字典，保证 `cognitive_update` 等能被语文、物理、甚至其他教育产品复用。
3. **变式题答案必由内核保证**：`generate_practice_set` 中 LLM 只出题型骨架，`solve_*` 出答案，杜绝"AI 出的题答案是错的"。
4. **sympy_runtime 入 obase 不入 oprim**：跨多个 solve_* 共用的横切关注点。
5. **渲染不入主库**：oprim 产出图示数据，前端渲染——3O 不覆盖 UI。
6. **入库即资产**：即使当前只有 Mneme 用，这些元素也入库（资产池性质）。`obase`（Claude provider/cost/sympy 沙箱）、`solve_*`、`cognitive_update` 都能直接服务你的其他项目。

---

**3O 元素清单与入库 SPEC 结束。元素业务语义以 Master 为准；入库标准以本文档 §6 为准。**
