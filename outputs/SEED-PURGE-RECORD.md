# 播种数据清理记录（W2a S4）

**执行时间（UTC）**：2026-07-16T04:01:42Z
**路径**：既有 `purge_service.purge_deleted_users`（软删 commit → 独立事务硬删，grace=0）。非一次性删除脚本。
**快照存档**：`outputs/seed_purge_snapshot.json`（清理前导出：199 users + 199 events + 199 kc_mastery 行）。

## 清理对象（cohort = 199）
出现在 `interaction_events` ∪ `kc_mastery` 的全部 student。

## 播种特征依据（为何判定为播种/合成、非真实学习者）
- **风险校验：cohort 内 >1 事件或有答对者 = 0** —— 全部单次作答、全部 is_correct=false。
- 193/199 手机号非真实 11 位格式；集中 1 个 KC（`GDMATH-SET-01` 198/199）。
- p_mastery 仅 3 个离散值（单次 BKT 更新产物）；n_attempts 全为 1。
- 结论：真实纵向学习者 ≈ 0，全错单次是极端噪声，留库污染此后所有探针读数。

## 硬删除结果
purged_users=199；级联删除 interaction_events=199 / kc_mastery=199 / mastery_snapshots=1 /
wrong_questions=1 / daily_missions=2 / users=199。gate.* 无该 cohort 记录（cohort 无门控数据）。

## 清理后基线（普查 SQL 复跑）
interaction_events=0 · kc_mastery=0 · is_correct=true 0 · mastery_confirmed 0 · n_attempts≥2 0 · users_remaining=9。
**五条探针从 0 起跑：此后任何非零即真人流量。**

## 附注
- 全 schema purge 守卫复跑绿（test_hard_delete 6 passed），无含 student_id 表游离清单外。
- 发现 `request_delete_and_purge_now`(grace=0) 单事务下因 Postgres now()=事务起始时间而 purge 0——
  另行上报（本次改走软删 commit + 独立事务硬删规避）。
