"""``actingweb.mcp.is_token_cached``: a read-only view of the MCP token
cache for code in front of ``/mcp`` (4.0.0rc3)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest

import actingweb.handlers.mcp as mcp_module
from actingweb.mcp import is_token_cached
from tests.mcp_helpers import make_mcp_config, make_mcp_handler

TOKEN = "aw_test_token_cache_query"


@pytest.fixture
def cache() -> Iterator[dict[str, dict[str, Any]]]:
    saved = dict(mcp_module._token_cache)
    mcp_module._token_cache.clear()
    try:
        yield mcp_module._token_cache
    finally:
        mcp_module._token_cache.clear()
        mcp_module._token_cache.update(saved)


def _entry(config: Any, age: float = 0.0) -> dict[str, Any]:
    return {
        "actor_id": "actor-1",
        "client_id": "client-1",
        "token_data": {},
        "cached_at": time.time() - age,
        "config": config,
    }


def test_a_fresh_entry_is_cached_and_reads_no_store(
    cache: dict[str, dict[str, Any]],
) -> None:
    """AC-19: no store is touched, no entry and no counter changes."""
    config = make_mcp_config()
    cache[TOKEN] = _entry(config)
    before = dict(cache[TOKEN])
    stats = dict(mcp_module._cache_stats)

    def no_store(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("the query read a store")

    with (
        patch("actingweb.db.get_attribute", no_store),
        patch("actingweb.db.get_actor", no_store),
    ):
        assert is_token_cached(TOKEN, config) is True
    assert cache[TOKEN] == before
    assert mcp_module._cache_stats == stats


@pytest.mark.parametrize("case", ["unknown", "expired", "other_config", "no_cached_at"])
def test_a_miss(cache: dict[str, dict[str, Any]], case: str) -> None:
    """AC-20: false is "not cached in this process", never "invalid"."""
    config = make_mcp_config()
    if case == "expired":
        cache[TOKEN] = _entry(config, age=mcp_module._cache_ttl + 1)
    elif case == "other_config":
        cache[TOKEN] = _entry(make_mcp_config())
    elif case == "no_cached_at":
        cache[TOKEN] = {"actor_id": "a1", "config": config}
    assert is_token_cached(TOKEN, config) is False
    assert is_token_cached("", config) is False
    # A miss evicts nothing: the handler's own sweep does that.
    assert (TOKEN in cache) is (case != "unknown")


def test_an_evicted_token_is_not_cached(cache: dict[str, dict[str, Any]]) -> None:
    config = make_mcp_config()
    cache[TOKEN] = _entry(config)
    assert is_token_cached(TOKEN, config) is True
    make_mcp_handler(cfg=config).clear_token_from_cache(TOKEN)
    assert is_token_cached(TOKEN, config) is False


@pytest.mark.parametrize("case", ["fresh", "expired", "other_config", "no_cached_at"])
def test_the_handler_and_the_query_agree(
    cache: dict[str, dict[str, Any]], case: str
) -> None:
    """One predicate serves both, so they cannot drift."""
    config = make_mcp_config()
    entry = {
        "fresh": _entry(config),
        "expired": _entry(config, age=mcp_module._cache_ttl + 1),
        "other_config": _entry(make_mcp_config()),
        "no_cached_at": {"actor_id": "a1", "config": config},
    }[case]
    assert mcp_module._token_cache_entry_is_fresh(entry, config, time.time()) is (
        case == "fresh"
    )
    cache[TOKEN] = entry
    assert is_token_cached(TOKEN, config) is (case == "fresh")
