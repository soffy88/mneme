#!/bin/bash
# EchoMimic V2 sidecar entrypoint
set -e

echo "[echomimic] device=$ECHO_DEVICE half_body=$ECHO_HALF_BODY ref=$ECHO_REF_IMAGE"

# 预下载模型（首次启动时）
if [ ! -d "/app/echomimic/pretrained_weights" ]; then
    echo "[echomimic] Downloading pretrained weights..."
    cd /app/echomimic
    python -c "
from huggingface_hub import snapshot_download
snapshot_download('Badmao/EchoMimicV2', local_dir='pretrained_weights')
" || echo "[echomimic] WARN: model download failed, will retry on first request"
fi

exec "$@"
