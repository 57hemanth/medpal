"""Small deterministic in-boundary embedding adapter.

This is not a clinical semantic model; it is a local adapter with the production shape and 1,024
dimensions so retrieval, storage, and privacy boundaries can be tested before a model is swapped in.
"""

import hashlib
import math
import re

DIMENSIONS = 1024
_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9]+")


def embed_text(text: str) -> list[float]:
    vector = [0.0] * DIMENSIONS
    for word in _WORD_RE.findall(text.lower()):
        digest = hashlib.blake2b(word.encode(), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "big") % DIMENSIONS
        sign = 1.0 if digest[4] % 2 else -1.0
        vector[idx] += sign
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def pgvector_literal(vector: list[float]) -> str:
    if len(vector) != DIMENSIONS:
        raise ValueError("embedding must be 1024-dimensional")
    return "[" + ",".join(f"{v:.8f}" for v in vector) + "]"
