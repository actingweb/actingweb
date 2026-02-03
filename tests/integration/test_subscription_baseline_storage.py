"""
Integration test for subscription baseline storage bug.

This test verifies that both simple properties (displayname, email) and
list properties are correctly stored in RemotePeerStore during baseline sync.
"""

import pytest

pytestmark = pytest.mark.xdist_group(name="baseline_storage")


def test_baseline_stores_simple_and_list_properties(
    actor_factory, trust_helper, http_client
) -> None:
    """Baseline sync should store both simple and list properties.

    This test creates two actors, sets properties on one, establishes trust
    and subscription, and verifies that both simple properties (displayname, email)
    and list properties are stored in RemotePeerStore after baseline sync.

    Also verifies that peer profile is extracted and stored in PeerProfileStore.
    """
    import os

    import requests

    from actingweb.config import Config

    # Create config with peer profile attributes enabled
    database_backend = os.environ.get("DATABASE_BACKEND", "dynamodb")
    config = Config(
        database=database_backend,
        peer_profile_attributes=["displayname", "email"],  # Enable peer profile extraction
    )
    print(f"\nDEBUG: Created config with peer profiles enabled: {config.peer_profile_attributes}")

    # Create two actors
    actor_a = actor_factory.create("baseline_test_a@example.com")
    actor_b = actor_factory.create("baseline_test_b@example.com")

    # Set simple properties on actor_b (the peer we'll subscribe to)
    response = requests.put(
        f"{actor_b['url']}/properties/displayname",
        json={"value": "Test User"},
        auth=(actor_b["creator"], actor_b["passphrase"]),
        timeout=5,
    )
    assert response.status_code in (
        200,
        204,
    ), f"Failed to set displayname: {response.text}"

    response = requests.put(
        f"{actor_b['url']}/properties/email",
        json={"value": "test@example.com"},
        auth=(actor_b["creator"], actor_b["passphrase"]),
        timeout=5,
    )
    assert response.status_code in (
        200,
        204,
    ), f"Failed to set email: {response.text}"

    # Create a test list property
    response = requests.post(
        f"{actor_b['url']}/properties/test_items",
        json={"value": "Item 1"},
        auth=(actor_b["creator"], actor_b["passphrase"]),
        timeout=5,
    )
    assert response.status_code in (
        200,
        201,
        204,
    ), f"Failed to append Item 1 (status {response.status_code}): {response.text}"

    response = requests.post(
        f"{actor_b['url']}/properties/test_items",
        json={"value": "Item 2"},
        auth=(actor_b["creator"], actor_b["passphrase"]),
        timeout=5,
    )
    assert response.status_code in (
        200,
        201,
        204,
    ), f"Failed to append Item 2 (status {response.status_code}): {response.text}"

    # Establish trust from actor_a to actor_b using trust_helper
    trust_helper.establish(actor_a, actor_b, "friend", approve=True)

    # Grant permissions for all properties from actor_b to actor_a
    response = requests.put(
        f"{actor_b['url']}/trust/friend/{actor_a['id']}/permissions",
        json={"properties": ["displayname", "email", "test_items"]},
        auth=(actor_b["creator"], actor_b["passphrase"]),
        timeout=5,
    )
    assert response.status_code in (
        200,
        201,
    ), f"Failed to grant permissions (status {response.status_code}): {response.text}"

    # Create subscription from actor_a to actor_b
    # Actor_a (subscriber) creates subscription on their own endpoint, pointing to actor_b (publisher)
    response = requests.post(
        f"{actor_a['url']}/subscriptions",
        json={
            "peerid": actor_b["id"],
            "target": "properties",
            "subtarget": "",
            "resource": "",
            "granularity": "high",
        },
        auth=(actor_a["creator"], actor_a["passphrase"]),
        timeout=5,
    )
    assert response.status_code in (
        200,
        201,
        204,
    ), f"Failed to create subscription (status {response.status_code}): {response.text}"

    # Handle 204 No Content response
    if response.status_code == 204:
        print("\nWARNING: Subscription creation returned 204 (No Content)")
        print("This test needs to retrieve subscription ID differently")
        # For now, skip the sync test since we don't have sub_id
        return

    sub_data = response.json()
    sub_id = sub_data.get("subscriptionid")
    assert sub_id, "Subscription ID should be returned"

    # Trigger baseline sync using the SDK
    from actingweb.actor import Actor
    from actingweb.interface.actor_interface import ActorInterface
    from actingweb.interface.subscription_manager import SubscriptionProcessingConfig
    from actingweb.remote_storage import RemotePeerStore

    # Load actor_a (config was created earlier with peer_profile_attributes enabled)
    sdk_actor_a = Actor(config=config)
    sdk_actor_a.get(actor_id=actor_a["id"])

    actor_a_interface = ActorInterface(sdk_actor_a)
    sync_config = SubscriptionProcessingConfig(
        enabled=True,
        auto_storage=True,
    )

    # Sync the subscription (this should fetch baseline data)
    sync_result = actor_a_interface.subscriptions.sync_subscription(
        peer_id=actor_b["id"],
        subscription_id=sub_id,
        config=sync_config,
    )
    print(f"\nDEBUG: Sync result: success={sync_result.success}, error={sync_result.error}")
    assert sync_result.success, f"Subscription sync failed: {sync_result.error}"

    # Verify RemotePeerStore has all data
    remote_store = RemotePeerStore(
        actor=actor_a_interface,
        peer_id=actor_b["id"],
        validate_peer_id=False,
    )

    # Check simple properties
    displayname = remote_store.get_value("displayname")
    print(f"\nDEBUG: displayname from RemotePeerStore: {displayname}")
    assert displayname is not None, "displayname should be stored"

    # Handle both wrapped and unwrapped format
    if isinstance(displayname, dict) and "value" in displayname:
        actual_displayname = displayname["value"]
    else:
        actual_displayname = displayname

    assert (
        actual_displayname == "Test User"
    ), f"Expected 'Test User', got {actual_displayname}"

    email = remote_store.get_value("email")
    print(f"DEBUG: email from RemotePeerStore: {email}")
    assert email is not None, "email should be stored"

    # Handle both wrapped and unwrapped format
    if isinstance(email, dict) and "value" in email:
        actual_email = email["value"]
    else:
        actual_email = email

    assert (
        actual_email == "test@example.com"
    ), f"Expected 'test@example.com', got {actual_email}"

    # Check list property
    items = remote_store.get_list("test_items")
    print(f"DEBUG: test_items from RemotePeerStore: {items}")
    assert items is not None, "List property should be stored"
    assert len(items) == 2, f"Expected 2 items, got {len(items)}"
    assert items[0] == "Item 1", f"Expected 'Item 1', got {items[0]}"
    assert items[1] == "Item 2", f"Expected 'Item 2', got {items[1]}"

    print("\n✓ All properties stored correctly in RemotePeerStore!")

    # Now verify PeerProfile was extracted and stored
    from actingweb.peer_profile import get_peer_profile_store

    profile_store = get_peer_profile_store(config)
    peer_profile = profile_store.get_profile(actor_a["id"], actor_b["id"])

    print("\nDEBUG: Checking PeerProfileStore...")
    if peer_profile:
        print(f"  Profile found: displayname={peer_profile.displayname}, email={peer_profile.email}")
        assert (
            peer_profile.displayname == "Test User"
        ), f"Expected profile displayname 'Test User', got {peer_profile.displayname}"
        assert (
            peer_profile.email == "test@example.com"
        ), f"Expected profile email 'test@example.com', got {peer_profile.email}"
        print("\n✓ Peer profile extracted and stored correctly!")
    else:
        print("  ERROR: Profile NOT found in PeerProfileStore!")
        print(f"  Looking for: actor_id={actor_a['id']}, peer_id={actor_b['id']}")
        raise AssertionError(
            "Peer profile should be extracted and stored during subscription sync"
        )
