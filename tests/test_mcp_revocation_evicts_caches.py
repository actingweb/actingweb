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


class TestEveryWiredCallSiteActuallyFires:
    """The wiring, not the machinery.

    Raised in review on #130: the eviction helpers were well covered, but
    nothing asserted that the one-line call added to each revocation path is
    still there. A regression that silently dropped one would have been
    invisible — which is precisely how this class of bug got in originally,
    since ``clear_token_from_cache()`` had exactly one caller for months
    without anyone noticing.
    """

    def test_trust_delete_evicts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import actingweb.mcp.invalidation as invalidation
        import actingweb.trust as trust_module

        seen: list[str] = []
        monkeypatch.setattr(
            invalidation, "evict_caches_for_actor", lambda a: seen.append(a) or 0
        )

        handle = type("H", (), {"delete": lambda self: True, "get": lambda self: {}})()
        t = trust_module.Trust.__new__(trust_module.Trust)
        t.handle = handle  # type: ignore[assignment]
        t.actor_id = ACTOR
        t.trust = {"peerid": "peer1"}
        t.config = None

        assert t.delete() is True
        assert seen == [ACTOR]

    def test_permission_store_evicts_on_write(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import actingweb.mcp.invalidation as invalidation
        import actingweb.trust_permissions as tp

        seen: list[str] = []
        monkeypatch.setattr(
            invalidation, "evict_caches_for_actor", lambda a: seen.append(a) or 0
        )

        store = tp.TrustPermissionStore.__new__(tp.TrustPermissionStore)
        store._cache = {}
        store.config = None  # type: ignore[assignment]
        monkeypatch.setattr(
            store,
            "_get_permissions_bucket",
            lambda actor_id: type("B", (), {"set_attr": lambda self, **kw: True})(),
        )

        permissions = tp.TrustPermissions(
            actor_id=ACTOR, peer_id="peer1", trust_type="mcp_client"
        )
        assert store._store_permissions_internal(permissions) is True
        assert seen == [ACTOR]

    def test_permission_store_evicts_on_delete(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import actingweb.mcp.invalidation as invalidation
        import actingweb.trust_permissions as tp

        seen: list[str] = []
        monkeypatch.setattr(
            invalidation, "evict_caches_for_actor", lambda a: seen.append(a) or 0
        )

        store = tp.TrustPermissionStore.__new__(tp.TrustPermissionStore)
        store._cache = {}
        store.config = None  # type: ignore[assignment]
        monkeypatch.setattr(
            store,
            "_get_permissions_bucket",
            lambda actor_id: type("B", (), {"delete_attr": lambda self, **kw: True})(),
        )

        assert store.delete_permissions(ACTOR, "peer1") is True
        assert seen == [ACTOR]

    def test_spa_token_chain_revocation_evicts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The production theft response, and the one the first pass missed.

        `revoke_all_tokens()` was wired first and has zero callers; refresh-token
        reuse actually routes through `revoke_token_chain()`.
        """
        import actingweb.mcp.invalidation as invalidation
        import actingweb.oauth_session as oauth_session

        seen: list[str] = []
        monkeypatch.setattr(
            invalidation, "evict_caches_for_actor", lambda a: seen.append(a) or 0
        )
        monkeypatch.setattr(
            oauth_session,
            "get_attribute",
            lambda config: type(
                "D", (), {"delete_by_chain": lambda self, *a, **kw: 2}
            )(),
            raising=False,
        )
        monkeypatch.setattr(
            "actingweb.db.get_attribute",
            lambda config: type(
                "D", (), {"delete_by_chain": lambda self, *a, **kw: 2}
            )(),
        )

        mgr = oauth_session.OAuth2SessionManager.__new__(
            oauth_session.OAuth2SessionManager
        )
        mgr.config = None  # type: ignore[assignment]

        assert mgr.revoke_token_chain(ACTOR, "chain-abc") == 2
        assert seen == [ACTOR]

    def test_spa_access_token_revocation_evicts_the_owning_actor(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`/oauth/revoke` routes here, and it was missed on the first pass."""
        import actingweb.mcp.invalidation as invalidation
        import actingweb.oauth_session as oauth_session

        seen: list[str] = []
        monkeypatch.setattr(
            invalidation, "evict_caches_for_actor", lambda a: seen.append(a) or 0
        )

        class FakeBucket:
            def get_attr(self, name: str) -> dict:  # noqa: ARG002
                return {"data": {"actor_id": ACTOR}}

            def delete_attr(self, name: str) -> bool:  # noqa: ARG002
                return True

        monkeypatch.setattr("actingweb.attribute.Attributes", lambda **kw: FakeBucket())

        mgr = oauth_session.OAuth2SessionManager.__new__(
            oauth_session.OAuth2SessionManager
        )
        mgr.config = None  # type: ignore[assignment]

        assert mgr.revoke_access_token("spa_token") is True
        assert seen == [ACTOR]


class TestCacheFillCannotOutraceEviction:
    """The P1 Codex raised: eviction is useless if an in-flight read refills.

    A request reads a token from storage, a revocation deletes the row *and*
    evicts, and then the request writes what it read back into the cache. The
    credential is live again for a full TTL and the eviction reported success.
    """

    def test_a_fill_is_refused_when_an_eviction_landed_mid_read(self) -> None:
        generation = mcp_module._current_cache_generation()
        mcp_module.evict_mcp_caches_for_actor(ACTOR)
        assert mcp_module._cache_fill_still_valid(generation) is False

    def test_an_undisturbed_fill_is_allowed(self) -> None:
        generation = mcp_module._current_cache_generation()
        assert mcp_module._cache_fill_still_valid(generation) is True

    def test_the_generation_moves_even_when_nothing_was_cached(self) -> None:
        """The entry being evicted may not exist *yet* — that is the race."""
        before = mcp_module._current_cache_generation()
        mcp_module.evict_mcp_caches_for_actor("an-actor-with-no-cache-entries")
        assert mcp_module._current_cache_generation() != before

    def test_token_keyed_eviction_also_moves_the_generation(self) -> None:
        before = mcp_module._current_cache_generation()
        mcp_module.MCPHandler.clear_token_from_cache("a-token-never-cached")
        assert mcp_module._current_cache_generation() != before
