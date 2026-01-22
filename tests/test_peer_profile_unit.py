"""
Peer Profile Unit Tests.

Pure unit tests for PeerProfile dataclass and related logic.
No DynamoDB required.

References:
- actingweb/peer_profile.py - PeerProfile dataclass and utility functions
"""


class TestPeerProfileDataclass:
    """Test PeerProfile dataclass functionality."""

    def test_create_basic_profile(self):
        """Test creating a basic PeerProfile with required fields."""
        from actingweb.peer_profile import PeerProfile

        profile = PeerProfile(
            actor_id="actor123",
            peer_id="peer456",
        )

        assert profile.actor_id == "actor123"
        assert profile.peer_id == "peer456"
        assert profile.displayname is None
        assert profile.email is None
        assert profile.description is None
        assert profile.extra_attributes == {}
        assert profile.fetched_at is None
        assert profile.fetch_error is None

    def test_create_profile_with_standard_attributes(self):
        """Test creating a PeerProfile with standard attributes."""
        from actingweb.peer_profile import PeerProfile

        profile = PeerProfile(
            actor_id="actor123",
            peer_id="peer456",
            displayname="Test User",
            email="test@example.com",
            description="A test peer actor",
        )

        assert profile.displayname == "Test User"
        assert profile.email == "test@example.com"
        assert profile.description == "A test peer actor"

    def test_profile_with_extra_attributes(self):
        """Test creating a PeerProfile with extra custom attributes."""
        from actingweb.peer_profile import PeerProfile

        profile = PeerProfile(
            actor_id="actor123",
            peer_id="peer456",
            extra_attributes={
                "avatar_url": "https://example.com/avatar.png",
                "timezone": "UTC",
            },
        )

        assert profile.extra_attributes["avatar_url"] == "https://example.com/avatar.png"
        assert profile.extra_attributes["timezone"] == "UTC"

    def test_profile_with_metadata(self):
        """Test creating a PeerProfile with metadata fields."""
        from actingweb.peer_profile import PeerProfile

        profile = PeerProfile(
            actor_id="actor123",
            peer_id="peer456",
            fetched_at="2025-01-22T10:00:00",
            fetch_error="Connection refused",
        )

        assert profile.fetched_at == "2025-01-22T10:00:00"
        assert profile.fetch_error == "Connection refused"


class TestPeerProfileMethods:
    """Test PeerProfile instance methods."""

    def test_get_profile_key(self):
        """Test that get_profile_key returns correct format."""
        from actingweb.peer_profile import PeerProfile

        profile = PeerProfile(
            actor_id="actor123",
            peer_id="peer456",
        )

        assert profile.get_profile_key() == "actor123:peer456"

    def test_get_attribute_standard(self):
        """Test getting standard attributes by name."""
        from actingweb.peer_profile import PeerProfile

        profile = PeerProfile(
            actor_id="actor123",
            peer_id="peer456",
            displayname="Test User",
            email="test@example.com",
            description="A test description",
        )

        assert profile.get_attribute("displayname") == "Test User"
        assert profile.get_attribute("email") == "test@example.com"
        assert profile.get_attribute("description") == "A test description"

    def test_get_attribute_extra(self):
        """Test getting extra attributes by name."""
        from actingweb.peer_profile import PeerProfile

        profile = PeerProfile(
            actor_id="actor123",
            peer_id="peer456",
            extra_attributes={"avatar_url": "https://example.com/avatar.png"},
        )

        assert profile.get_attribute("avatar_url") == "https://example.com/avatar.png"

    def test_get_attribute_missing_returns_none(self):
        """Test that getting missing attribute returns None."""
        from actingweb.peer_profile import PeerProfile

        profile = PeerProfile(
            actor_id="actor123",
            peer_id="peer456",
        )

        assert profile.get_attribute("nonexistent") is None
        assert profile.get_attribute("displayname") is None

    def test_set_attribute_standard(self):
        """Test setting standard attributes by name."""
        from actingweb.peer_profile import PeerProfile

        profile = PeerProfile(
            actor_id="actor123",
            peer_id="peer456",
        )

        profile.set_attribute("displayname", "New Name")
        profile.set_attribute("email", "new@example.com")
        profile.set_attribute("description", "New description")

        assert profile.displayname == "New Name"
        assert profile.email == "new@example.com"
        assert profile.description == "New description"

    def test_set_attribute_extra(self):
        """Test setting extra attributes goes to extra_attributes dict."""
        from actingweb.peer_profile import PeerProfile

        profile = PeerProfile(
            actor_id="actor123",
            peer_id="peer456",
        )

        profile.set_attribute("avatar_url", "https://example.com/avatar.png")
        profile.set_attribute("timezone", "UTC")

        assert profile.extra_attributes["avatar_url"] == "https://example.com/avatar.png"
        assert profile.extra_attributes["timezone"] == "UTC"

    def test_validate_valid_profile(self):
        """Test validation passes for valid profile."""
        from actingweb.peer_profile import PeerProfile

        profile = PeerProfile(
            actor_id="actor123",
            peer_id="peer456",
        )

        assert profile.validate() is True

    def test_validate_missing_actor_id(self):
        """Test validation fails when actor_id is missing."""
        from actingweb.peer_profile import PeerProfile

        profile = PeerProfile(
            actor_id="",  # Empty string
            peer_id="peer456",
        )

        assert profile.validate() is False

    def test_validate_missing_peer_id(self):
        """Test validation fails when peer_id is missing."""
        from actingweb.peer_profile import PeerProfile

        profile = PeerProfile(
            actor_id="actor123",
            peer_id="",  # Empty string
        )

        assert profile.validate() is False


class TestPeerProfileSerialization:
    """Test PeerProfile serialization (to_dict/from_dict)."""

    def test_to_dict_basic(self):
        """Test converting basic profile to dictionary."""
        from actingweb.peer_profile import PeerProfile

        profile = PeerProfile(
            actor_id="actor123",
            peer_id="peer456",
        )

        data = profile.to_dict()

        assert data["actor_id"] == "actor123"
        assert data["peer_id"] == "peer456"
        assert data["displayname"] is None
        assert data["email"] is None
        assert data["description"] is None
        assert data["extra_attributes"] == {}
        assert data["fetched_at"] is None
        assert data["fetch_error"] is None

    def test_to_dict_full(self):
        """Test converting full profile to dictionary."""
        from actingweb.peer_profile import PeerProfile

        profile = PeerProfile(
            actor_id="actor123",
            peer_id="peer456",
            displayname="Test User",
            email="test@example.com",
            description="A test description",
            extra_attributes={"avatar_url": "https://example.com/avatar.png"},
            fetched_at="2025-01-22T10:00:00",
            fetch_error=None,
        )

        data = profile.to_dict()

        assert data["actor_id"] == "actor123"
        assert data["peer_id"] == "peer456"
        assert data["displayname"] == "Test User"
        assert data["email"] == "test@example.com"
        assert data["description"] == "A test description"
        assert data["extra_attributes"]["avatar_url"] == "https://example.com/avatar.png"
        assert data["fetched_at"] == "2025-01-22T10:00:00"
        assert data["fetch_error"] is None

    def test_from_dict_basic(self):
        """Test creating profile from basic dictionary."""
        from actingweb.peer_profile import PeerProfile

        data = {
            "actor_id": "actor123",
            "peer_id": "peer456",
            "displayname": None,
            "email": None,
            "description": None,
            "extra_attributes": {},
            "fetched_at": None,
            "fetch_error": None,
        }

        profile = PeerProfile.from_dict(data)

        assert profile.actor_id == "actor123"
        assert profile.peer_id == "peer456"
        assert profile.displayname is None

    def test_from_dict_full(self):
        """Test creating profile from full dictionary."""
        from actingweb.peer_profile import PeerProfile

        data = {
            "actor_id": "actor123",
            "peer_id": "peer456",
            "displayname": "Test User",
            "email": "test@example.com",
            "description": "A test description",
            "extra_attributes": {"avatar_url": "https://example.com/avatar.png"},
            "fetched_at": "2025-01-22T10:00:00",
            "fetch_error": None,
        }

        profile = PeerProfile.from_dict(data)

        assert profile.actor_id == "actor123"
        assert profile.peer_id == "peer456"
        assert profile.displayname == "Test User"
        assert profile.email == "test@example.com"
        assert profile.description == "A test description"
        assert profile.extra_attributes["avatar_url"] == "https://example.com/avatar.png"
        assert profile.fetched_at == "2025-01-22T10:00:00"
        assert profile.fetch_error is None

    def test_round_trip_serialization(self):
        """Test that to_dict -> from_dict preserves all data."""
        from actingweb.peer_profile import PeerProfile

        original = PeerProfile(
            actor_id="actor123",
            peer_id="peer456",
            displayname="Test User",
            email="test@example.com",
            description="A test description",
            extra_attributes={
                "avatar_url": "https://example.com/avatar.png",
                "timezone": "UTC",
                "nested": {"key": "value"},
            },
            fetched_at="2025-01-22T10:00:00",
            fetch_error="Some error",
        )

        # Round trip
        data = original.to_dict()
        restored = PeerProfile.from_dict(data)

        assert restored.actor_id == original.actor_id
        assert restored.peer_id == original.peer_id
        assert restored.displayname == original.displayname
        assert restored.email == original.email
        assert restored.description == original.description
        assert restored.extra_attributes == original.extra_attributes
        assert restored.fetched_at == original.fetched_at
        assert restored.fetch_error == original.fetch_error


class TestActingWebAppConfiguration:
    """Test ActingWebApp.with_peer_profile() configuration."""

    def test_peer_profile_disabled_by_default(self):
        """Test that peer profile caching is disabled by default."""
        from actingweb.interface.app import ActingWebApp

        app = ActingWebApp(
            aw_type="urn:test:example.com:test",
            fqdn="test.example.com",
        )

        assert app._peer_profile_attributes is None

    def test_with_peer_profile_default_attributes(self):
        """Test with_peer_profile() sets default attributes."""
        from actingweb.interface.app import ActingWebApp

        app = (
            ActingWebApp(
                aw_type="urn:test:example.com:test",
                fqdn="test.example.com",
            )
            .with_peer_profile()
        )

        assert app._peer_profile_attributes == ["displayname", "email", "description"]

    def test_with_peer_profile_custom_attributes(self):
        """Test with_peer_profile() with custom attributes."""
        from actingweb.interface.app import ActingWebApp

        custom_attrs = ["displayname", "avatar_url", "timezone"]
        app = (
            ActingWebApp(
                aw_type="urn:test:example.com:test",
                fqdn="test.example.com",
            )
            .with_peer_profile(attributes=custom_attrs)
        )

        assert app._peer_profile_attributes == custom_attrs

    def test_with_peer_profile_empty_list_disables(self):
        """Test with_peer_profile() with empty list disables caching."""
        from actingweb.interface.app import ActingWebApp

        app = (
            ActingWebApp(
                aw_type="urn:test:example.com:test",
                fqdn="test.example.com",
            )
            .with_peer_profile(attributes=[])
        )

        # Empty list should be set, not None
        assert app._peer_profile_attributes == []

    def test_config_propagates_peer_profile_attributes(self):
        """Test that peer_profile_attributes is propagated to Config."""
        from actingweb.interface.app import ActingWebApp

        app = (
            ActingWebApp(
                aw_type="urn:test:example.com:test",
                fqdn="test.example.com",
            )
            .with_peer_profile(attributes=["displayname", "email"])
        )

        config = app.get_config()
        assert config.peer_profile_attributes == ["displayname", "email"]


class TestConfigPeerProfileAttributes:
    """Test Config.peer_profile_attributes."""

    def test_config_default_peer_profile_none(self):
        """Test that Config defaults peer_profile_attributes to None."""
        from actingweb.config import Config

        config = Config()
        assert config.peer_profile_attributes is None

    def test_config_accepts_peer_profile_attributes(self):
        """Test that Config accepts peer_profile_attributes parameter."""
        from actingweb.config import Config

        config = Config(peer_profile_attributes=["displayname", "email"])
        assert config.peer_profile_attributes == ["displayname", "email"]

    def test_config_peer_profile_empty_list(self):
        """Test that Config accepts empty list for peer_profile_attributes."""
        from actingweb.config import Config

        config = Config(peer_profile_attributes=[])
        assert config.peer_profile_attributes == []
