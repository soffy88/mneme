"""Provider-dispatched text embedding."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from oprim._logging import log as olog
from oprim.errors import EmbeddingError


class TextEmbedder(Protocol):
    def embed(self, texts: Sequence[str], dim: int = 1024) -> list[list[float]]: ...

    @property
    def model_name(self) -> str: ...

    @property
    def native_dim(self) -> int: ...


def _get_provider(name: str) -> TextEmbedder:
    if name == "qwen3_dashscope":
        from oprim.embedding.qwen3_dashscope import Qwen3DashscopeEmbedder

        return Qwen3DashscopeEmbedder()
    elif name == "qwen3_local":
        from oprim.embedding.qwen3_local import Qwen3LocalEmbedder

        return Qwen3LocalEmbedder()
    elif name == "bge_m3":
        from oprim.embedding.bge_m3 import BgeM3Embedder

        return BgeM3Embedder()
    else:
        raise EmbeddingError(f"Unknown embedding provider: {name}")


def embed_text(
    texts: Sequence[str],
    provider: str = "qwen3_dashscope",
    dim: int = 1024,
    batch_size: int = 32,
) -> list[list[float]]:
    """Embed a list of texts using *provider*.

    Args:
        texts: Input strings.
        provider: "qwen3_dashscope" or "bge_m3".
        dim: Output dimension (truncated/padded if native_dim differs).
        batch_size: Number of texts per provider call.

    Returns:
        List of float vectors, one per input text.
    """
    if not texts:
        return []
    embedder = _get_provider(provider)
    results: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = list(texts[i : i + batch_size])
        batch_result = embedder.embed(batch, dim=dim)
        results.extend(batch_result)
    olog.emit("embed_text", provider=provider, count=len(texts), dim=dim)
    return results
