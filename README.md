# 自我助学系统 · 算法内核 (v1.3)

KT（知识追踪）+ FSRS（间隔重复）算法内核的最小可运行实现。学科：**广东数学**（新高考人教A版）。

这是 PRD v1.3 的落地代码：把「掌握了吗」和「何时复习」做成产品的算法护城河，而把已商品化的苏格拉底对话交给基础模型。

## 跑起来

```bash
pip install fsrs fastapi "uvicorn[standard]"

# 1) 看 KC 字典摘要
python3 data/guangdong_math_kc.py

# 2) 跑引擎验证（6项测试）
python3 tests/test_engine.py

# 3) 启动 API
uvicorn api.main:app --reload   # 然后访问 http://localhost:8000/docs
```

## 目录结构

```
self_learning_os/
├── data/
│   └── guangdong_math_kc.py   # C: 广东数学 KC 字典（地基，29个知识点）
├── core/
│   ├── bkt.py                 # A: BKT 知识追踪（forgetting-aware + 粗心/不会判定）
│   ├── fsrs_engine.py         # A: FSRS 间隔重复封装（基于 py-fsrs）
│   └── cognitive_state.py     # A: KT+FSRS 统一协调器
├── api/
│   └── main.py                # B: FastAPI 服务
└── tests/
    └── test_engine.py         # 引擎验证（含 AUC）
```

## 三个设计要点

**1. 掌握度用 BKT，不用拍脑袋公式**
每个知识点维护掌握概率 P(L)，每次答题做贝叶斯更新（见 `bkt.py`）。
四参数 P(L₀)/P(T)/P(G)/P(S) 都有教育学含义，可解释、可用 AUC 验证。

**2. 粗心 vs 不会 = BKT 的客观判据**
答错时：粗心权重 ∝ P(L)·P(S)，不会权重 ∝ (1-P(L))·(1-P(G))。
高掌握却答错 → 粗心；低掌握答错 → 不会。
**同一个知识点，系统能根据历史区分两种错误**——这是 BKT 优于 LLM 猜测的核心。

**3. forgetting-aware：KT 与 FSRS 统一**
用 FSRS 的可提取性 R 衰减 BKT 的先验掌握度：`P(L)_eff = P(L) · R`。
掌握度 = 长期是否学会(BKT) × 此刻是否记得(FSRS)，与真实认知一致。
- `long_term_mastery`：去遗忘的长期掌握度 → 成长曲线展示
- `effective_mastery`：含遗忘 → 决定今日该复习什么

## 验证结果（test_engine.py）

| 测试 | 结果 |
|------|------|
| 连续答对掌握度上升并封顶 0.97 | ✓ |
| 连续答错掌握度下降 | ✓ |
| 高掌握答错→粗心 / 低掌握答错→不会 | ✓ |
| forgetting-aware 遗忘衰减 | ✓ |
| 下一题正确率预测 合成数据 AUC≥0.65（0.77 为目标，真实数据待验证）| ✓（随机=0.5）|
| KT+FSRS 端到端 | ✓ |

## API 速览

| 接口 | 说明 |
|------|------|
| `POST /v1/interaction` | 上报一次答题/回顾，触发 KT+FSRS 更新 |
| `GET /v1/mastery/{student_id}` | 各知识点掌握度（按薄弱排序）|
| `GET /v1/review-queue/{student_id}` | 今日到期复习池 |
| `GET /v1/kc` · `GET /v1/kc/{kc_id}` | KC 字典摘要 / 详情（含前置链）|

## 下一步（生产化）

- 内存 `CognitiveStore` → PostgreSQL（表结构见 PRD v1.3 第6章）
- 接答题事件流 `interaction_events`，作为后续 DKT 训练数据
- BKT 群体参数用真实数据 EM 校准；数据足够后引入 DKT 并用 AUC 对比
- KC 字典从单科扩展（补全题型分布、权重标定、二级知识点细化）
