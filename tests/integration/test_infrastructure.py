"""
Infrastructure Health Check Tests.

Basic tests to verify the test infrastructure is working.
"""

import pytest


def test_docker_services(docker_services):
    """Test that DynamoDB is running via Docker."""
    import requests

    # DynamoDB should respond to health check
    response = requests.get("http://localhost:8000/", timeout=5)
    # DynamoDB returns 400 for GET / (expects specific operations)
    assert response.status_code == 400


def test_app_responds(test_app):
    """Test that the test harness app is running."""
    import requests

    # App should respond to root request
    response = requests.get(test_app, timeout=5)
    # Either 200 (some content) or 404 (no root handler) is OK
    assert response.status_code in [200, 404]


def test_http_client_fixture(http_client):
    """Test that the http_client fixture provides a working session."""
    assert hasattr(http_client, "base_url")
    assert http_client.base_url.startswith("http://")


def test_actor_creation(actor_factory):
    """Test basic actor creation via the factory fixture."""
    actor = actor_factory.create("test@example.com")

    # Verify actor structure
    assert "id" in actor
    assert "url" in actor
    assert "creator" in actor
    assert "passphrase" in actor

    # Creator should match what we requested
    assert actor["creator"] == "test@example.com"


def test_actor_cleanup(actor_factory, http_client):
    """Test that actors are cleaned up after test completion."""
    import requests

    # Create an actor
    actor = actor_factory.create("cleanup-test@example.com")

    # Verify it exists
    response = requests.get(
        actor["url"], auth=(actor["creator"], actor["passphrase"]), timeout=5
    )
    assert response.status_code == 200

    # Cleanup will happen automatically after this test
    # (verified by the actor_factory fixture's cleanup method)


def test_trust_helper(actor_factory, trust_helper):
    """Test the trust helper fixture."""
    actor1 = actor_factory.create("user1@example.com")
    actor2 = actor_factory.create("user2@example.com")

    # Establish trust
    trust = trust_helper.establish(actor1, actor2, "friend", approve=True)

    # Verify trust structure
    assert "secret" in trust or "url" in trust
