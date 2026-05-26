"""Tests for the configurable MCP server_name parameter.

Covers propagation from get_server_manager() -> MCPServerManager ->
ActingWebMCPServer -> the underlying MCP Server name, and the singleton
warning when get_server_manager() is called again with a different name.
"""

import unittest
from unittest.mock import Mock, patch

from actingweb.interface.hooks import HookRegistry
from actingweb.mcp import sdk_server
from actingweb.mcp.sdk_server import (
    ActingWebMCPServer,
    MCPServerManager,
    get_server_manager,
)


class TestMCPServerNamePropagation(unittest.TestCase):
    def setUp(self) -> None:
        # Reset the module-level singleton between tests
        sdk_server._server_manager = None

    def tearDown(self) -> None:
        sdk_server._server_manager = None

    def test_default_server_name_is_actingweb(self) -> None:
        manager = MCPServerManager()
        self.assertEqual(manager._server_name, "actingweb")

    def test_custom_server_name_stored_on_manager(self) -> None:
        manager = MCPServerManager(server_name="emm")
        self.assertEqual(manager._server_name, "emm")

    def test_actingweb_server_uses_provided_name(self) -> None:
        actor = Mock()
        server = ActingWebMCPServer(
            actor_id="actor1",
            hooks=HookRegistry(),
            actor=actor,
            server_name="emm",
        )
        self.assertEqual(server.server_name, "emm")
        # The underlying mcp.Server is constructed with the same name
        self.assertEqual(server.server.name, "emm")

    def test_actingweb_server_default_name_does_not_include_actor_id(self) -> None:
        actor = Mock()
        server = ActingWebMCPServer(
            actor_id="actor1", hooks=HookRegistry(), actor=actor
        )
        self.assertEqual(server.server_name, "actingweb")
        self.assertEqual(server.server.name, "actingweb")

    def test_manager_propagates_name_to_per_actor_servers(self) -> None:
        manager = MCPServerManager(server_name="emm")
        hooks = HookRegistry()
        actor = Mock()
        server = manager.get_server("actor1", hooks, actor)
        self.assertEqual(server.server_name, "emm")
        self.assertEqual(server.server.name, "emm")

    def test_get_server_manager_first_call_sets_name(self) -> None:
        manager = get_server_manager(server_name="emm")
        self.assertEqual(manager._server_name, "emm")

    def test_get_server_manager_singleton_warns_on_name_conflict(self) -> None:
        get_server_manager(server_name="emm")
        with patch.object(sdk_server.logger, "warning") as mock_warn:
            again = get_server_manager(server_name="other")
            mock_warn.assert_called_once()
            # The existing singleton name is preserved
            self.assertEqual(again._server_name, "emm")

    def test_get_server_manager_singleton_silent_when_name_matches(self) -> None:
        get_server_manager(server_name="emm")
        with patch.object(sdk_server.logger, "warning") as mock_warn:
            get_server_manager(server_name="emm")
            mock_warn.assert_not_called()


class TestMCPInstructionsPropagation(unittest.TestCase):
    """Plumbing for the MCP protocol `InitializeResult.instructions` field."""

    def setUp(self) -> None:
        sdk_server._server_manager = None

    def tearDown(self) -> None:
        sdk_server._server_manager = None

    def test_default_instructions_is_none(self) -> None:
        manager = MCPServerManager()
        self.assertIsNone(manager._instructions)

    def test_instructions_stored_on_manager(self) -> None:
        manager = MCPServerManager(server_name="emm", instructions="Call how_to_use()")
        self.assertEqual(manager._instructions, "Call how_to_use()")

    def test_actingweb_server_passes_instructions_to_underlying_mcp_server(
        self,
    ) -> None:
        actor = Mock()
        server = ActingWebMCPServer(
            actor_id="actor1",
            hooks=HookRegistry(),
            actor=actor,
            server_name="emm",
            instructions="Hello LLM",
        )
        self.assertEqual(server.instructions, "Hello LLM")
        # The underlying mcp.Server exposes instructions on the same attribute
        self.assertEqual(server.server.instructions, "Hello LLM")

    def test_actingweb_server_default_instructions_is_none(self) -> None:
        actor = Mock()
        server = ActingWebMCPServer(
            actor_id="actor1", hooks=HookRegistry(), actor=actor
        )
        self.assertIsNone(server.instructions)
        self.assertIsNone(server.server.instructions)

    def test_manager_propagates_instructions_to_per_actor_servers(self) -> None:
        manager = MCPServerManager(server_name="emm", instructions="Hello LLM")
        hooks = HookRegistry()
        actor = Mock()
        server = manager.get_server("actor1", hooks, actor)
        self.assertEqual(server.instructions, "Hello LLM")
        self.assertEqual(server.server.instructions, "Hello LLM")

    def test_get_server_manager_first_call_sets_instructions(self) -> None:
        manager = get_server_manager(server_name="emm", instructions="Hello LLM")
        self.assertEqual(manager._instructions, "Hello LLM")

    def test_get_server_manager_singleton_warns_on_instructions_conflict(self) -> None:
        get_server_manager(server_name="emm", instructions="Hello LLM")
        with patch.object(sdk_server.logger, "warning") as mock_warn:
            again = get_server_manager(server_name="emm", instructions="Goodbye LLM")
            self.assertTrue(mock_warn.called)
            # The original instructions are kept; the late value is ignored.
            self.assertEqual(again._instructions, "Hello LLM")

    def test_get_server_manager_singleton_silent_when_instructions_omitted(self) -> None:
        get_server_manager(server_name="emm", instructions="Hello LLM")
        with patch.object(sdk_server.logger, "warning") as mock_warn:
            get_server_manager(server_name="emm")
            mock_warn.assert_not_called()

    def test_get_server_manager_singleton_silent_when_instructions_match(self) -> None:
        get_server_manager(server_name="emm", instructions="Hello LLM")
        with patch.object(sdk_server.logger, "warning") as mock_warn:
            get_server_manager(server_name="emm", instructions="Hello LLM")
            mock_warn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
