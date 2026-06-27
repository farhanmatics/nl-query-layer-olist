"""Layer 1 cache: LLM translation (question -> tool call).

This caches ONLY the model's translation step (question text -> {tool, args}).
It deliberately does NOT cache query results, so a cache hit still re-executes
the parameterized query against Postgres — the live number is never stale.
The only thing skipped is the expensive LLM inference.

Why this is safe (per the project's faithfulness rule):
- the cached value contains no data, just the chosen function + arguments;
- the key hashes the full system prompt, so any change to the tool library,
  few-shot examples, or (future) per-role prompt automatically invalidates it;
- only successful tool calls are cached — transient errors (timeouts, invalid
  JSON, unreachable model) are never stored.
"""
import hashlib
import threading
import time
from collections import OrderedDict
from typing import Any, Optional

from config import settings


class TTLCache:
    """A tiny thread-safe cache with per-entry TTL and LRU eviction."""

    def __init__(self, max_entries: int = 1024, default_ttl: int = 86400):
        self._store: "OrderedDict[str, tuple]" = OrderedDict()
        self._max = max_entries
        self._ttl = default_ttl
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        now = time.monotonic()
        with self._lock:
            item = self._store.get(key)
            if item is None:
                self.misses += 1
                return None
            expires_at, value = item
            if expires_at < now:
                del self._store[key]
                self.misses += 1
                return None
            self._store.move_to_end(key)
            self.hits += 1
            return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        ttl = self._ttl if ttl is None else ttl
        expires_at = time.monotonic() + ttl
        with self._lock:
            self._store[key] = (expires_at, value)
            self._store.move_to_end(key)
            while len(self._store) > self._max:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self.hits = 0
            self.misses = 0

    def stats(self) -> dict:
        with self._lock:
            total = self.hits + self.misses
            return {
                "entries": len(self._store),
                "max_entries": self._max,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 3) if total else 0.0,
                "ttl_seconds": self._ttl,
                "enabled": settings.llm_cache_enabled,
            }


translation_cache = TTLCache(
    max_entries=settings.llm_cache_max_entries,
    default_ttl=settings.llm_cache_ttl_seconds,
)


def _normalize_question(question: str) -> str:
    """Collapse whitespace, lowercase, and drop trailing punctuation so trivial
    phrasing differences ("Deliveries today?" vs "deliveries today") share a key.
    Only used for the cache key — the original question is still sent to the LLM
    on a miss."""
    return " ".join(question.strip().lower().split()).rstrip("?.! ")


def translation_key(question: str, system_prompt: str) -> str:
    """Stable cache key over (system prompt, normalized question).

    Hashing the system prompt ties each cached translation to the exact tool
    library / few-shots / role-scope that produced it, so a prompt change is a
    free, automatic invalidation.
    """
    h = hashlib.sha256()
    h.update(system_prompt.encode("utf-8"))
    h.update(b"\x00")
    h.update(_normalize_question(question).encode("utf-8"))
    return h.hexdigest()
