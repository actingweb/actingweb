"""Revocation must evict the MCP caches, not wait out their TTL.

``MCPHandler`` caches validated tokens, actor wrappers and resolved trust
relationships in module globals on a five-minute TTL. Until this landed,
``clear_token_from_cache()`` had exactly **one** caller — the logout handler.
Token revocation, revoke-all, trust deletion and permission downgrade all
missed it, so a revoked credential or a narrowed permission kept working from
any warm process for up to the TTL.

That is a staleness window, not the cross-client authorization bypass fixed in
#117 — a revoked client only ever gets its *own* prior permissions back, never
someone else's. It is still wrong, and the eviction is wiring rather than
design because the tuple-keyed ``_trust_cache`` already supported it.

**Single process only.** Every cache here is a module global, so eviction
clears the process that served the revocation. Other workers keep their own
entries until TTL — §2 of
``thoughts/todo/mcp-cache-lifecycle-and-revocation.md``, out of scope.
"""

import pytest

from actingweb.handlers import mcp as mcp_module
from actingweb.mcp.invalidation import evict_caches_for_actor, evict_caches_for_token

ACTOR = "actor-under-test"
OTHER_ACTOR = "an-unrelated-actor"


@pytest.fixture(autouse=True)
def _clean_caches() -> None:
    mcp_module._token_cache.clear()
    mcp_module._actor_cache.clear()
    mcp_module._trust_cache.clear()


def _seed(actor_id: str = ACTOR, token: str = "aw_token") -> None:
    """Populate all three caches for one actor, the way a live request would."""
    mcp_module._token_cache[token] = {"actor_id": actor_id, "cached_at": 0.0}
    mcp_module._actor_cache[actor_id] = {
        "actor": object(),
        "last_accessed": 0.0,
        "config": None,
    }
    mcp_module._trust_cache[(actor_id, "client-a")] = {"trust": object()}
    mcp_module._trust_cache[(actor_id, "client-b")] = {"trust": object()}


class TestActorWideEviction:
    """Actor-wide is required, not overreach — see the function's docstring."""

    def test_every_cache_is_cleared_for_the_actor(self) -> None:
        _seed()
        evicted = mcp_module.evict_mcp_caches_for_actor(ACTOR)

        assert not mcp_module._token_cache
        assert ACTOR not in mcp_module._actor_cache
        assert not [k for k in mcp_module._trust_cache if k[0] == ACTOR]
        # 1 token + 1 actor wrapper + 2 trust entries
        assert evicted == 4

    def test_other_actors_are_untouched(self) -> None:
        _seed()
        _seed(OTHER_ACTOR, token="aw_other")

        mcp_module.evict_mcp_caches_for_actor(ACTOR)

        assert "aw_other" in mcp_module._token_cache
        assert OTHER_ACTOR in mcp_module._actor_cache
        assert [k for k in mcp_module._trust_cache if k[0] == OTHER_ACTOR]

    def test_evicting_an_uncached_actor_is_a_no_op(self) -> None:
        assert mcp_module.evict_mcp_caches_for_actor("never-seen") == 0

    def test_the_actor_wrapper_goes_too_not_just_the_trust_entry(self) -> None:
        """The reason narrower eviction does not work.

        ``_actor_cache`` holds a live ``ActorInterface`` — and therefore the
        core ``Actor`` and every memo on it, including its trust list — shared
        across requests and across users of the container. Dropping only the
        ``_trust_cache`` tuple would leave that wrapper serving stale trust.
        """
        _seed()
        mcp_module.evict_mcp_caches_for_actor(ACTOR)
        assert ACTOR not in mcp_module._actor_cache


class TestInvalidationShims:
    """The hooks core modules call. They must never raise into a revocation."""

    def test_token_eviction_reports_whether_anything_was_cached(self) -> None:
        _seed(token="aw_live")
        assert evict_caches_for_token("aw_live") is True
        assert evict_caches_for_token("aw_live") is False

    def test_actor_eviction_returns_the_count(self) -> None:
        _seed()
        assert evict_caches_for_actor(ACTOR) == 4

    @pytest.mark.parametrize("value", ["", None])
    def test_empty_identifiers_are_ignored(self, value: str | None) -> None:
        assert evict_caches_for_token(value) is False  # type: ignore[arg-type]
        assert evict_caches_for_actor(value) == 0  # type: ignore[arg-type]

    def test_an_eviction_failure_does_not_propagate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Revocation must never fail because a cache could not be told.

        The credential is already gone from storage by the time these run; a
        raised exception here would turn a successful revocation into a
        failed-looking one.
        """

        def boom(actor_id: str) -> int:
            raise RuntimeError("cache module is on fire")

        monkeypatch.setattr(mcp_module, "evict_mcp_caches_for_actor", boom)
        assert evict_caches_for_actor(ACTOR) == 0


class TestTokenKeyedEviction:
    """``clear_token_from_cache`` resolves the actor and then goes actor-wide."""

    def test_clearing_a_token_also_clears_its_actor_and_trust_entries(self) -> None:
        _seed(token="aw_live")
        assert mcp_module.MCPHandler.clear_token_from_cache("aw_live") is True
        assert ACTOR not in mcp_module._actor_cache
        assert not [k for k in mcp_module._trust_cache if k[0] == ACTOR]

    def test_clearing_an_unknown_token_reports_false(self) -> None:
        assert mcp_module.MCPHandler.clear_token_from_cache("aw_nope") is False
