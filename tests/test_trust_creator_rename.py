"""``PUT /<id>/trust/trustee`` with a new ``creator`` (3.16, second iteration).

A self-asserted creator unvouches the actor (``creator_changed``). Two values
hand the actor to nobody new and keep the marker: the protocol's
``"trustee"`` and the actor's own stored email. With
``force_email_prop_as_creator`` the creator is pinned to the stored email,
and any other address is refused.
"""

import json
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

from actingweb.actor import Actor
from actingweb.handlers.trust import TrustRelationshipHandler
from actingweb.oauth2 import VOUCHED_CREATOR, is_vouched_actor
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
    handler.response = MagicMock()
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


class TestStaleHandle:
    def test_f10_a_concurrent_rename_answers_409_not_500(self) -> None:
        config = make_config()
        config.force_email_prop_as_creator = False
        actor, _owner = _vouched(config)
        elsewhere = uuid_email()
        assert _reload(config, actor).modify(creator=elsewhere)  # another request

        response = _put(config, actor, {"creator": uuid_email()})

        assert response.set_status.call_args[0][0] == 409
        assert _reload(config, actor).creator == elsewhere

    def test_f11_a_rename_that_landed_before_its_answer_was_lost_succeeds(
        self,
    ) -> None:
        config = make_config()
        config.force_email_prop_as_creator = False
        actor, _owner = _vouched(config)
        wanted = uuid_email()
        assert _reload(config, actor).modify(creator=wanted)  # this request's write

        response = _put(config, actor, {"creator": wanted})

        response.set_status.assert_called_with(204, "No content")

    def test_f11_a_deleted_actor_answers_404(self) -> None:
        config = make_config()
        config.force_email_prop_as_creator = False
        actor, _owner = _vouched(config)
        doomed = _reload(config, actor)
        assert doomed.handle is not None and doomed.handle.delete()

        response = _put(config, actor, {"creator": uuid_email()})

        assert response.set_status.call_args[0][0] == 404


class TestConcurrentRestore:
    """A12: a failed concurrent change (CreatorTaken under the flag, on
    demand) restores the old marker after its re-read. The vouch is bound
    to the address it proved, so whatever order that restore and this
    change's writes land in, the actor ends unvouched under the new one."""

    def _config(self) -> Any:
        config = make_config()
        config.force_email_prop_as_creator = False
        return config

    def test_a12_a_restore_landing_before_the_rename(self) -> None:
        config = self._config()
        actor, owner = _vouched(config)
        real_modify = Actor.modify

        def restore_lands_first(self: Actor, *args: Any, **kwargs: Any) -> bool:
            other = _reload(config, actor)
            assert Actor._restore_marker(istore(other), "google_oauth2", owner)
            return real_modify(self, *args, **kwargs)

        with patch.object(Actor, "modify", restore_lands_first):
            assert actor.modify_creator_unvouched(uuid_email())
        assert not is_vouched_actor(_reload(config, actor))

    def test_a12_a_restore_landing_after_the_rename(self) -> None:
        config = self._config()
        actor, owner = _vouched(config)
        real_modify = Actor.modify

        def restore_lands_last(self: Actor, *args: Any, **kwargs: Any) -> bool:
            done = real_modify(self, *args, **kwargs)
            other = _reload(config, actor)
            assert Actor._restore_marker(istore(other), "google_oauth2", owner)
            return done

        with patch.object(Actor, "modify", restore_lands_last):
            assert actor.modify_creator_unvouched(uuid_email())
        renamed = _reload(config, actor)
        assert istore(renamed).auth_method == "google_oauth2"  # the restore won
        assert not is_vouched_actor(renamed)

    def test_a12_a_pre_316_vouched_actor_is_bound_by_the_restore(self) -> None:
        config = self._config()
        actor, owner = _vouched(config)
        assert istore(actor).set_confirmed(VOUCHED_CREATOR, None)  # before 3.16
        real_modify = Actor.modify

        def restore_lands_last(self: Actor, *args: Any, **kwargs: Any) -> bool:
            done = real_modify(self, *args, **kwargs)
            other = _reload(config, actor)
            assert Actor._restore_marker(istore(other), "google_oauth2", owner)
            return done

        with patch.object(Actor, "modify", restore_lands_last):
            assert actor.modify_creator_unvouched(uuid_email())
        assert not is_vouched_actor(_reload(config, actor))

    def test_r8_a_clean_that_landed_meanwhile_is_not_restored_over(self) -> None:
        # Finding 3 of round 8: the restore only replaces this change's
        # "creator_changed", not the marker a sign-in wrote since.
        config = self._config()
        actor, owner = _vouched(config)
        store = istore(actor)
        assert store.set_confirmed("auth_method", "creator_changed")
        other = istore(_reload(config, actor))
        assert other.set_confirmed("auth_method", "email_verified")  # the clean
        assert not Actor._restore_marker(store, "email_unverified", owner)
        assert istore(_reload(config, actor)).auth_method == "email_verified"


class TestApplicationRename:
    def test_r8_an_application_rename_keeps_the_vouch(self) -> None:
        from actingweb.interface.actor_interface import ActorInterface

        config = make_config()
        config.force_email_prop_as_creator = False
        actor, _owner = _vouched(config)
        moved = uuid_email()
        assert ActorInterface(actor).modify_creator(moved)
        assert is_vouched_actor(_reload(config, actor))
