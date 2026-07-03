#!/bin/bash
# Mneme 数据备份：pg_dump（自定义格式）+ MinIO 对象快照
#
# 用法：
#   ./scripts/backup.sh            # 备份到 $MNEME_BACKUP_DIR（默认 ~/backups/mneme）
#   MNEME_BACKUP_DIR=/x ./scripts/backup.sh
#
# 建议 crontab（每日 02:10，避开夜间 GPU 任务）：
#   10 2 * * * cd /data/soffy/projects/mneme && ./scripts/backup.sh >> ~/backups/mneme/backup.log 2>&1
#
# 恢复：
#   pg:    cat <dump> | docker compose exec -T db pg_restore -U postgres -d mneme --no-owner --clean --if-exists
#   minio: docker cp <snapshot>/. mneme-minio-1:/data && docker compose restart minio

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BACKUP_DIR="${MNEME_BACKUP_DIR:-$HOME/backups/mneme}"
KEEP_DAYS="${MNEME_BACKUP_KEEP_DAYS:-14}"
TS="$(date +%Y%m%d_%H%M%S)"

mkdir -p "$BACKUP_DIR/pg" "$BACKUP_DIR/minio"

echo "[$(date '+%F %T')] backup start ts=$TS dir=$BACKUP_DIR"

# --- PostgreSQL ---
PG_FILE="$BACKUP_DIR/pg/mneme_${TS}.dump"
docker compose exec -T db pg_dump -U postgres -d mneme -Fc > "$PG_FILE"
echo "  pg   -> $PG_FILE ($(du -h "$PG_FILE" | cut -f1))"

# --- MinIO（对象 + 桶元数据一起快照）---
MINIO_DIR="$BACKUP_DIR/minio/data_${TS}"
docker cp mneme-minio-1:/data "$MINIO_DIR"
echo "  minio-> $MINIO_DIR ($(du -sh "$MINIO_DIR" | cut -f1))"

# --- 轮转：删除 KEEP_DAYS 天前的备份 ---
find "$BACKUP_DIR/pg" -name 'mneme_*.dump' -mtime "+$KEEP_DAYS" -delete 2>/dev/null || true
find "$BACKUP_DIR/minio" -maxdepth 1 -name 'data_*' -type d -mtime "+$KEEP_DAYS" -exec rm -rf {} + 2>/dev/null || true

echo "[$(date '+%F %T')] backup done"
