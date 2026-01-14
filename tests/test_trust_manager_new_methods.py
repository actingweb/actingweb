"""
Unit tests for newly added TrustManager developer API methods.

Tests the methods added during TrustHandler refactoring:
- create_verified_trust()
- modify_and_notify()
- delete_peer_trust()
- trustee_root property (getter and setter)
"""

from typing import Any

from actingweb.interface.trust_manager import TrustManager


class FakeConfig:
    """Minimal Config mock for testing."""

    def __init__(self) -> None:
        self.root = "https://example.com/"

    def new_token(self) -> str:
        return "secret-token-123"


class FakeStore:
    """Mock store with trustee_root property."""

    def __init__(self) -> None:
        self._trustee_root: str | None = None

    @property
    def trustee_root(self) -> str | None:
        return self._trustee_root

    @trustee_root.setter
    def trustee_root(self, value: str | None) -> None:
        self._trustee_root = value


class FakeCoreActor:
    """Minimal core Actor mock for testing."""

    def __init__(self) -> None:
        self.id = "actor_1"
        self.config = FakeConfig()
        self.store: FakeStore = FakeStore()
        self._trusts: dict[str, dict[str, Any]] = {}

    def create_verified_trust(
        self,
        baseuri: str,
        peerid: str,
        approved: bool,
        secret: str,
        verification_token: str | None,
        trust_type: str,
        peer_approved: bool,
        relationship: str,
        desc: str = "",
    ) -> dict[str, Any] | None:
        """Mock create_verified_trust for testing."""
        trust_data = {
            "baseuri": baseuri,
            "peerid": peerid,
            "approved": approved,
            "secret": secret,
            "verification_token": verification_token,
            "type": trust_type,
            "peer_approved": peer_approved,
            "relationship": relationship,
            "desc": desc,
        }
        self._trusts[peerid] = trust_data
        return trust_data

    def modify_trust_and_notify(
        self,
        peerid: str,
        relationship: str,
        baseuri: str = "",
        approved: bool | None = None,
        peer_approved: bool | None = None,
        desc: str = "",
    ) -> bool:
        """Mock modify_trust_and_notify for testing."""
        if peerid not in self._trusts:
            return False

        trust = self._trusts[peerid]
        trust["relationship"] = relationship
        if baseuri:
            trust["baseuri"] = baseuri
        if approved is not None:
            trust["approved"] = approved
        if peer_approved is not None:
            trust["peer_approved"] = peer_approved
        if desc:
            trust["desc"] = desc

        return True

    def delete_reciprocal_trust(self, peerid: str, delete_peer: bool = True) -> bool:
        """Mock delete_reciprocal_trust for testing."""
        if peerid in self._trusts:
            del self._trusts[peerid]
            return True
        return False


class TestTrustManagerCreateVerifiedTrust:
    """Tests for TrustManager.create_verified_trust()."""

    def test_create_verified_trust_basic(self):
        """Test creating a verified trust with basic parameters."""
        actor = FakeCoreActor()
        manager = TrustManager(actor)  # type: ignore[arg-type]

        result = manager.create_verified_trust(
            baseuri="https://peer.example.com/peer_1",
            peer_id="peer_1",
            approved=True,
            secret="shared-secret",
            verification_token="verify-123",
            trust_type="peer",
            peer_approved=True,
            relationship="friend",
            description="Test trust",
        )

        assert result is not None
        assert result["peerid"] == "peer_1"
        assert result["approved"] is True
        assert result["peer_approved"] is True
        assert result["relationship"] == "friend"
        assert result["secret"] == "shared-secret"
        assert result["verification_token"] == "verify-123"
        assert result["type"] == "peer"
        assert result["desc"] == "Test trust"

    def test_create_verified_trust_not_approved(self):
        """Test creating trust that's not yet approved."""
        actor = FakeCoreActor()
        manager = TrustManager(actor)  # type: ignore[arg-type]

        result = manager.create_verified_trust(
            baseuri="https://peer.example.com/peer_2",
            peer_id="peer_2",
            approved=False,
            secret="secret-456",
            verification_token=None,
            trust_type="peer",
            peer_approved=False,
            relationship="acquaintance",
        )

        assert result is not None
        assert result["approved"] is False
        assert result["peer_approved"] is False
        assert result["relationship"] == "acquaintance"

    def test_create_verified_trust_without_verification_token(self):
        """Test creating trust without verification token."""
        actor = FakeCoreActor()
        manager = TrustManager(actor)  # type: ignore[arg-type]

        result = manager.create_verified_trust(
            baseuri="https://peer.example.com/peer_3",
            peer_id="peer_3",
            approved=True,
            secret="secret-789",
            verification_token=None,
            trust_type="peer",
            peer_approved=True,
            relationship="colleague",
        )

        assert result is not None
        assert result["verification_token"] is None

    def test_create_verified_trust_empty_description(self):
        """Test creating trust with empty description."""
        actor = FakeCoreActor()
        manager = TrustManager(actor)  # type: ignore[arg-type]

        result = manager.create_verified_trust(
            baseuri="https://peer.example.com/peer_4",
            peer_id="peer_4",
            approved=True,
            secret="secret-xyz",
            verification_token="token",
            trust_type="peer",
            peer_approved=True,
            relationship="friend",
            description="",
        )

        assert result is not None
        assert result["desc"] == ""


class TestTrustManagerModifyAndNotify:
    """Tests for TrustManager.modify_and_notify()."""

    def test_modify_and_notify_relationship_only(self):
        """Test modifying just the relationship."""
        actor = FakeCoreActor()
        # Create initial trust
        actor._trusts["peer_1"] = {
            "peerid": "peer_1",
            "relationship": "acquaintance",
            "baseuri": "https://peer.example.com/peer_1",
        }

        manager = TrustManager(actor)  # type: ignore[arg-type]
        result = manager.modify_and_notify(peer_id="peer_1", relationship="friend")

        assert result is True
        assert actor._trusts["peer_1"]["relationship"] == "friend"

    def test_modify_and_notify_with_approval(self):
        """Test modifying trust with approval status."""
        actor = FakeCoreActor()
        actor._trusts["peer_2"] = {
            "peerid": "peer_2",
            "relationship": "friend",
            "approved": False,
        }

        manager = TrustManager(actor)  # type: ignore[arg-type]
        result = manager.modify_and_notify(
            peer_id="peer_2", relationship="friend", approved=True
        )

        assert result is True
        assert actor._trusts["peer_2"]["approved"] is True

    def test_modify_and_notify_with_peer_approval(self):
        """Test modifying peer approval status."""
        actor = FakeCoreActor()
        actor._trusts["peer_3"] = {
            "peerid": "peer_3",
            "relationship": "colleague",
            "peer_approved": False,
        }

        manager = TrustManager(actor)  # type: ignore[arg-type]
        result = manager.modify_and_notify(
            peer_id="peer_3",
            relationship="colleague",
            peer_approved=True,
        )

        assert result is True
        assert actor._trusts["peer_3"]["peer_approved"] is True

    def test_modify_and_notify_with_baseuri(self):
        """Test modifying trust with new baseuri."""
        actor = FakeCoreActor()
        actor._trusts["peer_4"] = {
            "peerid": "peer_4",
            "relationship": "friend",
            "baseuri": "https://old.example.com/peer_4",
        }

        manager = TrustManager(actor)  # type: ignore[arg-type]
        result = manager.modify_and_notify(
            peer_id="peer_4",
            relationship="friend",
            baseuri="https://new.example.com/peer_4",
        )

        assert result is True
        assert actor._trusts["peer_4"]["baseuri"] == "https://new.example.com/peer_4"

    def test_modify_and_notify_with_description(self):
        """Test modifying trust description."""
        actor = FakeCoreActor()
        actor._trusts["peer_5"] = {
            "peerid": "peer_5",
            "relationship": "friend",
            "desc": "Old description",
        }

        manager = TrustManager(actor)  # type: ignore[arg-type]
        result = manager.modify_and_notify(
            peer_id="peer_5",
            relationship="friend",
            description="New description",
        )

        assert result is True
        assert actor._trusts["peer_5"]["desc"] == "New description"

    def test_modify_and_notify_all_parameters(self):
        """Test modifying multiple trust parameters at once."""
        actor = FakeCoreActor()
        actor._trusts["peer_6"] = {
            "peerid": "peer_6",
            "relationship": "acquaintance",
            "approved": False,
            "peer_approved": False,
            "baseuri": "https://old.example.com/peer_6",
            "desc": "Old",
        }

        manager = TrustManager(actor)  # type: ignore[arg-type]
        result = manager.modify_and_notify(
            peer_id="peer_6",
            relationship="friend",
            baseuri="https://new.example.com/peer_6",
            approved=True,
            peer_approved=True,
            description="Updated trust",
        )

        assert result is True
        trust = actor._trusts["peer_6"]
        assert trust["relationship"] == "friend"
        assert trust["approved"] is True
        assert trust["peer_approved"] is True
        assert trust["baseuri"] == "https://new.example.com/peer_6"
        assert trust["desc"] == "Updated trust"

    def test_modify_and_notify_nonexistent_peer(self):
        """Test modifying non-existent trust returns False."""
        actor = FakeCoreActor()
        manager = TrustManager(actor)  # type: ignore[arg-type]

        result = manager.modify_and_notify(peer_id="peer_999", relationship="friend")

        assert result is False


class TestTrustManagerDeletePeerTrust:
    """Tests for TrustManager.delete_peer_trust()."""

    def test_delete_peer_trust_with_notification(self):
        """Test deleting trust with peer notification."""
        actor = FakeCoreActor()
        actor._trusts["peer_1"] = {
            "peerid": "peer_1",
            "relationship": "friend",
        }

        manager = TrustManager(actor)  # type: ignore[arg-type]
        result = manager.delete_peer_trust(peer_id="peer_1", notify_peer=True)

        assert result is True
        assert "peer_1" not in actor._trusts

    def test_delete_peer_trust_without_notification(self):
        """Test deleting trust without peer notification."""
        actor = FakeCoreActor()
        actor._trusts["peer_2"] = {
            "peerid": "peer_2",
            "relationship": "colleague",
        }

        manager = TrustManager(actor)  # type: ignore[arg-type]
        result = manager.delete_peer_trust(peer_id="peer_2", notify_peer=False)

        assert result is True
        assert "peer_2" not in actor._trusts

    def test_delete_peer_trust_default_notification(self):
        """Test deleting trust with default notification (True)."""
        actor = FakeCoreActor()
        actor._trusts["peer_3"] = {
            "peerid": "peer_3",
            "relationship": "friend",
        }

        manager = TrustManager(actor)  # type: ignore[arg-type]
        result = manager.delete_peer_trust(peer_id="peer_3")  # Default notify_peer=True

        assert result is True
        assert "peer_3" not in actor._trusts

    def test_delete_peer_trust_nonexistent(self):
        """Test deleting non-existent trust returns False."""
        actor = FakeCoreActor()
        manager = TrustManager(actor)  # type: ignore[arg-type]

        result = manager.delete_peer_trust(peer_id="peer_999")

        assert result is False


class TestTrustManagerTrusteeRootProperty:
    """Tests for TrustManager.trustee_root property."""

    def test_get_trustee_root_none(self):
        """Test getting trustee root when not set."""
        actor = FakeCoreActor()
        manager = TrustManager(actor)  # type: ignore[arg-type]

        assert manager.trustee_root is None

    def test_set_trustee_root(self):
        """Test setting trustee root."""
        actor = FakeCoreActor()
        manager = TrustManager(actor)  # type: ignore[arg-type]

        manager.trustee_root = "https://trustee.example.com/root"

        assert manager.trustee_root == "https://trustee.example.com/root"
        assert actor.store.trustee_root == "https://trustee.example.com/root"

    def test_get_trustee_root_after_set(self):
        """Test getting trustee root after setting it."""
        actor = FakeCoreActor()
        manager = TrustManager(actor)  # type: ignore[arg-type]

        manager.trustee_root = "https://trustee.example.com/root"
        value = manager.trustee_root

        assert value == "https://trustee.example.com/root"

    def test_set_trustee_root_to_none(self):
        """Test clearing trustee root by setting to None."""
        actor = FakeCoreActor()
        manager = TrustManager(actor)  # type: ignore[arg-type]

        # Set initial value
        manager.trustee_root = "https://trustee.example.com/root"
        assert manager.trustee_root is not None

        # Clear it
        manager.trustee_root = None
        assert manager.trustee_root is None

    def test_set_trustee_root_multiple_times(self):
        """Test changing trustee root value."""
        actor = FakeCoreActor()
        manager = TrustManager(actor)  # type: ignore[arg-type]

        manager.trustee_root = "https://trustee1.example.com/"
        assert manager.trustee_root == "https://trustee1.example.com/"

        manager.trustee_root = "https://trustee2.example.com/"
        assert manager.trustee_root == "https://trustee2.example.com/"

    def test_trustee_root_property_without_store(self):
        """Test trustee root when store is None."""
        actor = FakeCoreActor()
        actor.store = None  # type: ignore[assignment]
        manager = TrustManager(actor)  # type: ignore[arg-type]

        # Should return None without error
        assert manager.trustee_root is None


class TestTrustManagerIntegration:
    """Integration tests combining multiple TrustManager operations."""

    def test_create_modify_delete_workflow(self):
        """Test complete trust workflow: create, modify, delete."""
        actor = FakeCoreActor()
        manager = TrustManager(actor)  # type: ignore[arg-type]

        # Create trust
        trust = manager.create_verified_trust(
            baseuri="https://peer.example.com/peer_1",
            peer_id="peer_1",
            approved=False,
            secret="secret",
            verification_token="token",
            trust_type="peer",
            peer_approved=False,
            relationship="acquaintance",
        )
        assert trust is not None
        assert trust["approved"] is False

        # Modify to approve
        result = manager.modify_and_notify(
            peer_id="peer_1",
            relationship="friend",
            approved=True,
            peer_approved=True,
        )
        assert result is True
        assert actor._trusts["peer_1"]["approved"] is True
        assert actor._trusts["peer_1"]["relationship"] == "friend"

        # Delete trust
        deleted = manager.delete_peer_trust(peer_id="peer_1")
        assert deleted is True
        assert "peer_1" not in actor._trusts

    def test_trustee_root_with_trust_operations(self):
        """Test trustee root alongside trust operations."""
        actor = FakeCoreActor()
        manager = TrustManager(actor)  # type: ignore[arg-type]

        # Set trustee root
        manager.trustee_root = "https://trustee.example.com/"
        assert manager.trustee_root == "https://trustee.example.com/"

        # Create trust
        trust = manager.create_verified_trust(
            baseuri="https://peer.example.com/peer_1",
            peer_id="peer_1",
            approved=True,
            secret="secret",
            verification_token=None,
            trust_type="peer",
            peer_approved=True,
            relationship="friend",
        )
        assert trust is not None

        # Trustee root should still be set
        assert manager.trustee_root == "https://trustee.example.com/"

    def test_multiple_trust_modifications(self):
        """Test modifying same trust multiple times."""
        actor = FakeCoreActor()
        manager = TrustManager(actor)  # type: ignore[arg-type]

        # Create trust
        manager.create_verified_trust(
            baseuri="https://peer.example.com/peer_1",
            peer_id="peer_1",
            approved=False,
            secret="secret",
            verification_token=None,
            trust_type="peer",
            peer_approved=False,
            relationship="stranger",
        )

        # First modification
        manager.modify_and_notify(peer_id="peer_1", relationship="acquaintance")
        assert actor._trusts["peer_1"]["relationship"] == "acquaintance"

        # Second modification
        manager.modify_and_notify(
            peer_id="peer_1", relationship="friend", approved=True
        )
        assert actor._trusts["peer_1"]["relationship"] == "friend"
        assert actor._trusts["peer_1"]["approved"] is True

        # Third modification
        manager.modify_and_notify(
            peer_id="peer_1",
            relationship="close_friend",
            peer_approved=True,
            description="Best friend",
        )
        assert actor._trusts["peer_1"]["relationship"] == "close_friend"
        assert actor._trusts["peer_1"]["peer_approved"] is True
        assert actor._trusts["peer_1"]["desc"] == "Best friend"
