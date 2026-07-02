# moat_eval — KT(BKT)+FSRS 内核与数据飞轮的护城河实证（合成数据）

三个可复跑实验，全部固定 seed=42。实验 2 需要隔离库 `mneme_moat_eval`
（**不要指向 dev 库 `mneme`**，脚本内有 DATABASE_URL 校验兜底）。

## 怎么跑（宿主机，api 容器内执行）

```bash
# 一次性：建隔离库 + 迁移
docker compose exec -T db psql -U postgres -c "CREATE DATABASE mneme_moat_eval;"
docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/mneme_moat_eval \
  api alembic upgrade head

# 实验 1：内核判别力基线（纯回放，不碰任何库）
docker compose exec -T api python scripts/moat_eval/exp1_kernel_auc.py

# 实验 2：数据飞轮（前半灌库→校准/权重择优→后半对比）
docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/mneme_moat_eval \
  api python scripts/moat_eval/exp2_flywheel.py
# 可选：MOAT_FIT_MAXITER=1 追加 scipy Powell 权重拟合（慢 ~5min；实测过拟合、
# 后半 AUC 反而下降——诚实保留为负结果开关）

# 实验 3：调度质量（纯模拟，不碰任何库）
docker compose exec -T -e MOAT_TRUTH=exp  api python scripts/moat_eval/exp3_scheduling.py
docker compose exec -T -e MOAT_TRUTH=fsrs api python scripts/moat_eval/exp3_scheduling.py
# 灵敏度：MOAT_BUDGET=5|8  MOAT_S0=1.5|3.0（仅 exp 真值）

# 收尾：丢弃隔离库
docker compose exec -T db psql -U postgres -c "DROP DATABASE mneme_moat_eval;"
```

## 各实验一句话

- **exp1_kernel_auc.py**：200 合成学生 × ≥50 交互（12 个广东数学 KC），隐藏真值
  （二元知识态 + 指数遗忘 + slip/guess + 学习率），用
  `oskill.cognitive_state.cognitive_update` 纯回放（等价生产算法路径，含 20h
  集中练习去抖），每步先用 P(L)×R 预测再更新，报 AUC / log-loss。
- **exp2_flywheel.py**：同一群体前半灌 `interaction_events`（真实字段），跑
  `services.calibration_service.calibrate_bkt_priors`（写 calibrated_from_n）与
  `services.fsrs_optimize_service.select_best_weights`（global cohort），后半对比
  默认 vs 校准后先验/权重的 AUC / log-loss（4 arm 归因）。
- **exp3_scheduling.py**：30 天记忆模拟，同预算下对比 FSRS 调度 / 固定 3 天 /
  不复习的第 30 天保留率；两种真值遗忘模型（对抗形 exp、同族形 fsrs）。

## CI 守卫（T.4）

exp1 有快速档（100 学生 × 20 学习日，`run_exp1(seed, n_students, n_study_days)`，
单 seed ~1s，纯计算不碰任何库），已接进质量门做内核判别力回归守卫：

```bash
MOAT=1 bash scripts/check.sh                       # 常规三步 + 守卫步
docker compose exec -T -e MOAT=1 api \
  python -m pytest tests/test_moat_guard.py -q --no-cov   # 只跑守卫
```

- **阈值**：合成 AUC ≥ 0.65（overall 与 warm_only 双门），seed=42/7/2026 三档全过。
  快速档稳定性：30 seed 扫描 min 0.654 / mean 0.677，与全量档（200×25，0.677）一致。
- **何时跑**：任何触碰调度/先验/内核（`oprim/bkt`、`oprim/fsrs_engine`、
  `oskill/cognitive_state`、种子先验、`predict_correct` 路径）的改动，
  **提交前先跑守卫**；常规 `bash scripts/check.sh` 不设 MOAT 时自动跳过（不变慢）。
- 守卫红 = 判别力被打回 0.65 以下，视为回归，task 未完成（红线同级）。

## 已知局限（读结果前必看）

1. **合成 ≠ 真实**：全部结论只证明"内核在其建模假设近似成立时可辨别/可校准"，
   不能替代真实学生数据回归（0.77 AUC 是真实数据目标，本处只看 0.65 合成门槛）。
2. **同构乐观偏差**：真值生成模型（隐藏知识态 + 遗忘 + slip/guess）与 BKT 结构
   相似，难度调制与内核 `_item_adjust` 同形——AUC 天然偏乐观。
3. **实验 3 的真值遗忘动力学是假设**：exp 真值下 FSRS 不敌固定 3 天（真实遗忘
   比 FSRS 假设快得多时间隔拉太长）；fsrs 族真值下 FSRS 用约一半复习次数达到
   其设计目标保留率（效率优势）。结论对真值形状敏感，需真实复习日志验证。
4. **FSRS 权重拟合负结果**：合成作答里 slip/guess 噪声与遗忘混杂，拟合内部
   log-loss 改善但后半预测 AUC 下降（过拟合），故默认只做候选择优不做 Powell。
