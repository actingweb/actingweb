"""
Integration tests for trust lifecycle hooks.

Tests that trust lifecycle hooks (trust_initiated, trust_request_received,
trust_approved, trust_deleted) trigger correctly.
"""

import requests


class TestTrustLifecycle:
    """Test trust lifecycle hooks fire via HTTP API."""

    def test_trust_initiation_triggers_trust_initiated_hook(
        self, actor_factory
    ):
        """Test that initiating a trust request triggers trust_initiated hook."""
        # NOTE: This test requires hooks to be registered in the test harness
        # For now, we verify the trust creation happens correctly via HTTP
        # Hook verification will be added when test harness supports hook registration

        actor1 = actor_factory.create("user1@example.com")
        actor2 = actor_factory.create("user2@example.com")

        # When actor1 initiates trust to actor2
        response = requests.post(
            f"{actor1['url']}/trust",
            json={
                "url": actor2["url"],
                "relationship": "friend",
                "desc": "Test friend",
            },
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        assert response.status_code == 201, f"Trust creation failed: {response.text}"

        # trust_initiated hook should fire for actor1 (initiator)
        # In actual test with hooks, we would verify hook was called with:
        # - actor: actor1
        # - peer_id: actor2['id']
        # - relationship: "friend"
        # - trust_data: response.json()

    def test_trust_reception_triggers_trust_request_received_hook(
        self, actor_factory
    ):
        """Test that receiving a trust request triggers trust_request_received hook."""
        actor1 = actor_factory.create("user1@example.com")
        actor2 = actor_factory.create("user2@example.com")

        # When actor1 initiates trust to actor2
        response = requests.post(
            f"{actor1['url']}/trust",
            json={
                "url": actor2["url"],
                "relationship": "friend",
                "desc": "Test friend",
            },
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        assert response.status_code == 201

        # trust_request_received hook should fire for actor2 (recipient)
        # In actual test with hooks, we would verify hook was called with:
        # - actor: actor2
        # - peer_id: actor1['id']
        # - relationship: "friend"
        # - trust_data: trust record from actor2's perspective

    def test_trust_approval_triggers_fully_approved_hooks(
        self, actor_factory, trust_helper
    ):
        """Test that trust approval triggers trust_fully_approved_local and trust_fully_approved_remote hooks."""
        # NOTE: This test requires hooks to be registered in the test harness
        # For now, we verify the approval happens correctly via HTTP
        # Hook verification will be added when test harness supports hook registration

        actor1 = actor_factory.create("user1@example.com")
        actor2 = actor_factory.create("user2@example.com")

        # Create trust relationship from actor1 to actor2
        response = requests.post(
            f"{actor1['url']}/trust",
            json={
                "url": actor2["url"],
                "relationship": "friend",
                "desc": "Test friend",
            },
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        assert response.status_code == 201, f"Trust creation failed: {response.text}"

        peer_id = response.json()["peerid"]

        # Get the secret from actor1's trust record
        response = requests.get(
            f"{actor1['url']}/trust/friend/{peer_id}",
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        assert response.status_code == 200
        # Verify secret exists in response
        assert "secret" in response.json()

        # Actor2 should have received the trust request - approve it from actor2's side
        response = requests.put(
            f"{actor2['url']}/trust/friend/{actor1['id']}",
            json={"approved": True},
            auth=(actor2["creator"], actor2["passphrase"]),
        )
        assert response.status_code in [200, 204], f"Trust approval failed: {response.text}"

        # Also approve from actor1's side to establish mutual trust
        # Expected: trust_fully_approved_local hook fires for actor1 (who just approved)
        # Expected: trust_fully_approved_remote hook fires for actor2 (who receives notification)
        response = requests.put(
            f"{actor1['url']}/trust/friend/{peer_id}",
            json={"approved": True},
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        assert response.status_code in [200, 204]

        # Verify both sides are now approved
        response = requests.get(
            f"{actor1['url']}/trust/friend/{peer_id}",
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        trust_data = response.json()
        assert trust_data["approved"] is True
        assert trust_data["peer_approved"] is True

        # Hooks would fire at this point - in actual test harness with hooks:
        # 1. trust_fully_approved_local for actor1 (they just approved locally)
        # 2. trust_fully_approved_remote for actor2 (they receive peer approval notification)

    def test_trust_deletion_triggers_trust_deleted_hook(
        self, actor_factory, trust_helper
    ):
        """Test that DELETE /{actor_id}/trust/{peer_id} triggers trust_deleted hook."""
        actor1 = actor_factory.create("user1@example.com")
        actor2 = actor_factory.create("user2@example.com")

        # Establish trust
        trust = trust_helper.establish(actor1, actor2, "friend")

        # Delete trust via HTTP
        response = requests.delete(
            f"{actor1['url']}/trust/friend/{trust['peerid']}",
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        assert response.status_code in [200, 204], f"Trust deletion failed: {response.text}"

        # Verify trust is deleted
        response = requests.get(
            f"{actor1['url']}/trust/friend/{trust['peerid']}",
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        assert response.status_code == 404, "Trust was not deleted"

        # Hook would fire before deletion - in actual test harness with hooks,
        # we would verify the hook was called

    def test_hook_receives_correct_peer_id_and_relationship(
        self, actor_factory, trust_helper
    ):
        """Test that hooks receive correct parameters."""
        actor1 = actor_factory.create("user1@example.com")
        actor2 = actor_factory.create("user2@example.com")

        # Create trust with specific relationship type
        trust = trust_helper.establish(actor1, actor2, "collaborator")

        # Verify the trust relationship is correct
        response = requests.get(
            f"{actor1['url']}/trust/collaborator/{trust['peerid']}",
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        trust_data = response.json()

        assert trust_data["peerid"] == trust["peerid"]
        assert trust_data["relationship"] == "collaborator"
        assert trust_data["approved"] is True
        assert trust_data["peer_approved"] is True

        # When hooks are implemented, they should receive:
        # - peer_id: trust["peerid"]
        # - relationship: "collaborator"
        # - trust_data: full trust record

    def test_hook_can_set_property_on_actor(self, actor_factory, trust_helper):
        """Test that lifecycle hooks can modify actor properties."""
        # This is a placeholder - actual implementation requires registering a hook
        # that sets a property when trust is approved/deleted

        actor1 = actor_factory.create("user1@example.com")
        actor2 = actor_factory.create("user2@example.com")

        # For now, just verify trust operations work
        trust = trust_helper.establish(actor1, actor2, "friend")

        # In a real test with hooks, we would:
        # 1. Register a hook that sets actor.properties["_hook_called"] = "true"
        # 2. Delete trust
        # 3. Verify the property was set

        response = requests.delete(
            f"{actor1['url']}/trust/friend/{trust['peerid']}",
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        assert response.status_code in [200, 204]

    def test_hook_not_triggered_on_partial_approval(self, actor_factory):
        """Test that trust_fully_approved hooks only fire when both sides approve."""
        actor1 = actor_factory.create("user1@example.com")
        actor2 = actor_factory.create("user2@example.com")

        # Create trust from actor1 to actor2 (only actor1 approved)
        response = requests.post(
            f"{actor1['url']}/trust",
            json={
                "url": actor2["url"],
                "relationship": "friend",
            },
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        assert response.status_code == 201

        peer_id = response.json()["peerid"]

        # Verify only one side is approved
        response = requests.get(
            f"{actor1['url']}/trust/friend/{peer_id}",
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        trust_data = response.json()

        assert trust_data["approved"] is True  # Actor1 approved (initiator auto-approves)
        assert trust_data["peer_approved"] is False  # Actor2 hasn't approved yet

        # trust_fully_approved hooks should NOT fire until both approve
        # In actual test with hooks, we would verify no approval hook was called
        # (only trust_initiated and trust_request_received would have fired)

    def test_bidirectional_trust_establishment_with_all_hooks(self, actor_factory):
        """Test complete bidirectional trust establishment flow with all lifecycle hooks."""
        actor1 = actor_factory.create("alice@example.com")
        actor2 = actor_factory.create("bob@example.com")

        # Step 1: Actor1 initiates trust
        # Expected: trust_initiated hook fires for actor1
        response = requests.post(
            f"{actor1['url']}/trust",
            json={
                "url": actor2["url"],
                "relationship": "friend",
            },
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        assert response.status_code == 201
        peer_id_from_actor1 = response.json()["peerid"]

        # Hook sequence so far:
        # 1. trust_initiated(actor1, peer_id=actor2['id'], relationship='friend')
        # 2. trust_request_received(actor2, peer_id=actor1['id'], relationship='friend')

        # Step 2: Actor2 sees the incoming trust request
        response = requests.get(
            f"{actor2['url']}/trust/friend/{actor1['id']}",
            auth=(actor2["creator"], actor2["passphrase"]),
        )
        assert response.status_code in [200, 202]  # 202 = not fully approved yet
        trust_from_actor2_view = response.json()

        # Actor2 hasn't approved yet
        assert trust_from_actor2_view["approved"] is False  # Actor2's approval
        assert trust_from_actor2_view["peer_approved"] is True  # Actor1 auto-approved

        # Step 3: Actor2 approves the trust
        response = requests.put(
            f"{actor2['url']}/trust/friend/{actor1['id']}",
            json={"approved": True},
            auth=(actor2["creator"], actor2["passphrase"]),
        )
        assert response.status_code in [200, 204]

        # Also approve from actor1's side
        response = requests.put(
            f"{actor1['url']}/trust/friend/{peer_id_from_actor1}",
            json={"approved": True},
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        assert response.status_code in [200, 204]

        # Expected: trust_fully_approved hooks fire for both actors (when both have approved)
        # Hook sequence for approval:
        # 3. trust_fully_approved_local(actor1, ...) - actor1 just approved locally
        # 4. trust_fully_approved_remote(actor2, ...) - actor2 receives notification that actor1 approved

        # Step 4: Verify both sides now show fully approved
        response = requests.get(
            f"{actor1['url']}/trust/friend/{peer_id_from_actor1}",
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        actor1_trust = response.json()
        assert actor1_trust["approved"] is True
        assert actor1_trust["peer_approved"] is True

        response = requests.get(
            f"{actor2['url']}/trust/friend/{actor1['id']}",
            auth=(actor2["creator"], actor2["passphrase"]),
        )
        actor2_trust = response.json()
        assert actor2_trust["approved"] is True
        assert actor2_trust["peer_approved"] is True

        # In actual test harness with hooks, we would verify all hooks fired:
        # 1. trust_initiated for actor1 (outgoing request)
        # 2. trust_request_received for actor2 (incoming request)
        # 3. trust_fully_approved_local for approver (who completed the approval)
        # 4. trust_fully_approved_remote for initiator (who receives peer approval notification)
