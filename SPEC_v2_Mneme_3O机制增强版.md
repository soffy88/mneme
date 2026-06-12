# SPEC v2.0 · Mneme（学鉴）· 3O 机制增强版

> 工程代号 **Mneme**（记忆女神），对外中文名 **学鉴**。
> 本版做两件事：(1) 把全部元素**按 3O 范式归层**；(2) 整合**七大机制增强**（确定性内核 / 交错练习 / 检索练习 / 可视化生成 / 图示自检 / 努力错觉对抗 / 识别能力训练）。
> 取代 v1 SPEC 的"传统 routers/services/models 分层"组织方式；v1 的数据模型 DDL、API 契约、合规专章继续有效，本版只增补与重组。
> 配套：`CLAUDE.md`（需按本版 §2 更新 3O 约定）、`TASKS.md`（按本版 §6 增补 Epic）。

---

## 0. 设计哲学：三条主线（机制优秀的根）

实证调研（Khanmigo / Interactive Sketchpad / 学习科学前沿）指向同一结论。Mneme 的"机制优秀"不在界面炫，在三条主线：

**主线一：确定性内核兜住"算"和"图"，LLM 只负责"问"和"讲"。**
Khan Academy 公开承认给 Khanmigo 单独造了计算器，不靠 LLM 算数。edulab 用 sympy 精确求解再喂可视化。Mneme 比它们更进一步：不只剥离"计算"，还剥离"掌握度建模"(BKT)和"复习调度"(FSRS)。凡是有确定答案的（数值、坐标、图示几何关系），一律走确定性内核；LLM 只做语义任务（识别、引导、讲解组织）。

**主线二：把有硬证据却被忽视的学习科学机制做进调度。**
- 检索练习 > 重复阅读（回忆提升约 50%）→ 回顾必须主动回忆，不是重看。
- 交错练习训练"识别能力"（辨别效应 d=0.67）→ 复习池刻意混合知识点，不扎堆。
- 惰性知识：学生不是"不会"，是"没认出该用哪个方法"→ 区分"掌握"与"识别"。
- 努力错觉：学生因"感觉吃力"误判策略无效 → 可视化"难但有效"的学习收益。

**主线三：永久档案 + KT/FSRS 是护城河（继承 v1.2/v1.3，不变）。**

---

## 1. 七大机制增强总览

| 编号 | 机制 | 一句话 | 主线 |
|------|------|--------|------|
| M-A | 确定性求解内核 | sympy/numpy 精确求解，供苏格拉底校验 / 出题 / 图示取数 | 一 |
| M-B | 交错练习调度 | 复习池/今日目标刻意混合知识点，训练识别 | 二 |
| M-C | 检索练习约束 | 回顾必须先遮答案主动回忆，不是重看 | 二 |
| M-D | 可视化数据生成 | 确定性内核产出 2D/3D 图示数据（前端 Mafs/Three.js 渲染） | 一 |
| M-E | LLM 图示 pipeline + 自检 | SVG/代码中间表示 + 自动评估，兜 LLM 画图质量 | 一 |
| M-F | 努力错觉对抗 | 向学生展示"你以为没用但其实有效"的数据 | 二 |
| M-G | 识别能力训练 | BKT 区分"知识掌握"vs"识别该用"，对抗惰性知识 | 二 |

---

## 2. 3O 全景分层（核心：所有元素归层）

> 这是 CC 实施的导航图。仓库物理结构按 3O：`oprim/` `oskill/` `omodul/` `obase/` + 项目 `services/`（Layer 4）。
> MVP 阶段可先单 repo 内分目录（逻辑分层），验证后再拆四个独立包（见 §7 演进）。

### 2.1 oprim（元实现 · 单次原子操作）

| oprim | 形态 | 状态 | 机制 |
|-------|------|------|------|
| `bkt_update` | 纯计算（贝叶斯更新） | ✅ 已实现 | — |
| `classify_error` | 纯计算（粗心/不会） | ✅ 已实现 | — |
| `predict_correct` | 纯计算（AUC 预测） | ✅ 已实现 | — |
| `fsrs_review` | 单算法调用（py-fsrs） | ✅ 已实现 | — |
| `fsrs_retrievability` | 纯计算（R） | ✅ 已实现 | — |
| `solve_conic` | sympy 确定性求解（圆锥曲线） | 🆕 | M-A |
| `solve_geometry3d` | sympy 坐标向量法（立体几何） | 🆕 | M-A |
| `solve_derivative` | sympy（导数运算/单调极值） | 🆕 | M-A |
| `solve_sequence` | sympy（数列通项/求和） | 🆕 | M-A |
| `solve_trig` | sympy（三角恒等变换/解三角形） | 🆕 | M-A |
| `solve_probability` | sympy/numpy（古典概型/期望方差） | 🆕 | M-A |
| `solve_function` | sympy（函数性质/方程不等式） | 🆕 | M-A |
| `verify_step` | 纯计算（校验学生某一步是否成立） | 🆕 | M-A |
| `kernel_to_plot2d` | 纯计算（求解结果 → 2D 图示数据 JSON） | 🆕 | M-D |
| `kernel_to_three` | 纯计算（求解结果 → 3D 顶点/边数据） | 🆕 | M-D |
| `ocr_paper` | 单 Vision 调用（试卷结构化） | 待做 | — |
| `grade_question` | 单调用（确定性对比优先，无解析解时 LLM） | 待做 | — |
| `profiler_analyze` | 单 LLM 调用（错误细分） | 待做 | — |
| `socratic_turn` | 单 LLM 调用（一轮追问） | 待做 | — |
| `generate_svg_diagram` | 单 LLM 调用（题意 → SVG） | 🆕 | M-E |
| `evaluate_diagram` | 单 VLM 调用 或 确定性校验（图示质量） | 🆕 | M-E |
| `compute_effortful_gain` | 纯计算（难度×记忆增益指标） | 🆕 | M-F |
| `recognition_update` | 纯计算（识别能力贝叶斯更新） | 🆕 | M-G |

**关键归层判断**：
- 每个 `solve_*` 是"一次确定性计算" = oprim（符合 §3.2 形态 1）。
- `ocr_paper` / `profiler_analyze` / `socratic_turn` / `generate_svg_diagram` 都是"单 LLM 调用" = oprim（不是 oskill，复杂≠层级）。
- `kernel_to_plot2d` / `kernel_to_three` 是纯计算（求解结果转图示数据），与求解**同源** = oprim。
- **可视化的"渲染"（Mafs React / Three.js）不入 3O**，属前端（§9 范式不覆盖 UI）。主库只产出**图示数据**，前端负责画。

### 2.2 oskill（元技能 · ≥2 oprim 组合算法）

| oskill | 组合的 oprim（≥2） | 状态 | 机制 |
|--------|-------------------|------|------|
| `cognitive_update` | `fsrs_retrievability` + `bkt_update` + `classify_error`(+`recognition_update`) | ✅ 已实现，需扩展 | M-G |
| `solve_and_visualize` | `solve_*` + `kernel_to_plot2d`/`kernel_to_three` + `evaluate_diagram` | 🆕 | M-A/D/E |
| `socratic_loop` | `socratic_turn`(循环) + `verify_step` + 情绪检测 | 待做 | M-A |
| `interleave_select` | 掌握度查询 + `compute_effortful_gain` + 混合排程算法 | 🆕 | M-B |
| `longitudinal_pattern` | 时间序列统计 + 单 LLM 解读 | 待做 | — |

**归层要点**：
- `solve_and_visualize` 是 edulab 范式的核心 oskill：求解→转图示数据→自检，≥2 不同 oprim，stateless。
- `socratic_loop` 是 agentic 循环 oskill（§4.3 形态 2），内部用 `verify_step` 让确定性内核兜每一步正确性——**这是主线一在对话里的落地**。
- `interleave_select` 是交错练习的纯算法（输入掌握度+到期池，输出刻意混合的题序），stateless，不碰 IO。
- `cognitive_update` 扩展：答题后除更新掌握度，再调 `recognition_update` 更新识别维度。

### 2.3 omodul（元功能 · 业务事务，4 支柱按需）

| omodul | 组合 | 启用支柱 | 状态 | 机制 |
|--------|------|---------|------|------|
| `analyze_paper_workflow` | `ocr_paper`+`grade_question`+`profiler_analyze`+`cognitive_update`+共同断点 | 全 4 支柱 | 待做 | — |
| `socratic_session_workflow` | `socratic_loop`+`cognitive_update`(回写) | `{decision_trail, cost}` | 待做 | M-A |
| `generate_lesson_page` | `solve_and_visualize`+讲解组装 | `{fingerprint, report}` | 🆕 | M-A/D/E |
| `daily_mission_workflow` | `interleave_select`+检索约束+`compute_effortful_gain` | `{decision_trail}` | 🆕 | M-B/C/F |
| `longitudinal_analysis_workflow` | `longitudinal_pattern` | `{decision_trail}` | 待做 | — |
| 轻业务：`send_parent_report` / `export_archive` / `register_student` | — | 按需 | 待做 | — |

**归层要点**：
- `generate_lesson_page` = edulab 那种"一道题→讲解页"业务事务。`fingerprint` 用于同题去重（不重复求解），`report` 是讲解页交付物。
- `daily_mission_workflow` 把三个学习科学机制(M-B交错/M-C检索/M-F努力错觉)封装成"生成今日目标"这一业务事务。

### 2.4 obase（基础设施 · 与 3O 平行）

| obase | 用途 | 状态 |
|-------|------|------|
| `ProviderRegistry` | Claude / Vision provider 抽象 | 待做 |
| `CostTracker` | LLM 成本追踪 | 待做 |
| `sha256_hash` / `canonical_json` | dedup key / fingerprint | 待做 |
| `auth`（JWT/bcrypt） | 服务层鉴权 | 待做 |
| `fs` / `http` / `secrets` | 通用工具 | 待做 |
| `oss`（S3 兼容封装） | 试卷原图存储 | 待做 |
| `sympy_runtime` | sympy 执行沙箱（限时/限内存，安全跑求解） | 🆕 M-A |

**新增 `obase.sympy_runtime`**：所有 `solve_*` oprim 在受限沙箱内执行 sympy（超时杀、内存限、禁危险调用），因为 sympy 对恶意/病态输入可能卡死。这是横切关注点，多个 `solve_*` 共用 → obase 子模块。

### 2.5 服务层引擎（Layer 4 · 不入主库）

| 引擎/组件 | 职责 | 机制 |
|-----------|------|------|
| FastAPI 路由 | API 边界 | — |
| 鉴权/多租户/未成年人合规校验 | 横切（user_id 不进 omodul） | — |
| SSE 流式 | 苏格拉底对话推送（omodul on_step 回调） | M-A |
| Celery：试卷处理链 | 驱动 `analyze_paper_workflow` | — |
| Celery：日报/预警/纵向分析 | 调度 | — |
| **InterleaveSchedulerEngine** | 配置驱动：组织复习池的交错策略、节流 | M-B |
| 前端 PWA：Mafs(2D)/Three.js(3D) 渲染器 | 消费主库图示数据，渲染交互图 | M-D |
| 前端：检索练习交互（遮答案/计时/自评） | M-C 的 UI 落地 | M-C |
| 前端：努力错觉对抗看板 | 展示"难但有效"数据 | M-F |

---

## 3. 机制增强详述

### M-A 确定性求解内核

**目标**：消除"LLM 算错误导学生"，对标 Khanmigo 的计算器策略。

**覆盖范围**（按 KC 字典能力分级）：
- **完全覆盖（有解析解）**：圆锥曲线坐标计算、立体几何坐标向量法、导数运算与单调极值、数列通项求和、三角恒等变换/解三角形、古典概型/期望方差、函数性质/方程不等式求解。
- **部分覆盖（校验关键步 + LLM 兜底）**：导数压轴含参讨论、圆锥曲线综合证明——内核校验数值步骤，开放性论证由 LLM，但每个数值结论过 `verify_step`。
- **不覆盖**：纯文字论证题——标注 `solvable=false`，苏格拉底降级为纯对话。

**3O 归层**：各 `solve_*` = oprim；`verify_step` = oprim；沙箱 = `obase.sympy_runtime`；`socratic_loop` 调 `verify_step` 校验学生每步。

**接口契约**（示意）：
```python
def solve_conic(*, problem_spec: ConicSpec) -> SolveResult:
    """sympy 精确求解圆锥曲线问题。在 obase.sympy_runtime 沙箱内执行。
    Returns SolveResult(
        answer: str,              # LaTeX
        steps: list[Step],        # 每步含 latex + 中间值
        plot_data: dict | None,   # 供 kernel_to_plot2d 用的源数据
        solvable: bool,
    )
    """

def verify_step(*, kc_id: str, claim: str, context: dict) -> StepCheck:
    """校验学生在解题中提出的某一步是否成立（确定性）。
    Returns StepCheck(valid: bool, reason: str | None)
    """
```

**验收**：
- 每个 `solve_*` 有 ≥10 道样题的内核自检（内核答案 == 标准答案）。
- `socratic_loop` 红线测试：学生提出错误中间步时，`verify_step` 必须判 false（不依赖 LLM 判断）。
- 沙箱：病态输入（如超大幂、符号爆炸）必须在超时内被杀，不拖垮服务。

### M-B 交错练习调度

**目标**：复习池/今日目标刻意混合不同知识点，训练"识别该用哪个方法"（辨别效应 d=0.67），对抗惰性知识。

**3O 归层**：`interleave_select` = oskill（纯算法）；调度协调 = 服务层 `InterleaveSchedulerEngine`；封装为业务事务 = `daily_mission_workflow`。

**算法逻辑**（`interleave_select`）：
```
输入：到期复习池(FSRS due) + 各 KC 掌握度 + 当日时长预算
规则：
  1. 不连续出现同一 KC 的题（相邻题 KC 不同）
  2. 优先混合"易混淆 KC 对"（如椭圆/双曲线、排列/组合）——混淆对表配置化
  3. 难度梯度：穿插已掌握(检索巩固)与薄弱(学习)，避免连续受挫
  4. 总时长 ≤ 预算
输出：有序题列表（交错排布）
```

**验收**：
- 输出序列中相邻题 KC 不同（除非池中只剩一个 KC）。
- 对照测试：交错序列 vs 扎堆序列，可在模拟数据上验证交错覆盖更多 KC。

### M-C 检索练习约束

**目标**：回顾环节必须是**主动回忆**（先遮答案自己做），不是重看题和答案（检索提升回忆约 50%）。

**3O 归层**：这是业务规则 + 前端交互，体现在 `daily_mission_workflow`（mission 标记 `requires_active_recall=true`）和前端交互；回顾结果映射 FSRS rating 走 `cognitive_update`。

**落地要求**：
- 回顾题默认**隐藏答案和解析**，学生先作答/自评，再揭示。
- 学生自评（"想出来了/不确定/不会"）映射 FSRS Rating（见 v1.3 §3.3）。
- 禁止"一键看答案直接标记完成"——看答案视为 Again（记忆重置），不算检索成功。

**验收**：回顾流程前端测试：未作答不可见答案；看答案后该次 rating = Again。

### M-D 可视化数据生成（2D/3D）

**目标**：edulab 式"丝滑图示"——确定性内核产出图示数据，前端渲染交互图。覆盖函数图象、解析几何、概率/统计图(2D)、立体几何(3D)。

**3O 归层**：
- `kernel_to_plot2d` / `kernel_to_three` = oprim（求解结果→图示数据，与解题**同源**）。
- `solve_and_visualize` = oskill（求解+转数据+自检）。
- 渲染（**Mafs** for 2D React / **Three.js** for 3D）= **前端，不入主库**。
- 完整"题→讲解页"业务事务 = `generate_lesson_page` omodul。

**技术选型依据**：React PWA → 2D 用 Mafs（React 原生数学组件，零摩擦）或 Desmos API；3D 用 Three.js（edulab 已验证）。不用 Manim（离线视频，场景不符）。

**同源原则（MUST）**：图示的坐标/数值与解题答案来自**同一次 `solve_*` 调用**，杜绝"图和答案对不上"。

**验收**：讲解页自检——图示数据中的关键值 == 解题答案 == 末步显示值（三处一致，edulab 的自检机制）。

### M-E LLM 图示 pipeline + 自检

**目标**：对没有现成内核模板的题型，用 LLM 生成 SVG 作中间表示（arXiv 2503.07429 路径），并自动评估质量（DiagramIR 思路），兜住 LLM 画图的不可靠。

**3O 归层**：`generate_svg_diagram` = oprim（单 LLM 调用）；`evaluate_diagram` = oprim（VLM 单调用或确定性校验）；二者 + 重试组合进 `solve_and_visualize`（当无内核模板时走此分支）。

**pipeline**：
```
有内核模板（M-D）→ 优先用确定性图示数据（最可靠）
无内核模板 → generate_svg_diagram(LLM 出 SVG)
            → evaluate_diagram(校验：元素齐全/比例合理/标注正确)
            → 不合格则重试(≤2次)，仍不合格则降级为纯文字
```

**验收**：`evaluate_diagram` 能拦截明显错误图（缺元素/比例失真）；不合格不展示给学生。

### M-F 努力错觉对抗

**目标**：学生常因"感觉吃力"误判策略无效（误读努力假说）。主动可视化"难但有效"的学习收益，强化正确的学习行为。

**3O 归层**：`compute_effortful_gain` = oprim（纯计算：难度 × 记忆增益）；数据进 `daily_mission_workflow`；展示在前端看板。

**指标逻辑**（`compute_effortful_gain`）：
```
effortful_gain = struggle_score × retention_delta
  struggle_score: 本次作答的吃力程度(用时/Hard评分/苏格拉底轮次)
  retention_delta: FSRS 稳定性 S 的提升量
含义：越吃力且越提升记忆稳定性的题，gain 越高
```

**前端呈现**：
> "这道椭圆题你做得很吃力，但正因为难，你对它的记忆稳定性提升了最多——这种'费劲'恰恰是学得最牢的信号。"

**验收**：gain 指标计算正确；前端能展示当周 gain 最高的题及其文案。

### M-G 识别能力训练（对抗惰性知识）

**目标**：区分"知识掌握"与"识别该用哪个方法"。学生常有知识却认不出该用——这是迁移的主要障碍（Corral & Kurtz 2025）。

**3O 归层**：`recognition_update` = oprim（识别维度的贝叶斯更新）；`cognitive_update` oskill 扩展为同时更新 mastery 和 recognition；交错练习(M-B)是训练 recognition 的手段。

**模型设计**：
```
每个 KC 维护两个维度：
  p_mastery     : 会不会做（已有 BKT）
  p_recognition : 在混合情境下认不认得出该用这个 KC（新增）
区分信号：
  - 在"单 KC 专项"中做对 → 主要提升 mastery
  - 在"交错混合"中做对 → 同时提升 recognition（因为需要先识别）
  - 知识强但混合中错 → recognition 弱（惰性知识）→ 多安排交错练习
```

**验收**：构造"专项对但混合错"的模拟序列，系统能识别为 recognition 弱并增加交错练习推荐。

---

## 4. 数据模型增量（在 v1 DDL 基础上）

```sql
-- kc_mastery 表新增识别维度（M-G）
ALTER TABLE kc_mastery ADD COLUMN p_recognition FLOAT;
ALTER TABLE kc_mastery ADD COLUMN p_recognition_init FLOAT;

-- 求解缓存（M-A，避免重复 sympy 计算，配合 fingerprint 去重）
CREATE TABLE solve_cache (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kc_id        VARCHAR(100),
  problem_hash VARCHAR(64) UNIQUE,    -- 题目规格 hash
  solve_result JSONB,                  -- SolveResult 序列化
  solvable     BOOLEAN,
  created_at   TIMESTAMPTZ DEFAULT now()
);

-- 讲解页（M-D/E，generate_lesson_page 产物）
CREATE TABLE lesson_pages (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  question_id  UUID REFERENCES wrong_questions(id),
  fingerprint  VARCHAR(64),
  plot_data    JSONB,                  -- 图示数据（同源）
  diagram_svg  TEXT,                    -- LLM 生成分支的 SVG（如有）
  self_check_passed BOOLEAN,            -- 三处一致自检
  report_path  TEXT,
  created_at   TIMESTAMPTZ DEFAULT now()
);

-- daily_missions 增字段（M-B/C）
ALTER TABLE daily_missions ADD COLUMN interleaved BOOLEAN DEFAULT FALSE;
ALTER TABLE daily_missions ADD COLUMN requires_active_recall BOOLEAN DEFAULT FALSE;

-- 努力收益记录（M-F）
CREATE TABLE effortful_gains (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id  UUID,
  question_id UUID,
  struggle_score FLOAT,
  retention_delta FLOAT,
  effortful_gain FLOAT,
  occurred_at TIMESTAMPTZ DEFAULT now()
);

-- interaction_events 增字段（M-B/G：标记是否来自交错情境）
ALTER TABLE interaction_events ADD COLUMN is_interleaved BOOLEAN DEFAULT FALSE;
```

---

## 5. 关键质量门（机制相关，CI 必须卡）

继承 v1 质量门，新增：

- **确定性优先红线**：凡有 `solve_*` 能覆盖的题型，数值结论必须来自内核，禁止 LLM 直接出数值答案。测试：mock LLM 给错误数值，系统最终答案仍以内核为准。
- **同源自检**：`generate_lesson_page` 产物，图示关键值 == 解题答案 == 末步值，三处不一致则 `self_check_passed=false` 且不交付。
- **交错有效性**：`interleave_select` 输出相邻题 KC 不同。
- **检索约束**：回顾未作答不可见答案；看答案 = Again。
- **沙箱安全**：病态 sympy 输入超时被杀。
- **苏格拉底步校验**：错误中间步由 `verify_step` 拦截（确定性），不依赖 LLM。

---

## 6. 任务看板增量（新增 Epic，并入 TASKS.md）

```
Epic 10 · 确定性求解内核 (M-A)
  10.1 [P0] obase.sympy_runtime 沙箱（超时/内存/安全）
  10.2 [P0] solve_conic / solve_function / solve_derivative（高频先做）
  10.3 [P1] solve_geometry3d / solve_sequence / solve_trig / solve_probability
  10.4 [P0] verify_step + 接入 socratic_loop（对话步校验）
  10.5 [P1] solve_cache 去重
  DoD：每个 solve_* ≥10 样题内核自检通过；确定性优先红线测试通过

Epic 11 · 可视化生成 (M-D/E)
  11.1 [P0] kernel_to_plot2d / kernel_to_three（图示数据，同源）
  11.2 [P0] 前端 Mafs(2D) 渲染器 + 数据契约
  11.3 [P1] 前端 Three.js(3D) 渲染器（复用 edulab 思路）
  11.4 [P1] generate_svg_diagram + evaluate_diagram（LLM 分支 + 自检）
  11.5 [P0] solve_and_visualize oskill + generate_lesson_page omodul
  DoD：讲解页三处一致自检通过；不合格图不展示

Epic 12 · 学习科学机制 (M-B/C/F/G)
  12.1 [P0] recognition_update + cognitive_update 扩展（双维度）
  12.2 [P0] interleave_select oskill + 混淆对配置表
  12.3 [P0] daily_mission_workflow 整合交错+检索约束
  12.4 [P1] InterleaveSchedulerEngine（服务层调度）
  12.5 [P1] compute_effortful_gain + 前端努力错觉看板
  12.6 [P1] 检索练习前端交互（遮答案/自评/计时）
  DoD：交错相邻 KC 不同；检索约束生效；recognition 弱可被识别
```

依赖：Epic 10 是 11/12 部分功能的前置（图示和苏格拉底校验都依赖求解内核）。建议顺序 10.1→10.2→10.4，与 11.1→11.2→11.5 并行，再做 12。

---

## 7. 3O 演进策略（务实）

- **MVP 阶段**：单 repo 内按 3O 分目录（`oprim/ oskill/ omodul/ obase/ services/`），逻辑分层到位，但**不拆四个 PyPI 包、不上全套 CI 治理**。因为当前最大风险是 PMF 不是工程优雅。
- **验证通过后**：把已按 3O 写好的代码"提"成四个独立包，几乎零重构（这正是 3O 前期分层的红利）。
- **跨项目复用**：`obase`（Claude provider/cost/sympy 沙箱）、通用 omodul（注册/导出/通知）可复用到你的其他项目。

---

## 8. 风险（机制相关）

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| sympy 覆盖不全（压轴/证明题） | 高 | 中 | 分级：完全覆盖/校验关键步/不覆盖；不覆盖时苏格拉底降级纯对话，不硬撑 |
| 内核求解与教材标准解法不一致（坐标向量法 vs 综合几何法） | 中 | 中 | 内核保证答案对；讲解层注明"本解法用向量法"，提供方法选择 |
| LLM 生成 SVG 质量不稳 | 中 | 中 | 优先用内核图示数据；LLM 分支必过 evaluate_diagram + 重试 + 降级 |
| 交错练习增加初期挫败感 | 中 | 中 | 难度梯度穿插已掌握题；可配置交错强度；新手期降低交错比例 |
| 识别维度冷启动数据不足 | 高 | 低 | recognition 先验保守；数据足够前不强推结论 |
| 沙箱被病态输入拖垮 | 中 | 高 | obase.sympy_runtime 强制超时+内存限+进程隔离 |

---

**SPEC v2.0 结束。**

*核心：确定性内核兜住"算"与"图"，学习科学机制做进调度，LLM 只做"问"与"讲"。*
*这套机制 + 永久档案 + KT/FSRS，按 3O 沉淀为可跨项目复用的资产——这才是 Mneme 的护城河。*
