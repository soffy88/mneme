#!/bin/bash
# Mneme CI Quality Gate
# 职责：一条命令跑完全检查（Ruff + MyPy + Pytest w/ Coverage，fail_under 见 pyproject）
#
# 环境自适应：
#   1. 有 .venv/       → 用本地虚拟环境执行
#   2. docker api 在跑 → 透传到容器执行（docker compose exec -T api ...）
#   3. 两者都无        → 报错退出
#
# SKIP_PYTEST=1 可跳过 pytest 步骤（如 DB 被其他任务占用时），ruff/mypy 仍必须通过。
# MOAT=1 追加第四步：moat 守卫（tests/test_moat_guard.py，内核合成 AUC≥0.65 回归门）。

set -e

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# 选择执行环境
if [ -x ".venv/bin/python" ]; then
    RUN=(.venv/bin/python -m)
    echo -e "${GREEN}==> Environment: local .venv${NC}"
elif docker compose ps --status=running api 2>/dev/null | grep -q api; then
    RUN=(docker compose exec -T api python -m)
    echo -e "${GREEN}==> Environment: docker compose (api container)${NC}"
else
    echo -e "${RED}==> No environment found: neither .venv/ nor a running 'api' container.${NC}" >&2
    echo -e "${RED}    Run 'docker compose up -d' or create .venv first.${NC}" >&2
    exit 1
fi

echo -e "\n${GREEN}==> Running Ruff...${NC}"
"${RUN[@]}" ruff check .

echo -e "\n${GREEN}==> Running MyPy...${NC}"
"${RUN[@]}" mypy --explicit-package-bases .

if [ "${SKIP_PYTEST:-0}" = "1" ]; then
    echo -e "\n${GREEN}==> Skipping Pytest (SKIP_PYTEST=1).${NC}"
else
    echo -e "\n${GREEN}==> Running Pytest with Coverage...${NC}"
    "${RUN[@]}" pytest
fi

if [ "${MOAT:-0}" = "1" ]; then
    echo -e "\n${GREEN}==> Running Moat Guard (MOAT=1, kernel synthetic AUC gate)...${NC}"
    # 单独跑守卫文件：--no-cov 关闭覆盖率（fail_under 针对全量套件，不适用单文件）。
    if [ -x ".venv/bin/python" ]; then
        MOAT=1 .venv/bin/python -m pytest tests/test_moat_guard.py -q --no-cov
    else
        docker compose exec -T -e MOAT=1 api python -m pytest tests/test_moat_guard.py -q --no-cov
    fi
fi

echo -e "\n${GREEN}==> All checks passed!${NC}"
