#!/usr/bin/env bash
# 夜间自动补全「数学·高一」KU 的 rich_content（本地 Ollama qwen2.5:7b）。
# 由 crontab 调用。幂等：无待生成则立即退出。
set -u
export LANG=C.UTF-8 LC_ALL=C.UTF-8
cd /home/soffy/projects/mneme || exit 1

# Ollama 未启动则跳过（避免夜里 Ollama 没开时刷错误）
if ! curl -sf -o /dev/null http://localhost:11434/api/tags; then
  echo "$(date '+%F %T') Ollama 未运行，跳过本次"
  exit 0
fi

export LLM_BASE_URL=http://localhost:11434/v1
export LLM_MODEL=qwen2.5:7b
export LLM_API_KEY=ollama
export LLM_WORKERS=4
export LLM_MAX_TOKENS=2000

echo "=== $(date '+%F %T') 开始 高一 enrich ==="
# 5 小时封顶，避免拖到白天占 GPU；未完成的下次继续（脚本只取 NULL，可断点续）
timeout 18000 .venv/bin/python scripts/enrich_ku_content.py --subject math --grades 高一
echo "=== $(date '+%F %T') 结束（退出码 $?）==="
