"""
LLM response cache — disk-based, hash-keyed.

Uso:
    cache = LLMCache()
    key = cache.make_key(system_prompt, user_message, model, temperature)
    cached = cache.get(key)
    if cached is not None:
        return cached
    response = openai_call(...)
    cache.put(key, response)

Por que existe:
1. Reproducibilidade pro juiz — backtest re-roda sem custo
2. Tuning rapido — re-rodar 30d backtest custa $0 apos primeira vez
3. CI sem custo — testes usam fixtures cached
4. Audit trail — toda decisao LLM fica gravada em disco

Politica de invalidacao: hash inclui prompt + modelo + temperatura. Se mudar
qualquer um, hash muda automaticamente, cache miss → nova chamada → nova entrada.

Cache files: data/llm_cache/<sha256_hash>.json
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "llm_cache"


class LLMCache:
    """Disk-backed cache for LLM responses."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._stats = {"hits": 0, "misses": 0, "writes": 0}

    @staticmethod
    def make_key(system_prompt: str, user_message: str, model: str,
                 temperature: float, schema_signature: str = "") -> str:
        """SHA-256 hash of inputs that affect the LLM output.

        schema_signature: optional string identifying the response schema
        version. If you change schema fields, bump this string to invalidate
        cache without renaming files.
        """
        h = hashlib.sha256()
        h.update(b"v1\n")  # cache format version
        h.update(model.encode("utf-8"))
        h.update(b"\n")
        h.update(f"{temperature:.4f}".encode())
        h.update(b"\n")
        h.update(schema_signature.encode("utf-8"))
        h.update(b"\n---SYSTEM---\n")
        h.update(system_prompt.encode("utf-8"))
        h.update(b"\n---USER---\n")
        h.update(user_message.encode("utf-8"))
        return h.hexdigest()

    def _path(self, key: str) -> Path:
        # Spread across subdirs to avoid huge flat dir
        return self.cache_dir / key[:2] / f"{key}.json"

    def get(self, key: str) -> Optional[dict]:
        """Return cached response or None."""
        p = self._path(key)
        if not p.exists():
            self._stats["misses"] += 1
            return None
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            self._stats["hits"] += 1
            return data
        except Exception:
            self._stats["misses"] += 1
            return None

    def put(self, key: str, response: dict, metadata: Optional[dict] = None):
        """Save response to cache. metadata is opcional, anexada como _meta."""
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(response)
        if metadata:
            payload["_meta"] = metadata
        with open(p, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        self._stats["writes"] += 1

    @property
    def stats(self) -> dict:
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total if total else 0.0
        return {**self._stats, "hit_rate": round(hit_rate, 4), "total_lookups": total}

    def reset_stats(self):
        self._stats = {"hits": 0, "misses": 0, "writes": 0}

    def clear(self):
        """Delete all cached entries. Use with care."""
        if self.cache_dir.exists():
            for p in self.cache_dir.rglob("*.json"):
                p.unlink()

    def size(self) -> int:
        """Number of cached entries."""
        if not self.cache_dir.exists():
            return 0
        return sum(1 for _ in self.cache_dir.rglob("*.json"))
