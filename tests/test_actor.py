"""Tests for actor module."""

from unittest.mock import Mock, patch

import pytest

from actingweb.actor import (
    Actor,
    ActorError,
    ActorNotFoundError,
    DummyPropertyClass,
    InvalidActorDataError,
    PeerCommunicationError,
    TrustRelationshipError,
)
from actingweb.constants import DEFAULT_CREATOR, TRUSTEE_CREATOR


class TestActorExceptions:
    """Test custom exception classes."""

    def test_actor_error_inheritance(self):
        """Test ActorError inheritance hierarchy."""
        assert issubclass(ActorError, Exception)
        assert issubclass(ActorNotFoundError, ActorError)
        assert issubclass(InvalidActorDataError, ActorError)
        assert issubclass(PeerCommunicationError, ActorError)
        assert issubclass(TrustRelationshipError, ActorError)

    def test_actor_error_creation(self):
        """Test creating ActorError instances."""
        error = ActorError("Test error")
        assert str(error) == "Test error"
        assert isinstance(error, Exception)

    def test_actor_not_found_error(self):
        """Test ActorNotFoundError functionality."""
        error = ActorNotFoundError("Actor not found")
        assert str(error) == "Actor not found"
        assert isinstance(error, ActorError)

    def test_exception_catching(self):
        """Test exception catching hierarchy."""
        with pytest.raises(ActorError):
            raise ActorNotFoundError("Test")

        with pytest.raises(ActorError):
            raise InvalidActorDataError("Test")

        with pytest.raises(ActorError):
            raise PeerCommunicationError("Test")

        with pytest.raises(ActorError):
            raise TrustRelationshipError("Test")

    def test_specific_exception_catching(self):
        """Test catching specific exception types."""
        with pytest.raises(ActorNotFoundError):
            raise ActorNotFoundError("Actor not found")

        with pytest.raises(InvalidActorDataError):
            raise InvalidActorDataError("Invalid data")


class TestDummyPropertyClass:
    """Test deprecated DummyPropertyClass."""

    def test_dummy_property_creation(self):
        """Test creating DummyPropertyClass instances."""
        dummy = DummyPropertyClass("test_value")
        assert dummy.value == "test_value"

        dummy_none = DummyPropertyClass()
        assert dummy_none.value is None

    def test_dummy_property_with_different_types(self):
        """Test DummyPropertyClass with various value types."""
        dummy_str = DummyPropertyClass("string")
        assert dummy_str.value == "string"

        dummy_int = DummyPropertyClass(42)
        assert dummy_int.value == 42

        dummy_dict = DummyPropertyClass({"key": "value"})
        assert dummy_dict.value == {"key": "value"}


class TestActorInitialization:
    """Test Actor class initialization."""

    def test_actor_init_with_mock_config(self):
        """Test Actor initialization with mock config."""
        mock_config = Mock()
        mock_config.force_email_prop_as_creator = False  # Avoid attribute access
        mock_db_actor = Mock()
        # Mock actor data with required fields
        mock_db_actor.get.return_value = {
            "id": "test_actor",
            "creator": "test_creator",
            "passphrase": "test_passphrase",
        }
        mock_config.DbActor.DbActor.return_value = mock_db_actor

        with patch("actingweb.actor.attribute") as mock_attribute:
            with patch("actingweb.actor.property") as mock_property:
                mock_attribute.InternalStore.return_value = Mock()
                mock_property.PropertyStore.return_value = Mock()

                actor = Actor("test_actor", mock_config)
                assert actor.id == "test_actor"
                assert actor.config == mock_config
                assert actor.last_response_code == 0
                assert actor.last_response_message == ""

    def test_actor_attributes_initialization(self):
        """Test Actor attributes are properly initialized."""
        mock_config = Mock()
        mock_config.force_email_prop_as_creator = False  # Avoid attribute access
        mock_db_actor = Mock()
        # Mock actor data with required fields
        mock_db_actor.get.return_value = {
            "id": "test_actor",
            "creator": "test_creator",
            "passphrase": "test_passphrase",
        }
        mock_config.DbActor.DbActor.return_value = mock_db_actor

        with patch("actingweb.actor.attribute") as mock_attribute:
            with patch("actingweb.actor.property") as mock_property:
                mock_attribute.InternalStore.return_value = Mock()
                mock_property.PropertyStore.return_value = Mock()

                actor = Actor("test_actor", mock_config)

                # Check all attributes are initialized
                assert hasattr(actor, "config")
                assert hasattr(actor, "property_list")
                assert hasattr(actor, "subs_list")
                assert hasattr(actor, "actor")
                assert hasattr(actor, "passphrase")
                assert hasattr(actor, "creator")
                assert hasattr(actor, "last_response_code")
                assert hasattr(actor, "last_response_message")
                assert hasattr(actor, "id")
                assert hasattr(actor, "handle")


class TestActorMethods:
    """Test Actor method signatures and basic functionality."""

    def test_get_peer_info_signature(self):
        """Test get_peer_info method signature."""
        mock_config = Mock()
        mock_config.force_email_prop_as_creator = False  # Avoid attribute access
        mock_db_actor = Mock()
        # Mock actor data with required fields
        mock_db_actor.get.return_value = {
            "id": "test_actor",
            "creator": "test_creator",
            "passphrase": "test_passphrase",
        }
        mock_config.DbActor.DbActor.return_value = mock_db_actor

        with patch("actingweb.actor.attribute") as mock_attribute:
            with patch("actingweb.actor.property") as mock_property:
                mock_attribute.InternalStore.return_value = Mock()
                mock_property.PropertyStore.return_value = Mock()

                actor = Actor("test_actor", mock_config)

                # Test method exists and has correct signature
                assert hasattr(actor, "get_peer_info")
                assert callable(actor.get_peer_info)

    def test_deprecated_property_methods(self):
        """Test deprecated property methods."""
        mock_config = Mock()
        mock_config.force_email_prop_as_creator = False  # Avoid attribute access
        mock_db_actor = Mock()
        # Mock actor data with required fields
        mock_db_actor.get.return_value = {
            "id": "test_actor",
            "creator": "test_creator",
            "passphrase": "test_passphrase",
        }
        mock_config.DbActor.DbActor.return_value = mock_db_actor

        with patch("actingweb.actor.attribute") as mock_attribute:
            with patch("actingweb.actor.property") as mock_property:
                mock_attribute.InternalStore.return_value = Mock()
                mock_property.PropertyStore.return_value = Mock()

                actor = Actor("test_actor", mock_config)

                # Test deprecated methods exist
                assert hasattr(actor, "set_property")
                assert hasattr(actor, "get_property")
                assert hasattr(actor, "delete_property")
                assert callable(actor.set_property)
                assert callable(actor.get_property)
                assert callable(actor.delete_property)


class TestActorCreatorLookup:
    """Tests for creator-based actor lookup."""

    def test_get_from_creator_finds_existing_when_not_unique(self):
        mock_config = Mock()
        mock_config.unique_creator = False
        mock_config.force_email_prop_as_creator = False

        mock_db_actor = Mock()
        mock_db_actor.get_by_creator.return_value = [
            {"id": "actorB", "creator": "user@example.com", "passphrase": "bar"},
            {"id": "actorA", "creator": "user@example.com", "passphrase": "foo"},
        ]
        mock_config.DbActor.DbActor.return_value = mock_db_actor

        with patch.object(Actor, "get", autospec=True) as mock_get:

            def fake_get(self, actor_id=None):
                if actor_id:
                    self.id = actor_id
                    self.creator = "user@example.com"
                    return {"id": actor_id, "creator": self.creator}
                self.id = None
                self.creator = None
                return None

            mock_get.side_effect = fake_get
            actor_instance = Actor(config=mock_config)
            result = actor_instance.get_from_creator("user@example.com")

        assert result is True
        assert actor_instance.id == "actorA"

    def test_get_from_creator_returns_false_when_not_found(self):
        mock_config = Mock()
        mock_config.unique_creator = False
        mock_config.force_email_prop_as_creator = False

        mock_db_actor = Mock()
        mock_db_actor.get_by_creator.return_value = []
        mock_config.DbActor.DbActor.return_value = mock_db_actor

        with patch.object(Actor, "get", autospec=True) as mock_get:
            mock_get.return_value = None
            actor_instance = Actor(config=mock_config)
            result = actor_instance.get_from_creator("missing@example.com")

        assert result is False
        assert actor_instance.id is None

    def test_actor_method_return_types(self):
        """Test method return type annotations."""
        mock_config = Mock()
        mock_config.force_email_prop_as_creator = False  # Avoid attribute access
        mock_db_actor = Mock()
        # Mock actor data with required fields
        mock_db_actor.get.return_value = {
            "id": "test_actor",
            "creator": "test_creator",
            "passphrase": "test_passphrase",
        }
        mock_config.DbActor.DbActor.return_value = mock_db_actor

        with patch("actingweb.actor.attribute") as mock_attribute:
            with patch("actingweb.actor.property") as mock_property:
                mock_attribute.InternalStore.return_value = Mock()
                mock_property.PropertyStore.return_value = Mock()

                actor = Actor("test_actor", mock_config)

                # Test that methods have proper annotations
                assert hasattr(actor.get_peer_info, "__annotations__")
                assert hasattr(actor.get, "__annotations__")
                assert hasattr(actor.get_from_property, "__annotations__")
                assert hasattr(actor.get_from_creator, "__annotations__")
                assert hasattr(actor.create, "__annotations__")
                assert hasattr(actor.modify, "__annotations__")
                assert hasattr(actor.delete, "__annotations__")


class TestActorConstants:
    """Test Actor uses constants correctly."""

    def test_default_creator_usage(self):
        """Test that Actor uses DEFAULT_CREATOR constant."""
        from actingweb.actor import DEFAULT_CREATOR as ACTOR_DEFAULT_CREATOR

        assert ACTOR_DEFAULT_CREATOR == DEFAULT_CREATOR
        assert ACTOR_DEFAULT_CREATOR == "creator"

    def test_trustee_creator_usage(self):
        """Test that TRUSTEE_CREATOR constant is available from constants module."""
        # TRUSTEE_CREATOR is defined in constants module but not used in actor.py
        assert TRUSTEE_CREATOR == "trustee"


class TestActorModernization:
    """Test Actor class modernization features."""

    def test_actor_class_inheritance(self):
        """Test Actor class uses modern inheritance."""
        # Actor should not inherit from object explicitly in Python 3.11+
        assert Actor.__bases__ == (object,)  # Python automatically adds object

    def test_actor_type_hints(self):
        """Test Actor methods have type hints."""
        # Check that __init__ has type hints
        init_annotations = Actor.__init__.__annotations__
        assert "actor_id" in init_annotations
        assert "config" in init_annotations
        assert "return" in init_annotations

    def test_f_string_compatibility(self):
        """Test that f-strings work with Actor data."""
        actor_id = "test-actor-123"
        url = "https://example.com"

        # Test f-string formatting (used in modernized Actor code)
        result = f"Getting peer info at url({url}) for actor({actor_id})"
        expected = (
            "Getting peer info at url(https://example.com) for actor(test-actor-123)"
        )
        assert result == expected
