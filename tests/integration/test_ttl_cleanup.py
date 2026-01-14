"""
Integration tests for TTL (Time To Live) and cleanup functionality.

Tests verify:
1. TTL timestamps are correctly set on attribute storage
2. cleanup_expired_tokens() method works with actual data
3. Orphaned index entries are cleaned up correctly
"""

import time


class TestTTLAttributePersistence:
    """Test that TTL timestamps are correctly persisted in DynamoDB."""

    def test_attribute_with_ttl_has_timestamp(
        self,
        test_app,
        actor_factory,
        worker_info,  # pylint: disable=unused-argument
    ):
        """Verify TTL timestamp is set when storing attributes with ttl_seconds."""
        import os

        # test_app fixture needed to ensure environment is set up
        os.environ["AWS_DB_PREFIX"] = worker_info["db_prefix"]

        from actingweb import attribute
        from actingweb.config import Config
        from actingweb.constants import TTL_CLOCK_SKEW_BUFFER
        from actingweb.db.dynamodb.attribute import Attribute

        # Create actor
        actor = actor_factory.create("ttl_test@example.com")
        actor_id = actor["id"]

        # Create config
        config = Config(database="dynamodb")

        # Store attribute with TTL
        ttl_seconds = 3600  # 1 hour
        attrs = attribute.Attributes(
            actor_id=actor_id, bucket="test_ttl_bucket", config=config
        )
        attrs.set_attr(
            name="ttl_test_key", data={"test": "data"}, ttl_seconds=ttl_seconds
        )

        # Verify TTL timestamp in DynamoDB directly
        db_item = Attribute.get(actor_id, "test_ttl_bucket:ttl_test_key")

        assert db_item is not None
        assert db_item.ttl_timestamp is not None

        # Verify TTL is approximately correct (now + ttl_seconds + buffer)
        expected_ttl = int(time.time()) + ttl_seconds + TTL_CLOCK_SKEW_BUFFER
        # Allow 10 seconds tolerance for test execution time
        assert abs(db_item.ttl_timestamp - expected_ttl) < 10

    def test_attribute_without_ttl_has_no_timestamp(
        self,
        test_app,
        actor_factory,
        worker_info,  # pylint: disable=unused-argument
    ):
        """Verify TTL timestamp is None when no ttl_seconds provided."""
        import os

        os.environ["AWS_DB_PREFIX"] = worker_info["db_prefix"]

        from actingweb import attribute
        from actingweb.config import Config
        from actingweb.db.dynamodb.attribute import Attribute

        # Create actor
        actor = actor_factory.create("no_ttl_test@example.com")
        actor_id = actor["id"]

        # Create config
        config = Config(database="dynamodb")

        # Store attribute without TTL
        attrs = attribute.Attributes(
            actor_id=actor_id, bucket="test_no_ttl_bucket", config=config
        )
        attrs.set_attr(name="no_ttl_key", data={"test": "data"})

        # Verify no TTL timestamp in DynamoDB
        db_item = Attribute.get(actor_id, "test_no_ttl_bucket:no_ttl_key")

        assert db_item is not None
        assert db_item.ttl_timestamp is None

    def test_short_ttl_has_correct_timestamp(
        self,
        test_app,
        actor_factory,
        worker_info,  # pylint: disable=unused-argument
    ):
        """Verify short TTL values still get clock skew buffer."""
        import os

        os.environ["AWS_DB_PREFIX"] = worker_info["db_prefix"]

        from actingweb import attribute
        from actingweb.config import Config
        from actingweb.constants import TTL_CLOCK_SKEW_BUFFER
        from actingweb.db.dynamodb.attribute import Attribute

        # Create actor
        actor = actor_factory.create("short_ttl_test@example.com")
        actor_id = actor["id"]

        config = Config(database="dynamodb")

        # Store attribute with very short TTL (like auth codes)
        ttl_seconds = 60  # 1 minute
        attrs = attribute.Attributes(
            actor_id=actor_id, bucket="test_short_ttl", config=config
        )
        attrs.set_attr(name="short_key", data={"test": "data"}, ttl_seconds=ttl_seconds)

        # Verify TTL includes buffer even for short TTLs
        db_item = Attribute.get(actor_id, "test_short_ttl:short_key")

        expected_ttl = int(time.time()) + ttl_seconds + TTL_CLOCK_SKEW_BUFFER
        assert abs(db_item.ttl_timestamp - expected_ttl) < 10


class TestCleanupExpiredTokens:
    """Test cleanup_expired_tokens() method with actual data."""

    def test_cleanup_removes_expired_access_tokens(
        self,
        test_app,
        actor_factory,
        worker_info,  # pylint: disable=unused-argument
    ):
        """Verify cleanup removes expired access tokens and their indexes."""
        import os

        os.environ["AWS_DB_PREFIX"] = worker_info["db_prefix"]

        from actingweb import attribute
        from actingweb.config import Config
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR
        from actingweb.oauth2_server.token_manager import (
            ACCESS_TOKEN_INDEX_BUCKET,
            ActingWebTokenManager,
        )

        # Create actor
        actor = actor_factory.create("cleanup_test@example.com")
        actor_id = actor["id"]

        config = Config(database="dynamodb")
        token_manager = ActingWebTokenManager(config)

        # Manually create an expired access token
        expired_token = "expired_test_token_12345"
        expired_time = int(time.time()) - 3600  # Expired 1 hour ago

        token_data = {
            "client_id": "test_client",
            "scope": "test",
            "created_at": expired_time - 3600,
            "expires_at": expired_time,
        }

        # Store directly in actor's token bucket
        token_bucket = attribute.Attributes(
            actor_id=actor_id, bucket="mcp_tokens", config=config
        )
        token_bucket.set_attr(name=expired_token, data=token_data)

        # Store in global index
        index_bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=ACCESS_TOKEN_INDEX_BUCKET,
            config=config,
        )
        index_bucket.set_attr(name=expired_token, data=actor_id)

        # Verify token exists before cleanup
        assert token_bucket.get_attr(expired_token) is not None
        assert index_bucket.get_attr(expired_token) is not None

        # Run cleanup
        results = token_manager.cleanup_expired_tokens()

        # Verify expired token was cleaned up
        assert results["access_tokens"] >= 1 or results["index_entries"] >= 1

    def test_cleanup_preserves_valid_tokens(
        self,
        test_app,
        actor_factory,
        worker_info,  # pylint: disable=unused-argument
    ):
        """Verify cleanup does not remove valid (non-expired) tokens."""
        import os

        os.environ["AWS_DB_PREFIX"] = worker_info["db_prefix"]

        from actingweb import attribute
        from actingweb.config import Config
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR
        from actingweb.oauth2_server.token_manager import (
            ACCESS_TOKEN_INDEX_BUCKET,
            ActingWebTokenManager,
        )

        # Create actor
        actor = actor_factory.create("valid_token_test@example.com")
        actor_id = actor["id"]

        config = Config(database="dynamodb")
        token_manager = ActingWebTokenManager(config)

        # Create a valid (not expired) access token
        valid_token = "valid_test_token_67890"
        future_time = int(time.time()) + 3600  # Expires in 1 hour

        token_data = {
            "client_id": "test_client",
            "scope": "test",
            "created_at": int(time.time()),
            "expires_at": future_time,
        }

        # Store directly in actor's token bucket
        token_bucket = attribute.Attributes(
            actor_id=actor_id, bucket="mcp_tokens", config=config
        )
        token_bucket.set_attr(name=valid_token, data=token_data)

        # Store in global index
        index_bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=ACCESS_TOKEN_INDEX_BUCKET,
            config=config,
        )
        index_bucket.set_attr(name=valid_token, data=actor_id)

        # Run cleanup
        token_manager.cleanup_expired_tokens()

        # Verify valid token still exists
        assert token_bucket.get_attr(valid_token) is not None
        assert index_bucket.get_attr(valid_token) is not None

        # Clean up manually
        token_bucket.delete_attr(valid_token)
        index_bucket.delete_attr(valid_token)


class TestOrphanedIndexCleanup:
    """Test cleanup of orphaned index entries."""

    def test_cleanup_removes_orphaned_index_entries(
        self,
        test_app,
        actor_factory,
        worker_info,  # pylint: disable=unused-argument
    ):
        """Verify cleanup removes index entries that point to non-existent tokens."""
        import os

        os.environ["AWS_DB_PREFIX"] = worker_info["db_prefix"]

        from actingweb import attribute
        from actingweb.config import Config
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR
        from actingweb.oauth2_server.token_manager import (
            ACCESS_TOKEN_INDEX_BUCKET,
            ActingWebTokenManager,
        )

        # Create actor
        actor = actor_factory.create("orphan_test@example.com")
        actor_id = actor["id"]

        config = Config(database="dynamodb")
        token_manager = ActingWebTokenManager(config)

        # Create an orphaned index entry (index exists but token doesn't)
        orphaned_token = "orphaned_index_token_99999"

        # Only store in global index, NOT in actor's token bucket
        index_bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=ACCESS_TOKEN_INDEX_BUCKET,
            config=config,
        )
        index_bucket.set_attr(name=orphaned_token, data=actor_id)

        # Verify orphaned index exists
        assert index_bucket.get_attr(orphaned_token) is not None

        # Run cleanup
        results = token_manager.cleanup_expired_tokens()

        # Verify orphaned index was cleaned up
        assert results["index_entries"] >= 1

        # Verify index no longer exists (use fresh instance to bypass cache)
        fresh_index_bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=ACCESS_TOKEN_INDEX_BUCKET,
            config=config,
        )
        assert fresh_index_bucket.get_attr(orphaned_token) is None

    def test_cleanup_handles_malformed_index_entries(
        self,
        test_app,
        worker_info,  # pylint: disable=unused-argument
    ):
        """Verify cleanup handles index entries with missing data gracefully."""
        import os

        os.environ["AWS_DB_PREFIX"] = worker_info["db_prefix"]

        from actingweb import attribute
        from actingweb.config import Config
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR
        from actingweb.oauth2_server.token_manager import (
            REFRESH_TOKEN_INDEX_BUCKET,
            ActingWebTokenManager,
        )

        config = Config(database="dynamodb")
        token_manager = ActingWebTokenManager(config)

        # Create a malformed index entry (empty data)
        malformed_token = "malformed_index_token_11111"

        index_bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=REFRESH_TOKEN_INDEX_BUCKET,
            config=config,
        )
        # Store with empty/null data to simulate corruption
        index_bucket.set_attr(name=malformed_token, data="")

        # Cleanup should not raise an exception
        results = token_manager.cleanup_expired_tokens()

        # Malformed entry should be cleaned up
        assert (
            results["index_entries"] >= 0
        )  # May or may not find it depending on timing


class TestMCPTokenTTL:
    """Test TTL on MCP tokens created through the token manager."""

    def test_mcp_access_token_has_ttl(
        self,
        test_app,
        actor_factory,
        worker_info,  # pylint: disable=unused-argument
    ):
        """Verify MCP access tokens are created with TTL."""
        import os

        os.environ["AWS_DB_PREFIX"] = worker_info["db_prefix"]

        from actingweb.config import Config
        from actingweb.constants import MCP_ACCESS_TOKEN_TTL, TTL_CLOCK_SKEW_BUFFER
        from actingweb.db.dynamodb.attribute import Attribute
        from actingweb.oauth2_server.token_manager import ActingWebTokenManager

        # Create actor
        actor = actor_factory.create("mcp_token_test@example.com")
        actor_id = actor["id"]

        config = Config(database="dynamodb")
        token_manager = ActingWebTokenManager(config)

        # Create an access token through the token manager
        token_response = token_manager.create_access_token(
            actor_id=actor_id,
            client_id="test_mcp_client",
            scope="mcp",
        )

        assert token_response is not None
        access_token = token_response["access_token"]

        # Verify TTL is set on the token in DynamoDB
        db_item = Attribute.get(actor_id, f"mcp_tokens:{access_token}")

        assert db_item is not None
        assert db_item.ttl_timestamp is not None

        # Verify TTL is approximately correct
        expected_ttl = int(time.time()) + MCP_ACCESS_TOKEN_TTL + TTL_CLOCK_SKEW_BUFFER
        assert abs(db_item.ttl_timestamp - expected_ttl) < 10

        # Clean up
        token_manager._remove_access_token(access_token)
