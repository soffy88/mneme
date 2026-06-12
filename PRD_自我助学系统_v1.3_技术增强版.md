# 产品需求文档（PRD）v1.3 · 技术增强版
# 自我助学系统 —— 算法内核：知识追踪 + FSRS

**文档版本**：v1.3（算法内核技术增强）
**上一版本**：v1.2（自我助学系统战略重定位版）
**更新日期**：2026年6月
**关系说明**：本版**承接 v1.2 的全部产品定位、用户、功能模块与商业模式**，仅深化"掌握度建模"与"遗忘曲线"两个技术内核。v1.2 中未被本文档覆盖的部分（苏格拉底引擎、试卷录入、家长端、合规专章、商业模式等）保持不变。

---

## v1.3 解决的核心问题

实证调研发现，v1.2 有两个"拍脑袋"的算法设计，业界已有成熟得多的方案：

| v1.2 的问题设计 | 行业成熟方案 | 升级收益 |
|----------------|-------------|---------|
| 掌握度 = 0.7×旧值 + 0.3×新值（无依据的加权） | **知识追踪 KT**（BKT→DKT） | 有概率意义、可解释、可被预测准确度（AUC）验证 |
| 遗忘曲线用 SM-2（1987年算法） | **FSRS**（2022，Anki默认） | 同等记忆留存下复习量减少 20-30%，有现成开源库 |
| 掌握度与遗忘是两套割裂逻辑 | **forgetting-aware 统一模型** | 掌握度估计本身考虑遗忘，单一一致的认知状态 |

三大升级共同构成产品的**算法护城河**——同行的苏格拉底对话已商品化，但"基于长期档案 + KT/FSRS 的个性化精度"是别人短期内做不出来的。

---

## 目录

1. 算法内核总览
2. 知识追踪引擎（BKT 详解 + DKT 演进）
3. FSRS 间隔重复引擎
4. 统一的 forgetting-aware 认知模型
5. 算法与 LLM 的分工边界
6. 数据模型变更
7. 成功指标更新（含 AUC）
8. 开发路线图调整
9. 风险评估
10. 附录：核心算法伪代码与接口

---

## 1. 算法内核总览

### 1.1 三层认知状态架构

```
┌─────────────────────────────────────────────┐
│  应用层（产品功能，承接 v1.2）                 │
│  今日目标 · 成长曲线 · 苏格拉底 · 家长端       │
└───────────────────┬─────────────────────────┘
                    │ 读取认知状态
┌───────────────────▼─────────────────────────┐
│  认知状态层（v1.3 新内核）                     │
│                                              │
│  ┌──────────────┐      ┌──────────────────┐  │
│  │ 知识追踪 KT  │◄────►│  FSRS 调度器     │  │
│  │ 「掌握了吗」 │      │  「何时该复习」  │  │
│  │              │      │                  │  │
│  │ P(掌握)      │      │  D / S / R 三变量│  │
│  │ slip/guess   │      │  下次复习日      │  │
│  └──────────────┘      └──────────────────┘  │
│           └──── forgetting-aware 统一 ────┘   │
└───────────────────┬─────────────────────────┘
                    │ 消费答题事件
┌───────────────────▼─────────────────────────┐
│  事件层：每一次答题 / 对话 / 回顾              │
│  (知识点, 对错, 用时, 距上次间隔, 时间戳)      │
└─────────────────────────────────────────────┘
```

### 1.2 两个引擎的分工

- **KT 回答"掌握了吗"**：估计学生对每个知识点的掌握概率，驱动战局判断、薄弱点识别、今日目标。
- **FSRS 回答"何时该复习"**：为每道错题/每个知识点调度最优复习时间，驱动遗忘曲线回顾。
- **二者协同**：KT 的掌握度作为 FSRS 的难度先验；FSRS 的"距上次间隔"作为 KT 的遗忘输入。详见第4章。

---

## 2. 知识追踪引擎（KT）

### 2.1 为什么选 BKT 作为 MVP 起点

不直接上深度模型（DKT），而是从 BKT（贝叶斯知识追踪）起步，原因：

- **可解释**：四个参数都有明确的教育学含义，能向学生/家长解释"为什么判断你掌握了"。
- **冷启动友好**：单个学生、少量数据即可工作，不需要海量训练数据（DKT 需要）。
- **参数即产品功能**：BKT 的 slip 参数天然对应"粗心错误"，guess 参数对应"蒙对"，省去让 LLM 猜测错误类型。
- **轻量**：纯概率计算，无需 GPU，FastAPI 进程内即可运行。

### 2.2 BKT 的四个参数

对每个知识点（Knowledge Component, KC），维护四个参数：

| 参数 | 符号 | 含义 | 产品对应 |
|------|------|------|---------|
| 初始掌握概率 | P(L₀) | 首次接触前已掌握的概率 | 不同年级/知识点设不同先验 |
| 学习转移概率 | P(T) | 一次有效练习后，从"未掌握"变为"掌握"的概率 | 反映该知识点的学习难度 |
| 猜测概率 | P(G) | 未掌握却答对（蒙对） | **对应"蒙对"，选择题应设较高 P(G)** |
| 失误概率 | P(S) | 已掌握却答错（粗心） | **对应"粗心错误"，直接量化** |

### 2.3 核心更新公式（贝叶斯）

每次观测到学生在某知识点上答对/答错后，分两步更新掌握概率：

**第一步：根据观测结果做贝叶斯后验更新**

```
若答对 (correct)：
                    P(Lₜ)·(1 - P(S))
  P(Lₜ | correct) = ───────────────────────────────────────
                    P(Lₜ)·(1 - P(S)) + (1 - P(Lₜ))·P(G)

若答错 (wrong)：
                    P(Lₜ)·P(S)
  P(Lₜ | wrong) = ───────────────────────────────────────
                  P(Lₜ)·P(S) + (1 - P(Lₜ))·(1 - P(G))
```

**第二步：应用学习（这次练习本身带来的提升）**

```
  P(Lₜ₊₁) = P(Lₜ | obs) + (1 - P(Lₜ | obs))·P(T)
```

P(Lₜ₊₁) 就是更新后的掌握度，取代 v1.2 的 `0.7旧+0.3新` 公式。

### 2.4 BKT 如何替代"错误类型分类"

v1.2 让 Profiler Agent（LLM）判断错误是"概念/迁移/粗心/思维断裂"。LLM 判断"粗心"其实不可靠。BKT 提供了**概率化的客观判据**：

```
当学生答错某题时：
  贡献于"粗心"的后验权重 ∝ P(Lₜ)·P(S)
    （高掌握度 + 失误 → 大概率是粗心）
  贡献于"不会"的后验权重 ∝ (1-P(Lₜ))·(1-P(G))
    （低掌握度 + 没蒙对 → 大概率是真不会）

→ 若 P(Lₜ) 高但答错，系统判定为"粗心"，不浪费苏格拉底资源在已掌握的知识点上
→ 若 P(Lₜ) 低且答错，判定为"概念/迁移问题"，触发苏格拉底深度引导
```

**分工**：BKT 负责"粗心 vs 不会"的客观区分（基于历史数据）；LLM（Profiler Agent）负责"不会"细分为概念/迁移/思维断裂（需要语义理解）。各用所长。

### 2.5 参数初始化与学习

- **冷启动**：按"科目 × 年级 × 知识点 × 题型"设置先验参数表（如选择题 P(G)=0.25，填空题 P(G)=0.05）。
- **个性化**：随着该学生数据积累，用 EM 算法或在线梯度对其个人参数微调（可选，Phase 2）。
- **群体校准**：积累多学生数据后，对每个知识点拟合更准的群体级参数，再作为新用户先验。

### 2.6 DKT 演进路径（Phase 3，数据充足后）

当单学生交互序列足够长、平台用户量足够大时，引入 DKT（深度知识追踪）：

- 用 LSTM/Transformer 建模答题序列，**捕捉 BKT 做不到的跨知识点迁移**（如"掌握了二次函数有助于解析几何"）。
- 这直接支撑 v1.2 的**跨学段衔接分析**（初中方程弱 → 预测高中函数弱）。
- 衡量标准：用 AUC 对比 DKT 与 BKT 的下一题正确率预测精度，DKT 显著更优（行业基准 AUC≈0.79 vs BKT≈0.61）再切换。
- **保留 BKT 作为可解释层**：即使上了 DKT，向用户解释时仍用 BKT 风格的"掌握概率"，避免黑盒。

---

## 3. FSRS 间隔重复引擎

### 3.1 替换 SM-2 的理由

v1.2 附录用的 SM-2 是 1987 年算法，主要缺陷：对所有人用同一套固定公式、卡片一旦多次答错就陷入"低间隔地狱"。FSRS（2022，Anki 自 2023.10 起默认）基于真实大规模复习数据训练，同等记忆留存下复习量减少约 20-30%，且能适应个人记忆模式。

### 3.2 FSRS 的三变量记忆模型

每道题（或每个知识点的记忆项）维护三个值，每次复习后更新：

| 变量 | 符号 | 含义 |
|------|------|------|
| 难度 | D（1~10） | 这道题对该学生有多难，由评分校准 |
| 稳定性 | S（天） | 回忆概率从100%衰减到目标留存率（默认90%）所需天数 |
| 可提取性 | R（0~1） | 当前这一刻能回忆起的概率，R = f(S, 距上次复习天数) |

调度逻辑：当 R 衰减到目标留存率（如 0.9）时，安排复习。答对则 S 增长（间隔拉长），答错（lapse）则 S 重置、D 上升。

### 3.3 评分映射（关键产品设计）

FSRS 需要每次复习的评分（Again/Hard/Good/Easy）。我们把学生的回顾表现映射为这四档：

| 学生表现 | FSRS Rating | 说明 |
|---------|-------------|------|
| 没做出来 / 看了答案 | Again | 触发记忆重置 |
| 做出来了但很吃力/超时 | Hard | |
| 正常做对 | Good | 默认档 |
| 一眼秒杀 | Easy | 间隔大幅拉长，减少无用复习 |

苏格拉底对话的结果同样映射：自主推导成功→Good/Easy；需大量提示→Hard；未能推导→Again。

### 3.4 工程接入：直接用 py-fsrs

不自己实现，用官方开源库 `py-fsrs`（PyPI 已有，活跃维护）：

```python
# pip install fsrs
from fsrs import Scheduler, Card, Rating, ReviewLog
from datetime import datetime, timezone

scheduler = Scheduler()  # 可传入个性化参数

# 新错题入库时创建 Card
card = Card()

# 学生回顾后，根据表现映射 Rating
rating = Rating.Good  # 由 3.3 的映射决定
card, review_log = scheduler.review_card(card, rating)

# card.due 即为下次复习时间，存入数据库
next_review = card.due
```

- Card 的状态（D/S/R、due、last_review）序列化存入 `wrong_questions` 表。
- 每日凌晨任务扫描 `due <= today` 的卡片，纳入"今日目标"的回顾池。
- 高考前 15 天逻辑：临近考试时把目标留存率从 0.9 上调（更频繁复习关键知识点），FSRS 支持调参实现。

### 3.5 FSRS 个性化（Phase 2）

FSRS 的 17 个参数可基于该学生历史复习记录用 `Optimizer` 重新拟合，进一步贴合个人记忆模式。MVP 用默认参数即可（官方默认已基于 7 亿+ 复习数据训练，开箱够用）。

---

## 4. 统一的 forgetting-aware 认知模型

### 4.1 问题：KT 和 FSRS 各算各的会矛盾

如果 KT 说"掌握度 0.9"，但 FSRS 说"这道题该复习了（R 已衰减到 0.5）"，产品该信谁？必须统一。

### 4.2 协同设计

让两个引擎共享"遗忘"这一事实，互为输入：

```
事件：学生在 KC_i 上答题/回顾
  │
  ├─► FSRS：更新该记忆项的 D/S/R，算出下次 due
  │
  └─► forgetting-aware BKT：
        在做贝叶斯更新前，先按"距上次接触的间隔"对先验掌握度做遗忘衰减：
        
        P(Lₜ)_effective = P(Lₜ) · R_fsrs
        
        （用 FSRS 的可提取性 R 作为遗忘因子，
          掌握度不再是"学会就永远是高值"，而是会随时间衰减）
        
        然后再用 2.3 的公式做观测更新
```

这样：
- **掌握度 = 长期是否学会（BKT） × 此刻是否记得（FSRS 的 R）**，与人的真实认知一致。
- 成长曲线展示"长期掌握度"（去除短期遗忘波动）；今日目标用"effective 掌握度"（含遗忘）决定该复习什么。
- 学术依据：这正是 forgetting-aware KT（DKT+Forget / HawkesKT）的核心思想——把"距上次交互时间"纳入知识状态建模。

### 4.3 对外呈现（避免数字打架）

- 给学生看：一个"掌握度"曲线（长期），+ "需要复习"标记（短期遗忘），不暴露两套数字。
- 给家长看：成长摘要用长期掌握度（稳定、向上），不展示短期波动以免误读。

---

## 5. 算法与 LLM 的分工边界

实证结论：苏格拉底对话已商品化。因此**把贵的、慢的、难差异化的交给基础模型；把便宜的、快的、可积累的交给算法内核**。

| 任务 | 由谁做 | 理由 |
|------|--------|------|
| 掌握度估计 | KT（算法） | 客观、可解释、可积累，不需要 LLM |
| 粗心 vs 不会 | KT（slip 概率） | 概率判据比 LLM 猜测可靠 |
| 复习调度 | FSRS（算法） | 成熟算法，无需 LLM |
| 错误类型细分（概念/迁移/思维断裂） | LLM | 需要语义理解 |
| 共同断点分析（冷启动钩子） | LLM | 需要跨题语义归纳 |
| 苏格拉底追问 | LLM（可用基础模型 Learning Mode） | 已商品化，不自研 |
| 个人学习模式识别 | LLM + KT 数据 | LLM 解读 KT 产出的时间序列 |

**成本收益**：把掌握度和调度从 LLM 调用中剥离，大幅降低 token 消耗（这些原本若靠 LLM 每次重算非常贵），也提升响应速度（算法是毫秒级，LLM 是秒级）。

---

## 6. 数据模型变更

在 v1.2 基础上修改/新增：

```sql
-- 知识点掌握状态（替代原 student_knowledge 的 mastery 字段逻辑）
kc_mastery (
  id UUID PRIMARY KEY,
  student_id UUID,
  knowledge_point VARCHAR(100),
  -- BKT 状态
  p_mastery FLOAT DEFAULT NULL,     -- 当前掌握概率 P(L)，NULL表示用先验
  p_init FLOAT,                     -- P(L0) 先验
  p_transit FLOAT,                  -- P(T)
  p_guess FLOAT,                    -- P(G)
  p_slip FLOAT,                     -- P(S)
  -- forgetting-aware
  last_interaction_at TIMESTAMP,    -- 上次接触时间（算遗忘用）
  long_term_mastery FLOAT,          -- 去遗忘的长期掌握度（展示用）
  updated_at TIMESTAMP
)

-- BKT 参数表（按 科目×年级×知识点×题型 的群体先验）
bkt_priors (
  id UUID PRIMARY KEY,
  subject VARCHAR(20),
  grade VARCHAR(10),
  knowledge_point VARCHAR(100),
  question_type VARCHAR(20),        -- choice/fill/solve
  p_init FLOAT, p_transit FLOAT, p_guess FLOAT, p_slip FLOAT,
  calibrated_from_n INTEGER,        -- 基于多少样本校准
  updated_at TIMESTAMP
)

-- 错题表新增 FSRS 字段（扩展 v1.2 的 wrong_questions）
ALTER wrong_questions ADD:
  fsrs_difficulty FLOAT,            -- D
  fsrs_stability FLOAT,             -- S
  fsrs_due DATE,                    -- 下次复习日
  fsrs_last_review TIMESTAMP,
  fsrs_state VARCHAR(20),           -- new/learning/review/relearning
  fsrs_card_json JSONB              -- py-fsrs Card 序列化

-- 答题/复习事件流（KT 和 FSRS 的共同输入，也是 DKT 训练数据）
interaction_events (
  id UUID PRIMARY KEY,
  student_id UUID,
  knowledge_point VARCHAR(100),
  question_id UUID,                 -- 可空（来自试卷或回顾）
  source ENUM('paper','quick','review','socratic'),
  is_correct BOOLEAN,
  fsrs_rating SMALLINT,             -- 1-4 (Again/Hard/Good/Easy)
  time_spent_seconds INTEGER,
  days_since_last_interaction FLOAT,
  occurred_at TIMESTAMP
)
```

> `mastery_snapshots`（v1.2 的月度快照表）保留，按月把 `long_term_mastery` 写入，支撑成长曲线。

---

## 7. 成功指标更新（含 AUC）

v1.2 的指标保留，新增**算法效果的客观验证指标**：

| 指标 | 目标值 | 衡量方式 |
|------|-------|---------|
| KT 下一题正确率预测 AUC | MVP(BKT) ≥ 0.65；DKT阶段 ≥ 0.75 | 预测学生下一题对错 vs 实际 |
| FSRS 回顾留存率 | ≥ 90%（达到目标 retention） | 到期回顾的实际答对率 |
| 复习量节省 | 比 SM-2 基线减少 ≥ 20% | A/B 对比同等留存下的复习次数 |
| 掌握度-成绩相关性 | 相关系数 ≥ 0.7 | KT 掌握度 vs 实际考试得分率 |
| 粗心判定准确率 | ≥ 75% | BKT 判"粗心" vs 学生事后确认 |

> **关键**：AUC 让"我们的算法到底准不准"第一次变得**可测量、可对外证明**。这是面对家长质疑（"凭什么说我孩子掌握了？"）时的硬证据，也是融资/合作时的技术壁垒证明。

---

## 8. 开发路线图调整

在 v1.2 路线图基础上插入算法内核工作：

### Phase 1（MVP）调整
| 周次 | 原 v1.2 | v1.3 增补 |
|------|---------|----------|
| 5-6 | 单次认知分析 + 共同断点 | **+ BKT 引擎 + 群体先验参数表** |
| 7-8 | 苏格拉底引擎 | **+ BKT 驱动"粗心 vs 不会"判定** |
| 9 | 今日目标 + 画像 | **+ 掌握度改由 BKT 输出** |

### Phase 2 调整
| 周次 | 原 v1.2 | v1.3 增补 |
|------|---------|----------|
| 17-18 | 遗忘曲线回顾 | **改为 FSRS（py-fsrs 接入）** |
| 14-16 | 纵向认知分析 | **+ forgetting-aware 统一模型** |
| 21-22 | 执行力支持 | **+ FSRS 个性化参数拟合** |

### Phase 3 新增
| 周次 | 内容 |
|------|------|
| 新增 | DKT 模型训练与 A/B（数据量达标后），AUC 对比 BKT 决定是否切换 |
| 新增 | BKT 个人参数 EM 微调 + 群体参数定期再校准 |

---

## 9. 风险评估（算法相关）

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| BKT 先验参数初期不准 | 高 | 中 | MVP 接受不完美；随数据用 EM 校准；先验来自公开教育数据集（如 ASSISTments）打底 |
| 知识点（KC）标注粒度不一致 | 高 | 高 | KC 体系是 KT 的地基，必须先做好；MVP 收窄到单科，人工+LLM 辅助标注，建立 KC 字典 |
| 一题多知识点的归因 | 中 | 中 | 用多 KC 标注 + 责任分配（错题按 KC 权重分摊 evidence） |
| FSRS 评分映射不准（学生表现→Rating） | 中 | 中 | 映射规则先定保守版；用回顾留存率反推校准映射 |
| 掌握度对外解释不当引发误解 | 中 | 中 | 只呈现长期掌握度曲线，不暴露概率细节；措辞"目前掌握较好"而非"92%" |
| DKT 黑盒不可解释 | 中 | 中 | 保留 BKT 作为解释层；DKT 仅用于内部预测，不直接对用户解释 |

---

## 10. 附录：核心算法伪代码与接口

### A. BKT 更新（forgetting-aware 版）

```python
def update_mastery(kc_state, is_correct, days_since_last):
    P_L = kc_state.p_mastery or kc_state.p_init
    P_G, P_S, P_T = kc_state.p_guess, kc_state.p_slip, kc_state.p_transit

    # 1) forgetting-aware: 用 FSRS 的可提取性 R 衰减先验
    R = fsrs_retrievability(kc_state, days_since_last)  # 0~1
    P_L_eff = P_L * R

    # 2) 贝叶斯观测更新
    if is_correct:
        num = P_L_eff * (1 - P_S)
        den = P_L_eff * (1 - P_S) + (1 - P_L_eff) * P_G
    else:
        num = P_L_eff * P_S
        den = P_L_eff * P_S + (1 - P_L_eff) * (1 - P_G)
    P_L_obs = num / den if den > 0 else P_L_eff

    # 3) 应用学习
    P_L_new = P_L_obs + (1 - P_L_obs) * P_T

    kc_state.p_mastery = P_L_new
    kc_state.long_term_mastery = blend_long_term(kc_state, P_L_new)  # 平滑去遗忘
    kc_state.last_interaction_at = now()
    return kc_state


def classify_error(kc_state):
    """答错时区分粗心 vs 不会"""
    P_L = kc_state.p_mastery or kc_state.p_init
    careless_weight = P_L * kc_state.p_slip
    dontknow_weight = (1 - P_L) * (1 - kc_state.p_guess)
    return "careless" if careless_weight > dontknow_weight else "dontknow"
```

### B. 认知状态服务接口（FastAPI）

```
POST /v1/interaction        # 上报一次答题/回顾事件，触发 KT+FSRS 更新
  body: {student_id, kc, is_correct, time_spent, source, question_id?}
  resp: {p_mastery, long_term_mastery, error_type?, next_review_due}

GET  /v1/mastery/{student_id}        # 当前各 KC 掌握度（含长期/effective）
GET  /v1/review-queue/{student_id}   # 今日到期复习池（FSRS due <= today）
GET  /v1/mastery-curve/{student_id}/{kc}  # 某知识点掌握度时间序列（成长曲线）
```

### C. 知识点（KC）字典是地基

KT 和 FSRS 都依赖统一的知识点编码。MVP 必须先建立：

```
KC 字典（单科起步，如某省初中数学）
  KC_id | 名称 | 父节点 | 年级 | 前置KC列表 | 题型分布 | 高考/中考权重
  
  前置KC列表 → 支撑跨学段衔接分析与 DKT 的迁移建模
```

**这是整个算法内核的真正起点**——没有干净的 KC 字典，KT 和 FSRS 都无从谈起。建议 MVP 第一周即启动 KC 字典建设（人工框架 + LLM 辅助填充）。

---

**文档结束**

*v1.3 核心：把"对话"留给已商品化的基础模型，把"认知状态的精度"做成自己的护城河。*
*KT 回答「掌握了吗」，FSRS 回答「何时复习」，forgetting-aware 让两者统一——这套内核 + 永久档案，才是别人复制不了的东西。*
