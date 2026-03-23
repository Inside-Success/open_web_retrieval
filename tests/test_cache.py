"""Tests for disk-based caching."""

from __future__ import annotations

import time

import pytest

from open_web_retrieval.cache import DiskCache


@pytest.fixture
def cache(tmp_path):
    """Fresh disk cache in a temp directory."""
    return DiskCache(tmp_path / "cache", default_ttl_seconds=60)


class TestDiskCache:
    def test_set_and_get(self, cache):
        cache.set("key1", {"data": "value"})
        result = cache.get("key1")
        assert result == {"data": "value"}

    def test_get_missing_returns_none(self, cache):
        assert cache.get("nonexistent") is None

    def test_ttl_expiration(self, cache):
        cache.set("key1", "value", ttl=0)
        time.sleep(0.01)
        assert cache.get("key1") is None

    def test_clear(self, cache):
        cache.set("a", 1)
        cache.set("b", 2)
        count = cache.clear()
        assert count == 2
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_evict_expired(self, cache):
        cache.set("fresh", "value", ttl=3600)
        cache.set("stale", "value", ttl=0)
        time.sleep(0.01)
        evicted = cache.evict_expired()
        assert evicted == 1
        assert cache.get("fresh") == "value"

    def test_overwrite(self, cache):
        cache.set("key", "v1")
        cache.set("key", "v2")
        assert cache.get("key") == "v2"

    def test_complex_values(self, cache):
        value = {"list": [1, 2, 3], "nested": {"a": True}}
        cache.set("complex", value)
        assert cache.get("complex") == value

    def test_deterministic_key_path(self, cache):
        """Same key always maps to same file."""
        path1 = cache._key_path("test")
        path2 = cache._key_path("test")
        assert path1 == path2

    def test_different_keys_different_paths(self, cache):
        path1 = cache._key_path("key_a")
        path2 = cache._key_path("key_b")
        assert path1 != path2
