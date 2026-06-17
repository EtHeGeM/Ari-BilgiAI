import re
import hashlib
from dataclasses import dataclass
from typing import Any

import numpy as np


_WORD_RE = re.compile(r"[A-Za-z0-9_ğüşöçıİĞÜŞÖÇ]+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    return [t.lower() for t in _WORD_RE.findall(text)]


def _hash_token(token: str) -> tuple[int, int]:
    """
    Deterministic feature hashing:
    - returns (bucket_index, sign)
    """
    h = hashlib.md5(token.encode("utf-8")).digest()
    idx = int.from_bytes(h[:4], "little", signed=False)
    sign = -1 if (h[4] & 1) else 1
    return idx, sign


def embed_text(text: str, *, dim: int = 1024) -> np.ndarray:
    vec = np.zeros((dim,), dtype=np.float32)
    for tok in _tokenize(text):
        idx, sign = _hash_token(tok)
        vec[idx % dim] += float(sign)
    n = float(np.linalg.norm(vec))
    if n > 0:
        vec /= n
    return vec


@dataclass
class SearchResult:
    score: float
    doc_id: str
    doc: dict[str, Any]


class EphemeralVectorDB:
    """
    In-memory, ephemeral "vector DB":
    - no persistence
    - simple hashed bag-of-words embeddings
    - cosine similarity via normalized dot products
    """

    def __init__(self, *, dim: int = 1024):
        self.dim = int(dim)
        self._matrix: np.ndarray | None = None  # shape: (n, dim)
        self._docs: list[dict[str, Any]] = []
        self._ids: list[str] = []

    def fit(self, docs: list[dict[str, Any]], *, text_key: str = "review") -> None:
        self._docs = docs or []
        self._ids = []
        if not self._docs:
            self._matrix = np.zeros((0, self.dim), dtype=np.float32)
            return

        embs = np.zeros((len(self._docs), self.dim), dtype=np.float32)
        for i, d in enumerate(self._docs):
            t = d.get(text_key, "")
            if not isinstance(t, str):
                t = str(t or "")
            embs[i] = embed_text(t, dim=self.dim)

            # stable-ish id for debugging/dedup
            name = str(d.get("name") or "")
            date = str(d.get("date") or "")
            base = f"{name}|{date}|{t[:120]}"
            self._ids.append(hashlib.sha256(base.encode("utf-8")).hexdigest()[:16])

        self._matrix = embs

    def search(self, query: str, *, top_k: int = 8) -> list[SearchResult]:
        if self._matrix is None:
            raise RuntimeError("Vector DB not fitted. Call fit() first.")
        if not self._docs:
            return []

        q = (query or "").strip()
        if not q:
            return []

        qv = embed_text(q, dim=self.dim)
        scores = self._matrix @ qv  # cosine since both normalized
        k = max(0, min(int(top_k), len(self._docs)))
        if k == 0:
            return []

        # partial sort for top-k
        idxs = np.argpartition(-scores, kth=k - 1)[:k]
        idxs = idxs[np.argsort(-scores[idxs])]

        out: list[SearchResult] = []
        for i in idxs:
            out.append(SearchResult(score=float(scores[i]), doc_id=self._ids[int(i)], doc=self._docs[int(i)]))
        return out

