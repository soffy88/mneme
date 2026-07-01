"""BGE-M3 local embedder (FlagEmbedding or sentence-transformers)."""
from __future__ import annotations

from collections.abc import Sequence

from oprim._logging import log as olog
from oprim.errors import EmbeddingError


class BgeM3Embedder:
    """Embed texts using BAAI/bge-m3.

    Tries FlagEmbedding first, then sentence-transformers as fallback.
    If neither is installed, embed() raises EmbeddingError.
    """

    _model: object
    _use_st: bool

    def __init__(self) -> None:
        self._model = None  # type: ignore[assignment]
        self._use_st = False
        try:
            from FlagEmbedding import BGEM3FlagModel  # type: ignore[import]

            self._model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
        except ImportError:
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore[import]

                self._model = SentenceTransformer("BAAI/bge-m3")
                self._use_st = True
            except ImportError:
                olog.warning(
                    "bge-m3: neither FlagEmbedding nor sentence-transformers installed"
                )

    @property
    def model_name(self) -> str:
        return "BAAI/bge-m3"

    @property
    def native_dim(self) -> int:
        return 1024

    def embed(self, texts: Sequence[str], dim: int = 1024) -> list[list[float]]:
        if self._model is None:
            raise EmbeddingError(
                "bge-m3 model not available: install FlagEmbedding or sentence-transformers"
            )
        try:
            if self._use_st:
                vecs = self._model.encode(  # type: ignore[union-attr]
                    list(texts), normalize_embeddings=True
                )
                return [v[:dim].tolist() for v in vecs]
            else:
                result = self._model.encode(  # type: ignore[union-attr]
                    list(texts), batch_size=12, max_length=8192
                )
                return [v[:dim].tolist() for v in result["dense_vecs"]]
        except Exception as e:
            raise EmbeddingError(f"bge-m3 embedding failed: {e}") from e
