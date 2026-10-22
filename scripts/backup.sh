#!/bin/bash
# Mneme 数据备份：pg_dump（custom 压缩格式）+ MinIO 对象快照，保留 7 天。
#
# 用法：
#   ./scripts/backup.sh                              # 默认 /data/soffy/backups/mneme
#   MNEME_BACKUP_DIR=/x ./scripts/backup.sh          # 覆盖目录
#
# 生产 cron（已配置）：
#   10 2 * * * /data/soffy/backups/mneme/run_backup.sh
#   生产入口脚本与本文件保持同一行为；日志写 $MNEME_BACKUP_DIR/backup.log。
#
# 恢复：
#   pg:    docker compose exec -T db pg_restore -U postgres -d <db> --no-owner --clean --if-exists < dump
#   minio: docker cp <snapshot>/. mneme-minio-1:/data && docker compose restart minio
#
# 恢复演练记录见 docs/RESTORE_DRILL.md。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${MNEME_BACKUP_DIR:-/data/soffy/backups/mneme}"
KEEP_DAYS="${MNEME_BACKUP_KEEP_DAYS:-7}"
MIN_FREE_GB="${MNEME_BACKUP_MIN_FREE_GB:-8}"
TS="$(date +%Y%m%d_%H%M%S)"
PG_DIR="$BACKUP_DIR/pg"
MINIO_DIR_ROOT="$BACKUP_DIR/minio"
LOG_FILE="$BACKUP_DIR/backup.log"
LOCK_FILE="$BACKUP_DIR/.backup.lock"

mkdir -p "$PG_DIR" "$MINIO_DIR_ROOT"
exec >>"$LOG_FILE" 2>&1

log() { echo "[$(date '+%F %T')] $*"; }

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "backup skipped: another run holds $LOCK_FILE"
  exit 0
fi

free_gb="$(df -BG --output=avail /data | tail -1 | tr -dc '0-9')"
log "backup start ts=$TS dir=$BACKUP_DIR free=${free_gb}G keep=${KEEP_DAYS}d"
if [ "${free_gb:-0}" -lt "$MIN_FREE_GB" ]; then
  log "ERROR: /data free space ${free_gb}G < ${MIN_FREE_GB}G; abort before writing"
  exit 1
fi

cd "$REPO_ROOT"

# --- PostgreSQL（custom format 自带压缩）---
PG_FILE="$PG_DIR/mneme_${TS}.dump"
if ! docker compose exec -T db pg_dump -U postgres -d mneme -Fc -Z 6 >"$PG_FILE"; then
  log "ERROR: pg_dump failed; removing partial $PG_FILE"
  rm -f "$PG_FILE"
  exit 1
fi
if [ ! -s "$PG_FILE" ]; then
  log "ERROR: pg_dump produced an empty file"
  rm -f "$PG_FILE"
  exit 1
fi
log "pg    -> $PG_FILE ($(du -h "$PG_FILE" | cut -f1))"

# --- MinIO ---
MINIO_DIR="$MINIO_DIR_ROOT/data_${TS}"
rm -rf "$MINIO_DIR" 2>/dev/null || true
docker cp mneme-minio-1:/data "$MINIO_DIR"
touch "$MINIO_DIR"
log "minio -> $MINIO_DIR ($(du -sh "$MINIO_DIR" | cut -f1))"

# --- 轮转：保留 KEEP_DAYS 天（含今天）---
find "$PG_DIR" -maxdepth 1 -type f -name 'mneme_*.dump' -mtime "+$((KEEP_DAYS - 1))" -delete
find "$MINIO_DIR_ROOT" -maxdepth 1 -type d -name 'data_*' -mtime "+$((KEEP_DAYS - 1))" -exec rm -rf {} +

log "backup done ts=$TS"
