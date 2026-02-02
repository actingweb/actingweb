"""
Integration test for peer profile extraction during subscription sync.

This test verifies that profile data (displayname, email) is correctly extracted
from RemotePeerStore and stored in PeerProfileStore during baseline sync.
"""

import os

import pytest
import requests

pytestmark = pytest.mark.xdist_group(name="peer_profile_extraction")


def test_peer_profile_extraction_during_sync(
    actor_factory, trust_helper, http_client, docker_services, setup_database, worker_info
):
    """Test that peer profile is extracted and stored during subscription baseline sync."""
    from actingweb.actor import Actor
    from actingweb.config import Config
    from actingweb.interface.actor_interface import ActorInterface
    from actingweb.peer_profile import get_peer_profile_store
    from actingweb.remote_storage import RemotePeerStore
    from actingweb.subscription_config import SubscriptionProcessingConfig

    # Create config with peer profile attributes enabled
    database_backend = os.environ.get("DATABASE_BACKEND", "dynamodb")

    # Set up environment for PostgreSQL schema isolation
    if database_backend == "postgresql":
        os.environ["PG_DB_HOST"] = os.environ.get("PG_DB_HOST", "localhost")
        os.environ["PG_DB_PORT"] = os.environ.get("PG_DB_PORT", "5433")
        os.environ["PG_DB_NAME"] = os.environ.get("PG_DB_NAME", "actingweb_test")
        os.environ["PG_DB_USER"] = os.environ.get("PG_DB_USER", "actingweb")
        os.environ["PG_DB_PASSWORD"] = os.environ.get("PG_DB_PASSWORD", "testpassword")
        os.environ["PG_DB_PREFIX"] = worker_info["db_prefix"]
        os.environ["PG_DB_SCHEMA"] = "public"

    config = Config(
        database=database_backend,
        peer_profile_attributes=["displayname", "email"],  # Enable peer profile extraction
    )
    print(f"\n✓ Created config with peer profiles enabled: {config.peer_profile_attributes}")

    # Create two actors via HTTP API
    actor_a = actor_factory.create("profile_test_a@example.com")
    actor_b = actor_factory.create("profile_test_b@example.com")
    print(f"✓ Created actors: A={actor_a['id']}, B={actor_b['id']}")

    # Set properties on actor_b (the peer)
    response = requests.put(
        f"{actor_b['url']}/properties/displayname",
        json={"value": "Test User B"},
        auth=(actor_b["creator"], actor_b["passphrase"]),
        timeout=5,
    )
    assert response.status_code in (200, 204)

    response = requests.put(
        f"{actor_b['url']}/properties/email",
        json={"value": "user_b@example.com"},
        auth=(actor_b["creator"], actor_b["passphrase"]),
        timeout=5,
    )
    assert response.status_code in (200, 204)
    print("✓ Set properties on actor B: displayname='Test User B', email='user_b@example.com'")

    # Establish trust from actor_a to actor_b
    trust_helper.establish(actor_a, actor_b, "friend", approve=True)
    print("✓ Established trust: A trusts B")

    # Grant permissions for properties from actor_b to actor_a
    response = requests.put(
        f"{actor_b['url']}/trust/friend/{actor_a['id']}/permissions",
        json={"properties": ["displayname", "email"]},
        auth=(actor_b["creator"], actor_b["passphrase"]),
        timeout=5,
    )
    assert response.status_code in (200, 201)
    print("✓ Granted permissions: B allows A to read displayname, email")

    # Create subscription from actor_a to actor_b
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
    assert response.status_code in (200, 201, 204)
    print("✓ Created subscription: A subscribes to B's properties")

    # Get subscription ID
    response = requests.get(
        f"{actor_a['url']}/subscriptions/{actor_b['id']}",
        auth=(actor_a["creator"], actor_a["passphrase"]),
        timeout=5,
    )
    assert response.status_code == 200
    sub_data = response.json()
    sub_id = None
    if "data" in sub_data and len(sub_data["data"]) > 0:
        sub_id = sub_data["data"][0]["subscriptionid"]
    assert sub_id, "Should have subscription ID"
    print(f"✓ Subscription ID: {sub_id}")

    # Load actor_a using SDK to trigger sync
    sdk_actor_a = Actor(config=config)
    sdk_actor_a.get(actor_id=actor_a["id"])

    actor_a_interface = ActorInterface(sdk_actor_a)
    sync_config = SubscriptionProcessingConfig(
        enabled=True,
        auto_storage=True,
    )

    # Sync the peer (this should fetch baseline data AND extract profile)
    print("\n🔍 Starting sync_peer (which triggers profile extraction)...")
    sync_result = actor_a_interface.subscriptions.sync_peer(
        peer_id=actor_b["id"],
        config=sync_config,
    )
    print(f"✓ Sync completed: success={sync_result.success}, error={sync_result.error}")
    print(f"  Subscriptions synced: {sync_result.subscriptions_synced}")
    print(f"  Total diffs processed: {sync_result.total_diffs_processed}")
    assert sync_result.success, f"Peer sync failed: {sync_result.error}"

    # Verify RemotePeerStore has the properties
    print("\n🔍 Checking RemotePeerStore...")
    remote_store = RemotePeerStore(
        actor=actor_a_interface,
        peer_id=actor_b["id"],
        validate_peer_id=False,
    )

    displayname_data = remote_store.get_value("displayname")
    print(f"  displayname from RemotePeerStore (raw): {displayname_data}")
    print(f"  displayname type: {type(displayname_data)}")
    print(f"  displayname is_dict: {isinstance(displayname_data, dict)}")
    if isinstance(displayname_data, dict):
        print(f"  displayname keys: {displayname_data.keys()}")
        print(f"  'value' in displayname_data: {'value' in displayname_data}")
    assert displayname_data is not None, "displayname should be stored in RemotePeerStore"

    # Properties are stored in wrapped format: {"value": "..."}
    if isinstance(displayname_data, dict) and "value" in displayname_data:
        actual_displayname = displayname_data["value"]
        print(f"  displayname (extracted from wrapped format): {actual_displayname}")
    else:
        actual_displayname = displayname_data
        print(f"  displayname (used directly): {actual_displayname}")

    assert (
        actual_displayname == "Test User B"
    ), f"Expected 'Test User B', got {actual_displayname} (type: {type(actual_displayname)})"

    email_data = remote_store.get_value("email")
    print(f"  email from RemotePeerStore (raw): {email_data}")
    assert email_data is not None, "email should be stored in RemotePeerStore"

    # Properties are stored in wrapped format: {"value": "..."}
    if isinstance(email_data, dict):
        if "value" in email_data:
            actual_email = email_data["value"]
        else:
            actual_email = email_data
    else:
        actual_email = email_data

    print(f"  email (extracted): {actual_email}")
    assert (
        actual_email == "user_b@example.com"
    ), f"Expected 'user_b@example.com', got {actual_email}"

    print("✓ All properties stored correctly in RemotePeerStore!")

    # Now verify PeerProfile was extracted and stored
    print("\n🔍 Checking PeerProfileStore...")
    profile_store = get_peer_profile_store(config)
    peer_profile = profile_store.get_profile(actor_a["id"], actor_b["id"])

    if peer_profile:
        print(
            f"  ✓ Profile found: displayname={peer_profile.displayname}, email={peer_profile.email}"
        )
        assert (
            peer_profile.displayname == "Test User B"
        ), f"Expected profile displayname 'Test User B', got {peer_profile.displayname}"
        assert (
            peer_profile.email == "user_b@example.com"
        ), f"Expected profile email 'user_b@example.com', got {peer_profile.email}"
        print("\n✅ SUCCESS: Peer profile extracted and stored correctly!")
    else:
        print("  ❌ ERROR: Profile NOT found in PeerProfileStore!")
        print(f"  Looking for: actor_id={actor_a['id']}, peer_id={actor_b['id']}")
        raise AssertionError(
            "Peer profile should be extracted and stored during subscription sync"
        )
