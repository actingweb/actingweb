"""AC-20: ``ActorInterface.is_vouched()``: whether a provider, the operator
or the application vouched for the actor's *current* creator. A marker being
present is not the test (``factory`` and ``email_unverified`` are markers
that do not vouch; a renamed creator makes a vouch stale)."""

from __future__ import annotations

from typing import Any

import pytest

from actingweb.db import get_attribute
from actingweb.db.exceptions import DbError
from actingweb.interface.actor_interface import ActorInterface
from actingweb.oauth2 import VOUCHED_CREATOR
from tests._adoption_helpers import (
    aid,
    backend_fault,
    create_core_actor,
    make_config,
    raise_db_error,
    uuid_email,
)


def _iface(config: Any, actor: Any) -> ActorInterface:
    found = ActorInterface.get_by_id(aid(actor), config)
    assert found is not None
    return found


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        ("google_oauth2", True),
        ("operator", True),
        ("app", True),
        (None, False),
        ("factory", False),
        ("email_unverified", False),
    ],
)
def test_vouched_and_unvouched_markers(marker: str | None, expected: bool) -> None:
    config = make_config()
    creator = uuid_email()
    actor = create_core_actor(config, creator, auth_method=marker)
    if marker and expected:
        get_attribute(config).set_attr(
            aid(actor), "_internal", VOUCHED_CREATOR, creator
        )
    assert _iface(config, actor).is_vouched() is expected


def test_a_renamed_creator_is_unvouched() -> None:
    config = make_config()
    creator = uuid_email()
    actor = create_core_actor(config, creator, auth_method="google_oauth2")
    get_attribute(config).set_attr(aid(actor), "_internal", VOUCHED_CREATOR, creator)
    iface = _iface(config, actor)
    assert iface.is_vouched() is True
    iface.core_actor.modify(creator=uuid_email())
    assert _iface(config, actor).is_vouched() is False


def test_a_marker_without_a_bound_address() -> None:
    """Written before the address was recorded: vouched for any creator."""
    config = make_config()
    actor = create_core_actor(config, uuid_email(), auth_method="operator")
    assert _iface(config, actor).is_vouched() is True


def test_an_unread_marker_raises() -> None:
    config = make_config()
    actor = create_core_actor(config, uuid_email(), auth_method="operator")
    iface = _iface(config, actor)
    with (
        backend_fault(
            config, "get_bucket", lambda a, b, n: a == aid(actor), raise_db_error
        ),
        pytest.raises(DbError),
    ):
        iface.is_vouched()
