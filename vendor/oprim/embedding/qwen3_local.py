"""Local Qwen3-Embedding via Ollama HTTP API."""
from __future__ import annotations

import time
from collections.abc import Sequence

import httpx

from oprim._config import cfg
from oprim._logging import log as olog
from oprim.errors import EmbeddingError

_MODEL = "qwen3-embedding:0.6b"
_DEFAULT_BASE_URL = "http://localhost:11434"


class Qwen3LocalEmbedder:
    """Embed texts via local Ollama (qwen3-embedding:0.6b)."""

    def __init__(self) -> None:
        self._base_url = str(
            cfg.get("OLLAMA_BASE_URL", _DEFAULT_BASE_URL)
        ).rstrip("/")

    @property
    def model_name(self) -> str:
        return _MODEL

    @property
    def native_dim(self) -> int:
        return 1024

    def embed(self, texts: Sequence[str], dim: int = 1024) -> list[list[float]]:
        results: list[list[float]] = []
        for text in texts:
            vec = self._call_with_retry(text)
            results.append(vec[:dim])
        return results

    def _call_with_retry(self, text: str) -> list[float]:
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                resp = httpx.post(
                    f"{self._base_url}/api/embeddings",
                    json={"model": _MODEL, "prompt": text},
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()
                embedding = data.get("embedding")
                if not embedding:
                    raise EmbeddingError(
                        f"Ollama returned empty embedding: {data}"
                    )
                return embedding
            except EmbeddingError:
                raise
            except Exception as e:
                last_err = e
                if attempt < 2:
                    wait = 2**attempt
                    olog.warning(
                        "qwen3_local embed retry",
                        attempt=attempt,
                        error=str(e),
                        wait_s=wait,
                    )
                    time.sleep(wait)
        raise EmbeddingError(
            f"Ollama embedding failed after 3 retries: {last_err}"
        ) from last_err
