"""
This file is refactored from packages/core_ts/src/utils/LruCache.ts.

Python's standard library provides a robust LRU Cache implementation
via the `functools.lru_cache` decorator. We will use that directly
instead of re-implementing the class.

This file can be used to export `lru_cache` for consistency or for any
custom cache implementations in the future.
"""

from functools import lru_cache

__all__ = ["lru_cache"]
