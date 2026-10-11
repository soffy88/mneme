"""text_embedder —— Knowledge Hub 的 embedding 后端选择（CPU 侧车 / 旧 Ollama 路径）。

2026-10-11 背景：RTX 3080 掉卡（Xid 154），Ollama qwen3-embedding（4096 维）整体
不可用；生产文本 LLM 走 Veya 网关，而网关没有 /embeddings。语义检索因此一直落在
词面兜底。这里接一个 CPU-only 的 embedding 侧车（docker/embedder，compose 服务名
`embedder`，OpenAI-compatible /v1/embeddings，L2 归一化）。默认模型
BAAI/bge-small-zh-v1.5（512 维）；选型与阈值标定见 docs/knowledge_hub_cpu_embedding.md。

后端由环境变量决定（每次调用时读，便于测试 monkeypatch）：

  MNEME_EMBED_BACKEND = "cpu"     → 侧车（生产 compose 设置此值）
                      = "legacy"  → 旧路径 oprim.embed_chunks（Ollama/OpenAI），
                                    向量在 textbook_chunks.embedding（默认，测试与
                                    未配置环境的既有行为不变）
                      = "off"     → 不做语义检索（直接词面兜底）
  MNEME_EMBED_URL     = 侧车 base url（默认 http://embedder:8080/v1）
  MNEME_EMBED_MODEL   = 侧车模型名（默认 bge-small-zh-v1.5；同时是新向量表 model 列的值）

CPU 后端的 chunk 向量存在 `textbook_chunk_embeddings`（chunk_id, model 主键），
不覆盖旧的 4096 维 `textbook_chunks.embedding`——查询与入库必须同一模型，
model 列就是这个约束的落点。

红线：本模块只做向量化，不 import 任何门控/判分模块。
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BACKENDS = ("cpu", "legacy", "off")
DEFAULT_CPU_URL = "http://embedder:8080/v1"
DEFAULT_CPU_MODEL = "bge-small-zh-v1.5"


def embed_backend() -> str:
    b = (os.environ.get("MNEME_EMBED_BACKEND") or "legacy").strip().lower()
    if b not in BACKENDS:
        logger.warning("MNEME_EMBED_BACKEND=%r 未知，按 legacy 处理", b)
        return "legacy"
    return b


def cpu_embed_url() -> str:
    return (os.environ.get("MNEME_EMBED_URL") or DEFAULT_CPU_URL).rstrip("/")


def cpu_embed_model() -> str:
    return os.environ.get("MNEME_EMBED_MODEL") or DEFAULT_CPU_MODEL


def match_method(model: str) -> str:
    """ku_chunk_matches.method 的取值（varchar(50)），与旧 A3 命名一致。"""
    return f"embedding_cosine_{model}"[:50]


async def embed_texts_cpu(
    texts: list[str], *, timeout: float = 30.0, input_type: str = "passage"
) -> Optional[list[list[float]]]:
    """批量调用 CPU 侧车。失败（连不上/非 200/形状不对）返回 None，不抛异常。

    input_type="query" 让侧车加该模型的检索指令前缀（bge-*-zh-v1.5 的短 query
    用法）；chunk 正文用默认 "passage"。KU 名称/描述作为"查询"一侧，也用 query。
    """
    if not texts:
        return []
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{cpu_embed_url()}/embeddings",
                json={"input": texts, "model": cpu_embed_model(), "input_type": input_type},
            )
        if resp.status_code != 200:
            logger.warning("embedder HTTP %s: %s", resp.status_code, resp.text[:200])
            return None
        data = sorted(resp.json().get("data") or [], key=lambda d: d.get("index", 0))
        vecs = [d.get("embedding") for d in data]
        if len(vecs) != len(texts) or not all(vecs):
            logger.warning("embedder 返回条数/形状不符")
            return None
        return vecs
    except Exception as exc:  # 侧车宕机/网络错误 → 调用方走兜底
        logger.warning("embedder 调用失败: %s", exc)
        return None


async def embed_query(text: str, *, timeout: float = 10.0) -> tuple[Optional[list[float]], Optional[str]]:
    """查询侧 embedding：返回 (向量, 模型名)。

    模型名为 None 表示旧路径（向量在 textbook_chunks.embedding，按维度匹配）；
    非 None 表示 CPU 侧车（向量在 textbook_chunk_embeddings，按 model 匹配）。
    """
    backend = embed_backend()
    if backend == "off":
        return None, None
    if backend == "cpu":
        vecs = await embed_texts_cpu([text], timeout=timeout, input_type="query")
        return (vecs[0] if vecs else None), cpu_embed_model()
    from oprim.embed_chunks import embed_text

    return await embed_text(text), None
