"""Caché in-memory con TTL para reducir hits a la API de Notion.

Thread-safe. Sin dependencias externas. Eviction LRU al alcanzar max_size
(descarta lo menos usado recientemente, no lo más viejo a secas).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, Optional, Tuple

log = logging.getLogger("tomi.cache")

# TTL más largo y caché más grande: descargan Notion en vez de competir con él.
DEFAULT_TTL = int(os.getenv("TOMI_CACHE_TTL", "300"))
DEFAULT_MAX_SIZE = int(os.getenv("TOMI_CACHE_MAX_SIZE", "2000"))


class TTLCache:
    """Caché con TTL por entrada y eviction LRU."""

    def __init__(self, ttl_seconds: int = DEFAULT_TTL, max_size: int = DEFAULT_MAX_SIZE):
        self._store: "OrderedDict[str, Tuple[Any, float]]" = OrderedDict()
        self._lock = threading.Lock()
        self.ttl = ttl_seconds
        self.max_size = max_size
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                self._misses += 1
                return None
            value, expiry = entry
            if time.time() > expiry:
                self._store.pop(key, None)
                self._misses += 1
                return None
            self._store.move_to_end(key)  # marcar como usado recientemente (LRU)
            self._hits += 1
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            elif len(self._store) >= self.max_size:
                # LRU: descartar el menos usado recientemente (primero de la cola)
                self._store.popitem(last=False)
            self._store[key] = (value, time.time() + self.ttl)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> Dict[str, Any]:
        total = self._hits + self._misses
        return {
            "size": len(self._store),
            "max_size": self.max_size,
            "ttl_seconds": self.ttl,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 3) if total else 0.0,
        }


# Caché global para queries Notion
notion_cache = TTLCache()


def hash_key(*parts: Any) -> str:
    """Genera una clave determinística para tuplas (db_id, filter), (page_id, props), etc."""
    payload = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def cached(prefix: str, key_fn: Callable[..., str]):
    """Decorator que cachea el resultado de una función usando key_fn(*args, **kwargs)."""
    def wrap(fn: Callable):
        def inner(*args, **kwargs):
            key = f"{prefix}:{key_fn(*args, **kwargs)}"
            hit = notion_cache.get(key)
            if hit is not None:
                return hit
            result = fn(*args, **kwargs)
            if result is not None:
                notion_cache.set(key, result)
            return result
        return inner
    return wrap
