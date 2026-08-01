"""Regression tests for the MCP trust-cache client-crossing defect.

The MCP authentication path used to cache each actor's resolved trust
relationship under an actor-only key. Because the permission evaluator
resolves the entire permission rule set (the trust *type*) from the
cached `peer_id`, one MCP client's trust could silently replace another
client's trust on the same actor -- a demonstrated authorization bypass,
not a display bug (see thoughts/research/2026-07-30-mcp-trust-cache-crosses-clients.md).

These tests exercise the real module-global caches, the real
`authenticate_and_get_actor_cached()` / `_get_or_create_actor_cached()` /
`_lookup_mcp_trust_relationship()`, and the real `RuntimeContext`. Only the
storage and OAuth2 boundaries are mocked, matching the research document's
independent reproduction (R1).
"""

import contextlib
import threading
import time
import unittest
from typing import Any
from unittest import mock

from actingweb.handlers import async_mcp as async_mcp_mod
from actingweb.handlers import mcp as mcp_mod
from actingweb.runtime_context import MCPContext, RuntimeContext
from tests.mcp_helpers import make_mcp_config, make_mcp_handler

ACTOR_ID = "actor-1"
OTHER_ACTOR_ID = "actor-2"


class FakeTrust:
    """Stands in for a persisted TrustRelationship row."""

    def __init__(self, client_id: str) -> None:
        self.peerid = f"oauth2_client:{client_id}:{client_id}"
        self.established_via = "oauth2_client"
        self.relationship = "mcp_client"
        self.oauth_client_id: str | None = client_id
        self.client_name = f"Client {client_id}"
        self.client_version = "1.0"
        self.client_platform = ""
        self.peer_approved = True


TRUST_A = FakeTrust("client-A")
TRUST_B = FakeTrust("client-B")
TRUSTS = [TRUST_A, TRUST_B]


class FakeTrustManager:
    """Stands in for ActorInterface.trust; the resolver iterates .relationships."""

    @property
    def relationships(self):
        return TRUSTS

    def get_relationship(self, peer_id):
        for t in TRUSTS:
            if t.peerid == peer_id:
                return t
        return None


class FakeCoreActor:
    def __init__(self, actor_id=None, config=None):
        self.id = actor_id
        self.config = config
        self.actor = {"id": actor_id, "creator": "user@example.com"}


TOKENS = {
    # Realistic (email-free) token_data, matching what
    # token_manager.py actually persists (see research C3).
    "token-A": (ACTOR_ID, "client-A", {"token_id": "t-a", "scope": "mcp"}),
    "token-B": (ACTOR_ID, "client-B", {"token_id": "t-b", "scope": "mcp"}),
    "token-none": (ACTOR_ID, "client-none", {"token_id": "t-n", "scope": "mcp"}),
    "token-other-actor": (
        OTHER_ACTOR_ID,
        "client-A",
        {"token_id": "t-oa", "scope": "mcp"},
    ),
}


class FakeOAuth2Server:
    def validate_mcp_token(self, token):
        return TOKENS.get(token)


@contextlib.contextmanager
def _patches(cfg):
    """The set of mocks needed to exercise the real cache/auth code path."""
    with (
        mock.patch(
            "actingweb.actor.Actor",
            lambda actor_id=None, config=None: FakeCoreActor(actor_id, cfg),
        ),
        mock.patch(
            "actingweb.oauth2_server.oauth2_server.get_actingweb_oauth2_server",
            return_value=FakeOAuth2Server(),
        ),
        mock.patch.object(
            mcp_mod.MCPHandler, "_mark_client_peer_approved", lambda *a, **k: None
        ),
        mock.patch.object(
            mcp_mod.ActorInterface,
            "trust",
            property(lambda self: FakeTrustManager()),
        ),
    ):
        yield


class TrustCacheTestCase(unittest.TestCase):
    """Base class: clears all three module-global MCP caches around every test."""

    def setUp(self) -> None:
        self._clear_caches()
        self.cfg = make_mcp_config()

    def tearDown(self) -> None:
        self._clear_caches()

    @staticmethod
    def _clear_caches() -> None:
        mcp_mod._token_cache.clear()
        mcp_mod._actor_cache.clear()
        mcp_mod._trust_cache.clear()
        for key in mcp_mod._cache_stats:
            mcp_mod._cache_stats[key] = 0
        mcp_mod._next_cleanup_at = 0.0

    def run_request(
        self, token: str, handler_cls=mcp_mod.MCPHandler
    ) -> tuple[Any, MCPContext]:
        handler = handler_cls(
            mcp_mod.aw_web_request.AWWebObj(
                url="https://test.example.com/mcp",
                params={},
                body="",
                headers={"Authorization": f"Bearer {token}"},
                cookies={},
            ),
            self.cfg,
        )
        with _patches(self.cfg):
            actor_iface = handler.authenticate_and_get_actor_cached()
        assert actor_iface is not None, f"auth failed for {token}"
        ctx = RuntimeContext(actor_iface).get_mcp_context()
        assert ctx is not None, f"no MCP context after {token}"
        return actor_iface, ctx


class TestIdentitySequence(TrustCacheTestCase):
    """A/B/A/B/A on one actor: every request must see its own identity."""

    def test_alternating_clients_never_cross(self) -> None:
        sequence = ["token-A", "token-B", "token-A", "token-B", "token-A"]
        expected_client = {
            "token-A": "client-A",
            "token-B": "client-B",
        }
        expected_trust = {
            "token-A": TRUST_A,
            "token-B": TRUST_B,
        }

        for i, token in enumerate(sequence):
            _, ctx = self.run_request(token)
            self.assertEqual(
                ctx.client_id, expected_client[token], f"request {i} ({token})"
            )
            self.assertEqual(
                ctx.peer_id,
                expected_trust[token].peerid,
                f"request {i} ({token})",
            )
            self.assertIs(
                ctx.trust_relationship,
                expected_trust[token],
                f"request {i} ({token})",
            )

        # Requests 3-5 (index 2+) must be genuine cache hits, not misses that
        # happen to resolve correctly.
        self.assertGreaterEqual(mcp_mod._cache_stats["trust_hits"], 3)

    def test_this_test_fails_against_actor_only_keying(self) -> None:
        """Prove the test has teeth: simulate the old actor-only key shape.

        Writes directly through an actor-keyed wrapper (mimicking the
        pre-fix cache) and shows the alternation misattributes client A as
        client B, exactly as the research document's R1 reproduction did.
        """
        legacy_cache: dict[str, dict] = {}

        def legacy_get(actor_id, client_id):
            entry = legacy_cache.get(actor_id)
            if entry is None:
                return False, None
            return True, entry["trust"]

        def legacy_put(actor_id, client_id, trust):
            legacy_cache[actor_id] = {"trust": trust}

        results = []
        with (
            mock.patch.object(
                mcp_mod,
                "_trust_cache_get",
                side_effect=lambda key: legacy_get(key[0], key[1]),
            ),
            mock.patch.object(
                mcp_mod,
                "_trust_cache_put",
                side_effect=lambda key, trust: legacy_put(key[0], key[1], trust),
            ),
        ):
            for token in ["token-A", "token-B", "token-A"]:
                _, ctx = self.run_request(token)
                results.append((token, ctx.client_id, ctx.peer_id))

        # Request 3 (token-A) is served client B's peer id under actor-only
        # keying -- the exact misattribution the tuple-key fix closes.
        self.assertEqual(results[2][0], "token-A")
        self.assertEqual(results[2][2], TRUST_B.peerid)
        self.assertNotEqual(results[2][2], TRUST_A.peerid)


class TestResolverCallCounts(TrustCacheTestCase):
    def test_resolver_called_once_per_actor_client_pair(self) -> None:
        with mock.patch.object(
            mcp_mod.MCPHandler,
            "_lookup_mcp_trust_relationship",
            autospec=True,
            side_effect=mcp_mod.MCPHandler._lookup_mcp_trust_relationship,
        ) as spy:
            self.run_request("token-A")
            self.run_request("token-B")
            self.run_request("token-A")
            self.run_request("token-B")

        # One resolver call per distinct (actor, client) pair while hot.
        self.assertEqual(spy.call_count, 2)


class TestCachedNoneIsPerClient(TrustCacheTestCase):
    def test_none_for_one_client_does_not_suppress_another(self) -> None:
        # client-none resolves to no trust; client-A must still see its own.
        _, ctx_none = self.run_request("token-none")
        self.assertIsNone(ctx_none.trust_relationship)
        self.assertEqual(ctx_none.peer_id, "")

        _, ctx_a = self.run_request("token-A")
        self.assertEqual(ctx_a.peer_id, TRUST_A.peerid)

        # And in the other order.
        self._clear_caches()
        _, ctx_a2 = self.run_request("token-A")
        self.assertEqual(ctx_a2.peer_id, TRUST_A.peerid)
        _, ctx_none2 = self.run_request("token-none")
        self.assertIsNone(ctx_none2.trust_relationship)
        self.assertEqual(ctx_none2.peer_id, "")


class TestActorExpiryEviction(TrustCacheTestCase):
    def test_actor_expiry_evicts_only_that_actors_tuples(self) -> None:
        self.run_request("token-A")
        self.run_request("token-B")
        self.run_request("token-other-actor")

        self.assertEqual(
            set(mcp_mod._trust_cache.keys()),
            {
                (ACTOR_ID, "client-A"),
                (ACTOR_ID, "client-B"),
                (OTHER_ACTOR_ID, "client-A"),
            },
        )

        # Force actor-1's actor-cache entry to look expired.
        mcp_mod._actor_cache[ACTOR_ID]["last_accessed"] = (
            time.time() - mcp_mod._cache_ttl - 1
        )

        handler = make_mcp_handler(cfg=self.cfg)
        handler._cleanup_expired_cache_entries()

        remaining = set(mcp_mod._trust_cache.keys())
        self.assertNotIn((ACTOR_ID, "client-A"), remaining)
        self.assertNotIn((ACTOR_ID, "client-B"), remaining)
        self.assertIn((OTHER_ACTOR_ID, "client-A"), remaining)
        self.assertNotIn(ACTOR_ID, mcp_mod._actor_cache)

    def test_scheduler_trigger_fires_cleanup(self) -> None:
        self.run_request("token-A")
        mcp_mod._actor_cache[ACTOR_ID]["last_accessed"] = (
            time.time() - mcp_mod._cache_ttl - 1
        )
        # Force the monotonic cleanup deadline to be in the past so the next
        # request trips it.
        mcp_mod._next_cleanup_at = 0.0

        # One more authenticated request should trip the scheduler and
        # evict the now-stale actor before doing its own fresh lookup.
        self.run_request("token-B")

        self.assertNotIn((ACTOR_ID, "client-A"), mcp_mod._trust_cache)


class TestClearTokenFromCache(TrustCacheTestCase):
    def test_clear_evicts_every_tuple_for_the_actor(self) -> None:
        self.run_request("token-A")
        self.run_request("token-B")

        found = mcp_mod.MCPHandler.clear_token_from_cache("token-A")
        self.assertTrue(found)
        self.assertEqual(mcp_mod._trust_cache, {})
        self.assertNotIn(ACTOR_ID, mcp_mod._actor_cache)

        not_found = mcp_mod.MCPHandler.clear_token_from_cache("token-A")
        self.assertFalse(not_found)


class TestEvictionUnderConcurrentMutation(TrustCacheTestCase):
    def test_no_runtime_error_during_concurrent_insert(self) -> None:
        for i in range(200):
            mcp_mod._trust_cache[(f"actor-{i}", "client-x")] = {
                "trust": None,
                "cached_at": 0.0,
            }

        stop = threading.Event()
        errors: list[BaseException] = []

        def inserter():
            # Bounded: enough concurrent mutation to race with the evictor's
            # scan without growing the dict without limit (which would make
            # every subsequent snapshot scan progressively slower).
            i = 1000
            while not stop.is_set() and i < 5000:
                mcp_mod._trust_cache[(f"actor-{i}", "client-x")] = {
                    "trust": None,
                    "cached_at": time.time(),
                }
                i += 1

        def evictor():
            try:
                for i in range(200):
                    mcp_mod._evict_trust_entries_for_actor(f"actor-{i}")
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        t_insert = threading.Thread(target=inserter)
        t_evict = threading.Thread(target=evictor)
        t_insert.start()
        t_evict.start()
        t_evict.join()
        stop.set()
        t_insert.join(timeout=5)

        self.assertEqual(errors, [])


class TestAsyncParity(TrustCacheTestCase):
    def test_identity_sequence_through_async_handler(self) -> None:
        sequence = ["token-A", "token-B", "token-A"]
        for token in sequence:
            _, ctx = self.run_request(token, handler_cls=async_mcp_mod.AsyncMCPHandler)
            expected = TRUST_A if token == "token-A" else TRUST_B
            self.assertEqual(ctx.peer_id, expected.peerid)


class TestInvariantCheck(TrustCacheTestCase):
    def test_mismatch_logs_error_without_leaking_email_or_token(self) -> None:
        handler = make_mcp_handler(cfg=self.cfg)
        mismatched_trust = FakeTrust("client-B")
        mismatched_trust.oauth_client_id = "client-B"  # does not match client-A

        with self.assertLogs("actingweb.handlers.mcp", level="ERROR") as cm:
            handler._check_trust_client_invariant(
                ACTOR_ID, "client-A", mismatched_trust
            )
        self.assertTrue(any("mismatch" in m.lower() for m in cm.output))
        joined = "\n".join(cm.output)
        self.assertNotIn("user@example.com", joined)
        self.assertNotIn("oauth2_client:client-B:client-B", joined)

    def test_normalized_client_id_peer_stays_silent(self) -> None:
        handler = make_mcp_handler(cfg=self.cfg)
        trust = FakeTrust("client-C")
        trust.oauth_client_id = None
        trust.peerid = "oauth2_client:user_at_example_dot_com:client-C"

        with self.assertRaises(AssertionError):
            with self.assertLogs("actingweb.handlers.mcp", level="ERROR"):
                handler._check_trust_client_invariant(ACTOR_ID, "client-C", trust)

    def test_oauth_client_id_matched_row_stays_silent(self) -> None:
        handler = make_mcp_handler(cfg=self.cfg)
        with self.assertRaises(AssertionError):
            with self.assertLogs("actingweb.handlers.mcp", level="ERROR"):
                handler._check_trust_client_invariant(ACTOR_ID, "client-A", TRUST_A)


if __name__ == "__main__":
    unittest.main()
