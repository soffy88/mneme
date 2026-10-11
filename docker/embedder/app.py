"""mneme-embedder —— CPU-only 文本 embedding 侧车（OpenAI-compatible /v1/embeddings）。

2026-10-11：RTX 3080 掉卡（Xid 154）后 Ollama qwen3-embedding 不可用，Veya 网关
没有 /embeddings。这个侧车在 CPU 上跑一个 BERT 类 embedding 模型（CLS 池化 + L2
归一化；默认 BAAI/bge-small-zh-v1.5，512 维，也兼容 bge-m3 等同族模型），供 knowledge_hub_search 的 query embedding 与
scripts/knowledge_hub_backfill.py 的 chunk/KU 向量化共用——查询与入库必须同一模型。

刻意保持最小：不进 api 镜像（torch CPU 也有数百 MB），单进程单模型，
推理串行（一把锁）以免多请求把 CPU 线程数翻倍抢占整机。
"""

from __future__ import annotations

import os
import threading
import time
from typing import Union

os.environ["CUDA_VISIBLE_DEVICES"] = ""  # GPU 已坏：绝不碰 CUDA

import torch  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from transformers import AutoModel, AutoTokenizer  # noqa: E402

MODEL_DIR = os.environ.get("EMBED_MODEL_DIR", "/model")
MODEL_NAME = os.environ.get("EMBED_MODEL_NAME", "bge-small-zh-v1.5")
MAX_LEN = int(os.environ.get("EMBED_MAX_LENGTH", "512"))
THREADS = int(os.environ.get("EMBED_THREADS", "4"))
MAX_BATCH = int(os.environ.get("EMBED_MAX_BATCH", "32"))
# 非对称检索模型的指令前缀：bge-*-zh-v1.5 建议短 query 加检索指令、passage 不加；
# bge-m3 两侧都不加。input_type 由调用方给（query / passage，默认 passage）。
QUERY_PREFIX = os.environ.get("EMBED_QUERY_PREFIX", "")
PASSAGE_PREFIX = os.environ.get("EMBED_PASSAGE_PREFIX", "")

torch.set_num_threads(THREADS)
_tok = AutoTokenizer.from_pretrained(MODEL_DIR)
_model = AutoModel.from_pretrained(MODEL_DIR, torch_dtype=torch.float32).eval()
DIM = int(_model.config.hidden_size)
_lock = threading.Lock()

app = FastAPI(title="mneme-embedder")


class EmbReq(BaseModel):
    input: Union[str, list[str]]
    model: str | None = None
    input_type: str = "passage"  # 扩展字段（OpenAI 协议没有）：query | passage


def _encode(texts: list[str]) -> list[list[float]]:
    out: list[list[float] | None] = [None] * len(texts)
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))  # 按长度分批，少 padding
    with _lock, torch.inference_mode():
        for s in range(0, len(order), 8):
            idx = order[s : s + 8]
            enc = _tok(
                [texts[i] for i in idx],
                padding=True,
                truncation=True,
                max_length=MAX_LEN,
                return_tensors="pt",
            )
            cls = _model(**enc).last_hidden_state[:, 0]
            cls = torch.nn.functional.normalize(cls, p=2, dim=-1)
            for j, i in enumerate(idx):
                out[i] = cls[j].tolist()
    return [v for v in out if v is not None]


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "dim": DIM,
        "threads": THREADS,
        "query_prefix": bool(QUERY_PREFIX),
    }


@app.post("/v1/embeddings")
def embeddings(req: EmbReq) -> dict:
    texts = [req.input] if isinstance(req.input, str) else list(req.input)
    if not texts or len(texts) > MAX_BATCH:
        raise HTTPException(400, f"input must have 1..{MAX_BATCH} items")
    prefix = QUERY_PREFIX if req.input_type == "query" else PASSAGE_PREFIX
    texts = [prefix + (t if t.strip() else " ") for t in texts]
    t0 = time.perf_counter()
    vecs = _encode(texts)
    ms = (time.perf_counter() - t0) * 1000
    return {
        "object": "list",
        "model": MODEL_NAME,
        "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vecs)],
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
        "elapsed_ms": round(ms, 1),
    }
