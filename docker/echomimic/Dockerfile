# EchoMimic V2 Sidecar — 音频驱动半身数字人视频生成
# docker/echomimic/Dockerfile
#
# 用法:
#   docker compose build echomimic
#   docker compose up echomimic
#
# 环境变量:
#   ECHO_DEVICE=cuda  (cuda | cpu)
#   ECHO_HALF_BODY=1  (半身模式，默认)
#   ECHO_REF_IMAGE=/app/ref/aria_ref.jpg  (参考图像路径)
#
# 端口: 8080 (FastAPI)
# GPU: 需要 NVIDIA GPU + nvidia-container-toolkit

FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04 AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ECHO_DEVICE=cuda \
    ECHO_HALF_BODY=1 \
    ECHO_REF_IMAGE=/app/ref/aria_ref.jpg

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-pip python3.11-dev \
    git ffmpeg libsm6 libxext6 libgl1 \
    curl wget \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.11 /usr/bin/python

WORKDIR /app

# EchoMimic V2 + 依赖
RUN pip install --no-cache-dir \
    torch==2.1.0 torchvision==0.16.0 --index-url https://download.pytorch.org/whl/cu121 \
    && pip install --no-cache-dir \
    fastapi uvicorn[standard] python-multipart \
    numpy opencv-python-headless pillow \
    diffusers transformers accelerate safetensors \
    librosa soundfile pydub \
    huggingface_hub

# 克隆 EchoMimic V2
RUN git clone --depth 1 https://github.com/Badmao/EchoMimicV2.git /app/echomimic \
    && cd /app/echomimic && pip install --no-cache-dir -r requirements.txt

# 复制侧车代码
COPY server.py /app/server.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# 参考图像目录（挂载卷）
RUN mkdir -p /app/ref /app/output /app/cache

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

EXPOSE 8080

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "/app/server.py"]
