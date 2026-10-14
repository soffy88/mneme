# Mneme 拍照问题目 OCR sidecar：免费 CPU OCR（RapidOCR + ONNXRuntime，中文+数字+英文）。
# 只在 compose 内网暴露 :8100（不映射宿主端口）；无状态、不落盘、不记录图片/文本。
# 不走 apt：opencv 用 headless 版（无需 libgl1）。
FROM python:3.12-slim
ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --index-url ${PIP_INDEX_URL} \
      "rapidocr-onnxruntime==1.4.4" --no-deps \
 && pip install --index-url ${PIP_INDEX_URL} \
      onnxruntime "opencv-python-headless<4.12" "numpy<2.3" pyclipper shapely pyyaml six tqdm pillow \
      fastapi==0.115.12 uvicorn==0.34.2
COPY server.py /srv/server.py
WORKDIR /srv
# 构建期加载一次模型（模型随 wheel 分发），避免首请求冷启动
RUN python -c "from rapidocr_onnxruntime import RapidOCR; RapidOCR()"
EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8100/health',timeout=3)" || exit 1
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8100", "--workers", "1"]
