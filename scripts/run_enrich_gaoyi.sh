#!/usr/bin/env bash
# 夜间自动补全「数学·高一」KU 的 rich_content（本地 Ollama qwen2.5vl:7b）。
# 由 crontab 调用。幂等：无待生成则立即退出。
#
# 2026-07-05 修复：本项目所有 Python 都跑在 docker 容器里，宿主机没有
# .venv（原脚本假设 host 端有 venv，实际从未存在，导致 cron 每晚静默失败）。
# 改为容器内执行 + host.docker.internal 访问宿主机 Ollama。
set -u
export LANG=C.UTF-8 LC_ALL=C.UTF-8
cd /data/soffy/projects/mneme || exit 1

# Ollama 未启动则跳过（避免夜里 Ollama 没开时刷错误；host 侧检测，容器内也走
# host.docker.internal 访问同一个 Ollama）。
if ! curl -sf -o /dev/null http://localhost:11434/api/tags; then
  echo "$(date '+%F %T') Ollama 未运行，跳过本次"
  exit 0
fi

echo "=== $(date '+%F %T') 开始 高一 enrich ==="
# 5 小时封顶，避免拖到白天占 GPU；未完成的下次继续（脚本只取 NULL，可断点续）
timeout 18000 docker compose exec -T \
  -e LLM_BASE_URL=http://host.docker.internal:11434/v1 \
  -e LLM_MODEL=qwen2.5vl:7b \
  -e LLM_API_KEY=ollama \
  -e LLM_WORKERS=4 \
  -e LLM_MAX_TOKENS=2000 \
  -e DATABASE_URL_SYNC=postgresql://postgres:postgres@db:5432/mneme \
  api python3 scripts/enrich_ku_content.py --subject math --grades 高一
echo "=== $(date '+%F %T') 结束（退出码 $?）==="
