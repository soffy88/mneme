#!/bin/bash
# P3: EchoMimic V2 侧车启动脚本（宿主机 native 运行）
#
# 用法:
#   ./scripts/start_echo_sidecar.sh        # 前台启动（调试）
#   ./scripts/start_echo_sidecar.sh --bg   # 后台启动（生产）
#   ./scripts/start_echo_sidecar.sh --stop # 停止
#   ./scripts/start_echo_sidecar.sh --status # 状态检查

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO_ROOT/.venv-echo"
SERVER="$REPO_ROOT/.echo/server.py"
PID_FILE="$REPO_ROOT/.echo/server.pid"
LOG_FILE="$REPO_ROOT/.echo/server.log"
PORT="${ECHO_PORT:-8081}"

if [[ ! -d "$VENV" ]]; then
    echo "ERROR: venv not found at $VENV"
    echo "Run: python3.11 -m venv $VENV && $VENV/bin/pip install torch fastapi ..."
    exit 1
fi

if [[ ! -f "$SERVER" ]]; then
    echo "ERROR: server.py not found at $SERVER"
    exit 1
fi

case "${1:-}" in
    --stop)
        if [[ -f "$PID_FILE" ]]; then
            PID=$(cat "$PID_FILE")
            if kill -0 "$PID" 2>/dev/null; then
                kill "$PID"
                echo "Stopped sidecar (PID $PID)"
            else
                echo "PID $PID not running"
            fi
            rm -f "$PID_FILE"
        else
            echo "No PID file found"
            # Try to find and kill by name
            pkill -f ".echo/server.py" 2>/dev/null && echo "Killed by name" || echo "Not running"
        fi
        exit 0
        ;;
    --status)
        if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            PID=$(cat "$PID_FILE")
            echo "Sidecar running (PID $PID) on port $PORT"
            curl -sf "http://localhost:$PORT/health" | python3 -m json.tool
        else
            echo "Sidecar not running"
            # Check if anything is on the port
            if curl -sf "http://localhost:$PORT/health" > /dev/null 2>&1; then
                echo "But something IS listening on port $PORT:"
                curl -sf "http://localhost:$PORT/health" | python3 -m json.tool
            fi
        fi
        exit 0
        ;;
    --bg)
        if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "Sidecar already running (PID $(cat "$PID_FILE"))"
            exit 0
        fi
        echo "Starting EchoMimic V2 sidecar on :$PORT (background)..."
        nohup "$VENV/bin/python3.11" "$SERVER" > "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
        sleep 2
        if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "Started (PID $(cat "$PID_FILE"))"
            echo "Log: $LOG_FILE"
            curl -sf "http://localhost:$PORT/health" | python3 -m json.tool
        else
            echo "FAILED to start. Check log:"
            tail -20 "$LOG_FILE"
            exit 1
        fi
        ;;
    *)
        echo "Starting EchoMimic V2 sidecar on :$PORT (foreground)..."
        echo "Press Ctrl+C to stop"
        exec "$VENV/bin/python3.11" "$SERVER"
        ;;
esac
