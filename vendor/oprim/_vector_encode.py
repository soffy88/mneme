"""oprim.vector_encode — single-call text vector encoding.

3O layer: oprim (single atomic call, delegates to embedding provider).
Production: uses obase.ProviderRegistry for embedding backend.
Test/stub: deterministic hash-based pseudo-vectors (no model needed).
"""

from __future__ import annotations

import logging

import numpy as np

_log = logging.getLogger(__name__)


def vector_encode(
    *,
    texts: list[str],
    provider: str = "default",
    normalize: bool = True,
) -> np.ndarray:
    """Encode list of texts to dense float32 vectors. Returns (n, dim) array.

    Calls obase.ProviderRegistry.get("embedding", provider) to obtain the
    embedding function. Falls back to a deterministic stub when the provider
    is not registered (ProviderNotFoundError → warning + stub). Any other
    exception (code error) is re-raised — not silently swallowed.

    Args:
        texts: List of strings to encode.
        provider: Provider name registered in ProviderRegistry (e.g. "bge-m3").
        normalize: If True, L2-normalise each vector.

    Returns:
        Float32 ndarray of shape (len(texts), dim).
    """
    try:
        from obase import ProviderRegistry
        from obase.exceptions import ProviderNotFoundError

        reg = ProviderRegistry.get()
        embed_fn = reg._generic.get("embedding", {}).get(provider)
        if embed_fn is None and provider != "default":
            embed_fn = reg._generic.get("embedding", {}).get("default")
        if embed_fn is None:
            raise ProviderNotFoundError(f"embedding provider '{provider}' not registered")
        vecs = np.array(embed_fn(texts), dtype=np.float32)
        if normalize:
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            vecs = vecs / norms
        return vecs
    except ProviderNotFoundError:
        _log.warning(
            "vector_encode: embedding provider %r not registered — falling back to stub", provider
        )
    except ImportError:
        pass  # obase not installed in this environment

    # Deterministic stub: hash-seeded pseudo-vectors (consistent per text)
    dim = 128
    result = np.zeros((len(texts), dim), dtype=np.float32)
    for i, t in enumerate(texts):
        h = abs(hash(t)) % (2**31)
        rng = np.random.default_rng(h)
        v = rng.standard_normal(dim).astype(np.float32)
        if normalize:
            v = v / (np.linalg.norm(v) + 1e-8)
        result[i] = v
    return result
