# mneme-embedder：CPU-only 文本 embedding 侧车（见 app.py 顶部说明）。模型权重不进镜像，
# 由 compose 以只读卷挂入。torch 取 CPU wheel，镜像里没有任何 CUDA 库。
FROM python:3.12-slim
ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 CUDA_VISIBLE_DEVICES="" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.5.1 \
 && pip install "transformers==4.46.3" "fastapi==0.115.6" "uvicorn==0.32.1" "numpy<2.3"
WORKDIR /srv
COPY app.py /srv/app.py
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/health').status==200 else 1)"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
