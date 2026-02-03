"""
Peer Permissions Unit Tests.

Pure unit tests for PeerPermissions dataclass and related logic.
No DynamoDB required.

References:
- actingweb/peer_permissions.py - PeerPermissions dataclass and utility functions
"""


class TestPeerPermissionsDataclass:
    """Test PeerPermissions dataclass functionality."""

    def test_create_basic_permissions(self):
        """Test creating a basic PeerPermissions with required fields."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
        )

        assert permissions.actor_id == "actor123"
        assert permissions.peer_id == "peer456"
        assert permissions.properties is None
        assert permissions.methods is None
        assert permissions.actions is None
        assert permissions.tools is None
        assert permissions.resources is None
        assert permissions.prompts is None
        assert permissions.extra_attributes == {}
        assert permissions.fetched_at is None
        assert permissions.fetch_error is None

    def test_create_permissions_with_properties(self):
        """Test creating PeerPermissions with property permissions."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*", "profile/*"],
                "operations": ["read", "subscribe"],
                "excluded_patterns": ["memory_private_*"],
            },
        )

        assert permissions.properties is not None
        assert permissions.properties["patterns"] == ["memory_*", "profile/*"]
        assert permissions.properties["operations"] == ["read", "subscribe"]
        assert permissions.properties["excluded_patterns"] == ["memory_private_*"]

    def test_create_permissions_with_methods(self):
        """Test creating PeerPermissions with method permissions."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            methods={
                "allowed": ["sync_*", "get_*"],
                "denied": ["delete_*"],
            },
        )

        assert permissions.methods is not None
        assert permissions.methods["allowed"] == ["sync_*", "get_*"]
        assert permissions.methods["denied"] == ["delete_*"]

    def test_create_permissions_with_tools(self):
        """Test creating PeerPermissions with MCP tool permissions."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            tools={
                "allowed": ["search", "fetch", "create_note"],
                "denied": ["delete_*"],
            },
        )

        assert permissions.tools is not None
        assert permissions.tools["allowed"] == ["search", "fetch", "create_note"]
        assert permissions.tools["denied"] == ["delete_*"]

    def test_create_permissions_with_metadata(self):
        """Test creating PeerPermissions with metadata fields."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            fetched_at="2026-01-22T10:00:00Z",
            fetch_error="Connection refused",
        )

        assert permissions.fetched_at == "2026-01-22T10:00:00Z"
        assert permissions.fetch_error == "Connection refused"


class TestPeerPermissionsMethods:
    """Test PeerPermissions instance methods."""

    def test_get_permissions_key(self):
        """Test that get_permissions_key returns correct format."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
        )

        assert permissions.get_permissions_key() == "actor123:peer456"

    def test_validate_valid_permissions(self):
        """Test validation passes for valid permissions."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
        )

        assert permissions.validate() is True

    def test_validate_missing_actor_id(self):
        """Test validation fails when actor_id is missing."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="",  # Empty string
            peer_id="peer456",
        )

        assert permissions.validate() is False

    def test_validate_missing_peer_id(self):
        """Test validation fails when peer_id is missing."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="",  # Empty string
        )

        assert permissions.validate() is False


class TestPeerPermissionsAccessChecking:
    """Test PeerPermissions access checking methods."""

    def test_has_property_access_no_properties(self):
        """Test has_property_access returns None when no properties defined."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
        )

        assert permissions.has_property_access("memory_travel", "read") is None

    def test_has_property_access_allowed(self):
        """Test has_property_access returns True for allowed pattern."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read", "subscribe"],
            },
        )

        assert permissions.has_property_access("memory_travel", "read") is True
        assert permissions.has_property_access("memory_work", "subscribe") is True

    def test_has_property_access_denied_by_excluded_pattern(self):
        """Test has_property_access returns False for excluded pattern."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read"],
                "excluded_patterns": ["memory_private_*"],
            },
        )

        # memory_private_* is excluded
        assert (
            permissions.has_property_access("memory_private_journal", "read") is False
        )
        # memory_* is allowed but not memory_private_*
        assert permissions.has_property_access("memory_travel", "read") is True

    def test_has_property_access_operation_not_allowed(self):
        """Test has_property_access returns None for disallowed operation."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read"],  # Only read allowed, not write
            },
        )

        # Operation not in allowed list
        assert permissions.has_property_access("memory_travel", "write") is None

    def test_has_property_access_pattern_not_matched(self):
        """Test has_property_access returns None for non-matching pattern."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read"],
            },
        )

        # Pattern doesn't match memory_*
        assert permissions.has_property_access("profile_name", "read") is None

    def test_has_method_access_no_methods(self):
        """Test has_method_access returns None when no methods defined."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
        )

        assert permissions.has_method_access("sync_data") is None

    def test_has_method_access_allowed(self):
        """Test has_method_access returns True for allowed method."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            methods={
                "allowed": ["sync_*", "get_*"],
                "denied": [],
            },
        )

        assert permissions.has_method_access("sync_data") is True
        assert permissions.has_method_access("get_profile") is True

    def test_has_method_access_denied(self):
        """Test has_method_access returns False for denied method."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            methods={
                "allowed": ["*"],  # Allow all
                "denied": ["delete_*"],  # Except delete
            },
        )

        # delete_* is denied, takes precedence over allow
        assert permissions.has_method_access("delete_user") is False
        assert permissions.has_method_access("get_user") is True

    def test_has_method_access_not_matched(self):
        """Test has_method_access returns None for non-matching pattern."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            methods={
                "allowed": ["sync_*"],
                "denied": [],
            },
        )

        # Pattern doesn't match sync_*
        assert permissions.has_method_access("get_user") is None

    def test_has_tool_access_no_tools(self):
        """Test has_tool_access returns None when no tools defined."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
        )

        assert permissions.has_tool_access("search") is None

    def test_has_tool_access_allowed(self):
        """Test has_tool_access returns True for allowed tool."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            tools={
                "allowed": ["search", "fetch"],
                "denied": [],
            },
        )

        assert permissions.has_tool_access("search") is True
        assert permissions.has_tool_access("fetch") is True

    def test_has_tool_access_denied(self):
        """Test has_tool_access returns False for denied tool."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            tools={
                "allowed": ["*"],
                "denied": ["delete_*"],
            },
        )

        assert permissions.has_tool_access("delete_memory") is False
        assert permissions.has_tool_access("search") is True


class TestPeerPermissionsSerialization:
    """Test PeerPermissions serialization (to_dict/from_dict)."""

    def test_to_dict_basic(self):
        """Test converting basic permissions to dictionary."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
        )

        data = permissions.to_dict()

        assert data["actor_id"] == "actor123"
        assert data["peer_id"] == "peer456"
        assert data["properties"] is None
        assert data["methods"] is None
        assert data["actions"] is None
        assert data["tools"] is None
        assert data["resources"] is None
        assert data["prompts"] is None
        assert data["extra_attributes"] == {}
        assert data["fetched_at"] is None
        assert data["fetch_error"] is None

    def test_to_dict_full(self):
        """Test converting full permissions to dictionary."""
        from actingweb.peer_permissions import PeerPermissions

        permissions = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read"],
            },
            methods={
                "allowed": ["sync_*"],
                "denied": [],
            },
            tools={
                "allowed": ["search"],
                "denied": [],
            },
            fetched_at="2026-01-22T10:00:00Z",
        )

        data = permissions.to_dict()

        assert data["actor_id"] == "actor123"
        assert data["peer_id"] == "peer456"
        assert data["properties"]["patterns"] == ["memory_*"]
        assert data["methods"]["allowed"] == ["sync_*"]
        assert data["tools"]["allowed"] == ["search"]
        assert data["fetched_at"] == "2026-01-22T10:00:00Z"

    def test_from_dict_basic(self):
        """Test creating permissions from basic dictionary."""
        from actingweb.peer_permissions import PeerPermissions

        data = {
            "actor_id": "actor123",
            "peer_id": "peer456",
            "properties": None,
            "methods": None,
            "actions": None,
            "tools": None,
            "resources": None,
            "prompts": None,
            "extra_attributes": {},
            "fetched_at": None,
            "fetch_error": None,
        }

        permissions = PeerPermissions.from_dict(data)

        assert permissions.actor_id == "actor123"
        assert permissions.peer_id == "peer456"
        assert permissions.properties is None

    def test_from_dict_full(self):
        """Test creating permissions from full dictionary."""
        from actingweb.peer_permissions import PeerPermissions

        data = {
            "actor_id": "actor123",
            "peer_id": "peer456",
            "properties": {
                "patterns": ["memory_*"],
                "operations": ["read"],
            },
            "methods": {
                "allowed": ["sync_*"],
                "denied": [],
            },
            "actions": None,
            "tools": {
                "allowed": ["search"],
                "denied": [],
            },
            "resources": None,
            "prompts": None,
            "extra_attributes": {},
            "fetched_at": "2026-01-22T10:00:00Z",
            "fetch_error": None,
        }

        permissions = PeerPermissions.from_dict(data)

        assert permissions.actor_id == "actor123"
        assert permissions.peer_id == "peer456"
        assert permissions.properties is not None
        assert permissions.properties["patterns"] == ["memory_*"]
        assert permissions.methods is not None
        assert permissions.methods["allowed"] == ["sync_*"]
        assert permissions.tools is not None
        assert permissions.tools["allowed"] == ["search"]
        assert permissions.fetched_at == "2026-01-22T10:00:00Z"

    def test_round_trip_serialization(self):
        """Test that to_dict -> from_dict preserves all data."""
        from actingweb.peer_permissions import PeerPermissions

        original = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*", "profile/*"],
                "operations": ["read", "write", "subscribe"],
                "excluded_patterns": ["memory_private_*"],
            },
            methods={
                "allowed": ["sync_*", "get_*"],
                "denied": ["delete_*"],
            },
            actions={
                "allowed": ["refresh"],
                "denied": [],
            },
            tools={
                "allowed": ["search", "fetch"],
                "denied": ["delete_*"],
            },
            resources={
                "allowed": ["data://*"],
                "denied": [],
            },
            prompts={
                "allowed": ["*"],
            },
            extra_attributes={"custom_key": "custom_value"},
            fetched_at="2026-01-22T10:00:00Z",
            fetch_error="Some warning",
        )

        # Round trip
        data = original.to_dict()
        restored = PeerPermissions.from_dict(data)

        assert restored.actor_id == original.actor_id
        assert restored.peer_id == original.peer_id
        assert restored.properties == original.properties
        assert restored.methods == original.methods
        assert restored.actions == original.actions
        assert restored.tools == original.tools
        assert restored.resources == original.resources
        assert restored.prompts == original.prompts
        assert restored.extra_attributes == original.extra_attributes
        assert restored.fetched_at == original.fetched_at
        assert restored.fetch_error == original.fetch_error


class TestGlobMatching:
    """Test the glob pattern matching functionality."""

    def test_exact_match(self):
        """Test exact string matching."""
        from actingweb.peer_permissions import PeerPermissions

        perm = PeerPermissions(actor_id="a", peer_id="b")

        assert perm._glob_match("search", "search") is True
        assert perm._glob_match("search", "fetch") is False

    def test_wildcard_match(self):
        """Test wildcard (*) matching."""
        from actingweb.peer_permissions import PeerPermissions

        perm = PeerPermissions(actor_id="a", peer_id="b")

        assert perm._glob_match("memory_travel", "memory_*") is True
        assert perm._glob_match("memory_work", "memory_*") is True
        assert perm._glob_match("profile_name", "memory_*") is False

    def test_prefix_wildcard(self):
        """Test prefix with wildcard."""
        from actingweb.peer_permissions import PeerPermissions

        perm = PeerPermissions(actor_id="a", peer_id="b")

        assert perm._glob_match("sync_data", "sync_*") is True
        assert perm._glob_match("get_data", "sync_*") is False

    def test_suffix_wildcard(self):
        """Test suffix with wildcard."""
        from actingweb.peer_permissions import PeerPermissions

        perm = PeerPermissions(actor_id="a", peer_id="b")

        assert perm._glob_match("delete_user", "*_user") is True
        assert perm._glob_match("delete_data", "*_user") is False

    def test_star_matches_everything(self):
        """Test that * alone matches everything."""
        from actingweb.peer_permissions import PeerPermissions

        perm = PeerPermissions(actor_id="a", peer_id="b")

        assert perm._glob_match("anything", "*") is True
        assert perm._glob_match("", "*") is True

    def test_question_mark_single_char(self):
        """Test that ? matches single character."""
        from actingweb.peer_permissions import PeerPermissions

        perm = PeerPermissions(actor_id="a", peer_id="b")

        assert perm._glob_match("test1", "test?") is True
        assert perm._glob_match("test12", "test?") is False


class TestActingWebAppConfiguration:
    """Test ActingWebApp.with_peer_permissions() configuration."""

    def test_peer_permissions_disabled_by_default(self):
        """Test that peer permissions caching is disabled by default."""
        from actingweb.interface.app import ActingWebApp

        app = ActingWebApp(
            aw_type="urn:test:example.com:test",
            fqdn="test.example.com",
        )

        assert app._peer_permissions_caching is False

    def test_with_peer_permissions_enables_caching(self):
        """Test with_peer_permissions() enables caching."""
        from actingweb.interface.app import ActingWebApp

        app = ActingWebApp(
            aw_type="urn:test:example.com:test",
            fqdn="test.example.com",
        ).with_peer_permissions()

        assert app._peer_permissions_caching is True

    def test_with_peer_permissions_explicit_false(self):
        """Test with_peer_permissions(enable=False) disables caching."""
        from actingweb.interface.app import ActingWebApp

        app = ActingWebApp(
            aw_type="urn:test:example.com:test",
            fqdn="test.example.com",
        ).with_peer_permissions(enable=False)

        assert app._peer_permissions_caching is False

    def test_config_propagates_peer_permissions_caching(self):
        """Test that peer_permissions_caching is propagated to Config."""
        from actingweb.interface.app import ActingWebApp

        app = ActingWebApp(
            aw_type="urn:test:example.com:test",
            fqdn="test.example.com",
        ).with_peer_permissions()

        config = app.get_config()
        assert config.peer_permissions_caching is True


class TestConfigPeerPermissions:
    """Test Config.peer_permissions_caching."""

    def test_config_default_peer_permissions_false(self):
        """Test that Config defaults peer_permissions_caching to False."""
        from actingweb.config import Config

        config = Config()
        assert config.peer_permissions_caching is False

    def test_config_accepts_peer_permissions_caching(self):
        """Test that Config accepts peer_permissions_caching parameter."""
        from actingweb.config import Config

        config = Config(peer_permissions_caching=True)
        assert config.peer_permissions_caching is True


class TestCallbackTypePermission:
    """Test CallbackType.PERMISSION enum value."""

    def test_callback_type_permission_exists(self):
        """Test that CallbackType.PERMISSION exists."""
        from actingweb.callback_processor import CallbackType

        assert hasattr(CallbackType, "PERMISSION")
        assert CallbackType.PERMISSION.value == "permission"

    def test_callback_type_values(self):
        """Test all CallbackType values."""
        from actingweb.callback_processor import CallbackType

        assert CallbackType.DIFF.value == "diff"
        assert CallbackType.RESYNC.value == "resync"
        assert CallbackType.PERMISSION.value == "permission"


class TestBucketNamingConvention:
    """Test that bucket constants use _ prefix."""

    def test_trust_types_bucket_has_prefix(self):
        """Test TRUST_TYPES_BUCKET uses _ prefix."""
        from actingweb.constants import TRUST_TYPES_BUCKET

        assert TRUST_TYPES_BUCKET.startswith("_")

    def test_peer_permissions_bucket_has_prefix(self):
        """Test PEER_PERMISSIONS_BUCKET uses _ prefix."""
        from actingweb.constants import PEER_PERMISSIONS_BUCKET

        assert PEER_PERMISSIONS_BUCKET.startswith("_")
        assert PEER_PERMISSIONS_BUCKET == "_peer_permissions"

    def test_peer_profiles_bucket_has_prefix(self):
        """Test PEER_PROFILES_BUCKET uses _ prefix."""
        from actingweb.constants import PEER_PROFILES_BUCKET

        assert PEER_PROFILES_BUCKET.startswith("_")

    def test_peer_capabilities_bucket_has_prefix(self):
        """Test PEER_CAPABILITIES_BUCKET uses _ prefix."""
        from actingweb.constants import PEER_CAPABILITIES_BUCKET

        assert PEER_CAPABILITIES_BUCKET.startswith("_")

    def test_oauth_session_bucket_has_prefix(self):
        """Test OAUTH_SESSION_BUCKET uses _ prefix."""
        from actingweb.constants import OAUTH_SESSION_BUCKET

        assert OAUTH_SESSION_BUCKET.startswith("_")


class TestDetectRevokedPropertyPatterns:
    """Test detect_revoked_property_patterns() function."""

    def test_no_old_permissions_returns_empty(self):
        """Test that None old_permissions returns empty list."""
        from actingweb.peer_permissions import (
            PeerPermissions,
            detect_revoked_property_patterns,
        )

        new_perms = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read"],
            },
        )

        revoked = detect_revoked_property_patterns(None, new_perms)
        assert revoked == []

    def test_no_revocations_returns_empty(self):
        """Test that same patterns returns empty list."""
        from actingweb.peer_permissions import (
            PeerPermissions,
            detect_revoked_property_patterns,
        )

        old_perms = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read"],
            },
        )
        new_perms = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read"],
            },
        )

        revoked = detect_revoked_property_patterns(old_perms, new_perms)
        assert revoked == []

    def test_detects_single_revoked_pattern(self):
        """Test that a single revoked pattern is detected."""
        from actingweb.peer_permissions import (
            PeerPermissions,
            detect_revoked_property_patterns,
        )

        old_perms = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*", "profile_*"],
                "operations": ["read"],
            },
        )
        new_perms = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*"],  # profile_* was revoked
                "operations": ["read"],
            },
        )

        revoked = detect_revoked_property_patterns(old_perms, new_perms)
        assert revoked == ["profile_*"]

    def test_detects_multiple_revoked_patterns(self):
        """Test that multiple revoked patterns are detected."""
        from actingweb.peer_permissions import (
            PeerPermissions,
            detect_revoked_property_patterns,
        )

        old_perms = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*", "profile_*", "settings_*"],
                "operations": ["read"],
            },
        )
        new_perms = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*"],  # profile_* and settings_* were revoked
                "operations": ["read"],
            },
        )

        revoked = detect_revoked_property_patterns(old_perms, new_perms)
        assert set(revoked) == {"profile_*", "settings_*"}

    def test_all_patterns_revoked(self):
        """Test when all patterns are revoked (new has empty patterns)."""
        from actingweb.peer_permissions import (
            PeerPermissions,
            detect_revoked_property_patterns,
        )

        old_perms = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*", "profile_*"],
                "operations": ["read"],
            },
        )
        new_perms = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": [],  # All revoked
                "operations": ["read"],
            },
        )

        revoked = detect_revoked_property_patterns(old_perms, new_perms)
        assert set(revoked) == {"memory_*", "profile_*"}

    def test_old_no_properties_returns_empty(self):
        """Test when old has no properties."""
        from actingweb.peer_permissions import (
            PeerPermissions,
            detect_revoked_property_patterns,
        )

        old_perms = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties=None,
        )
        new_perms = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read"],
            },
        )

        revoked = detect_revoked_property_patterns(old_perms, new_perms)
        assert revoked == []


class TestDetectPermissionChanges:
    """Test detect_permission_changes() function."""

    def test_initial_callback_marks_is_initial(self):
        """Test that first callback is marked as initial."""
        from actingweb.peer_permissions import (
            PeerPermissions,
            detect_permission_changes,
        )

        new_perms = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read"],
            },
        )

        changes = detect_permission_changes(None, new_perms)

        assert changes["is_initial"] is True
        assert changes["has_revocations"] is False
        assert changes["granted_patterns"] == ["memory_*"]
        assert changes["revoked_patterns"] == []

    def test_detects_revocations(self):
        """Test that revocations are detected."""
        from actingweb.peer_permissions import (
            PeerPermissions,
            detect_permission_changes,
        )

        old_perms = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*", "profile_*"],
                "operations": ["read"],
            },
        )
        new_perms = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read"],
            },
        )

        changes = detect_permission_changes(old_perms, new_perms)

        assert changes["is_initial"] is False
        assert changes["has_revocations"] is True
        assert changes["revoked_patterns"] == ["profile_*"]
        assert changes["granted_patterns"] == []

    def test_detects_new_grants(self):
        """Test that newly granted patterns are detected."""
        from actingweb.peer_permissions import (
            PeerPermissions,
            detect_permission_changes,
        )

        old_perms = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read"],
            },
        )
        new_perms = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*", "profile_*"],
                "operations": ["read"],
            },
        )

        changes = detect_permission_changes(old_perms, new_perms)

        assert changes["is_initial"] is False
        assert changes["has_revocations"] is False
        assert changes["revoked_patterns"] == []
        assert changes["granted_patterns"] == ["profile_*"]

    def test_detects_both_grants_and_revocations(self):
        """Test that both grants and revocations are detected."""
        from actingweb.peer_permissions import (
            PeerPermissions,
            detect_permission_changes,
        )

        old_perms = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*", "settings_*"],
                "operations": ["read"],
            },
        )
        new_perms = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": [
                    "memory_*",
                    "profile_*",
                ],  # settings_* revoked, profile_* added
                "operations": ["read"],
            },
        )

        changes = detect_permission_changes(old_perms, new_perms)

        assert changes["is_initial"] is False
        assert changes["has_revocations"] is True
        assert changes["revoked_patterns"] == ["settings_*"]
        assert changes["granted_patterns"] == ["profile_*"]


class TestNormalizePropertyPermission:
    """Test normalize_property_permission() function."""

    def test_none_returns_none(self):
        """Test that None input returns None."""
        from actingweb.peer_permissions import normalize_property_permission

        result = normalize_property_permission(None)
        assert result is None

    def test_list_normalized_to_dict(self):
        """Test that shorthand list format is normalized to spec-compliant dict."""
        from actingweb.peer_permissions import normalize_property_permission

        # Shorthand: ["pattern1", "pattern2"]
        result = normalize_property_permission(["memory_*", "profile/*"])

        # Expected: {"patterns": [...], "operations": ["read"]}
        assert isinstance(result, dict)
        assert result["patterns"] == ["memory_*", "profile/*"]
        assert result["operations"] == ["read"]

    def test_empty_list_normalized(self):
        """Test that empty list is normalized correctly."""
        from actingweb.peer_permissions import normalize_property_permission

        result = normalize_property_permission([])

        assert isinstance(result, dict)
        assert result["patterns"] == []
        assert result["operations"] == ["read"]

    def test_dict_passed_through(self):
        """Test that spec-compliant dict is passed through unchanged."""
        from actingweb.peer_permissions import normalize_property_permission

        input_dict = {
            "patterns": ["memory_*"],
            "operations": ["read", "write"],
            "excluded_patterns": ["memory_private_*"],
        }

        result = normalize_property_permission(input_dict)

        assert result == input_dict

    def test_dict_without_operations_passed_through(self):
        """Test that dict without operations is passed through."""
        from actingweb.peer_permissions import normalize_property_permission

        input_dict = {"patterns": ["memory_*"]}

        result = normalize_property_permission(input_dict)

        # Should pass through as-is (caller may want to add operations)
        assert result == {"patterns": ["memory_*"]}

    def test_empty_dict_passed_through(self):
        """Test that empty dict is passed through unchanged."""
        from actingweb.peer_permissions import normalize_property_permission

        result = normalize_property_permission({})

        assert result == {}


class TestAutoDeleteOnRevocationConfiguration:
    """Test auto_delete_on_revocation configuration."""

    def test_auto_delete_disabled_by_default(self):
        """Test that auto_delete_on_revocation is disabled by default."""
        from actingweb.interface.app import ActingWebApp

        app = ActingWebApp(
            aw_type="urn:test:example.com:test",
            fqdn="test.example.com",
        ).with_peer_permissions()

        assert app._auto_delete_on_revocation is False

    def test_auto_delete_can_be_enabled(self):
        """Test that auto_delete_on_revocation can be enabled."""
        from actingweb.interface.app import ActingWebApp

        app = ActingWebApp(
            aw_type="urn:test:example.com:test",
            fqdn="test.example.com",
        ).with_peer_permissions(auto_delete_on_revocation=True)

        assert app._auto_delete_on_revocation is True

    def test_config_propagates_auto_delete(self):
        """Test that auto_delete_on_revocation is propagated to Config."""
        from actingweb.interface.app import ActingWebApp

        app = ActingWebApp(
            aw_type="urn:test:example.com:test",
            fqdn="test.example.com",
        ).with_peer_permissions(auto_delete_on_revocation=True)

        config = app.get_config()
        assert config.auto_delete_on_revocation is True

    def test_config_default_auto_delete_false(self):
        """Test that Config defaults auto_delete_on_revocation to False."""
        from actingweb.config import Config

        config = Config()
        assert config.auto_delete_on_revocation is False
