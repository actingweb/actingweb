"""The MCP path builds its actor per request (3.16).

``thoughts/plans/2026-11-06-subs-list-cache-lifetime.md``, Phase 1. These
tests drive ``authenticate_and_get_actor_cached`` against real storage (the
backend ``DATABASE_BACKEND`` selects): a real actor, the OAuth2 server
patched where the full path validates a token, and ``_token_cache`` seeded
with every key the cached-token branch reads.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from typing import Any
from unittest import mock

import pytest

from actingweb.actor import Actor
from actingweb.config import Config
from actingweb.db import get_actor
from actingweb.db.exceptions import DbError
from actingweb.handlers import mcp as mcp_mod
from actingweb.handlers.async_mcp import AsyncMCPHandler
from actingweb.runtime_context import RuntimeContext
from tests._adoption_helpers import aid, create_core_actor, istore, uuid_email
from tests._read_counters import backend_of, count_dynamodb_operations, count_reads
from tests.mcp_helpers import make_mcp_handler, make_mcp_webobj

CLIENT = "client-1"
SERVER = "actingweb.oauth2_server.oauth2_server.get_actingweb_oauth2_server"


def _config() -> Config:
    """A backend-following config (``make_config`` pins DynamoDB)."""
    cfg = Config(unique_creator=False)
    cfg.fqdn = "test.example.com"
    cfg.proto = "https://"
    cfg.aw_type = "urn:actingweb:test:mcp"
    cfg.devtest = True
    cfg.mcp = True
    return cfg


@pytest.fixture(autouse=True)
def _clean_caches() -> Iterator[None]:
    mcp_mod._token_cache.clear()
    mcp_mod._trust_cache.clear()
    mcp_mod._next_cleanup_at = time.time() + 3600
    yield
    mcp_mod._token_cache.clear()
    mcp_mod._trust_cache.clear()
    mcp_mod._next_cleanup_at = 0.0


@pytest.fixture
def cfg() -> Config:
    return _config()


@pytest.fixture
def actor(cfg: Config) -> Iterator[Actor]:
    a = create_core_actor(cfg, uuid_email(), auth_method="google_oauth2")
    yield a
    if Actor(a.id, cfg).id:
        Actor(a.id, cfg).delete()


def _seed_token(cfg: Any, token: str, actor_id: str, client_id: str = CLIENT) -> None:
    mcp_mod._token_cache[token] = {
        "actor_id": actor_id,
        "client_id": client_id,
        "token_data": {"scope": "mcp"},
        "cached_at": time.time(),
        "config": cfg,
    }


def _seed_trust(
    cfg: Any, actor_id: str, trust: Any = None, client_id: str = CLIENT
) -> None:
    mcp_mod._trust_cache[(actor_id, client_id)] = {
        "trust": trust,
        "cached_at": time.time(),
        "config": cfg,
    }


def _token() -> str:
    return f"aw_{uuid.uuid4().hex}"


def _auth(cfg: Any, token: str, handler_cls: Any = mcp_mod.MCPHandler) -> Any:
    handler = handler_cls(
        make_mcp_webobj({"Authorization": f"Bearer {token}"}), cfg, hooks=None
    )
    return handler.authenticate_and_get_actor_cached()


class _Server:
    """The token store: ``answer`` is what ``validate_mcp_token`` returns."""

    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.calls = 0

    def validate_mcp_token(self, token: str) -> Any:
        self.calls += 1
        return self.answer


class TestWarmRequests:
    def test_two_warm_requests_get_two_actors(self, cfg: Config, actor: Actor) -> None:
        token = _token()
        _seed_token(cfg, token, aid(actor))
        _seed_trust(cfg, aid(actor))

        first = _auth(cfg, token)
        second = _auth(cfg, token)

        assert first is not None and second is not None
        assert first is not second
        assert first.core_actor is not second.core_actor
        assert first.id == second.id == aid(actor)

    @pytest.mark.parametrize("flag", [True, False])
    def test_a_warm_request_reads_the_actor_row_once_and_nothing_else(
        self,
        cfg: Config,
        actor: Actor,
        flag: bool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg.force_email_prop_as_creator = flag
        # A vouched email that differs: with the check on, a load would read
        # _internal and rename the creator.
        istore(actor).email = uuid_email()
        token = _token()
        _seed_token(cfg, token, aid(actor))
        _seed_trust(cfg, aid(actor))

        ops = (
            count_dynamodb_operations(monkeypatch)
            if backend_of(cfg) == "dynamodb"
            else None
        )
        with count_reads(cfg) as counts:
            iface = _auth(cfg, token)

        assert iface is not None
        assert counts["actor_get"] == 1
        assert counts["subscription_list_fetch"] == 0
        if ops is not None:
            assert dict(ops) == {"GetItem": 1}
        else:
            assert counts["connection"] == 1
        assert iface.core_actor.creator == actor.creator

    def test_values_written_elsewhere_are_read_fresh(
        self, cfg: Config, actor: Actor
    ) -> None:
        token = _token()
        _seed_token(cfg, token, aid(actor))
        _seed_trust(cfg, aid(actor))

        first = _auth(cfg, token)
        assert first.core_actor.property.colour is None
        assert first.core_actor.store.note is None

        other = Actor(aid(actor), cfg)
        assert other.property is not None
        other.property.colour = "red"
        istore(other).note = "kept"

        second = _auth(cfg, token)
        assert second.core_actor.property.colour == "red"
        assert second.core_actor.store.note == "kept"
        # The first request's actor kept what it read: the reason no actor
        # outlives a request.
        assert first.core_actor.property.colour is None

    def test_a_subscription_created_elsewhere_gets_the_next_diff(
        self, cfg: Config, actor: Actor
    ) -> None:
        sub_one = uuid.uuid4().hex
        actor.create_subscription(
            peerid="peer-one",
            target="properties",
            granularity="high",
            subid=sub_one,
            callback=False,
        )
        token = _token()
        _seed_token(cfg, token, aid(actor))
        _seed_trust(cfg, aid(actor))

        first = _auth(cfg, token)
        first.core_actor.register_diffs(target="properties", blob='{"x": 1}')

        sub_two = uuid.uuid4().hex
        Actor(aid(actor), cfg).create_subscription(
            peerid="peer-two",
            target="properties",
            granularity="high",
            subid=sub_two,
            callback=False,
        )

        second = _auth(cfg, token)
        second.core_actor.register_diffs(target="properties", blob='{"x": 2}')

        def diffs(peer: str, subid: str) -> list[Any]:
            sub = Actor(aid(actor), cfg).get_subscription_obj(peer, subid)
            assert sub
            return sub.get_diffs()

        assert len(diffs("peer-one", sub_one)) == 2
        assert len(diffs("peer-two", sub_two)) == 1


class TestCachedTokenWithoutARow:
    def test_a_deleted_actor_answers_none_and_drops_the_entry(
        self, cfg: Config, actor: Actor
    ) -> None:
        token = _token()
        actor_id = aid(actor)
        _seed_token(cfg, token, actor_id)
        _seed_trust(cfg, actor_id)
        Actor(actor_id, cfg).delete()

        server = _Server(None)  # the actor's token rows went with it
        with mock.patch(SERVER, return_value=server):
            assert _auth(cfg, token) is None

        assert server.calls == 1
        assert token not in mcp_mod._token_cache
        assert Actor(actor_id, cfg).id is None

    def test_no_tombstone_still_never_creates(self, cfg: Config) -> None:
        # The state a failed tombstone write leaves: no row, no tombstone.
        token = _token()
        actor_id = f"mcp{uuid.uuid4().hex}"
        _seed_token(cfg, token, actor_id)

        with (
            mock.patch(SERVER, return_value=_Server(None)),
            mock.patch.object(Actor, "create") as create,
        ):
            assert _auth(cfg, token) is None

        create.assert_not_called()
        assert token not in mcp_mod._token_cache
        assert Actor(actor_id, cfg).id is None

    def test_a_token_that_still_validates_bridges_once_and_is_cached(
        self, cfg: Config
    ) -> None:
        token = _token()
        actor_id = f"mcp{uuid.uuid4().hex}"
        _seed_token(cfg, token, actor_id)
        server = _Server((actor_id, CLIENT, {"email": uuid_email()}))
        real_create = Actor.create
        creates: list[str] = []

        def counting(self: Actor, *a: Any, **k: Any) -> Any:
            creates.append(k.get("actor_id", ""))
            return real_create(self, *a, **k)

        try:
            with (
                mock.patch(SERVER, return_value=server),
                mock.patch.object(Actor, "create", counting),
            ):
                iface = _auth(cfg, token)

            assert iface is not None and iface.id == actor_id
            assert creates == [actor_id]
            # The second snapshot: the drop's own eviction record does not
            # refuse this request's fill.
            assert mcp_mod._token_cache[token]["actor_id"] == actor_id
        finally:
            if Actor(actor_id, cfg).id:
                Actor(actor_id, cfg).delete()

    def test_a_freshly_validated_token_for_a_deleted_actor_is_not_cached(
        self, cfg: Config, actor: Actor
    ) -> None:
        token = _token()
        actor_id = aid(actor)
        Actor(actor_id, cfg).delete()

        with mock.patch(SERVER, return_value=_Server((actor_id, CLIENT, {}))):
            assert _auth(cfg, token) is None

        assert token not in mcp_mod._token_cache


class TestFaults:
    @pytest.mark.parametrize("handler_cls", [mcp_mod.MCPHandler, AsyncMCPHandler])
    async def test_an_actor_read_fault_on_a_cached_token_answers_503(
        self, cfg: Config, actor: Actor, handler_cls: Any
    ) -> None:
        token = _token()
        _seed_token(cfg, token, aid(actor))
        _seed_trust(cfg, aid(actor))
        handler = handler_cls(
            make_mcp_webobj({"Authorization": f"Bearer {token}"}), cfg, hooks=None
        )
        body = {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}

        def down(*_a: Any, **_k: Any) -> Any:
            raise DbError("actor read")

        with mock.patch.object(mcp_mod, "_load_actor", down):
            if handler_cls is AsyncMCPHandler:
                await handler.post_async(body)
            else:
                handler.post(body)

        assert handler.response.status_code == 503
        assert token in mcp_mod._token_cache

    def test_a_resolver_bug_on_a_cached_token_answers_none(
        self, cfg: Config, actor: Actor
    ) -> None:
        token = _token()
        _seed_token(cfg, token, aid(actor))

        def bug(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError("resolver bug")

        with mock.patch.object(
            mcp_mod.MCPHandler, "_lookup_mcp_trust_relationship", bug
        ):
            assert _auth(cfg, token) is None


class TestOneApplicationPerEntry:
    def test_another_applications_entries_are_misses(
        self, cfg: Config, actor: Actor
    ) -> None:
        token = _token()
        _seed_token(cfg, token, aid(actor))
        _seed_trust(cfg, aid(actor), trust=mock.Mock(peerid="from-a"))
        other = _config()

        server = _Server(None)  # the second application does not know it
        with mock.patch(SERVER, return_value=server):
            assert _auth(other, token) is None

        assert server.calls == 1
        assert mcp_mod._token_cache[token]["config"] is cfg
        assert mcp_mod._trust_cache[(aid(actor), CLIENT)]["config"] is cfg

    def test_a_token_both_accept_is_one_slot(self, cfg: Config, actor: Actor) -> None:
        token = _token()
        _seed_token(cfg, token, aid(actor))
        _seed_trust(cfg, aid(actor))
        other = _config()

        server = _Server((aid(actor), CLIENT, {}))
        with (
            mock.patch(SERVER, return_value=server),
            mock.patch.object(
                mcp_mod.MCPHandler, "_lookup_mcp_trust_relationship", return_value=None
            ),
        ):
            assert _auth(other, token) is not None
            assert mcp_mod._token_cache[token]["config"] is other
            # The first application now misses and validates again.
            assert _auth(cfg, token) is not None

        assert server.calls == 2
        assert mcp_mod._token_cache[token]["config"] is cfg


class TestTrustEntries:
    def test_a_cached_negative_is_a_hit_with_an_empty_peer(
        self, cfg: Config, actor: Actor
    ) -> None:
        token = _token()
        _seed_token(cfg, token, aid(actor))
        _seed_trust(cfg, aid(actor), trust=None)

        with mock.patch.object(
            mcp_mod.MCPHandler, "_lookup_mcp_trust_relationship"
        ) as lookup:
            iface = _auth(cfg, token)

        lookup.assert_not_called()
        ctx = RuntimeContext(iface).get_mcp_context()
        assert ctx is not None and ctx.peer_id == ""

    def test_a_positive_entry_past_its_ttl_is_resolved_again(
        self, cfg: Config, actor: Actor
    ) -> None:
        token = _token()
        _seed_token(cfg, token, aid(actor))
        _seed_trust(cfg, aid(actor), trust=mock.Mock(peerid="old"))
        mcp_mod._trust_cache[(aid(actor), CLIENT)]["cached_at"] -= (
            mcp_mod._TRUST_CACHE_TTL + 1
        )
        fresh = mock.Mock(peerid="new", oauth_client_id=CLIENT)

        with mock.patch.object(
            mcp_mod.MCPHandler, "_lookup_mcp_trust_relationship", return_value=fresh
        ) as lookup:
            iface = _auth(cfg, token)

        lookup.assert_called_once()
        ctx = RuntimeContext(iface).get_mcp_context()
        assert ctx is not None and ctx.peer_id == "new"

    def test_the_sweep_removes_entries_by_their_own_ttl(self, cfg: Config) -> None:
        now = time.time()
        mcp_mod._trust_cache[("a", "old-positive")] = {
            "trust": object(),
            "cached_at": now - mcp_mod._TRUST_CACHE_TTL - 1,
            "config": cfg,
        }
        mcp_mod._trust_cache[("a", "young-positive")] = {
            "trust": object(),
            "cached_at": now - 60,
            "config": cfg,
        }
        mcp_mod._trust_cache[("a", "old-negative")] = {
            "trust": None,
            "cached_at": now - 11,
            "config": cfg,
        }
        mcp_mod._trust_cache[("a", "young-negative")] = {
            "trust": None,
            "cached_at": now - 1,
            "config": cfg,
        }

        make_mcp_handler(cfg=cfg)._cleanup_expired_cache_entries()

        assert set(mcp_mod._trust_cache) == {
            ("a", "young-positive"),
            ("a", "young-negative"),
        }

    def test_a_revocation_during_the_lookup_leaves_the_trust_unfilled(
        self, cfg: Config, actor: Actor
    ) -> None:
        token = _token()
        _seed_token(cfg, token, aid(actor))

        def revoked_meanwhile(*_a: Any, **_k: Any) -> Any:
            mcp_mod.evict_mcp_caches_for_actor(aid(actor))
            return None

        with mock.patch.object(
            mcp_mod.MCPHandler, "_lookup_mcp_trust_relationship", revoked_meanwhile
        ):
            assert _auth(cfg, token) is not None

        assert (aid(actor), CLIENT) not in mcp_mod._trust_cache


class TestNoSecondLoad:
    def test_the_two_trust_helpers_read_no_actor_row(
        self, cfg: Config, actor: Actor
    ) -> None:
        token = _token()
        _seed_token(cfg, token, aid(actor))
        _seed_trust(cfg, aid(actor))
        iface = _auth(cfg, token)
        handler = make_mcp_handler(cfg=cfg)
        trust = mock.Mock(
            peerid="no-such-peer",
            established_via="oauth2_client",
            peer_approved=False,
            relationship="mcp_client",
        )
        context = mock.Mock(peer_id="no-such-peer", trust_relationship=None)

        with (
            count_reads(cfg) as counts,
            mock.patch.object(
                mcp_mod.RuntimeContext, "get_mcp_context", return_value=context
            ),
            mock.patch.object(
                type(iface.core_actor), "modify_trust_and_notify", return_value=True
            ) as modify,
        ):
            handler._mark_client_peer_approved(iface, CLIENT, trust)
            handler._update_trust_with_client_info(iface, {"name": "Claude"})

        assert modify.call_count == 2
        assert counts["actor_get"] == 0

    def test_load_actor_hit_keeps_the_stored_creator(
        self, cfg: Config, actor: Actor
    ) -> None:
        cfg.force_email_prop_as_creator = True
        istore(actor).email = uuid_email()

        with count_reads(cfg) as counts:
            loaded = mcp_mod._load_actor(aid(actor), cfg)

        assert counts["actor_get"] == 1
        assert loaded.id == aid(actor)
        assert loaded.creator == actor.creator
        assert loaded.store is not None
        assert loaded.property is not None
        assert loaded.property_lists is not None
        # The constructor would have renamed it: the check is on.
        assert Actor(aid(actor), cfg).creator != actor.creator

    def test_load_actor_miss_has_no_id(self, cfg: Config) -> None:
        with count_reads(cfg) as counts:
            loaded = mcp_mod._load_actor(f"mcp{uuid.uuid4().hex}", cfg)
        assert counts["actor_get"] == 1
        assert loaded.id is None

    def test_the_race_winner_load_does_not_rename(
        self, cfg: Config, actor: Actor
    ) -> None:
        cfg.force_email_prop_as_creator = True
        istore(actor).email = uuid_email()
        handler = make_mcp_handler(cfg=cfg)

        assert handler._race_winner(aid(actor)) is True
        # Read the row itself: Actor(id, cfg) would run the rename.
        row = get_actor(cfg).get(actor_id=aid(actor))
        assert row is not None and row["creator"] == actor.creator
