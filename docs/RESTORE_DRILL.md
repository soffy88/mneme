# 备份恢复演练记录（Restore Drill）

- 日期：2026-10-22
- 执行人：engineering（P0-2 上线阻塞项修复）
- 目标：证明 `run_backup.sh` 产出的 pg_dump 可以完整恢复，且关键表行数与生产库一致。
- 生产库：`mneme`（`mneme-db-1`，Alembic head `vcm1a2b3c4d5`）
- 演练库：临时数据库 `mneme_restore_drill_20261022`（演练后已删除，未触碰生产库）

## 1. 备份脚本

- 入口：`/data/soffy/backups/mneme/run_backup.sh`（cron `10 2 * * *` 调用）
- 仓库内同源脚本：`scripts/backup.sh`
- 行为：PostgreSQL `pg_dump -Fc -Z 6`（custom 压缩格式）+ MinIO `/data` 快照，
  保留 7 天，日志追加到 `/data/soffy/backups/mneme/backup.log`，带 `flock` 防并发，
  并在 `/data` 可用空间低于 8GB 时提前退出。

本次手动执行成功：

```
[2026-10-22 11:18:42] backup start ts=20261022_111842 free=67G keep=7d
[2026-10-22 11:19:17] pg    -> /data/soffy/backups/mneme/pg/mneme_20261022_111842.dump (385M)
[2026-10-22 11:19:42] minio -> /data/soffy/backups/mneme/minio/data_20261022_111842 (2.5G)
[2026-10-22 11:19:42] backup done ts=20261022_111842
```

## 2. 恢复步骤与结果

```
# 建临时库
docker compose exec -T db psql -U postgres -d postgres \
  -c "DROP DATABASE IF EXISTS mneme_restore_drill_20261022 WITH (FORCE);" \
  -c "CREATE DATABASE mneme_restore_drill_20261022;"
# 恢复（约 25 秒）
docker compose exec -T db pg_restore -U postgres -d mneme_restore_drill_20261022 \
  --no-owner --no-privileges < pg/mneme_20261022_111842.dump
```

关键表行数比对（源库 `mneme` vs 演练库）：

| 表 | 源库 | 演练库 | 一致 |
|---|---:|---:|:--:|
| users | 115 | 115 | ✅ |
| knowledge_units | 14,646 | 14,646 | ✅ |
| knowledge_clusters | 1,931 | 1,931 | ✅ |
| textbooks | 133 | 133 | ✅ |
| wrong_questions | 30,153 | 30,153 | ✅ |
| question_records | 169 | 169 | ✅ |
| kc_mastery | 90 | 90 | ✅ |
| learning_events | 38 | 38 | ✅ |
| interaction_events | 139 | 139 | ✅ |
| guardian_consents | 12 | 12 | ✅ |

- 恢复耗时：约 25 秒（385MB dump，主机本地盘）。
- 迁移版本：源库与演练库均为 `vcm1a2b3c4d5`。
- 演练库已在比对通过后 `DROP DATABASE ... WITH (FORCE)` 删除，磁盘占用已回收。

## 3. 结论与后续

- 结论：**PASS**。备份可恢复，关键表行数一致，无静默丢表。
- 每日 cron 已指向存在的脚本，7 天轮转已生效（首次运行后 `/data` 仍余约 64GB）。
- 仍待 owner 决策：`BackupContract` 的 RPO/RTO 数值、异地/对象存储副本与加密、
  以及定期自动化 restore drill（当前为人工记录）。
