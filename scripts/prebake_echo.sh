#!/bin/bash
# P3: 预渲染 EchoMimic V2 缓存池
# 提前生成常用动作的视频片段，减少在线延迟。
#
# 用法:
#   ./scripts/prebake_echo.sh [--base-url http://localhost:8081] [--ref-image path]
#
# 前置条件:
#   - EchoMimic 侧车已启动 (docker compose --profile gpu up echomimic)
#   - edge-tts 已安装 (pip install edge-tts)

set -euo pipefail

BASE_URL="${ECHO_BASE_URL:-http://localhost:8081}"
REF_IMAGE=""
OUTPUT_DIR="./public/aria/echo_cache"
VOICE="en-US-AriaNeural"

# 预设片段：(文本, 情绪, 文件名)
PRESETS=(
    "Hello, I'm Aria. Let's play something together.|warm|greeting"
    "That was beautiful. Would you like to try another piece?|warm|encourage"
    "Focus on the rhythm. Feel the keys under your fingers.|focused|coaching"
    "Take a breath. Music is about feeling, not just notes.|gentle|reflect"
    "Wonderful! You're improving every day.|warm|praise"
)

usage() {
    echo "Usage: $0 [--base-url URL] [--ref-image PATH] [--output-dir DIR]"
    echo ""
    echo "Options:"
    echo "  --base-url URL      EchoMimic sidecar URL (default: \$ECHO_BASE_URL or http://localhost:8081)"
    echo "  --ref-image PATH    Reference image path (default: public/aria/dh/person_play.png)"
    echo "  --output-dir DIR    Output directory (default: ./public/aria/echo_cache)"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --base-url) BASE_URL="$2"; shift 2 ;;
        --ref-image) REF_IMAGE="$2"; shift 2 ;;
        --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

mkdir -p "$OUTPUT_DIR"

echo "=== EchoMimic V2 Prebake ==="
echo "Base URL:    $BASE_URL"
echo "Output dir:  $OUTPUT_DIR"
echo "Reference:   ${REF_IMAGE:-"(default)"}"
echo ""

# 健康检查
echo "[1/3] Checking sidecar health..."
if ! curl -sf "$BASE_URL/health" > /dev/null; then
    echo "ERROR: EchoMimic sidecar not reachable at $BASE_URL"
    echo "Start with: docker compose --profile gpu up echomimic"
    exit 1
fi
echo "  OK"

# 检查 edge-tts
if ! command -v edge-tts &> /dev/null; then
    echo "ERROR: edge-tts not installed. Run: pip install edge-tts"
    exit 1
fi

# 读取参考图
REF_B64=""
if [[ -n "$REF_IMAGE" ]]; then
    if [[ ! -f "$REF_IMAGE" ]]; then
        echo "ERROR: Reference image not found: $REF_IMAGE"
        exit 1
    fi
    REF_B64=$(base64 -w0 "$REF_IMAGE")
fi

echo ""
echo "[2/3] Generating ${#PRESETS[@]} clips..."

COUNT=0
for preset in "${PRESETS[@]}"; do
    IFS='|' read -r text emotion name <<< "$preset"
    COUNT=$((COUNT + 1))

    echo "  [$COUNT/${#PRESETS[@]}] $name ($emotion)..."

    # 生成 TTS 音频
    AUDIO_FILE=$(mktemp /tmp/echo_audio_XXXXXX.mp3)
    edge-tts --voice "$VOICE" --rate="-5%" --text "$text" --write-media "$AUDIO_FILE" 2>/dev/null

    if [[ ! -s "$AUDIO_FILE" ]]; then
        echo "    SKIP: TTS failed for '$text'"
        rm -f "$AUDIO_FILE"
        continue
    fi

    AUDIO_B64=$(base64 -w0 "$AUDIO_FILE")
    rm -f "$AUDIO_FILE"

    # 调用 EchoMimic
    JSON_BODY=$(cat <<EOF
{
    "audio_b64": "$AUDIO_B64",
    "emotion": "$emotion",
    "cache_key": "prebake_$name",
    "ref_image_b64": $(if [[ -n "$REF_B64" ]]; then echo "\"$REF_B64\""; else echo "null"; fi)
}
EOF
)

    RESPONSE=$(curl -sf -X POST "$BASE_URL/generate" \
        -H "Content-Type: application/json" \
        -d "$JSON_BODY" \
        --max-time 120) || {
        echo "    FAIL: sidecar request failed"
        continue
    }

    # 提取 video_b64
    VIDEO_B64=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('video_b64',''))" 2>/dev/null)

    if [[ -z "$VIDEO_B64" ]]; then
        echo "    FAIL: no video in response"
        echo "    $(echo "$RESPONSE" | head -c 200)"
        continue
    fi

    # 写入文件
    OUTPUT_FILE="$OUTPUT_DIR/${name}.mp4"
    echo "$VIDEO_B64" | base64 -d > "$OUTPUT_FILE"
    SIZE=$(stat -c%s "$OUTPUT_FILE" 2>/dev/null || stat -f%z "$OUTPUT_FILE" 2>/dev/null || echo "?")
    echo "    OK: $OUTPUT_FILE ($SIZE bytes)"
done

echo ""
echo "[3/3] Done. ${COUNT} clips processed."
echo "Output directory: $OUTPUT_DIR"
echo ""
echo "To use in frontend:"
echo "  Set ARIA_CLIP_PLAYING_URL=/aria/echo_cache/coaching.mp4"
echo "  Or reference individual clips from the media planner."
