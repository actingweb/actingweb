"""Shared fixtures for the adoption (3.16) tests.

Plants the state a squatter can leave on an actor created from unauthenticated
input: a chosen passphrase, an ``admin`` trust with a chosen secret and a peer
URL nobody should ever call, a subscription, and a prefilled property.
"""

import uuid
from typing import Any

from actingweb import subscription as subscription_module
from actingweb import trust as trust_module
from actingweb.actor import Actor
from actingweb.attribute import InternalStore
from actingweb.config import Config

UNROUTABLE = "http://127.0.0.1:9/never-called"
PLANTED_SECRET = "squatter-chosen-secret"


def uuid_email() -> str:
    return f"{uuid.uuid4()}@example.com"


def make_config(hooks: Any = None) -> Config:
    config = Config(
        fqdn="test.example.com",
        proto="https://",
        database="dynamodb",
        aw_type="urn:actingweb:test:adoption",
        devtest=True,
    )
    if hooks is not None:
        config._hooks = hooks  # type: ignore[attr-defined]
    return config


def create_core_actor(
    config: Config,
    creator: str,
    *,
    auth_method: str | None = "factory",
    passphrase: str = "squatter-passphrase",
) -> Actor:
    """Create an actor through ``Actor.create``; ``auth_method=None`` leaves
    the marker unset, as a pre-3.16 actor would be."""
    actor = Actor(config=config)
    assert actor.create(
        url="https://test.example.com/",
        creator=creator,
        passphrase=passphrase,
        auth_method=auth_method or "app",
    )
    if auth_method is None and actor.store:
        actor.store.auth_method = None
    return actor


def plant_squat_state(config: Config, actor: Actor, peer: str = "peer-squat") -> None:
    assert actor.id
    assert trust_module.Trust(actor_id=actor.id, peerid=peer, config=config).create(
        baseuri=UNROUTABLE,
        peer_type="urn:actingweb:test:peer",
        relationship="admin",
        secret=PLANTED_SECRET,
        approved=True,
        verified=True,
    )
    assert subscription_module.Subscription(
        actor_id=actor.id, peerid=peer, subid="sub-squat", config=config
    ).create(target="properties", granularity="high")
    assert actor.property is not None
    actor.property["prefilled"] = "squatter-value"


def aid(actor: Actor) -> str:
    """The actor's id, asserted present (for type narrowing in tests)."""
    assert actor.id
    return actor.id


def istore(actor: Actor) -> InternalStore:
    """The actor's ``_internal`` store, asserted present."""
    assert actor.store is not None
    return actor.store
