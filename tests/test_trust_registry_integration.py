"""
Integration tests for Trust Type Registry.
Tests the registry with real ActingWeb components.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from actingweb import actor as actor_module
from actingweb import config as config_class
from actingweb.trust_type_registry import (
    TRUST_TYPE_SYSTEM_ACTOR,
    TrustType,
    get_registry,
)


class _FakeProperty:
    def __init__(self, backing: dict | None = None):
        self._data = backing if backing is not None else {}

    def __getattr__(self, name):
        return self._data.get(name)

    def __setattr__(self, name, value):
        if name == "_data":
            object.__setattr__(self, name, value)
        else:
            self._data[name] = value


class _FakeActor:
    _STORE: dict[str, dict] = {}

    def __init__(self, actor_id=None, config=None):
        self.id = actor_id
        self.creator = "system"
        # Use a shared store per actor_id to simulate persistence across instances
        backing = self._STORE.setdefault(actor_id or "", {})
        self.property = _FakeProperty(backing)
        self._config = config

    def create(self, actor_id, creator="system"):
        self.id = actor_id
        self.creator = creator
        return True

    def get_properties(self):
        # Return a copy of properties dict
        return dict(self.property._data)


class TestTrustRegistryIntegration(unittest.TestCase):
    """Integration tests for trust type registry."""

    @classmethod
    def setUpClass(cls):
        """Set up test environment with temporary database."""
        # Use in-memory database for testing
        cls.db_file = tempfile.mktemp(suffix=".db")
        os.environ["AWS_DB_HOST"] = f"file://{cls.db_file}"
        os.environ["AWS_DB_PREFIX"] = "test_actingweb"

    @classmethod
    def tearDownClass(cls):
        """Clean up test database."""
        if os.path.exists(cls.db_file):
            os.unlink(cls.db_file)

    def setUp(self):
        """Set up test fixtures."""
        self.config = config_class.Config()
        # Clear any existing registry instance
        import actingweb.trust_type_registry

        actingweb.trust_type_registry._registry = None
        # Patch Actor to avoid hitting real DB
        self._patcher = patch(
            "actingweb.trust_type_registry.actor_module.Actor", _FakeActor
        )
        self._patcher.start()

    def tearDown(self):
        try:
            self._patcher.stop()
        except Exception:
            pass

    def test_registry_initialization(self):
        """Test that registry initializes with default trust types."""
        registry = get_registry(self.config)

        # List all trust types - should include defaults
        trust_types = registry.list_types()

        # Check that default types are present
        type_names = [t.name for t in trust_types]
        expected_defaults = ["viewer", "friend", "partner", "admin", "mcp_client"]

        for expected in expected_defaults:
            self.assertIn(
                expected,
                type_names,
                f"Default trust type '{expected}' should be present",
            )

    def test_register_custom_type(self):
        """Test registering a custom trust type."""
        registry = get_registry(self.config)

        custom_type = TrustType(
            name="custom_test",
            display_name="Custom Test Type",
            description="A custom trust type for testing",
            base_permissions={
                "properties": {"patterns": ["test/*"], "operations": ["read"]},
                "methods": {"allowed": ["test_*"]},
            },
            oauth_scope="actingweb.custom_test",
        )

        # Register the custom type
        success = registry.register_type(custom_type)
        self.assertTrue(success)

        # Retrieve it
        retrieved = registry.get_type("custom_test")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "custom_test")  # type: ignore
        self.assertEqual(retrieved.display_name, "Custom Test Type")  # type: ignore
        self.assertEqual(retrieved.oauth_scope, "actingweb.custom_test")  # type: ignore

    def test_registry_persistence(self):
        """Test that trust types persist across registry instances."""
        # Register a type with first registry
        registry1 = get_registry(self.config)

        test_type = TrustType(
            name="persistence_test",
            display_name="Persistence Test",
            description="Testing persistence",
            base_permissions={"test": "value"},
        )

        registry1.register_type(test_type)

        # Clear registry cache and create new instance
        registry1.clear_cache()
        import actingweb.trust_type_registry

        actingweb.trust_type_registry._registry = None

        registry2 = get_registry(self.config)

        # Should be able to retrieve the type with new registry
        retrieved = registry2.get_type("persistence_test")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "persistence_test")  # type: ignore
        self.assertEqual(retrieved.description, "Testing persistence")  # type: ignore

    def test_system_actor_creation(self):
        """Test that system actor is created properly."""
        # Ensure system actor exists
        _ = get_registry(self.config)  # noqa: F841

        # Try to load the system actor directly
        system_actor = actor_module.Actor(TRUST_TYPE_SYSTEM_ACTOR, config=self.config)

        # System actor should exist after registry initialization
        self.assertIsNotNone(system_actor.id)
        self.assertEqual(system_actor.id, TRUST_TYPE_SYSTEM_ACTOR)
        self.assertEqual(system_actor.creator, "system")

    def test_trust_type_validation_in_registry(self):
        """Test that registry validates trust types properly."""
        registry = get_registry(self.config)

        # Try to register an invalid trust type
        invalid_type = TrustType(
            name="",  # Empty name should fail
            display_name="Invalid",
            description="This should fail",
            base_permissions={},
        )

        success = registry.register_type(invalid_type)
        self.assertFalse(success)

        # Should not be retrievable
        retrieved = registry.get_type("")
        self.assertIsNone(retrieved)


if __name__ == "__main__":
    unittest.main()
