# S4 — Z 回测数据可行性普查

**日期**：2026-07-17
**结论**：数据不足以支撑真实回测，本轮不跑，Z=0.84 不改、不放宽。

---

## 背景

`Z = 0.84`（`packages/mneme-core/mneme_core/oprim/mastery_gate.py`）是量化 KC
过门的置信下界 z 分数：`lower_bound = p_learned - Z*sigma`，`lower_bound >=
threshold` 才判定掌握。目前只在合成数据上验证过判别力（`scripts/moat_eval/`，
AUC 0.677 ≥ 0.65 合成门槛），真实数据回测（校验 Z=0.84 对应的置信下界是否
真达到约 80% 校准覆盖率）尚未做——`scripts/moat_eval/README.md` 明确列为
已知局限："合成 ≠ 真实...不能替代真实学生数据回归"。

S4 先做可行性普查：数够不够跑真实回测，不做真跑。

## 普查方法

`scripts/z_backtest_feasibility.py`（可重跑）。合格判据沿用 `mastery_gate`
自己的口径 —— `kc_mastery.n_attempts >= N_MIN`（N_MIN=2，即 Z 置信下界在生产
门控逻辑里实际生效的最低观测数），理由：只有已过 N_MIN 门槛的 (student,KC)
对，Z 置信下界才会被 gate 实际使用，用同一门槛统计"够不够格回测"最贴合真实
使用面。

## 结果（2026-07-17 实测）

```
Z（当前值，不改）        = 0.84
N_MIN（合格判据）        = 2
kc_mastery 总行数        = 4
distinct 学生数          = 4
合格 (student,KC) 对     = 0
可行性门槛               = 200
```

- 生产库非删除用户仅 **13 个**（含 W2 studio pilot 的 Wiki+孩子账号、
  soffy88@gmail.com 本人账号、若干测试手机号）。
- `kc_mastery` 全表仅 4 行，即 4 个 (student,KC) 观测对，**且无一达到
  n_attempts>=2**——合格对数为 **0**，远低于 200 门槛。
- （注：此前 199 个纯种子/合成测试用户已在 `outputs/SEED-PURGE-RECORD.md`
  记录的清理中物理删除，不会虚增此次计数。）

## 决策（S4 拍定的规则，本轮按此执行）

- **合格对 < 200 → 不跑真实回测，只记录当前值**（本文档）。
- **推迟到真实数据量上来**——用户外部跟踪为 W4（不在本仓库 TASKS.md 内起新
  条目跟踪，等真实数据量上来后由 W4 决定何时重跑本普查）。
- **`Z=0.84` 本身不改、不放宽**——已核对 `mastery_gate.py` 当前值仍为
  `0.84`，本轮零代码改动。

## 何时重跑

`docker compose exec api python scripts/z_backtest_feasibility.py`。当合格对
数 ≥ 200 时，再设计真实回测方法论（如：对已过门 (student,KC) 对的下一次真实
作答，检验实际正确率是否 ≈ 置信下界隐含的目标覆盖率）——不在本次范围。
