"""A fault reading the OAuth2 state encryption key must not replace the key.

``OAuth2StateManager._get_or_create_encryption_key`` read the stored key
inside ``except Exception`` and, on any exception, generated a new key and
stored it over the existing one. A throttle on the system actor's property
read therefore invalidated every OAuth2 state in flight on every instance.
See thoughts/research/2026-10-29-oauth2-state-key-overwritten-on-read-fault.md.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest

from actingweb.actor import Actor
from actingweb.constants import OAUTH2_SYSTEM_ACTOR
from actingweb.db import get_property
from actingweb.db.exceptions import DbError
from tests._adoption_helpers import make_config

KEY_NAME = "oauth2_state_encryption_key"


def _stored_key(config: Any) -> Any:
    return get_property(config).get(actor_id=OAUTH2_SYSTEM_ACTOR, name=KEY_NAME)


def _key_read_faults(config: Any) -> Any:
    cls = type(get_property(config))
    real_get = cls.get

    def get(self: Any, actor_id: str | None = None, name: str | None = None) -> Any:
        if name == KEY_NAME:
            raise DbError("property read", actor_id)
        return real_get(self, actor_id=actor_id, name=name)

    return mock.patch.object(cls, "get", get)


def test_a_key_read_fault_raises_and_keeps_the_stored_key() -> None:
    from actingweb.oauth2_server.state_manager import OAuth2StateManager

    config = make_config()
    OAuth2StateManager(config)  # creates and stores a key if none exists
    before = _stored_key(config)
    assert before

    with _key_read_faults(config), pytest.raises(DbError):
        OAuth2StateManager(config)

    assert _stored_key(config) == before


def test_a_system_actor_load_fault_raises_instead_of_an_in_memory_key() -> None:
    from actingweb.oauth2_server.state_manager import OAuth2StateManager

    config = make_config()
    OAuth2StateManager(config)

    def failing_get(self: Actor, actor_id: str | None = None) -> Any:
        raise DbError("actor get", actor_id)

    with mock.patch.object(Actor, "get", failing_get), pytest.raises(DbError):
        OAuth2StateManager(config)


def test_without_a_fault_the_stored_key_is_reused() -> None:
    from actingweb.oauth2_server.state_manager import OAuth2StateManager

    config = make_config()
    first = OAuth2StateManager(config).encryption_key
    second = OAuth2StateManager(config).encryption_key
    assert first == second
