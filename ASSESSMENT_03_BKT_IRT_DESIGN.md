# BKT + IRT 最小落地方案（P1 · 难度感知掌握度）

> 目标：在**不推翻已验证 BKT 内核**、**不违反任何算法红线**的前提下，给掌握度估计加入"题目难度"这一最高 ROI 的信号。
> 现状问题：BKT 的 `slip/guess` 是 **KC 级**（甚至只按 `question_type` 分桶），同一知识点的易题/难题被一视同仁——既伤掌握度估计，也伤选题与"粗心/不会"判定。
> 依据：`platform/3O/oprim/oprim/bkt.py`、`oprim/_cognitive.py`、`oprim/tests/test_cognitive.py`、`mneme/services/models.py`、CLAUDE.md 红线。

---

## ✅ Phase 0 已完成（2026-06-28，零行为变化）

**生产链路核实**：`services/cognitive_service.py → omodul.cognitive → oskill.cognitive_state → **oprim.bkt**`（无前缀那份才是生产实现；`_cognitive.py` 的 `bkt_*` 是 AUC 测试与另一 oskill 用的孪生份）。

**改动**（纯增量，`difficulty=None`/`0.5` → 逐位等价旧行为）：
- `oprim/bkt.py`：+`import math`、私有 `_item_adjust`（logit 空间调制 slip/guess，0.5 短路防浮点漂移）、`bkt_update`/`predict_correct`/`classify_error` 加 `difficulty: float|None=None`。
- `oprim/_cognitive.py`：**孪生份同步相同增量**（不加剧 D5 漂移），`bkt_update`/`bkt_predict_correct`/`bkt_classify_error` 同样加 `difficulty`。
- 未碰 KCState、未改更新顺序、未动 DB（DDL/migration 属 Phase 1）。

**验收**：
- 新增 `oprim/tests/test_bkt_irt.py`：R1 逐位兼容（None==省略==0.5，含孪生份）、R2 难度方向性、R3 边界(0,0.97]、R6 单调封顶——**69 passed**。
- 既有 `test_cognitive.py` **18 passed（零回归）**；mneme 生产链路 `test_engine/cognitive_service/paper/paper_analysis` **13 passed**。

---

## ✅ D5 单源收敛 + Phase 1 已完成（2026-06-28）

### D5 BKT 单源收敛（零行为变化）
- **实证**：差分脚本在 **19440 个真实参数组合**下，旧 `bkt.py` 与 `_cognitive` 的 `p_mastery/long_term/predict/classify` 输出**逐位一致**（max|Δ|=0）。差异仅存在于不可达极端（R 恰为 0 的 clip、浮点平局）。
- **收敛**：依赖方向锁定（`bkt.py→types→_cognitive`），故 `oprim/bkt.py` 改为指向 `_cognitive`（被 AUC 验证、拥有 KCState/FSRS）的**纯别名层**（`classify_error=bkt_classify_error` 等）。`new_state_from_prior`/`exp_forgetting` 无外部调用方，别名安全。
- **守卫**：`test_bkt_single_source.py` 断言 `oprim.bkt.* is oprim._cognitive.*`，防未来重新 fork。

### Phase 1 难度透传 + 落库
- **链路**（全程透传 `difficulty`）：`POST /v1/interaction`(InteractionInput 加字段，自动接受) → `cognitive_service.process_interaction(difficulty=)` → `omodul InteractionInput` → `oskill CognitiveUpdateInput` → `oprim.bkt.bkt_update/classify_error`。
- **落库**：`omodul.cognitive` event_data 加 `item_difficulty`；`obase PgStore.append_event` 写入；`services.models.InteractionEvent` 加 `item_difficulty FLOAT NULL`；**Alembic `d049051a89f6`**（仅加该列，剔除 autogenerate 的无关 drift）。
- **R4 价值证明**：`test_bkt_irt.py::test_r4_difficulty_aware_auc_not_worse` —— 难度依赖的合成序列上，难度感知 AUC ≥ 难度盲且 ≥0.65。

### 验收（证据）
- 内核 `test_bkt_irt.py`(70) + `test_bkt_single_source.py`(2) + `test_cognitive.py`(18) = **90 passed**。
- mneme 生产链路 `test_engine/cognitive_service/paper/paper_analysis/statestore` = **16 passed**。
- **Migration 对 live Postgres 真跑**：upgrade→downgrade→re-upgrade 可逆；列确认 `item_difficulty | double precision | nullable`。
- **Live 端到端**：真实链路 `process_interaction(difficulty=0.8)` 回写 `item_difficulty=0.8`（已清理冒烟数据）。
- 注：mneme 全量 `pytest tests/` 有 6 个**预存在**失败（health 期望'ok'实为'healthy'、daily_plan 空计划假设、socratic end `kc_updated` 键）——与本变更无关（本轮 mneme 源码仅 4 行增量，未碰 socratic/daily_plan/health）。

**仍未做（Phase 2 起）**：按 `question_id` join `questions.difficulty` 自动取难度（当前为入参透传，未传则 item_difficulty=NULL、行为不变）；群体 p-value 校准回填难度；2PL/DKT 演进。

---

---

## 0. 前置项（动手前必须先做）
- [ ] **收敛 BKT 单源**（同 DRIFT D5）：`bkt.py` 与 `_cognitive.py` 各有一份 `KCState/bkt_update`，先确定唯一权威、另一份 re-export，否则改一份漏一份。**本方案以 `bkt.py` 的签名为准**。

---

## 1. 选型：难度调制 slip/guess（不引入 θ 的最小 IRT 融合）

学界成熟做法（Khajah 2014「Integrating KT and IRT」一类）有两档：
- **A. 难度调制发射参数（推荐 · 最小）**：保留 KC 级 `P(L)` 与贝叶斯更新结构不变，只让 `slip/guess` 随题目难度 `b∈[0,1]` 单调变化。
- **B. 完整 2PL（θ + 区分度 a）**：需拟合学生能力 θ 与题目 a/b，工程量大、需数据——列为**后续演进**，不在最小落地。

选 **A**：改动面小、`b=0.5` 时与现状**逐位等价**（现有测试全绿）、且复用 `questions.difficulty` 已存在的列（`models.py:443` `Float default 0.5`）。

### 直觉
- 题越**难**（b↑）：已掌握者也可能错 → `slip↑`；没掌握者也难蒙对 → `guess↓`。
- 题越**易**（b↓）：`slip↓`、`guess↑`。
- 推论（正确的方向性）：**答对一道难题** = 更强的掌握证据（后验涨更多）；**答错一道易题** = 更强的未掌握证据（后验跌更多）。

### 数学（在 logit 空间单调调制，天然限幅）
设难度偏移 `δ = b - 0.5`，敏感度常数 `γ_s, γ_g`（默认 1.0，可调）：
```
slip_eff  = σ( logit(P_S) + γ_s · δ )      # b>0.5 → slip 增
guess_eff = σ( logit(P_G) − γ_g · δ )      # b>0.5 → guess 减
```
`b=0.5 → δ=0 → slip_eff=P_S, guess_eff=P_G`（**完全回退到现状**）。
随后**贝叶斯更新分子分母结构完全不变**，只是把 `P_S/P_G` 换成 `slip_eff/guess_eff`：
```
答对： num = P_L_eff·(1−slip_eff);  den = P_L_eff·(1−slip_eff) + (1−P_L_eff)·guess_eff
答错： num = P_L_eff·slip_eff;       den = P_L_eff·slip_eff   + (1−P_L_eff)·(1−guess_eff)
```
`predict_correct` 同样用 `slip_eff/guess_eff`。

### 红线一致性核对（逐条）
| 红线（CLAUDE.md） | 是否仍满足 |
|---|---|
| `P(L)∈(0,0.97]` | ✅ 更新与封顶逻辑未动（`_clip(..., hi=_MASTERY_CAP)`） |
| `effective = long_term × R` | ✅ forgetting-aware 步未动，难度只调发射参数 |
| `careless ∝ P(L)·P(S)` | ✅ 用 `slip_eff` 仍是 `P(L)·P(S)` 比例形式（题目级 P(S)） |
| `dontknow ∝ (1−P(L))·(1−P(G))` | ✅ 用 `guess_eff`，比例形式不变 |
| 更新顺序：算R→forgetting-aware BKT→classify→FSRS→落库 | ✅ 难度调制发生在"forgetting-aware BKT"内部，顺序不变 |
| 连续答对单调不降 | ✅ 固定难度下仍单调（需 R6 测试守护） |
| 不推翻已验证内核 | ✅ 纯扩展、`b=0.5` 等价旧行为 |

---

## 2. 落地改动（按层，遵守 3O 约束）

### 2.1 oprim 层 —— `platform/3O/oprim/oprim/bkt.py`
- 加 **模块私有** 纯函数（同文件内，**不构成 oprim 互调**，不违反 H1-prim）：
  ```python
  def _item_adjust(p_guess, p_slip, difficulty, gamma_g=1.0, gamma_s=1.0):
      """难度调制发射参数；difficulty=None → 原样返回 (无 IRT)。"""
  ```
- `bkt_update(...)` 增可选参 `difficulty: float | None = None`；内部据此算 `slip_eff/guess_eff` 再走原更新。`None`/`0.5` → 行为不变。
- `predict_correct(...)`、`classify_error(...)` 同样增 `difficulty: float | None = None`。
- 不改 `KCState`（难度是**题目**属性，不进 KC 状态）。

### 2.2 oskill 层 —— `cognitive_update`（platform/3O/oskill）
- 编排时把"本题难度"透传给 `bkt_update/classify_error`：从 `questions.difficulty` 或事件入参取 `difficulty`。oskill 负责"取难度并传参"，oprim 负责"用难度算"——分层干净。

### 2.3 服务层 —— `mneme/services/cognitive_service.py`
- `POST /v1/interaction` 接收/查得 `difficulty`（按 `question_id` join `questions.difficulty`，缺则 `0.5`），传入 `cognitive_update`。

### 2.4 数据 —— `mneme/services/models.py` + Alembic
- `interaction_events` 加列 `item_difficulty FLOAT NULL`，**落库记录本次用的难度**（符合"interaction_events 只增不改、未来 DKT 训练数据"原则；为后续 EM 校准与 AUC 复算留证据）。
- 走 `alembic revision --autogenerate`（红线：DB 只走 migration）。

---

## 3. 回归测试（守红线 + 证明增益）
新增 `tests/test_bkt_irt.py`（内核侧）+ 复用现有 `test_engine.py` 不变以证兼容。

- [ ] **R1 向后兼容（最关键）**：对随机 state，`difficulty=None` 与 `difficulty=0.5` 时，`bkt_update/predict_correct/classify_error` 输出与旧实现**逐位一致**（|Δ|<1e-9）。→ 保证现有测试与线上行为不变。
- [ ] **R2 难度方向性**：固定 state，**答对**时 `posterior(b=0.8) > posterior(b=0.5) > posterior(b=0.2)`；**答错**时 `drop(b=0.2) > drop(b=0.5) > drop(b=0.8)`。
- [ ] **R3 边界安全**：`difficulty∈{0,0.5,1}` × 任意 state，结果 `∈(0,0.97]`、无 NaN/inf；`slip_eff,guess_eff∈(0,1)`。
- [ ] **R4 AUC 增益（价值证明）**：扩 `test_bkt_auc_simulation` —— 合成数据里给每题抽难度 `b`，真实 slip/guess 依 `b` 变化；对比"难度盲 BKT"与"难度感知 BKT"两条预测序列，断言 `auc_aware ≥ auc_blind` 且 `auc_aware ≥ 0.65`。固定 `np.random.seed`。
- [ ] **R5 classify 一致性**：高 `P(L)` + 答错 → 仍判 `careless`；低 `P(L)` + 答错 → 仍判 `dontknow`；难度不应翻转显著情形。比例式 `P(L)·slip_eff` vs `(1−P(L))·(1−guess_eff)` 成立。
- [ ] **R6 单调不降**：固定难度连续答对，`P(L)` 单调非降且收敛 ≤0.97（守 CLAUDE.md 红线）。

---

## 4. 分阶段上线（每步都可单独发，零回退风险）
1. **Phase 0（无行为变化）**：2.1 全部加 `difficulty=None` 默认；R1/R3/R6 绿。线上一切照旧。
2. **Phase 1（接线）**：2.2/2.3/2.4 透传真实难度（先用 `question_type` 启发式或人工标，缺省 0.5）；R2/R4/R5 绿。
3. **Phase 2（校准难度）**：当某题累计作答 ≥N，用群体正确率（经典 p-value→b）回填 `questions.difficulty`，闭合 `bkt_priors.calibrated_from_n` 的"数据驱动"承诺。
4. **Phase 3（演进，可选）**：上完整 2PL（θ + 区分度 a）或 DKT/AKT，用 AUC 对比决定是否切换，**保留 BKT 作可解释层**（与 Master §4.7 演进条款一致）。

## 5. 配置与调参
- `γ_s, γ_g` 入 `pydantic-settings`（默认 1.0），初期保守、避免破坏稳定性；后续可按 R4 的 AUC 网格微调。
- 难度来源优先级：人工/考试元数据标注 > question_type 启发式 > 默认 0.5。

---

### 一句话
这是"用一个已存在的列（`questions.difficulty`）+ 一段 logit 调制 + `b=0.5` 等价回退"换来掌握度精度与选题质量的提升——**最小改动、零红线冲突、可证明增益（R4）**，且为后续 EM 校准与 2PL/DKT 铺好了数据底座（`interaction_events.item_difficulty`）。
