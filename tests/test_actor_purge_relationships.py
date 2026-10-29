"""``Actor.purge_relationships`` and ``notify_peers=False`` (3.16).

An actor nobody vouched for may hold relationships whose peer URLs were chosen
by whoever created it, so adopting it must not call them.
"""

from unittest.mock import patch

from actingweb import peertrustee
from actingweb import subscription as subscription_module
from actingweb import trust as trust_module
from actingweb.actor import Actor
from tests._adoption_helpers import (
    PLANTED_SECRET,
    create_core_actor,
    make_config,
    plant_squat_state,
    uuid_email,
)


def _plant_peer_trustee(config, actor) -> None:
    # The stored type is the actor-type URN of a configured short type.
    peer_type = next(iter(config.actors.values()))["type"]
    assert peertrustee.PeerTrustee(
        actor_id=actor.id, peerid="peer-trustee", peer_type=peer_type, config=config
    ).create(baseuri="http://127.0.0.1:9/trustee", passphrase="trustee-pass")


class TestPurgeRelationships:
    def test_removes_everything_locally_without_network(self) -> None:
        config = make_config()
        actor = create_core_actor(config, uuid_email())
        plant_squat_state(config, actor)
        _plant_peer_trustee(config, actor)

        with patch("actingweb.actor.requests") as requests_mock:
            summary = actor.purge_relationships(notify_peers=False)

        requests_mock.delete.assert_not_called()
        assert summary["confirmed"] is True
        assert summary["subscription_peers"] == ["peer-squat"]
        assert [t["peerid"] for t in summary["trusts"]] == ["peer-squat"]
        assert summary["trusts"][0]["relationship"] == "admin"
        # Secrets never leave the actor, not even into the summary.
        assert all("secret" not in t for t in summary["trusts"])
        assert PLANTED_SECRET not in repr(summary)

        assert not trust_module.Trusts(actor_id=actor.id, config=config).fetch()
        assert not subscription_module.Subscriptions(
            actor_id=actor.id, config=config
        ).fetch()
        assert not peertrustee.PeerTrustee(
            actor_id=actor.id, peerid="peer-trustee", config=config
        ).get()

    def test_unconfirmed_when_a_trust_row_survives(self) -> None:
        config = make_config()
        actor = create_core_actor(config, uuid_email())
        plant_squat_state(config, actor)

        # The bulk delete reports success whatever the backend did.
        with (
            patch.object(trust_module.Trusts, "delete", return_value=True),
            patch.object(Actor, "delete_reciprocal_trust", return_value=True),
        ):
            summary = actor.purge_relationships(notify_peers=False)

        assert summary["confirmed"] is False

    def test_empty_actor_is_confirmed(self) -> None:
        config = make_config()
        actor = create_core_actor(config, uuid_email())
        summary = actor.purge_relationships()
        assert summary == {"trusts": [], "subscription_peers": [], "confirmed": True}


class TestNotifyPeers:
    def test_delete_without_notify_makes_no_remote_call(self) -> None:
        config = make_config()
        actor = create_core_actor(config, uuid_email())
        plant_squat_state(config, actor)
        _plant_peer_trustee(config, actor)

        with patch("actingweb.actor.requests") as requests_mock:
            actor.delete(notify_peers=False)

        requests_mock.delete.assert_not_called()
        assert not Actor(actor_id=actor.id, config=config).id

    def test_delete_with_notify_still_calls_peers(self) -> None:
        config = make_config()
        actor = create_core_actor(config, uuid_email())
        plant_squat_state(config, actor)

        with patch("actingweb.actor.requests") as requests_mock:
            requests_mock.delete.return_value.status_code = 204
            actor.delete()

        assert requests_mock.delete.called
