"""``PUT /<id>/trust/trustee`` with a new ``creator`` (3.16, second iteration).

A self-asserted creator unvouches the actor (``creator_changed``). Two values
hand the actor to nobody new and keep the marker: the protocol's
``"trustee"`` and the actor's own stored email. With
``force_email_prop_as_creator`` the creator is pinned to the stored email,
and any other address is refused.
"""

import json
from typing import Any
from unittest.mock import Mock, patch

import pytest

from actingweb.actor import Actor
from actingweb.handlers.trust import TrustRelationshipHandler
from tests._adoption_helpers import (
    aid,
    backend_fault,
    create_core_actor,
    istore,
    make_config,
    marker_write_fault,
    uuid_email,
)


def _put(
    config: Any, actor: Actor, body: dict[str, Any], interface: Mock | None = None
) -> Mock:
    handler = TrustRelationshipHandler()
    handler.config = config
    handler.request = Mock()
    handler.request.body = json.dumps(body)
    handler.response = Mock()
    auth_result = Mock()
    auth_result.success = True
    auth_result.actor = actor
    auth_result.authorize = Mock(return_value=True)
    handler.authenticate_actor = Mock(return_value=auth_result)
    handler._get_actor_interface = Mock(return_value=interface or Mock())  # type: ignore[method-assign]
    handler.put(aid(actor), "trustee")
    return handler.response


def _vouched(config: Any) -> tuple[Actor, str]:
    owner = uuid_email()
    actor = create_core_actor(config, owner, auth_method="google_oauth2")
    istore(actor).email = owner
    return actor, owner


def _reload(config: Any, actor: Actor) -> Actor:
    return Actor(actor_id=aid(actor), config=config)


class TestUnpinnedCreator:
    def _config(self) -> Any:
        config = make_config()
        config.force_email_prop_as_creator = False
        return config

    def test_other_address_unvouches(self) -> None:
        config = self._config()
        actor, _owner = _vouched(config)
        other = uuid_email()

        response = _put(config, actor, {"creator": other})

        response.set_status.assert_called_with(204, "No content")
        row = _reload(config, actor)
        assert row.creator == other
        assert istore(row).auth_method == "creator_changed"

    def test_trustee_handoff_and_back_keeps_the_vouch(self) -> None:
        config = self._config()
        actor, owner = _vouched(config)

        _put(
            config, actor, {"trustee_root": "https://t.example/", "creator": "trustee"}
        )
        assert _reload(config, actor).creator == "trustee"
        _put(config, _reload(config, actor), {"creator": owner})

        row = _reload(config, actor)
        assert row.creator == owner
        assert istore(row).auth_method == "google_oauth2"

    def test_marker_write_fault_refuses_the_rename(self) -> None:
        config = self._config()
        actor, owner = _vouched(config)

        with marker_write_fault(config, aid(actor)):
            response = _put(config, actor, {"creator": uuid_email()})

        response.set_status.assert_called_with(500, "Internal error")
        row = _reload(config, actor)
        assert row.creator == owner
        assert istore(row).auth_method == "google_oauth2"


class TestPinnedCreator:
    def test_other_address_is_refused(self) -> None:
        config = make_config()
        config.force_email_prop_as_creator = True
        actor, owner = _vouched(config)

        response = _put(config, actor, {"creator": uuid_email()})

        assert response.set_status.call_args[0][0] == 400
        row = _reload(config, actor)
        assert row.creator == owner
        assert istore(row).auth_method == "google_oauth2"


class TestRenameFaults:
    """Third iteration: a rename that is refused or fails changes nothing."""

    def _config(self) -> Any:
        config = make_config()
        config.force_email_prop_as_creator = False
        return config

    def test_factory_actor_keeps_its_marker(self) -> None:
        # A squatter's factory actor renamed to the victim's address must
        # still be replaced at the victim's sign-in, not cleaned in place.
        config = self._config()
        actor = create_core_actor(config, uuid_email(), auth_method="factory")

        response = _put(config, actor, {"creator": uuid_email()})

        response.set_status.assert_called_with(204, "No content")
        assert istore(_reload(config, actor)).auth_method == "factory"

    @pytest.mark.parametrize(
        "modify",
        [
            pytest.param(Mock(side_effect=RuntimeError("save")), id="raises"),
            pytest.param(Mock(return_value=False), id="false"),
        ],
    )
    def test_failed_modify_answers_500_and_restores_the_marker(
        self, modify: Mock
    ) -> None:
        config = self._config()
        actor, owner = _vouched(config)

        with patch.object(Actor, "modify", modify):
            response = _put(config, actor, {"creator": uuid_email()})

        response.set_status.assert_called_with(500, "Internal error")
        row = _reload(config, actor)
        assert row.creator == owner
        assert istore(row).auth_method == "google_oauth2"

    def test_unreadable_internal_bucket_answers_500(self) -> None:
        config = make_config()
        config.force_email_prop_as_creator = True
        actor, owner = _vouched(config)

        # PostgreSQL's caught fault: the bucket read answers None.
        with backend_fault(
            config,
            "get_bucket",
            lambda a, b, _n: a == aid(actor) and b == "_internal",
            lambda: None,
        ):
            response = _put(config, _reload(config, actor), {"creator": uuid_email()})

        response.set_status.assert_called_with(500, "Internal error")
        row = _reload(config, actor)
        assert row.creator == owner
        assert istore(row).auth_method == "google_oauth2"

    def test_refused_rename_does_not_write_trustee_root(self) -> None:
        config = make_config()
        config.force_email_prop_as_creator = True
        actor, _owner = _vouched(config)
        interface = Mock()
        interface.trust.trustee_root = None

        response = _put(
            config,
            actor,
            {"trustee_root": "https://t.example/", "creator": uuid_email()},
            interface,
        )

        assert response.set_status.call_args[0][0] == 400
        assert interface.trust.trustee_root is None
