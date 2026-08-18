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
YELLOW='\033[0;33m'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ruff 缓存目录可能被 root 创建过（历史权限噪音），不可写时回退到临时目录，
# 保证 ruff 步骤在任何环境下都能跑（缓存只是加速，不影响结果）。
if [ -d "$REPO_ROOT/.ruff_cache" ] && [ ! -w "$REPO_ROOT/.ruff_cache" ]; then
    export RUFF_CACHE_DIR="$(mktemp -d /tmp/ruff-cache-XXXXXX)"
    echo -e "${YELLOW}==> .ruff_cache 不可写，ruff 缓存回退到 $RUFF_CACHE_DIR${NC}"
fi
# mypy 缓存同理（root 占用的 .mypy_cache 会让 mypy 直接 INTERNAL ERROR）。
if [ -d "$REPO_ROOT/.mypy_cache" ] && [ ! -w "$REPO_ROOT/.mypy_cache" ]; then
    export MYPY_CACHE_DIR="$(mktemp -d /tmp/mypy-cache-XXXXXX)"
    echo -e "${YELLOW}==> .mypy_cache 不可写，mypy 缓存回退到 $MYPY_CACHE_DIR${NC}"
fi

# 选择执行环境
if [ -x ".venv/bin/python" ]; then
    RUN=(.venv/bin/python -m)
    MODE=venv
    echo -e "${GREEN}==> Environment: local .venv${NC}"
elif docker compose ps --status=running api 2>/dev/null | grep -q api; then
    RUN=(docker compose exec -T api python -m)
    MODE=docker
    echo -e "${GREEN}==> Environment: docker compose (api container)${NC}"
else
    echo -e "${RED}==> No environment found: neither .venv/ nor a running 'api' container.${NC}" >&2
    echo -e "${RED}    Run 'docker compose up -d' or create .venv first.${NC}" >&2
    exit 1
fi

# ── 测试库解析：绝不在生产库 `mneme` 上跑测试（conftest 无事务隔离，会写真库）──
# 专用测试库 mneme_test 已存在（同 PG 实例）。解析顺序：
#   1. 显式 TEST_DATABASE_URL（用户/CI 提供）
#   2. 否则从活 api 容器的 DATABASE_URL 派生（仅换库名 mneme→mneme_test，口令不落库）
# .venv（宿主）执行时再把容器内 host:port 换成宿主映射（docker compose port db 5432）。
# 结果设入全局 TEST_DB_URL；解析失败或结果非 mneme_test 直接退出（fail-closed）。
resolve_test_db_url() {
    local src="${TEST_DATABASE_URL:-}"
    if [ -z "$src" ]; then
        src="$(docker compose exec -T api printenv DATABASE_URL 2>/dev/null | tr -d '\r')"
    fi
    if [ -z "$src" ]; then
        echo -e "${RED}==> 无法解析测试库 URL：请设 TEST_DATABASE_URL，或让 api 容器在跑以派生。${NC}" >&2
        exit 1
    fi
    # 强制库名 → mneme_test（覆盖 /mneme、/mneme_test、带 query 串等形态）
    src="$(printf '%s' "$src" | sed -E 's#/mneme(_test)?(\?[^ ]*)?$#/mneme_test\2#')"
    # 宿主执行：容器内 hostname:port（如 db:5432）→ 宿主映射端口
    if [ "$MODE" = "venv" ]; then
        local hostport
        hostport="$(docker compose port db 5432 2>/dev/null | sed -E 's/.*:([0-9]+)[[:space:]]*$/\1/')"
        hostport="${hostport:-5433}"
        src="$(printf '%s' "$src" | sed -E "s#@[^/@]+/#@localhost:${hostport}/#")"
    fi
    # 安全闸：解析结果必须落在 mneme_test
    case "$src" in
        */mneme_test|*/mneme_test\?*) : ;;
        *) echo -e "${RED}==> 拒绝：解析出的测试库不是 mneme_test（${src%%\?*}）——不在生产库上跑测试。${NC}" >&2; exit 1 ;;
    esac
    TEST_DB_URL="$src"
}

echo -e "\n${GREEN}==> Running Ruff...${NC}"
"${RUN[@]}" ruff check .

echo -e "\n${GREEN}==> vendor edu closure (runtime 不得 import 金融 3O 路径)...${NC}"
if [ "$MODE" = "venv" ]; then
    .venv/bin/python scripts/vendor_edu_closure.py --check
else
    docker compose exec -T api python scripts/vendor_edu_closure.py --check
fi

# 纯单测 / AST 红线：不依赖真 DB 业务数据，约数十秒。全量 pytest 仍走 mneme_test。
echo -e "\n${GREEN}==> Smoke (red-line AST / sandbox / db_guard)...${NC}"
SMOKE_FILES=(
    tests/test_db_guard.py
    tests/test_partner_no_self_judged_mastery.py
    tests/test_vendor_edu_boundary.py
    tests/test_sandbox_selfcheck.py
    tests/test_sandbox_ast_audit.py
    tests/test_sandbox_zero_bypass.py
    tests/test_mastery_write_path_guards.py
    tests/test_kernel_contract.py
    tests/test_cognitive_store_lock.py
)
if [ "$MODE" = "venv" ]; then
    "${RUN[@]}" pytest --no-cov -q "${SMOKE_FILES[@]}"
else
    docker compose exec -T api python -m pytest --no-cov -q "${SMOKE_FILES[@]}"
fi

echo -e "\n${GREEN}==> Running MyPy...${NC}"
"${RUN[@]}" mypy --explicit-package-bases .

if [ "${SKIP_PYTEST:-0}" = "1" ]; then
    echo -e "\n${GREEN}==> Skipping Pytest (SKIP_PYTEST=1).${NC}"
else
    resolve_test_db_url
    echo -e "\n${GREEN}==> Running Pytest with Coverage (DB=$(printf '%s' "$TEST_DB_URL" | sed -E 's#://[^@]+@#://***@#'))...${NC}"
    if [ "$MODE" = "venv" ]; then
        DATABASE_URL="$TEST_DB_URL" "${RUN[@]}" pytest
    else
        docker compose exec -T -e DATABASE_URL="$TEST_DB_URL" api python -m pytest
    fi
fi

if [ "${MOAT:-0}" = "1" ]; then
    echo -e "\n${GREEN}==> Running Moat Guards (MOAT=1, exp1/exp6 回归门)...${NC}"
    # 单独跑守卫文件：--no-cov 关闭覆盖率（fail_under 针对全量套件，不适用单文件）。
    # test_moat_guard=exp1 合成 AUC；test_recognition_guard=exp6 识别维度（GH-2）。
    # test_external_auc（GH-1）依赖本地 data/external（不入主库），不进门、手动跑。
    [ -z "${TEST_DB_URL:-}" ] && resolve_test_db_url   # SKIP_PYTEST=1 时也要解析
    if [ "$MODE" = "venv" ]; then
        MOAT=1 DATABASE_URL="$TEST_DB_URL" .venv/bin/python -m pytest tests/test_moat_guard.py tests/test_recognition_guard.py -q --no-cov
    else
        docker compose exec -T -e MOAT=1 -e DATABASE_URL="$TEST_DB_URL" api python -m pytest tests/test_moat_guard.py tests/test_recognition_guard.py -q --no-cov
    fi
fi

echo -e "\n${GREEN}==> All checks passed!${NC}"
