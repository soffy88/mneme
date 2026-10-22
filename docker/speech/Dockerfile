# mneme-speech：sherpa-onnx CPU 语音服务（ASR SenseVoice + VAD silero + TTS matcha-zh-baker）
# 模型不打进镜像：compose 只读挂载宿主 /data/soffy/models/sherpa → /models
FROM python:3.12-slim
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL} PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir "sherpa-onnx==1.12.*" numpy fastapi "uvicorn[standard]" \
    && useradd -m -u 10001 speech
WORKDIR /srv
COPY server.py /srv/server.py
USER speech
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=4)"
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
