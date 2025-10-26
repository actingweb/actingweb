"""
Tests for the Trust Type Registry.
"""

import json
import unittest
from unittest.mock import Mock, patch

from actingweb import config as config_class
from actingweb.trust_type_registry import (
    TRUST_TYPE_SYSTEM_ACTOR,
    TrustType,
    TrustTypeRegistry,
    get_registry,
)


class TestTrustType(unittest.TestCase):
    """Test the TrustType dataclass."""

    def test_trust_type_creation(self):
        """Test creating a trust type."""
        trust_type = TrustType(
            name="test_type",
            display_name="Test Type",
            description="A test trust type",
            base_permissions={"properties": {"allowed": ["*"]}}
        )

        self.assertEqual(trust_type.name, "test_type")
        self.assertEqual(trust_type.display_name, "Test Type")
        self.assertTrue(trust_type.allow_user_override)
        self.assertIsNone(trust_type.oauth_scope)

    def test_trust_type_validation(self):
        """Test trust type validation."""
        # Valid trust type
        valid_type = TrustType(
            name="valid",
            display_name="Valid Type",
            description="Valid",
            base_permissions={}
        )
        self.assertTrue(valid_type.validate())

        # Invalid - no name
        invalid_type = TrustType(
            name="",
            display_name="Invalid",
            description="Invalid",
            base_permissions={}
        )
        self.assertFalse(invalid_type.validate())

        # Invalid - bad permissions
        invalid_type2 = TrustType(
            name="invalid2",
            display_name="Invalid 2",
            description="Invalid",
            base_permissions="not a dict"  # type: ignore[arg-type]
        )
        self.assertFalse(invalid_type2.validate())

    def test_trust_type_serialization(self):
        """Test converting to/from dict."""
        trust_type = TrustType(
            name="test",
            display_name="Test",
            description="Test type",
            base_permissions={"test": "value"},
            oauth_scope="test.scope"
        )

        # Convert to dict
        data = trust_type.to_dict()
        self.assertIsInstance(data, dict)
        self.assertEqual(data["name"], "test")
        self.assertEqual(data["oauth_scope"], "test.scope")

        # Convert back
        restored = TrustType.from_dict(data)
        self.assertEqual(restored.name, trust_type.name)
        self.assertEqual(restored.oauth_scope, trust_type.oauth_scope)


class TestTrustTypeRegistry(unittest.TestCase):
    """Test the Trust Type Registry."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = config_class.Config()
        self.registry = TrustTypeRegistry(self.config)

        # Mock actor for testing with simple property store
        self.mock_actor = Mock()
        self.mock_actor.id = TRUST_TYPE_SYSTEM_ACTOR
        class _FakeProperty:
            def __init__(self):
                self._data = {}
            def __getattr__(self, name):
                return self._data.get(name)
            def __setattr__(self, name, value):
                if name == "_data":
                    object.__setattr__(self, name, value)
                else:
                    self._data[name] = value
        self.mock_actor.property = _FakeProperty()

    @patch('actingweb.trust_type_registry.actor_module.Actor')
    def test_system_actor_creation(self, mock_actor_class):
        """Test system actor creation."""
        # Mock actor that doesn't exist initially
        mock_actor_instance = self.mock_actor
        mock_actor_instance.id = None
        mock_actor_class.return_value = mock_actor_instance

        # First call should try to load existing actor
        # Second call should create new actor
        def side_effect(*args, **kwargs):
            if 'actor_id' in kwargs:
                mock_actor_instance.create(actor_id=TRUST_TYPE_SYSTEM_ACTOR, creator="system")
                return mock_actor_instance
            return mock_actor_instance

        mock_actor_class.side_effect = side_effect

        system_actor = self.registry._get_system_actor()
        self.assertIsNotNone(system_actor)
        mock_actor_instance.create.assert_called_once()

    @patch('actingweb.trust_type_registry.actor_module.Actor')
    def test_register_trust_type(self, mock_actor_class):
        """Test registering a trust type."""
        mock_actor_class.return_value = self.mock_actor

        trust_type = TrustType(
            name="test_register",
            display_name="Test Register",
            description="Test registration",
            base_permissions={"test": "permissions"}
        )

        result = self.registry.register_type(trust_type)
        self.assertTrue(result)

        # Verify property was set
        expected_property = f"trust_type:{trust_type.name}"
        self.assertIsNotNone(self.mock_actor.property.__getattr__(expected_property))

    @patch('actingweb.trust_type_registry.actor_module.Actor')
    def test_get_trust_type(self, mock_actor_class):
        """Test retrieving a trust type."""
        mock_actor_class.return_value = self.mock_actor

        # Mock stored trust type data
        trust_type_data = {
            "name": "test_get",
            "display_name": "Test Get",
            "description": "Test retrieval",
            "base_permissions": {"test": "permissions"},
            "allow_user_override": True,
            "oauth_scope": None,
            "created_by": "system"
        }

        # Preload property value directly and query
        self.mock_actor.property._data["trust_type:test_get"] = json.dumps(trust_type_data)
        with patch('actingweb.trust_type_registry.actor_module.Actor', return_value=self.mock_actor):
            trust_type = self.registry.get_type("test_get")

        self.assertIsNotNone(trust_type)
        self.assertEqual(trust_type.name, "test_get")  # type: ignore
        self.assertEqual(trust_type.display_name, "Test Get")  # type: ignore

    @patch('actingweb.trust_type_registry.actor_module.Actor')
    def test_list_trust_types(self, mock_actor_class):
        """Test listing all trust types."""
        mock_actor_class.return_value = self.mock_actor

        # Mock properties with trust types
        mock_properties = {
            "trust_type:type1": json.dumps({
                "name": "type1",
                "display_name": "Type 1",
                "description": "First type",
                "base_permissions": {},
                "allow_user_override": True,
                "oauth_scope": None,
                "created_by": "system"
            }),
            "trust_type:type2": json.dumps({
                "name": "type2",
                "display_name": "Type 2",
                "description": "Second type",
                "base_permissions": {},
                "allow_user_override": True,
                "oauth_scope": None,
                "created_by": "system"
            }),
            "other_property": "not a trust type"
        }

        self.mock_actor.get_properties.return_value = mock_properties
        with patch('actingweb.trust_type_registry.actor_module.Actor', return_value=self.mock_actor):
            trust_types = self.registry.list_types()

        self.assertEqual(len(trust_types), 2)
        names = [t.name for t in trust_types]
        self.assertIn("type1", names)
        self.assertIn("type2", names)

    def test_invalid_trust_type_registration(self):
        """Test that invalid trust types are rejected."""
        invalid_type = TrustType(
            name="",  # Invalid name
            display_name="Invalid",
            description="Invalid",
            base_permissions={}
        )

        result = self.registry.register_type(invalid_type)
        self.assertFalse(result)


class TestRegistrySingleton(unittest.TestCase):
    """Test the singleton registry."""

    def test_singleton_behavior(self):
        """Test that get_registry returns the same instance."""
        config = config_class.Config()

        registry1 = get_registry(config)
        registry2 = get_registry(config)

        self.assertIs(registry1, registry2)


if __name__ == '__main__':
    unittest.main()
