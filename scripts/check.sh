#!/bin/bash
# Mneme CI Quality Gate
# 职责：一条命令跑完全检查（Ruff + MyPy + Pytest w/ Coverage）

set -e

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}==> Running Ruff...${NC}"
.venv/bin/python -m ruff check .

echo -e "\n${GREEN}==> Running MyPy...${NC}"
.venv/bin/python -m mypy --explicit-package-bases .

echo -e "\n${GREEN}==> Running Pytest with Coverage...${NC}"
.venv/bin/python -m pytest

echo -e "\n${GREEN}==> All checks passed!${NC}"
