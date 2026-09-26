"""Sentence embeddings: text in, unit-length vectors out.

"minilm" is sentence-transformers/all-MiniLM-L6-v2, a small pretrained model
(384 dimensions) that runs on a laptop CPU. It downloads once (about 90 MB)
and is loaded lazily, once per process.

"hashing" is a deterministic stand-in built from scikit-learn's
HashingVectorizer. It needs no download and captures word overlap only, so the
test suite uses it; it's not meant for real use.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def _minilm():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME, device="cpu")


def _hashing(texts: list[str]) -> np.ndarray:
    from sklearn.feature_extraction.text import HashingVectorizer

    vectors = HashingVectorizer(n_features=384, alternate_sign=False, norm="l2").transform(texts)
    return vectors.toarray().astype(np.float32)


def embed(texts: list[str], kind: str = "minilm") -> np.ndarray:
    """Embed texts as rows of L2-normalized float32 vectors."""
    texts = [text or "" for text in texts]
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    if kind == "hashing":
        return _hashing(texts)
    if kind != "minilm":
        raise ValueError(f"Unknown embedder {kind!r}; use 'minilm' or 'hashing'.")
    return _minilm().encode(texts, batch_size=64, normalize_embeddings=True,
                            show_progress_bar=False, convert_to_numpy=True).astype(np.float32)


def model_label(kind: str) -> str:
    return MODEL_NAME if kind == "minilm" else f"hashing-384"
