#!/usr/bin/env bash
# 夜间自动补全「数学·高一」KU 的 rich_content（本地 Ollama qwen2.5vl:7b）。
# 由 crontab 调用。幂等：无待生成则立即退出。
#
# 2026-07-05 修复①：cron PATH 只有 /usr/bin:/bin，timeout 已在 /usr/bin，
#   改用绝对路径 /usr/bin/timeout 彻底规避 PATH 问题。
# 2026-07-05 修复②：连带把 curl/docker 也换成绝对路径，同一根因（cron 下
#   PATH 精简）一次修完，避免再次静默失败。
set -u
export LANG=C.UTF-8 LC_ALL=C.UTF-8
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
cd /data/soffy/projects/mneme || exit 1

# Ollama 未启动则跳过
if ! /usr/bin/curl -sf -o /dev/null http://localhost:11434/api/tags; then
  echo "$(date '+%F %T') Ollama 未运行，跳过本次"
  exit 0
fi

echo "=== $(date '+%F %T') 开始 高一 enrich ==="

# 5 小时封顶：用 /usr/bin/timeout 绝对路径，兼容 uutils 和 GNU coreutils
/usr/bin/timeout 18000 /usr/bin/docker compose exec -T \
  -e LLM_BASE_URL=http://host.docker.internal:11434/v1 \
  -e LLM_MODEL=qwen2.5vl:7b \
  -e LLM_API_KEY=ollama \
  -e LLM_WORKERS=4 \
  -e LLM_MAX_TOKENS=2000 \
  -e DATABASE_URL_SYNC=postgresql://postgres:postgres@db:5432/mneme \
  api python3 scripts/enrich_ku_content.py --subject math --grades 高一
EXIT_CODE=$?
echo "=== $(date '+%F %T') 结束（退出码 ${EXIT_CODE}）==="
