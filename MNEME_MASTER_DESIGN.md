# Mneme（善学记）· 主设计文档

> **工程代号** Mneme（希腊记忆女神）｜**对外中文名** 善学记（旧名"学鉴"已于 2026-07 废弃）
> **文档状态** 唯一事实来源（SSOT）｜**版本** Master v1.0｜**日期** 2026-06
>
> 本文档是 Mneme 的**唯一权威设计**，整合并取代以下历史文档：PRD v1.0/v1.1（高考作战系统，已废弃方向）、PRD v1.2（战略重定位）、PRD v1.3（算法内核）、SPEC v1（工程实施）、SPEC v2（3O 机制增强）。历史文档转为"设计演进记录"，不再作为施工依据。
> CC 与协作者**只读本文档**。冲突时以本文档为准；需偏离先改本文档。
> 执行看板见 `TASKS.md`，工程约定见 `CLAUDE.md`（二者均指向本文档为权威）。

---

## 目录

```
第一部分 · 产品
  1  产品概述与三条主线
  2  用户与场景
  3  永久学习档案（核心差异化）
第二部分 · 技术内核
  4  算法内核：KT + FSRS + 识别维度
  5  七大机制增强
  6  3O 架构全景分层
第三部分 · 工程契约
  7  完整数据模型（DDL）
  8  完整 API 契约
  9  技术栈与全局约束
第四部分 · 治理
  10 未成年人合规（强制专章）
  11 商业模式
  12 开发路线图与任务总表
  13 非功能需求 / 质量门 / 风险
  附录 A  KC 知识点字典  ·  B  术语表  ·  C  设计演进史
```

---

# 第一部分 · 产品

## 1. 产品概述与三条主线

### 1.1 定位

Mneme 是面向**全年级学生（初中、高中）**的**个人学习成长档案与自主学习工具**。它把学生从初中到高中的每一张试卷、每一道错题、每一次认知突破永久保存为不断生长的"学习成长档案"，并用 AI 帮助学生认识自己的学习模式、修复认知断点、持续自主进步。

> **价值主张**：它不替你决定该学什么。它帮你看清——你是怎么学的，你在怎样变好。
> **核心隐喻**：一面照见自己学习轨迹的镜子，而非作战参谋。

### 1.2 三条设计主线（机制优秀的根）

实证调研（Khanmigo / Interactive Sketchpad / 学习科学前沿）指向同一结论。Mneme 的"机制优秀"不在界面，在三条主线：

1. **确定性内核兜住"算"和"图"，LLM 只负责"问"和"讲"。** Khan Academy 公开承认给 Khanmigo 单独造计算器不靠 LLM 算数；edulab 用 sympy 精确求解再喂可视化。Mneme 更进一步：不只剥离"计算"，还把"掌握度建模"(BKT) 和"复习调度"(FSRS) 也做成确定性算法。凡有确定答案的（数值、坐标、图示几何关系），一律走确定性内核；LLM 只做语义任务（识别、引导、讲解组织）。

2. **把有硬证据却被忽视的学习科学机制做进调度。** 检索练习 > 重复阅读（回忆提升约 50%）；交错练习训练"识别能力"（辨别效应 d=0.67）；惰性知识——学生不是"不会"而是"没认出该用哪个方法"；努力错觉——学生因"感觉吃力"误判策略无效。

3. **永久档案 + KT/FSRS 是护城河。** 苏格拉底对话已被大厂和基础模型商品化，不能作差异化。真正别人复制不了的，是一份随时间增值、归学生所有的永久学习档案，加上 KT/FSRS 带来的个性化精度。

### 1.3 现有工具的根本缺陷（我们为何存在）

数据是碎片而非连续的；只诊断当下不追踪历史；只给答案不修复认知；数据属于平台而非学生；给了计划没有执行支持；错题本静态、不对抗遗忘。

---

## 2. 用户与场景

### 2.1 目标用户

**主要：全年级学生（初一至高三，12–18 岁）**。分层需求：初中生建立习惯、积累错题、认识薄弱点；高一高二长期追踪、查漏补缺；高三冲刺期重点突破（作为可选"冲刺模式"，非唯一焦点）。

**次要：家长**。诉求是看到孩子长期连续的成长而非单次分数；二孩家庭需多孩子统一管理；主要通过微信获取信息。

### 2.2 痛点矩阵

| 角色 | 痛点 | Mneme 解法 |
|------|------|-----------|
| 学生 | 错题攒了就丢 | 永久数字档案 |
| 学生 | 不知道自己在进步吗 | 纵向成长曲线 |
| 学生 | 同样的错反复犯 | 遗忘曲线 + 模式识别 |
| 学生 | 学了不理解 | 苏格拉底引导自主推导 |
| 学生 | 有知识却认不出该用 | 识别能力训练（交错练习） |
| 学生 | 升学换工具历史归零 | 跨学段永久保存 |
| 家长 | 信息黑洞、不知如何帮 | 成长摘要 + 行动指南 |
| 家长 | 不用 APP 也想知道 | 微信一句话日报 |
| 家长 | 两个孩子要管 | 多孩子切换 |

### 2.3 关键场景

- **首次顿悟（冷启动钩子）**：上传一张卷，系统不只列错题，而是指出"这些错误背后的同一个断点"，再进入一次苏格拉底"想通了"的瞬间。
- **跨年度成长回看**：看到"二次函数"掌握度从初二 0.3 → 初三 0.55 → 现在 0.8，错误类型从"概念不清"变成"偶尔粗心"——真正理解了。
- **个人模式识别**：积累半年后，"你在 3 步以上推理的题正确率骤降，薄弱不在知识点而在多步骤思路保持"。
- **家长看成长非分数**：看到"本月物理薄弱点从 7 个减到 4 个，已连续学习 23 天"，而非一个可能偏低的预估分。

### 2.4 冷启动双层钩子

- **第一层 · 即时顿悟（不依赖长期数据）**：上传一张卷即看到"共同断点" + 一次苏格拉底顿悟。目标：第一次就产生"它真的看懂了我"。
- **第二层 · 长期增值（用得越久越离不开）**：档案随时间增长，纵向洞察越来越准，迁移成本指数上升。目标：用满 3 个月后不愿丢掉自己的成长档案。

---

## 3. 永久学习档案（核心差异化）

### 3.1 档案构成

```
个人学习成长档案
├── 试卷库（永久保存所有试卷原图 + 结构化数据）
├── 错题库（每道错题 + 当时认知分析 + 苏格拉底对话记录）
├── 知识点掌握度时间序列（逐月演变曲线）
├── 错误类型演变（概念→迁移→粗心的转化轨迹）
├── 个人学习模式画像（识别出的独特规律）
└── 成长里程碑（突破时刻、连续学习记录）
```

### 3.2 为什么"永久"是壁垒

不可复制（竞品无法获得用户过去几年连续数据）；迁移成本极高；越用越准（纵向越长，模式识别越精确）；数据归学生（可导出 PDF 成长报告）。

### 3.3 数据→洞察转化（避免数据沉睡）

| 数据积累 | 产出洞察 |
|---------|---------|
| 单次试卷 | 本次认知断点 + 同类错误归因 |
| 1 个月 | 高频薄弱点 + 错误类型分布 |
| 1 学期 | 掌握演变 + 个人模式初判 |
| 1 学年+ | 跨年度成长曲线 + 稳定学习者画像 |
| 跨学段 | 初中→高中知识衔接断层识别 |

---

# 第二部分 · 技术内核

## 4. 算法内核：KT + FSRS + 识别维度

### 4.1 三层认知状态架构

```
应用层（今日目标·成长曲线·苏格拉底·家长端）
        │ 读取认知状态
认知状态层（v1.3 内核）
  ┌──────────────┐      ┌──────────────────┐
  │ 知识追踪 KT  │◄────►│  FSRS 调度器     │
  │「掌握了吗」  │      │「何时该复习」    │
  │ P(掌握)      │      │  D / S / R       │
  │ slip/guess   │      │  下次复习日      │
  │ +识别维度    │      │                  │
  └──────────────┘      └──────────────────┘
        └──── forgetting-aware 统一 ────┘
        │ 消费答题事件
事件层：每次答题/对话/回顾 (KC, 对错, 用时, 距上次间隔, 时间戳)
```

### 4.2 BKT 知识追踪（确定性，已实现并验证）

为何从 BKT 起步而非 DKT：可解释、冷启动友好、参数即产品功能（slip=粗心、guess=蒙对）、轻量（进程内纯计算）。

**四参数**（每个知识点 KC）：

| 参数 | 符号 | 含义 | 产品对应 |
|------|------|------|---------|
| 初始掌握 | P(L₀) | 接触前已掌握概率 | 按年级/知识点设先验 |
| 学习转移 | P(T) | 一次有效练习学会的概率 | 反映学习难度 |
| 猜测 | P(G) | 未掌握却答对 | 选择题设较高 |
| 失误 | P(S) | 已掌握却答错 | **直接量化"粗心"** |

**贝叶斯更新（两步）**：

```
答对： P(L|correct) = P(L)(1-S) / [P(L)(1-S) + (1-P(L))G]
答错： P(L|wrong)   = P(L)·S   / [P(L)·S   + (1-P(L))(1-G)]
应用学习： P(L') = P(L|obs) + (1 - P(L|obs))·T
掌握度封顶 0.97（现实中无"100%掌握"，且为遗忘留空间）
```

**粗心 vs 不会判定**（客观判据，优于 LLM 猜测）：
```
careless ∝ P(L)·P(S)        # 高掌握却答错 → 粗心
dontknow ∝ (1-P(L))·(1-P(G)) # 低掌握答错 → 不会
```

### 4.3 FSRS 间隔重复（确定性，已实现）

替代 SM-2（1987）。FSRS 同等记忆留存下复习量减少约 20-30%，Anki 2023.10 起默认。

**三变量记忆模型**：难度 D(1-10)、稳定性 S(天)、可提取性 R(0-1, 当前能回忆概率)。当 R 衰减到目标留存率（默认 0.9）时安排复习；答对 S 增长（间隔拉长），答错 S 重置。

**评分映射**：没做出/看答案→Again；吃力→Hard；正常→Good；秒杀→Easy。苏格拉底结果同样映射。

**工程**：直接用官方 `py-fsrs`，不自研。Card 状态序列化入库。

### 4.3.1 FSRS 权重个性化（从真实复习日志优化，护城河兑现）

**问题**：默认 `py-fsrs` 用一套全局 FSRS-6 权重，人人吃群体默认间隔——"KT/FSRS 个性化精度"这条护城河没真正兑现。

**设计**（数据飞轮）：
- `fsrs_engine` 的 `fsrs_review/retrievability` 接受可选 `parameters`（21 维权重）；`None`=全局默认（行为不变）。缓存按权重的 `Scheduler`。
- `interaction_events`（只增）即复习日志。`fsrs_optimize_service` 重放每张卡片序列，以「复习前预测可提取性 R vs 真实回忆结果」的**对数损失**为目标函数。
- **优化方法：导数无关（derivative-free）的 `scipy.optimize`（Powell/Nelder-Mead）**，直接最小化上述 log-loss——**不引入 torch**：py-fsrs 前向不可微，且 scipy 已在 numpy/sympy 技术栈内，无需重写 FSRS 前向或加重型依赖。超出 FSRS 合法区间的权重记 `inf`，自然被排除。
- **两级粒度**：cohort=`global`（全体）兜底；cohort=`student:{id}`（个体，复习量足够才拟合）。`process_interaction` 加载时**先个体后全体**，都无则默认。权重存 `fsrs_weights(cohort UNIQUE, parameters JSONB, logloss, n_reviews)`。
- 离线任务（Celery beat）周期性拟合；权重只读加载进调度，不改已验证的 BKT/FSRS 算法契约。

### 4.4 forgetting-aware 统一模型（KT 与 FSRS 协同）

解决"KT 说掌握了、FSRS 说该复习了"的矛盾：让两者共享"遗忘"事实。

```
事件：学生在 KC_i 答题/回顾
  ├─► FSRS：更新 D/S/R，算出下次 due
  └─► forgetting-aware BKT：
        更新前先用 FSRS 的可提取性 R 衰减先验掌握度
        P(L)_eff = P(L) · R
        再做贝叶斯观测更新
```

含义：**掌握度 = 长期是否学会(BKT) × 此刻是否记得(FSRS 的 R)**。
- `long_term_mastery`（去遗忘）→ 成长曲线展示
- `effective_mastery`（含遗忘）→ 今日目标决定该复习什么

### 4.5 识别维度（对抗惰性知识，机制 M-G）

每个 KC 维护两个维度，区分"知识掌握"与"识别该用"：

```
p_mastery     ：会不会做（BKT 已有）
p_recognition ：混合情境下认不认得出该用这个 KC（新增）
区分信号：
  单 KC 专项做对 → 主要提升 mastery
  交错混合做对   → 同时提升 recognition（需先识别）
  知识强但混合错 → recognition 弱（惰性知识）→ 多安排交错练习
```

### 4.6 算法与 LLM 分工边界

| 任务 | 由谁做 | 理由 |
|------|--------|------|
| 掌握度估计 / 粗心判定 / 复习调度 / 数值求解 | 算法（确定性） | 客观、可积累、毫秒级、省 token |
| 错误类型细分 / 共同断点 / 苏格拉底追问 / 讲解组织 | LLM | 需语义理解 |
| 个人学习模式识别 | LLM + KT 数据 | LLM 解读 KT 时间序列 |

### 4.7 演进与已验证结果

- **已验证**（内核 `oprim/tests/test_cognitive.py`、`test_bkt_irt.py` 全绿）：掌握度收敛合理并封顶 0.97；同一 KC 能区分粗心/不会；forgetting-aware 衰减正常；下一题预测**合成数据 AUC≥0.65**（随机=0.5；**0.77 为目标，真实数据待验证**）；KT+FSRS 端到端正常。
- **DKT 演进（Phase 3）**：数据充足后引入 LSTM/Transformer 建模序列，捕捉跨知识点迁移，支撑跨学段衔接分析；用 AUC 对比 BKT 决定切换；保留 BKT 作可解释层。

### 4.8 FIRe-lite：前置复习信用回写（机制 M-H，2026-07 新增契约）

> 借鉴 Math Academy FIRe（Fractional Implicit Repetition）：成功解出综合题 = 隐式检索了其前置知识，应按比例折算前置的复习信用，压缩总复习量。本契约为保守的 **lite 版**：只顺延调度，不改记忆状态。

**触发条件**（全部满足）：
1. 一次交互 `is_correct=True` 落在 KC/KU `c`，且 `c` 在前置图上有 `verified` 的前置边（未过校验门的 LLM 前置边不参与——防幻觉边扩散信用）；
2. 该交互为真实检索（过了 20h 集中练习去抖、非 fire_credit 自身产生）。

**回写规则**：对每个前置 `p ∈ prereq(c)`：
- 信用系数 `κ_p = κ0 · P(L)_p`，`κ0 = 0.5` 默认。**乘 P(L)_p 而非缺口**：前置掌握度高者，综合题成功才可信地意味着它被真正提取；掌握度低者可能被绕过/蒙对，不应免除其复习（这与 Math Academy 的全额隐式重复刻意不同，是防信号污染的保守化）。
- `κ_p < τ`（τ=0.3）不回写。
- 回写动作 = **仅顺延 due**：`new_due_p = max(due_p, now + κ_p × S_p 天)`（S_p 为该卡当前 stability）。**不执行 FSRS review、不改 D/S/R、不更新 BKT P(L)**——前置未被直接观测，只延后"什么时候需要再看"。
- 事件：interaction_events 追加 `source="fire_credit"` 一条（只增不改），记录触发交互 id、p、κ_p、顺延前后 due。

**红线交互**：更新顺序红线（§红线）不受影响——FIRe 回写发生在主更新链完成并落库之后，是独立后续步骤；P(L)∈(0,0.97] 无涉；检索门无涉；`fire_credit` 事件不得再触发 FIRe（无级联）。

**3O 归层**：oskill `fire_propagate`（组合 `due_compute` + `fsrs_retrievability` 读状态 + 纯计算顺延，stateless）；omodul cognitive 事务在主链后调用；服务层不感知。

**上线门槛（顺序不可跳）**：① `scripts/moat_eval` exp4 仿真：同等 30 天保留率下总复习量压缩 ≥10% 才允许接线，否则调 κ0/τ 回炉；② 真实数据 A/B（对照组无 FIRe）确认保留率不降后全量。

---

## 5. 七大机制增强

| 编号 | 机制 | 一句话 | 3O 归层 |
|------|------|--------|---------|
| M-A | 确定性求解内核 | sympy 精确求解供苏格拉底校验/出题/图示 | oprim `solve_*`+`verify_step`；obase 沙箱 |
| M-B | 交错练习调度 | 复习池刻意混合 KC，训练识别 | oskill `interleave_select`；服务层引擎 |
| M-C | 检索练习约束 | 回顾先遮答案主动回忆 | omodul 规则 + 前端 |
| M-D | 可视化数据生成 | 内核产出 2D/3D 图示数据，前端渲染 | oprim `kernel_to_*`；前端 Mafs/Three.js |
| M-E | LLM 图示 + 自检 | SVG 中间表示 + 自动评估 | oprim `generate_svg`/`evaluate_diagram` |
| M-F | 努力错觉对抗 | 展示"难但有效"的学习收益 | oprim `compute_effortful_gain`；前端 |
| M-G | 识别能力训练 | 区分掌握 vs 识别（见 §4.5） | oprim `recognition_update` |
| M-H | FIRe-lite 前置信用回写 | 综合题答对按 κ=κ0·P(L) 顺延前置 due，压缩复习量（见 §4.8） | oskill `fire_propagate`；omodul cognitive |

### M-A 确定性求解内核

**覆盖分级**（按 KC 能力）：完全覆盖（圆锥曲线、立体几何坐标向量法、导数运算/单调极值、数列、三角、古典概型、函数/不等式）；部分覆盖（压轴含参讨论、综合证明——校验数值步 + LLM 兜开放论证）；不覆盖（纯文字论证——苏格拉底降级纯对话，不硬撑）。

**接口**：
```python
def solve_conic(*, problem_spec: ConicSpec) -> SolveResult:
    """sympy 精确求解，在 obase.sympy_runtime 沙箱执行。
    Returns SolveResult(answer:str(LaTeX), steps:list[Step],
                        plot_data:dict|None, solvable:bool)"""

def verify_step(*, kc_id: str, claim: str, context: dict) -> StepCheck:
    """确定性校验学生某一步是否成立。Returns StepCheck(valid:bool, reason)"""
```
`socratic_loop` 调 `verify_step` 校验每一步——确定性兜对错，不靠 LLM 判断。

### M-B 交错练习调度

`interleave_select`（oskill 纯算法）：输入到期池 + 掌握度 + 时长预算；规则：相邻题 KC 不同、优先混合易混淆 KC 对（椭圆/双曲线、排列/组合，配置化）、难度梯度穿插已掌握与薄弱、总时长 ≤ 预算；输出交错题序。封装进 `daily_mission_workflow`，服务层 `InterleaveSchedulerEngine` 协调。

### M-C 检索练习约束

回顾必须主动回忆：默认隐藏答案/解析，学生先作答自评再揭示；自评映射 FSRS Rating；**看答案视为 Again（记忆重置），不算检索成功**，禁止"一键看答案标记完成"。

### M-D 可视化数据生成

`kernel_to_plot2d`/`kernel_to_three`（oprim）由求解结果产出图示数据，与解题**同源**。渲染在前端：2D 用 **Mafs**（React 原生）或 Desmos API，3D 用 **Three.js**（edulab 已验证），不用 Manim。**同源原则（MUST）**：图示数值与答案来自同一次 `solve_*` 调用。

### M-E LLM 图示 pipeline + 自检

无内核模板时走此分支：`generate_svg_diagram`（LLM 出 SVG）→ `evaluate_diagram`（校验元素齐全/比例/标注）→ 不合格重试≤2次 → 仍不合格降级纯文字。优先用内核图示数据（最可靠）。

### M-F 努力错觉对抗

`compute_effortful_gain` = struggle_score（用时/Hard/苏格拉底轮次）× retention_delta（FSRS 稳定性提升量）。前端呈现："这道题你做得很吃力，但正因为难，你的记忆稳定性提升了最多——这种费劲恰恰是学得最牢的信号。"

---

## 6. 3O 架构全景分层

### 6.1 3O 范式在本项目的应用

3O = oprim（元实现，原子操作）+ oskill（元技能，≥2 oprim 组合）+ omodul（元功能，业务事务，4 支柱按需）+ obase（基础设施，与 3O 平行）。服务层（Layer 4）是对外运行边界，不入主库。物理上 MVP 单 repo 分目录，验证后拆四个独立包。

### 6.2 oprim（单次原子操作）

已实现：`bkt_update` `classify_error` `predict_correct` `fsrs_review` `fsrs_retrievability`。
机制新增：`solve_conic` `solve_geometry3d` `solve_derivative` `solve_sequence` `solve_trig` `solve_probability` `solve_function` `verify_step` `kernel_to_plot2d` `kernel_to_three` `generate_svg_diagram` `evaluate_diagram` `compute_effortful_gain` `recognition_update`。
待做：`ocr_paper` `grade_question` `profiler_analyze` `socratic_turn`（均为单 LLM 调用）。

### 6.3 oskill（≥2 oprim 组合算法）

`cognitive_update`（已实现，需扩展双维度）= `fsrs_retrievability`+`bkt_update`+`classify_error`+`recognition_update`。
`solve_and_visualize` = `solve_*`+`kernel_to_*`+`evaluate_diagram`（edulab 核心）。
`socratic_loop` = `socratic_turn`(循环)+`verify_step`+情绪检测（agentic）。
`interleave_select` = 掌握度查询+`compute_effortful_gain`+混合排程（纯算法）。
`longitudinal_pattern` = 时间序列统计+单 LLM 解读。

### 6.4 omodul（业务事务，支柱按需）

| omodul | 支柱 |
|--------|------|
| `analyze_paper_workflow`（OCR+批改+profiler+认知更新+共同断点） | 全 4 支柱 |
| `socratic_session_workflow` | {trail, cost} |
| `generate_lesson_page`（求解+可视化+自检+组装） | {fingerprint, report} |
| `daily_mission_workflow`（交错+检索约束+努力错觉） | {decision_trail} |
| 纵向模式分析 | {decision_trail} |（现状：由 `oskill.longitudinal_pattern` + 服务层 `GET /v1/patterns` 实现；未单独建 omodul 包装）|
| 轻业务 `send_parent_report` / `export_archive` / `register_student` | 按需 |

### 6.5 obase（基础设施）

`ProviderRegistry`（Claude/Vision）、`CostTracker`、`sha256_hash`/`canonical_json`、`auth`(JWT)、`fs`/`http`/`secrets`、`oss`、**`sympy_runtime`**（求解沙箱：超时/内存限/进程隔离，所有 `solve_*` 共用）。

### 6.6 服务层引擎（Layer 4，不入主库）

FastAPI 路由、鉴权/多租户/未成年人合规校验、SSE 流式（苏格拉底）、Celery（试卷链/日报/纵向分析）、`InterleaveSchedulerEngine`、前端 PWA（Mafs/Three.js 渲染、检索交互、努力错觉看板）。

**关键边界**：图示数据在主库（oprim），渲染在前端（不入 3O）；user_id 等服务层概念不进 omodul；算 fingerprint/写 report/累计 cost 由 omodul 自管。

---

# 第三部分 · 工程契约

## 7. 完整数据模型（DDL）

> **以代码为准（审计 2026-07-03 收口）**：本节 DDL 为设计基线；随功能迭代，实际库已达
> **31 张表**（含 textbooks/knowledge_clusters/knowledge_units/evaluation_runs/streaks 等
> 后续新增）。权威表结构以 `services/models.py` + `alembic/versions/` 迁移链为准，本节仅示意。

```sql
-- ===== 用户与合规 =====
CREATE TYPE user_role AS ENUM ('student','parent');
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  phone VARCHAR(11) UNIQUE NOT NULL, role user_role NOT NULL,
  name VARCHAR(40), birth_date DATE,            -- 判定<14岁（合规）
  grade VARCHAR(10), province VARCHAR(10) DEFAULT '广东',
  invite_code VARCHAR(6) UNIQUE,
  created_at TIMESTAMPTZ DEFAULT now(), deleted_at TIMESTAMPTZ );
CREATE TABLE parent_student (
  parent_id UUID REFERENCES users(id), student_id UUID REFERENCES users(id),
  nickname VARCHAR(20), display_order INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now(), PRIMARY KEY (parent_id, student_id) );
CREATE TABLE guardian_consents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), student_id UUID REFERENCES users(id),
  guardian_phone VARCHAR(11) NOT NULL, consent_type VARCHAR(50) NOT NULL,
  consent_version VARCHAR(20) NOT NULL, consented_at TIMESTAMPTZ DEFAULT now(),
  ip_address VARCHAR(45) );

-- ===== 学习数据 =====
CREATE TYPE paper_status AS ENUM ('processing','done','failed');
CREATE TYPE error_type AS ENUM ('conceptual','transfer','careless','logic_break','dontknow');
CREATE TYPE storage_tier AS ENUM ('hot','warm','cold','archived');
CREATE TABLE exams (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), student_id UUID REFERENCES users(id),
  exam_name VARCHAR(100), exam_date DATE, subject VARCHAR(20) DEFAULT 'math',
  total_score INT, scores JSONB, created_at TIMESTAMPTZ DEFAULT now() );
CREATE TABLE papers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), exam_id UUID REFERENCES exams(id),
  student_id UUID REFERENCES users(id), subject VARCHAR(20) DEFAULT 'math', grade VARCHAR(10),
  image_urls JSONB, ocr_result JSONB, status paper_status DEFAULT 'processing',
  storage_tier storage_tier DEFAULT 'hot',
  created_at TIMESTAMPTZ DEFAULT now(), archived_at TIMESTAMPTZ );
CREATE TABLE wrong_questions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), paper_id UUID REFERENCES papers(id),
  student_id UUID REFERENCES users(id), subject VARCHAR(20) DEFAULT 'math',
  question_text TEXT, student_answer TEXT, correct_answer TEXT,
  knowledge_points JSONB, error_type error_type, profiler_analysis JSONB,
  fsrs_card_json JSONB, fsrs_due TIMESTAMPTZ, fsrs_state VARCHAR(20),
  created_at TIMESTAMPTZ DEFAULT now() );

-- ===== 认知状态（内核落库）=====
CREATE TABLE kc_mastery (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), student_id UUID REFERENCES users(id),
  knowledge_point VARCHAR(100) NOT NULL,
  p_mastery FLOAT, p_init FLOAT NOT NULL, p_transit FLOAT NOT NULL,
  p_guess FLOAT NOT NULL, p_slip FLOAT NOT NULL,
  p_recognition FLOAT, p_recognition_init FLOAT,         -- M-G 识别维度
  long_term_mastery FLOAT, last_interaction_at TIMESTAMPTZ,
  n_attempts INT DEFAULT 0, updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (student_id, knowledge_point) );
CREATE TABLE bkt_priors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subject VARCHAR(20), grade VARCHAR(10), knowledge_point VARCHAR(100), question_type VARCHAR(20),
  p_init FLOAT, p_transit FLOAT, p_guess FLOAT, p_slip FLOAT,
  calibrated_from_n INT DEFAULT 0, updated_at TIMESTAMPTZ DEFAULT now() );
CREATE TYPE interaction_source AS ENUM ('paper','quick','review','socratic');
CREATE TABLE interaction_events (    -- 只增不改，未来 DKT 训练数据
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), student_id UUID REFERENCES users(id),
  knowledge_point VARCHAR(100) NOT NULL, question_id UUID, source interaction_source NOT NULL,
  is_correct BOOLEAN NOT NULL, fsrs_rating SMALLINT, time_spent_seconds INT,
  days_since_last FLOAT, is_interleaved BOOLEAN DEFAULT FALSE,    -- M-B
  occurred_at TIMESTAMPTZ DEFAULT now() );
CREATE TABLE mastery_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), student_id UUID REFERENCES users(id),
  knowledge_point VARCHAR(100), long_term_mastery FLOAT, dominant_error_type VARCHAR(20),
  grade VARCHAR(10), snapshot_month DATE, created_at TIMESTAMPTZ DEFAULT now() );
CREATE TABLE learning_patterns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), student_id UUID REFERENCES users(id),
  pattern_type VARCHAR(50), description TEXT, confidence FLOAT, evidence JSONB,
  suggestion TEXT, detected_at TIMESTAMPTZ DEFAULT now(), user_marked_useful BOOLEAN );

-- ===== 机制增强 =====
CREATE TABLE solve_cache (           -- M-A
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), kc_id VARCHAR(100),
  problem_hash VARCHAR(64) UNIQUE, solve_result JSONB, solvable BOOLEAN,
  created_at TIMESTAMPTZ DEFAULT now() );
CREATE TABLE lesson_pages (          -- M-D/E
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), question_id UUID REFERENCES wrong_questions(id),
  fingerprint VARCHAR(64), plot_data JSONB, diagram_svg TEXT,
  self_check_passed BOOLEAN, report_path TEXT, created_at TIMESTAMPTZ DEFAULT now() );
CREATE TABLE effortful_gains (       -- M-F
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), student_id UUID, question_id UUID,
  struggle_score FLOAT, retention_delta FLOAT, effortful_gain FLOAT,
  occurred_at TIMESTAMPTZ DEFAULT now() );

-- ===== 苏格拉底与目标 =====
CREATE TYPE socratic_mode AS ENUM ('deep','mixed','sprint');
CREATE TYPE socratic_outcome AS ENUM ('success','partial','failed','abandoned');
CREATE TABLE socratic_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), student_id UUID REFERENCES users(id),
  question_id UUID REFERENCES wrong_questions(id), mode socratic_mode,
  messages JSONB, emotion_log JSONB, outcome socratic_outcome,
  used_escape_hatch BOOLEAN DEFAULT FALSE, duration_seconds INT,
  created_at TIMESTAMPTZ DEFAULT now() );
CREATE TYPE mission_type AS ENUM ('review','socratic','upload','knowledge_focus');
CREATE TABLE daily_missions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), student_id UUID REFERENCES users(id),
  date DATE, mission_type mission_type, content JSONB, estimated_minutes INT,
  interleaved BOOLEAN DEFAULT FALSE, requires_active_recall BOOLEAN DEFAULT FALSE,  -- M-B/C
  completed BOOLEAN DEFAULT FALSE, completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(), UNIQUE (student_id, date) );
CREATE TABLE streaks (
  student_id UUID PRIMARY KEY REFERENCES users(id), current_streak INT DEFAULT 0,
  longest_streak INT DEFAULT 0, last_completed_date DATE, escape_count INT DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT now() );

-- ===== 家长端 =====
CREATE TYPE alert_type AS ENUM ('emotion','score_drop','task_missing','time_drop','late_night');
CREATE TYPE alert_level AS ENUM ('notice','attention','important');
CREATE TABLE parent_alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), parent_id UUID REFERENCES users(id),
  student_id UUID REFERENCES users(id), alert_type alert_type, alert_level alert_level,
  content TEXT, sent_via JSONB, is_read BOOLEAN DEFAULT FALSE, created_at TIMESTAMPTZ DEFAULT now() );
CREATE TABLE daily_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), student_id UUID REFERENCES users(id),
  date DATE, report_text TEXT, sent_at TIMESTAMPTZ, delivery_status VARCHAR(20),
  UNIQUE (student_id, date) );
```

## 8. 完整 API 契约

全部前缀 `/v1`，除 auth 外需 `Authorization: Bearer <jwt>`。

> 本节为**核心契约**（节选）。**实际路由全表以代码为准**：`python scripts/dump_routes.py [--md]` 从 FastAPI 导出（现 66 条），避免手抄漂移（DRIFT D3）。

```
# 认证
POST /v1/auth/send-code        {phone} → {ok}
POST /v1/auth/register/student {phone,code,name,birth_date,grade,guardian_phone?,guardian_consent?} → {token,user}
POST /v1/auth/register/parent  {phone,code,name,invite_code} → {token,user}
POST /v1/auth/login            {phone,code} → {token,user}
GET  /v1/auth/me → {user}
  # 合规：<14岁必须带 guardian_phone+guardian_consent，否则 422，写 guardian_consents

# 试卷
POST /v1/papers/upload   multipart(images[],exam_name?,grade) → {paper_id,status:'processing'}
GET  /v1/papers/{id} → {paper, wrong_questions[]}
GET  /v1/papers ?student_id&from&to → {papers[]}
POST /v1/papers/quick    multipart(image,kc_hint?) → {question_id,socratic_session_id}

# 认知状态
POST /v1/interaction  {kc_id,is_correct,used_answer?,struggled?,effortless?,source,question_id?,is_interleaved?}
     → {p_mastery,long_term_mastery,effective_mastery,p_recognition,error_type?,rating,next_review_due,n_attempts}
GET  /v1/mastery/{student_id} → {knowledge_points[]}   # 按薄弱排序
GET  /v1/mastery/curve/{student_id}/{kc_id} → [{month,long_term_mastery,dominant_error_type}]
GET  /v1/review-queue/{student_id} → {due_today[]}      # 经 interleave_select 排布
GET  /v1/patterns/{student_id} → {patterns[]}
GET  /v1/kc · GET /v1/kc/{kc_id} → KC 字典

# 求解与可视化（M-A/D/E）
POST /v1/solve {kc_id,problem_spec} → {answer,steps,plot_data,solvable}
GET  /v1/lesson/{question_id} → {plot_data,diagram_svg?,self_check_passed,report}

# 苏格拉底
POST /v1/socratic/start {question_id} → {session_id,mode,first_question}
POST /v1/socratic/{session_id}/message {text} → SSE 流式 {delta}...{done,emotion?,outcome?}
POST /v1/socratic/{session_id}/escape → {answer_outline}    # 逃生出口
POST /v1/socratic/{session_id}/end → {outcome,mastery_updated}

# 今日目标 / 努力收益
GET  /v1/missions/today/{student_id} → {mission,streak}
POST /v1/missions/{mission_id}/complete → {streak,next_preview}
GET  /v1/effortful-gains/{student_id} → {top_gains[]}       # M-F 看板

# 家长端
GET  /v1/parent/children → {children[]}
GET  /v1/parent/overview/{student_id} → {growth_summary,streak,emotion}  # 不含绝对分数
GET  /v1/parent/alerts/{student_id} → {alerts[]}
GET  /v1/parent/report/{student_id}?date → {report_text}
GET  /v1/parent/export/{student_id} → 触发档案导出（合规）
POST /v1/parent/delete-request/{student_id} → 触发删除（合规）
```

## 9. 技术栈与全局约束

| 层 | 选型 | 约束 |
|----|------|------|
| 后端 | Python 3.12 + FastAPI(async) | 类型注解必填 |
| ORM | SQLAlchemy 2.0 async + Alembic | schema 只走 migration |
| DB | PostgreSQL 16 | UUID 主键 |
| 缓存/队列 | Redis 7 | 会话/Celery/Streak |
| 异步 | Celery | OCR/纵向分析/日报 |
| 存储 | S3 兼容（MinIO→OSS） | 试卷原图冷热分层 |
| LLM | Anthropic Claude（经 obase.ProviderRegistry） | key 走环境变量 |
| 间隔重复 | py-fsrs | 不自研 |
| FSRS 权重拟合 | scipy.optimize（导数无关） | §4.3.1；**不引入 torch**（前向不可微，scipy 已在栈内足够） |
| 求解 | sympy/numpy（obase.sympy_runtime 沙箱） | 超时/内存限 |
| 前端 | React+TS+Vite+Tailwind+Mafs+Three.js+KaTeX | PWA；KaTeX 渲染 rich_content/讲解中的 LaTeX 公式 |
| 测试 | pytest + pytest-asyncio | service≥80% 总≥70% |

全局：配置走 pydantic-settings；数值在 API 边界 round；未成年人数据操作必过合规校验；错误统一 `{detail}`。存储分层：结构化数据（小而值钱）永久在线，原图（大）分层降冷，分析依赖结构化数据故原图归档不影响纵向分析。

---

# 第四部分 · 治理

## 10. 未成年人合规（强制专章）

永久保存大量未成年人学习数据是最敏感的合规高压线。本章为强制要求。

**法律依据**：《个人信息保护法》（不满 14 周岁个人信息属敏感信息）、《未成年人保护法》网络保护专章、《未成年人网络保护条例》。

**强制要求**：

| 要求 | 实现 |
|------|------|
| 监护人同意 | <14 岁注册需监护人手机验证 + 单独同意，存 `guardian_consents` |
| 单独处理规则 | 公示《儿童个人信息处理规则》 |
| 最小必要 | 只收学习相关数据 |
| 数据加密 | 传输 TLS + OSS 服务端加密 + DB 敏感字段加密 |
| 永久保存额外义务 | 告知保存期限/目的；提供随时删除/导出入口 |
| 数据可携带 | `/parent/export` 导出全部档案（JSON+PDF） |
| 删除权 | `/parent/delete-request` 软删 + 异步硬删（含 OSS 归档层） |
| 数据本地化 | 全部境内节点 |
| 禁止 | 不得用于广告或对外训练 |

"永久"是**为用户保存**，不是平台无限占有；用户随时可删除/导出/注销。

## 11. 商业模式

用户生命周期 3-6 年（全年级），LTV 远高于纯高三方案，靠续费而非单价。

| 套餐 | 价格 | 功能 |
|------|------|------|
| 免费版 | 0 | 每月 5 次上传，基础分析，档案近 1 学期回看 |
| 成长版 | 29/月 或 268/年 | 无限上传，苏格拉底，永久档案，纵向分析，遗忘曲线 |
| 家庭版 | 49/月 或 458/年 | 成长版 + 家长端全功能 + 多孩子 |
| 高三冲刺包 | 199/3 月 | 叠加冲刺模式 + 志愿参考 |

增长：老师推荐（错题管理工具，无合规争议）、成长报告分享（社交货币）、家长日报转发、跨学段口碑延续。

## 12. 开发路线图与任务总表

**核心闭环（最先打通）**：
```
基建 → 持久化(接已有内核) → 试卷入口 → 认知层
= 上传一张广东数学卷 → OCR批改 → 驱动 BKT/FSRS → 看见薄弱点排序
打通后即可真实用户验证（冷启动钩子 = 共同断点 + 苏格拉底顿悟）
```

**Epic 总表**（详见 TASKS.md）：

| Epic | 内容 | 阶段 |
|------|------|------|
| 0 基建 | 骨架/compose/Alembic/CI | MVP |
| 1 持久化 | models/PgStore/cognitive_service/KC seed | MVP |
| 2 用户合规 | 注册登录/JWT/<14岁校验/多孩子 | MVP |
| 3 试卷入口 | OSS/OCR/批改/接内核/共同断点/Celery | MVP |
| 4 认知层 | 掌握度总览/成长曲线/纵向分析/今日目标 | MVP |
| 5 苏格拉底 | 流式/不泄答案红线/情绪/逃生 | MVP |
| 6 家长端 | 成长摘要/微信日报/5类预警 | Phase2 |
| 7 前端 | 学生闭环/家长端 | Phase2 |
| 8 部署可观测 | compose/AUC监控 | Phase2 |
| 9 合规收口 | 导出/删除/加密 | Phase2 |
| 10 确定性内核(M-A) | 沙箱/solve_*/verify_step/缓存 | Phase2 |
| 11 可视化(M-D/E) | kernel_to_*/Mafs/Three.js/SVG自检/lesson_page | Phase2 |
| 12 学习科学(M-B/C/F/G) | recognition/interleave/检索约束/努力错觉 | Phase2 |

依赖：0→1→3→4 核心闭环优先；Epic 10 是 11/12 部分前置。

## 13. 非功能需求 / 质量门 / 风险

**性能**：单图 OCR ≤60s；单题首次苏格拉底——即时占位追问 ≤5s + 精准追问异步 ≤30s；后续对话 ≤3s（流式）；单次分析 ≤1min；档案可用性 ≥99.9%。

**质量门（CI 必卡）**：
- pytest 全绿，覆盖率 service≥80% 总≥70%；ruff+mypy 通过。
- **苏格拉底不泄露答案红线**（诱导测试）。
- **合规红线**：<14 岁无同意注册必失败；删除后不可查询。
- **算法回归**：AUC≥0.70 不退化；掌握度封顶≤0.97；连续答对单调不降。
- **确定性优先红线**：有 solve_* 覆盖的题型，数值结论必来自内核（mock LLM 给错值，最终仍以内核为准）。
- **同源自检**：lesson_page 图示值 == 答案 == 末步值，三处一致否则不交付。
- **交错有效性**：相邻题 KC 不同；**检索约束**：未作答不可见答案，看答案=Again；**沙箱安全**：病态 sympy 输入超时被杀；**苏格拉底步校验**：错误中间步由 verify_step 拦截。

**风险**：

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| 慢热产品冷启动流失 | 高 | 高 | 第一周靠即时顿悟留人 |
| 未成年人数据合规/泄露 | 中 | 极高 | 第10章强制框架+法务审查+安全审计 |
| 数据沉睡，洞察转化不足 | 中 | 高 | M6纵向分析为核心；洞察有用率作硬指标 |
| OCR 手写识别率低 | 高 | 高 | Claude Vision + 手动纠错；MVP 接受不完美 |
| sympy 覆盖不全 | 高 | 中 | 分级覆盖；不覆盖时苏格拉底降级纯对话 |
| 内核解法与教材不一致 | 中 | 中 | 答案保证对，注明解法，提供方法选择 |
| 交错增加初期挫败 | 中 | 中 | 难度梯度穿插已掌握题；交错强度可配 |
| 沙箱被病态输入拖垮 | 中 | 高 | obase.sympy_runtime 超时+内存限+进程隔离 |
| 新高考3+1+2/各省差异 | 高 | 中 | MVP 收窄单地区单科，验证后复制 |
| 失去高三紧迫感付费下降 | 高 | 高 | 双层钩子+年付+冲刺包补紧迫感 |

---

## 附录 A · KC 知识点字典

**两套粒度并存（勿混淆）**：① **KC**（粗粒度，BKT 先验/掌握度建模单位）——广东高中数学 `data/guangdong_math_kc.py`，含父节点、前置链、题型分布、高考权重、BKT 先验四参数；② **KU**（细粒度，知识单元，讲解/练习/地图单位）——已入库**数学 ~2395、物理 ~1551**（DB `knowledge_units`，含 rich_content）。掌握度建模走 KC；学习内容组织走 KU；二者通过 `knowledge_point` 关联。详见记忆 `project_knowledge_system_refactor`。

## 附录 B · 术语表

| 术语 | 定义 |
|------|------|
| 永久学习档案 | 学生跨学段全部学习数据的连续保存，归学生所有 |
| 纵向认知分析 | 跨时间追踪同一 KC 掌握演变与错误类型转化 |
| 共同断点 | 多道错题背后的同一根本认知原因（冷启动钩子） |
| KT/BKT/DKT | 知识追踪/贝叶斯/深度知识追踪 |
| FSRS | Free Spaced Repetition Scheduler，间隔重复算法 |
| forgetting-aware | 掌握度估计含遗忘衰减，P_eff = P × R |
| 识别能力(recognition) | 混合情境下认出该用哪个 KC 的能力（对抗惰性知识） |
| 交错/检索练习 | interleaving / retrieval practice，学习科学机制 |
| 确定性内核 | sympy/numpy 精确求解，兜住 LLM 算错 |
| 3O 范式 | oprim+oskill+omodul+obase 的可复用单位设计范式 |

## 附录 C · 设计演进史

| 版本 | 关键决策 |
|------|---------|
| PRD v1.0/1.1 | 高考作战系统（已废弃——合规/LTV/预估分三大风险） |
| PRD v1.2 | 战略重定位为全年级自我助学 + 永久档案，化解三风险 |
| PRD v1.3 | KT/FSRS 算法内核 + forgetting-aware 统一 |
| 代码内核 | BKT/FSRS/KC 字典实现并验证（合成数据 AUC≥0.65；0.77 为目标） |
| SPEC v1 | 工程实施（DDL/API/任务） |
| SPEC v2 | 3O 归层 + 七大机制增强 |
| **Master v1.0** | **整合全部为唯一 SSOT（本文档）** |

---

## 附录 · 先进教育理念增强契约（2026-07-03 起，逐条落地）

对标 ALEKS/Khanmigo/Duolingo 与国外 AIED，补齐"深度/透明/动机/社群"短板。守住已领先的
间隔/检索/交错三大记忆科学地基与苏格拉底确定性引导。各条为新增契约，红线不变。

- **01 掌握门控 + 知识空间选题（KST/ALEKS）**：`oprim.prereq_graph.fringe_status` 确定性分类
  KU 为 mastered/learning/**learnable(outer fringe：前置全掌握、自身未开始)**/**locked(前置未齐)**；
  门控阈值 0.6（对齐 daily_plan P4）。`/v1/knowledge-points` 附 `fringe` 字段供前端锁态展示。
  红线：确定性、纯函数、不改 BKT/FSRS 契约。
- **02 SDT 留存层**：胜任=`/v1/achievements`（已有，多档徽章）；**归属**=`/v1/league/{sid}`
  匿名同年级联赛（`oprim.compute_peer_percentile` 复用掌握 KU 数，返回百分位/段位/队列人数，
  **无任何他人身份/分数**，合规红线：未成年不暴露真实排名/PII，样本<2 不排名）；
  自主=每日目标自选强度（待 migration + 前端）。激励绑检索/努力行为，防裸积分挤出内在动机。
- **03 开放学习者模型（OLM）**：`/v1/learner-model/{sid}/{kc_id}` 透明返回长期 P(L)、此刻
  可提取性 R、有效掌握(P(L)×R)、错因画像(粗心 vs 没学会，`bkt_error_weights` 归一)、识别维度、
  下次复习。促元认知（"镜子"叙事）。"协商挑战"（我觉得会了→做题验证）复用 practice/submit。
  红线：读现有 KCState/内核，不改契约。

---

**Mneme 主设计文档结束。本文档为唯一权威，其余历史文档仅作演进参考。**
