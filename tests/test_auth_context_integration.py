"""Integration tests for authentication with request context."""

import logging
from collections.abc import Generator

import pytest

from actingweb import auth, request_context
from actingweb.config import Config
from actingweb.trust import Trust


class MockRequest:
    """Mock request object for testing."""

    def __init__(self, headers: dict[str, str] | None = None):
        self.headers = headers or {}


class MockAppRequest:
    """Mock appreq object for testing."""

    def __init__(self, headers: dict[str, str] | None = None):
        self.request = MockRequest(headers)


@pytest.fixture
def config() -> Config:
    """Create test config."""
    return Config()


@pytest.fixture
def test_actor(config: Config) -> Generator[tuple[str, str], None, None]:
    """Create a test actor with passphrase and return (actor_id, passphrase)."""
    import time

    actor_id = f"test_auth_{int(time.time() * 1000000)}"
    db_actor = config.DbActor.DbActor()  # type: ignore[attr-defined]
    success = db_actor.create(
        actor_id=actor_id, creator="testuser", passphrase="testpass123"
    )
    assert success, "Failed to create test actor"
    yield (actor_id, "testpass123")
    # Cleanup
    try:
        db_cleanup = config.DbActor.DbActor()  # type: ignore[attr-defined]
        db_cleanup.get(actor_id=actor_id)
        if db_cleanup.handle:
            db_cleanup.delete()
    except Exception:
        pass


@pytest.fixture
def peer_actor(config: Config) -> Generator[tuple[str, str], None, None]:
    """Create a peer actor and return (peer_id, passphrase)."""
    import time

    peer_id = f"peer_auth_{int(time.time() * 1000000)}"
    db_peer = config.DbActor.DbActor()  # type: ignore[attr-defined]
    success = db_peer.create(
        actor_id=peer_id, creator="peeruser", passphrase="peerpass123"
    )
    assert success, "Failed to create peer actor"
    yield (peer_id, "peerpass123")
    # Cleanup
    try:
        db_cleanup = config.DbActor.DbActor()  # type: ignore[attr-defined]
        db_cleanup.get(actor_id=peer_id)
        if db_cleanup.handle:
            db_cleanup.delete()
    except Exception:
        pass


@pytest.fixture
def trust_relationship(
    test_actor: tuple[str, str], peer_actor: tuple[str, str], config: Config
) -> Generator[tuple[str, str, str], None, None]:
    """Create a trust relationship and return (actor_id, peer_id, token)."""
    actor_id, _ = test_actor
    peer_id, _ = peer_actor
    trust = Trust(actor_id=actor_id, peerid=peer_id, config=config)
    success = trust.create(relationship="friend")
    assert success, "Failed to create trust relationship"
    # Get trust data to retrieve secret
    trust_data = trust.get()
    assert trust_data is not None, "Failed to get trust data"
    token = trust_data.get("secret", "")
    yield (actor_id, peer_id, token)
    # Cleanup
    try:
        trust.delete()
    except Exception:
        pass


class TestBasicAuthContext:
    """Tests for basic auth setting peer_id context."""

    def test_basic_auth_sets_empty_peer_id(
        self, test_actor: tuple[str, str], config: Config
    ) -> None:
        """Test that basic auth (creator) sets empty peer_id."""
        actor_id, passphrase = test_actor
        request_context.clear_request_context()

        # Set up basic auth request
        import base64

        credentials = base64.b64encode(f"testuser:{passphrase}".encode()).decode("utf-8")
        appreq = MockAppRequest(headers={"Authorization": f"Basic {credentials}"})

        auth_obj = auth.Auth(actor_id, auth_type="basic", config=config)
        auth_obj.check_authentication(appreq=appreq, path="/test")

        # Basic auth should succeed
        assert auth_obj.acl["authenticated"] is True
        assert auth_obj.acl["relationship"] == "creator"

        # Context should have empty peer_id
        assert request_context.get_peer_id() == ""

        request_context.clear_request_context()

    def test_basic_auth_appears_in_log_context(
        self, test_actor: tuple[str, str], config: Config, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that peer_id appears in log context after basic auth."""
        from actingweb.log_filter import add_context_filter_to_logger
        from actingweb.logging_config import get_context_format

        actor_id, passphrase = test_actor
        request_context.clear_request_context()
        request_context.set_request_id("test-request-123")

        # Set up logger
        logger = logging.getLogger("test_basic_auth_log")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()

        handler = logging.StreamHandler()
        logger.addHandler(handler)
        add_context_filter_to_logger(logger)
        formatter = logging.Formatter(get_context_format(include_context=True))
        handler.setFormatter(formatter)

        # Authenticate
        import base64

        credentials = base64.b64encode(f"testuser:{passphrase}".encode()).decode("utf-8")
        appreq = MockAppRequest(headers={"Authorization": f"Basic {credentials}"})

        auth_obj = auth.Auth(actor_id, auth_type="basic", config=config)
        auth_obj.check_authentication(appreq=appreq, path="/test")

        # Log a message
        with caplog.at_level(logging.INFO, logger="test_basic_auth_log"):
            logger.info("Authenticated as creator")

        # Check that context includes empty peer_id
        # Find the log record from our test logger (not actingweb.auth)
        test_records = [r for r in caplog.records if r.name == "test_basic_auth_log"]
        assert len(test_records) > 0
        assert hasattr(test_records[0], "context")
        # Format: [req_id:actor_id:peer_id] - peer_id should be empty (-)
        context_str: str = test_records[0].context  # type: ignore[attr-defined]
        # Check pattern: [<8chars>:<actor_id>:-]
        assert context_str.startswith("[")
        assert context_str.endswith(":-]")
        assert ":" in context_str

        # Cleanup
        logger.removeHandler(handler)
        request_context.clear_request_context()


class TestTokenAuthContext:
    """Tests for token auth setting peer_id context."""

    def test_token_auth_sets_peer_id(
        self, trust_relationship: tuple[str, str, str], config: Config
    ) -> None:
        """Test that token auth sets peer_id from trust."""
        actor_id, peer_id, token = trust_relationship
        request_context.clear_request_context()

        # Set up bearer token request
        appreq = MockAppRequest(headers={"Authorization": f"Bearer {token}"})

        auth_obj = auth.Auth(actor_id, auth_type="basic", config=config)
        auth_obj.check_authentication(appreq=appreq, path="/test")

        # Token auth should succeed
        assert auth_obj.acl["authenticated"] is True
        assert auth_obj.acl["peerid"] == peer_id

        # Context should have peer_id
        assert request_context.get_peer_id() == peer_id

        request_context.clear_request_context()

    def test_token_auth_appears_in_log_context(
        self,
        trust_relationship: tuple[str, str, str],
        config: Config,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that peer_id appears in log context after token auth."""
        from actingweb.log_filter import add_context_filter_to_logger
        from actingweb.logging_config import get_context_format

        actor_id, peer_id, token = trust_relationship
        request_context.clear_request_context()
        request_context.set_request_id("test-request-456")
        request_context.set_actor_id(actor_id)

        # Set up logger
        logger = logging.getLogger("test_token_auth_log")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()

        handler = logging.StreamHandler()
        logger.addHandler(handler)
        add_context_filter_to_logger(logger)
        formatter = logging.Formatter(get_context_format(include_context=True))
        handler.setFormatter(formatter)

        # Authenticate
        appreq = MockAppRequest(headers={"Authorization": f"Bearer {token}"})

        auth_obj = auth.Auth(actor_id, auth_type="basic", config=config)
        auth_obj.check_authentication(appreq=appreq, path="/test")

        # Log a message
        with caplog.at_level(logging.INFO, logger="test_token_auth_log"):
            logger.info("Authenticated via bearer token")

        # Check that context includes peer_id
        # Find the log record from our test logger (not actingweb.auth)
        test_records = [r for r in caplog.records if r.name == "test_token_auth_log"]
        assert len(test_records) > 0
        assert hasattr(test_records[0], "context")
        context_str: str = test_records[0].context  # type: ignore[attr-defined]

        # Format: [req_id:actor_id:peer_id]
        assert context_str.startswith("[")
        assert context_str.endswith("]")
        # peer_id should be last 8 chars or full if short
        short_peer = peer_id[-8:] if len(peer_id) > 8 else peer_id
        assert short_peer in context_str

        # Cleanup
        logger.removeHandler(handler)
        request_context.clear_request_context()

    def test_trustee_token_sets_empty_peer_id(self, config: Config) -> None:
        """Test that trustee token auth sets empty peer_id."""
        import time

        from actingweb.attribute import InternalStore

        # Create a trustee-type actor with strong passphrase
        trustee_id = f"trustee_auth_{int(time.time() * 1000000)}"
        trustee_passphrase = "veryLongAndSecurePassphraseWithHighEntropyForTesting12345!@#"

        db_trustee = config.DbActor.DbActor()  # type: ignore[attr-defined]
        success = db_trustee.create(
            actor_id=trustee_id,
            creator="trustee",
            passphrase=trustee_passphrase,
        )
        assert success, "Failed to create trustee actor"

        # Set trustee root
        store = InternalStore(actor_id=trustee_id, config=config)
        store.trustee_root = "https://trustee.example.com"

        request_context.clear_request_context()

        try:
            # Set up bearer token request with trustee passphrase
            appreq = MockAppRequest(
                headers={"Authorization": f"Bearer {trustee_passphrase}"}
            )

            auth_obj = auth.Auth(trustee_id, auth_type="basic", config=config)
            auth_obj.check_authentication(appreq=appreq, path="/test")

            # Trustee auth should succeed
            assert auth_obj.acl["authenticated"] is True
            assert auth_obj.acl["relationship"] == "trustee"

            # Context should have empty peer_id
            assert request_context.get_peer_id() == ""

        finally:
            # Cleanup
            try:
                db_cleanup = config.DbActor.DbActor()  # type: ignore[attr-defined]
                db_cleanup.get(actor_id=trustee_id)
                if db_cleanup.handle:
                    db_cleanup.delete()
            except Exception:
                pass
            request_context.clear_request_context()


class TestContextIsolationInAuth:
    """Tests for context isolation between authentication attempts."""

    def test_failed_auth_does_not_set_peer_id(
        self, test_actor: tuple[str, str], config: Config
    ) -> None:
        """Test that failed auth does not set peer_id."""
        actor_id, _ = test_actor
        request_context.clear_request_context()
        request_context.set_request_id("test-request-789")

        # Set up invalid bearer token request
        appreq = MockAppRequest(headers={"Authorization": "Bearer invalid-token-123"})

        auth_obj = auth.Auth(actor_id, auth_type="basic", config=config)
        auth_obj.check_authentication(appreq=appreq, path="/test")

        # Auth should fail
        assert auth_obj.acl["authenticated"] is False

        # Context should not have peer_id set
        assert request_context.get_peer_id() is None

        request_context.clear_request_context()

    def test_context_isolation_between_auth_attempts(
        self,
        trust_relationship: tuple[str, str, str],
        test_actor: tuple[str, str],
        config: Config,
    ) -> None:
        """Test that context is isolated between different auth attempts."""
        actor_id, peer_id, token = trust_relationship
        test_actor_id, test_passphrase = test_actor
        request_context.clear_request_context()

        # First auth - successful with peer_id
        appreq1 = MockAppRequest(headers={"Authorization": f"Bearer {token}"})
        auth_obj1 = auth.Auth(actor_id, auth_type="basic", config=config)
        auth_obj1.check_authentication(appreq=appreq1, path="/test")

        assert request_context.get_peer_id() == peer_id

        # Clear context (simulating end of request)
        request_context.clear_request_context()

        # Second auth - basic auth with different actor
        import base64

        credentials = base64.b64encode(f"testuser:{test_passphrase}".encode()).decode("utf-8")
        appreq2 = MockAppRequest(headers={"Authorization": f"Basic {credentials}"})
        auth_obj2 = auth.Auth(test_actor_id, auth_type="basic", config=config)
        auth_obj2.check_authentication(appreq=appreq2, path="/test")

        # Context should have empty peer_id (not the previous peer_id)
        assert request_context.get_peer_id() == ""

        request_context.clear_request_context()
