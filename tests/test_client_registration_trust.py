"""Registering an OAuth2 client writes its trust row and lists no relationships.

The registration path used to walk ``trust.relationships`` after creating the
trust row to build a log string; the peer id is already known, so the walk
(a read of every trust the actor holds) is gone.
"""

from unittest import mock

from actingweb.config import Config
from actingweb.oauth2_server.client_registry import MCPClientRegistry


def test_the_trust_row_is_created_without_listing_relationships() -> None:
    config = Config(unique_creator=False)
    registry = MCPClientRegistry.__new__(MCPClientRegistry)
    registry.config = config  # type: ignore[attr-defined]

    core_actor = mock.Mock()
    core_actor.actor = mock.Mock()
    trust_manager = mock.Mock()
    trust_manager.create_or_update_oauth_trust.return_value = True
    relationships = mock.PropertyMock(side_effect=AssertionError("listed trusts"))

    with (
        mock.patch("actingweb.actor.Actor", return_value=core_actor),
        mock.patch(
            "actingweb.interface.trust_manager.TrustManager",
            return_value=trust_manager,
        ),
        mock.patch(
            "actingweb.interface.actor_interface.ActorInterface.trust",
            new_callable=lambda: relationships,
            create=True,
        ),
    ):
        registry._create_client_trust_relationship(  # pyright: ignore[reportPrivateUsage]
            "actor-1",
            "client-1",
            {"client_name": "c", "client_secret": "s", "created_at": 1},
        )

    trust_manager.create_or_update_oauth_trust.assert_called_once()
    relationships.assert_not_called()
