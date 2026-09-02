"""Tests for Phase 3: exact trust matching and fail-closed authorization.

Two coupled changes, tested together because tightening the matcher without
fixing the fail-open would silently *widen* access for rows that stop
matching:

1. ``_lookup_mcp_trust_relationship`` now matches by exact ``oauth_client_id``
   (or, for legacy rows, an exact reconstructed peer id) instead of substring
   containment.
2. An authenticated token that resolves to no trust relationship is now
   denied (fail-closed), distinct from "permission subsystem unavailable"
   (fail-open until 3.14.4; also fail-closed since, with its own message --
   see ``TestFailClosedOnEvaluatorErrors``).
"""

import base64
import unittest
from typing import Any
from unittest.mock import Mock, patch

from actingweb.handlers.async_mcp import AsyncMCPHandler
from actingweb.handlers.mcp import MCPHandler
from actingweb.interface.hooks import HookRegistry
from actingweb.mcp.decorators import mcp_prompt, mcp_resource, mcp_tool
from actingweb.oauth2_server.state_manager import OAuth2StateManager
from tests.mcp_helpers import make_mcp_config


class FakeTrust:
    def __init__(
        self,
        peerid: str,
        established_via: str | None = None,
        oauth_client_id: str | None = None,
    ) -> None:
        self.peerid = peerid
        self.established_via = established_via
        self.oauth_client_id = oauth_client_id
        self.relationship = "mcp_client"


class FakeTrustManager:
    def __init__(self, trusts: list[FakeTrust]) -> None:
        self._trusts = trusts

    @property
    def relationships(self):
        return self._trusts


class FakeActor:
    def __init__(self, trusts: list[FakeTrust], actor_id: str = "actor-1") -> None:
        self.id = actor_id
        self.trust = FakeTrustManager(trusts)


class TestExactResolverMatching(unittest.TestCase):
    """`_lookup_mcp_trust_relationship` matches by exact identity only."""

    def setUp(self) -> None:
        self.handler = MCPHandler()

    def _lookup(self, actor: FakeActor, client_id: str, token_data: dict) -> Any:
        # FakeActor duck-types ActorInterface (only .id and .trust.relationships
        # are read); it is not a real ActorInterface, hence the ignore.
        return self.handler._lookup_mcp_trust_relationship(
            actor,  # type: ignore[arg-type]
            client_id,
            token_data,
        )

    def test_oauth_client_id_match_resolves_own_row_not_others(self) -> None:
        row_a = FakeTrust(
            "oauth2_client:a:a",
            established_via="oauth2_client",
            oauth_client_id="client-A",
        )
        row_b = FakeTrust(
            "oauth2_client:b:b",
            established_via="oauth2_client",
            oauth_client_id="client-B",
        )
        actor = FakeActor([row_a, row_b])

        found = self._lookup(actor, "client-A", {})
        self.assertIs(found, row_a)

        found_b = self._lookup(actor, "client-B", {})
        self.assertIs(found_b, row_b)

    def test_legacy_row_without_oauth_client_id_resolves_by_exact_peer_id(self) -> None:
        # Dynamic-registration shape: email was set to client_id, so the
        # peer id's email and client segments are identical.
        legacy_row = FakeTrust(
            "oauth2_client:client-legacy:client-legacy",
            established_via="oauth2_client",
            oauth_client_id=None,
        )
        actor = FakeActor([legacy_row])

        found = self._lookup(actor, "client-legacy", {})
        self.assertIs(found, legacy_row)

    def test_rejects_peer_id_that_merely_contains_client_id(self) -> None:
        # Substring containment must not match: client_id appears inside the
        # peer id but not as the exact reconstructed candidate.
        sneaky_row = FakeTrust(
            "oauth2_client:client-Xclient-A:client-Xclient-A",
            established_via="oauth2_client",
            oauth_client_id=None,
        )
        actor = FakeActor([sneaky_row])

        found = self._lookup(actor, "client-A", {})
        self.assertIsNone(found)

    def test_rejects_peer_id_that_merely_ends_with_client_id(self) -> None:
        ends_with_row = FakeTrust(
            "oauth2_client:evilclient-A:evilclient-A",
            established_via="oauth2_client",
            oauth_client_id=None,
        )
        actor = FakeActor([ends_with_row])

        found = self._lookup(actor, "client-A", {})
        self.assertIsNone(found)

    def test_rejects_established_via_outside_oauth2_family(self) -> None:
        # A row that exactly matches the candidate peer id shape but was
        # established via a non-OAuth2 mechanism (e.g. the ordinary /trust
        # peer protocol) must not satisfy the fallback.
        peer_row = FakeTrust(
            "oauth2_client:client-A:client-A",
            established_via="actingweb",
            oauth_client_id=None,
        )
        actor = FakeActor([peer_row])

        found = self._lookup(actor, "client-A", {})
        self.assertIsNone(found)

    def test_client_id_normalization_round_trips(self) -> None:
        client_id = "a@b.com:x"
        normalized = "a_at_b_dot_com_colon_x"
        legacy_row = FakeTrust(
            f"oauth2_client:{normalized}:{normalized}",
            established_via="oauth2_client",
            oauth_client_id=None,
        )
        actor = FakeActor([legacy_row])

        found = self._lookup(actor, client_id, {})
        self.assertIs(found, legacy_row)

    def test_no_match_returns_none(self) -> None:
        actor = FakeActor([])
        found = self._lookup(actor, "client-A", {})
        self.assertIsNone(found)

    def test_dead_user_email_branch_is_gone(self) -> None:
        """token_data containing an 'email' key must not change resolution.

        The old dead code tried a direct lookup keyed by
        f"oauth2:{email}:{client}" whenever token_data had an email -- a
        branch that never fired in production because persisted MCP token
        records carry no email (research finding C3). Resolution must be
        identical with or without an email key present.
        """
        row = FakeTrust(
            "oauth2_client:client-A:client-A",
            established_via="oauth2_client",
            oauth_client_id="client-A",
        )
        actor = FakeActor([row])

        without_email = self._lookup(actor, "client-A", {})
        with_email = self._lookup(actor, "client-A", {"email": "someone@example.com"})
        self.assertIs(without_email, row)
        self.assertIs(with_email, row)


def _make_resource_prompt_tool_hooks() -> HookRegistry:
    hooks = HookRegistry()

    @mcp_tool(description="a tool")
    def a_tool(actor, action_name, data):
        return {"content": [{"type": "text", "text": "ok"}]}

    @mcp_prompt(description="a prompt")
    def a_prompt(actor, method_name, data):
        return {"prompt": "hi"}

    @mcp_resource(uri_template="notes://{id}", mime_type="text/plain")
    def a_resource(actor, method_name, params):
        return {"note": "hi"}

    hooks.register_action_hook("a_tool", a_tool)
    hooks.register_method_hook("a_prompt", a_prompt)
    hooks.register_method_hook("a_resource", a_resource)
    return hooks


class FakeAuthedActor:
    def __init__(self, actor_id: str = "actor-1") -> None:
        self.id = actor_id


def _post(handler, method: str, params: dict) -> dict:
    return handler.post(
        {"jsonrpc": "2.0", "id": "1", "method": method, "params": params}
    )


async def _post_async(handler, method: str, params: dict) -> dict:
    return await handler.post_async(
        {"jsonrpc": "2.0", "id": "1", "method": method, "params": params}
    )


class TestFailClosedAcrossAllGates(unittest.TestCase):
    """No resolved trust -> lists are empty, single-item calls deny -32003.

    Covers all six gates the plan names (sync mcp.py, async async_mcp.py),
    matching the research definition-of-done: tools/list, resources/list,
    prompts/list return empty; tools/call, prompts/get, resources/read
    return -32003 with the no-trust message.
    """

    def setUp(self) -> None:
        self.actor = FakeAuthedActor()
        self.hooks = _make_resource_prompt_tool_hooks()

    def _sync_handler(self) -> MCPHandler:
        handler = MCPHandler()
        handler.hooks = self.hooks
        return handler

    def _async_handler(self) -> AsyncMCPHandler:
        handler = AsyncMCPHandler()
        handler.hooks = self.hooks
        return handler

    def _no_peer_context(self):
        ctx = Mock()
        ctx.peer_id = None
        return ctx

    def test_sync_tools_list_empty(self) -> None:
        handler = self._sync_handler()
        with (
            patch.object(
                MCPHandler, "authenticate_and_get_actor_cached", return_value=self.actor
            ),
            patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc,
        ):
            mock_rc.return_value.get_mcp_context.return_value = self._no_peer_context()
            resp = _post(handler, "tools/list", {})
        self.assertEqual(resp["result"]["tools"], [])

    def test_sync_resources_list_empty(self) -> None:
        handler = self._sync_handler()
        with (
            patch.object(
                MCPHandler, "authenticate_and_get_actor_cached", return_value=self.actor
            ),
            patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc,
        ):
            mock_rc.return_value.get_mcp_context.return_value = self._no_peer_context()
            resp = _post(handler, "resources/list", {})
        self.assertEqual(resp["result"]["resources"], [])

    def test_sync_prompts_list_empty(self) -> None:
        handler = self._sync_handler()
        with (
            patch.object(
                MCPHandler, "authenticate_and_get_actor_cached", return_value=self.actor
            ),
            patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc,
        ):
            mock_rc.return_value.get_mcp_context.return_value = self._no_peer_context()
            resp = _post(handler, "prompts/list", {})
        self.assertEqual(resp["result"]["prompts"], [])

    def test_sync_tools_call_denied(self) -> None:
        handler = self._sync_handler()
        with (
            patch.object(
                MCPHandler, "authenticate_and_get_actor_cached", return_value=self.actor
            ),
            patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc,
        ):
            mock_rc.return_value.get_mcp_context.return_value = self._no_peer_context()
            resp = _post(handler, "tools/call", {"name": "a_tool", "arguments": {}})
        self.assertEqual(resp["error"]["code"], -32003)
        self.assertIn("no trust relationship", resp["error"]["message"])

    def test_sync_prompts_get_denied(self) -> None:
        handler = self._sync_handler()
        with (
            patch.object(
                MCPHandler, "authenticate_and_get_actor_cached", return_value=self.actor
            ),
            patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc,
        ):
            mock_rc.return_value.get_mcp_context.return_value = self._no_peer_context()
            resp = _post(handler, "prompts/get", {"name": "a_prompt", "arguments": {}})
        self.assertEqual(resp["error"]["code"], -32003)
        self.assertIn("no trust relationship", resp["error"]["message"])

    def test_sync_resources_read_denied(self) -> None:
        handler = self._sync_handler()
        with (
            patch.object(
                MCPHandler, "authenticate_and_get_actor_cached", return_value=self.actor
            ),
            patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc,
        ):
            mock_rc.return_value.get_mcp_context.return_value = self._no_peer_context()
            resp = _post(handler, "resources/read", {"uri": "notes://1"})
        self.assertEqual(resp["error"]["code"], -32003)
        self.assertIn("no trust relationship", resp["error"]["message"])

    def test_async_tools_call_denied(self) -> None:
        import asyncio

        handler = self._async_handler()
        with (
            patch.object(
                AsyncMCPHandler,
                "authenticate_and_get_actor_cached",
                return_value=self.actor,
            ),
            patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc,
        ):
            mock_rc.return_value.get_mcp_context.return_value = self._no_peer_context()
            resp = asyncio.run(
                _post_async(handler, "tools/call", {"name": "a_tool", "arguments": {}})
            )
        self.assertEqual(resp["error"]["code"], -32003)
        self.assertIn("no trust relationship", resp["error"]["message"])

    def test_async_prompts_get_denied(self) -> None:
        import asyncio

        handler = self._async_handler()
        with (
            patch.object(
                AsyncMCPHandler,
                "authenticate_and_get_actor_cached",
                return_value=self.actor,
            ),
            patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc,
        ):
            mock_rc.return_value.get_mcp_context.return_value = self._no_peer_context()
            resp = asyncio.run(
                _post_async(
                    handler, "prompts/get", {"name": "a_prompt", "arguments": {}}
                )
            )
        self.assertEqual(resp["error"]["code"], -32003)
        self.assertIn("no trust relationship", resp["error"]["message"])

    def test_async_resources_read_denied(self) -> None:
        import asyncio

        handler = self._async_handler()
        with (
            patch.object(
                AsyncMCPHandler,
                "authenticate_and_get_actor_cached",
                return_value=self.actor,
            ),
            patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc,
        ):
            mock_rc.return_value.get_mcp_context.return_value = self._no_peer_context()
            resp = asyncio.run(
                _post_async(handler, "resources/read", {"uri": "notes://1"})
            )
        self.assertEqual(resp["error"]["code"], -32003)
        self.assertIn("no trust relationship", resp["error"]["message"])

    def test_async_tools_list_empty_via_inherited_sync_handler(self) -> None:
        """*/list methods route to the inherited sync handler on both
        transports (async_mcp.py dispatch), so this must also fail closed.
        """
        import asyncio

        handler = self._async_handler()
        with (
            patch.object(
                AsyncMCPHandler,
                "authenticate_and_get_actor_cached",
                return_value=self.actor,
            ),
            patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc,
        ):
            mock_rc.return_value.get_mcp_context.return_value = self._no_peer_context()
            resp = asyncio.run(_post_async(handler, "tools/list", {}))
        self.assertEqual(resp["result"]["tools"], [])


class TestFailClosedOnEvaluatorErrors(unittest.TestCase):
    """An evaluator that raises (permission subsystem unavailable) denies.

    Until 3.14.4 the six single-item gates logged at debug and served the
    request. They now deny with -32003, a message distinct from the no-trust
    denial, and an ``error`` log line with the traceback -- the same policy
    ``authenticated_views.py`` applies to property access.
    """

    def setUp(self) -> None:
        self.hooks = _make_resource_prompt_tool_hooks()
        self.actor = FakeAuthedActor()

    def _ctx(self):
        ctx = Mock()
        ctx.peer_id = "oauth2_client:client-A:client-A"
        return ctx

    def _sync(self, method: str, params: dict) -> dict:
        handler = MCPHandler()
        handler.hooks = self.hooks
        with (
            patch.object(
                MCPHandler, "authenticate_and_get_actor_cached", return_value=self.actor
            ),
            patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc,
            patch(
                "actingweb.permission_evaluator.get_permission_evaluator",
                side_effect=RuntimeError("permission system unavailable"),
            ),
            self.assertLogs("actingweb.handlers.mcp", level="ERROR") as logs,
        ):
            mock_rc.return_value.get_mcp_context.return_value = self._ctx()
            resp = _post(handler, method, params)
        self.assertTrue(any("Denying access" in line for line in logs.output))
        return resp

    def _async(self, method: str, params: dict) -> dict:
        import asyncio

        handler = AsyncMCPHandler()
        handler.hooks = self.hooks
        with (
            patch.object(
                AsyncMCPHandler,
                "authenticate_and_get_actor_cached",
                return_value=self.actor,
            ),
            patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc,
            patch(
                "actingweb.permission_evaluator.get_permission_evaluator",
                side_effect=RuntimeError("permission system unavailable"),
            ),
            self.assertLogs("actingweb.handlers.async_mcp", level="ERROR") as logs,
        ):
            mock_rc.return_value.get_mcp_context.return_value = self._ctx()
            resp = asyncio.run(_post_async(handler, method, params))
        self.assertTrue(any("Denying access" in line for line in logs.output))
        return resp

    def _assert_denied(self, resp: dict, kind: str) -> None:
        self.assertNotIn("result", resp)
        self.assertEqual(resp["error"]["code"], -32003)
        self.assertIn("unable to verify permission", resp["error"]["message"])
        self.assertIn(kind, resp["error"]["message"])
        self.assertNotIn("no trust relationship", resp["error"]["message"])

    def test_sync_tools_call(self) -> None:
        resp = self._sync("tools/call", {"name": "a_tool", "arguments": {}})
        self._assert_denied(resp, "tool 'a_tool'")

    def test_sync_prompts_get(self) -> None:
        resp = self._sync("prompts/get", {"name": "a_prompt", "arguments": {}})
        self._assert_denied(resp, "prompt 'a_prompt'")

    def test_sync_resources_read(self) -> None:
        resp = self._sync("resources/read", {"uri": "notes://1"})
        self._assert_denied(resp, "resource 'notes://1'")

    def test_async_tools_call(self) -> None:
        resp = self._async("tools/call", {"name": "a_tool", "arguments": {}})
        self._assert_denied(resp, "tool 'a_tool'")

    def test_async_prompts_get(self) -> None:
        resp = self._async("prompts/get", {"name": "a_prompt", "arguments": {}})
        self._assert_denied(resp, "prompt 'a_prompt'")

    def test_async_resources_read(self) -> None:
        resp = self._async("resources/read", {"uri": "notes://1"})
        self._assert_denied(resp, "resource 'notes://1'")


class TestNoTrustDenialSurvivesBrokenEvaluator(unittest.TestCase):
    """The no-trust denial must not sit inside the evaluator try/except.

    Both paths deny since 3.14.4, but with different messages: a no-trust
    request must still be reported as such rather than as an evaluator
    fault. This is the discriminating test for gate placement -- see
    research finding on positioning the denial outside the guarded region.
    """

    def test_denial_survives_evaluator_construction_raising(self) -> None:
        handler = MCPHandler()
        handler.hooks = _make_resource_prompt_tool_hooks()
        actor = FakeAuthedActor()

        with (
            patch.object(
                MCPHandler, "authenticate_and_get_actor_cached", return_value=actor
            ),
            patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc,
            patch(
                "actingweb.permission_evaluator.get_permission_evaluator",
                side_effect=RuntimeError("permission system unavailable"),
            ),
        ):
            ctx = Mock()
            ctx.peer_id = None  # no trust resolved
            mock_rc.return_value.get_mcp_context.return_value = ctx
            resp = _post(handler, "tools/call", {"name": "a_tool", "arguments": {}})

        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32003)
        self.assertIn("no trust relationship", resp["error"]["message"])


class TestNegativeTTL(unittest.TestCase):
    """A cached ``None`` trust re-resolves after the negative TTL, not the
    full 5-minute positive TTL.
    """

    def setUp(self) -> None:
        from actingweb.handlers import mcp as mcp_mod

        self.mcp_mod = mcp_mod
        mcp_mod._trust_cache.clear()

    def tearDown(self) -> None:
        self.mcp_mod._trust_cache.clear()

    def test_cached_none_expires_after_negative_ttl_not_full_ttl(self) -> None:
        mcp_mod = self.mcp_mod
        key = ("actor-1", "client-A")
        mcp_mod._trust_cache_put(key, None)

        # Just past the negative TTL, but nowhere near the 5-minute
        # positive-cache window: must be a miss (fresh lookup required).
        past_negative_ttl = (
            mcp_mod._trust_cache[key]["cached_at"]
            - mcp_mod._TRUST_CACHE_NEGATIVE_TTL
            - 1
        )
        mcp_mod._trust_cache[key]["cached_at"] = past_negative_ttl

        hit, trust = mcp_mod._trust_cache_get(key)
        self.assertFalse(hit)
        self.assertIsNone(trust)
        self.assertNotIn(key, mcp_mod._trust_cache)

    def test_fresh_cached_none_is_still_a_hit(self) -> None:
        mcp_mod = self.mcp_mod
        key = ("actor-1", "client-A")
        mcp_mod._trust_cache_put(key, None)

        hit, trust = mcp_mod._trust_cache_get(key)
        self.assertTrue(hit)
        self.assertIsNone(trust)


class TestOAuth2InteractiveReachability(unittest.TestCase):
    """`extract_mcp_context` returns None unless flow_type == "mcp_oauth2",
    so `handle_oauth_callback`'s trust-establishment branch can never see
    any other flow_type -- the removed "oauth2_interactive" else-branch
    was unreachable dead code (see oauth2_server.py).
    """

    def _state_manager(self) -> OAuth2StateManager:
        cfg = make_mcp_config()
        # Avoid the system-actor/DynamoDB-backed key path entirely for this
        # unit test by supplying a key directly.
        from cryptography.fernet import Fernet

        cfg.oauth2_state_encryption_key = base64.urlsafe_b64encode(  # type: ignore[attr-defined]
            Fernet.generate_key()
        ).decode("utf-8")
        return OAuth2StateManager(cfg)

    def test_extract_mcp_context_none_for_non_mcp_flow(self) -> None:
        sm = self._state_manager()
        state = sm.create_mcp_state(
            client_id="client-A",
            original_state=None,
            redirect_uri="https://client.example.com/callback",
            code_challenge=None,
            code_challenge_method=None,
            provider="google",
        )

        # create_mcp_state always sets flow_type="mcp_oauth2".
        decoded = sm.validate_and_extract_state(state)
        assert decoded is not None
        self.assertEqual(decoded.get("flow_type"), "mcp_oauth2")

        # A state lacking the MCP flow_type must not be treated as an MCP
        # context -- the invariant handle_oauth_callback's trust
        # establishment now depends on unconditionally.
        other_state = sm.create_state({**decoded, "flow_type": "something_else"})
        self.assertIsNone(sm.extract_mcp_context(other_state))

        # The genuine MCP state resolves to a non-None context whose
        # flow_type is always "mcp_oauth2".
        mcp_context = sm.extract_mcp_context(state)
        assert mcp_context is not None
        self.assertEqual(mcp_context.get("flow_type"), "mcp_oauth2")


if __name__ == "__main__":
    unittest.main()
