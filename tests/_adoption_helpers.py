"""Shared fixtures for the adoption (3.16) tests.

Plants the state a squatter can leave on an actor created from unauthenticated
input: a chosen passphrase, an ``admin`` trust with a chosen secret and a peer
URL nobody should ever call, a subscription, and a prefilled property.
"""

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from actingweb import subscription as subscription_module
from actingweb import trust as trust_module
from actingweb.actor import Actor
from actingweb.attribute import InternalStore
from actingweb.config import Config
from actingweb.db import get_attribute
from actingweb.db.exceptions import DbError

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


@contextmanager
def backend_fault(
    config: Any,
    method: str,
    matches: Callable[[Any, Any, Any], bool],
    answer: Callable[[], Any],
) -> Iterator[None]:
    """Replace one attribute-backend method for the (actor, bucket, name)
    calls ``matches`` accepts; every other call is real."""
    unpatched = get_attribute(config)
    cls = type(unpatched)
    real = getattr(unpatched, method)  # bound before patching

    def fake(*args: Any, **kw: Any) -> Any:
        if args and isinstance(args[0], cls):
            args = args[1:]
        names = ("actor_id", "bucket", "name")
        values = dict(zip(names, args, strict=False))
        values.update({k: v for k, v in kw.items() if k in names})
        if matches(values.get("actor_id"), values.get("bucket"), values.get("name")):
            return answer()
        return real(*args, **kw)

    with patch.object(cls, method, fake):
        yield


def raise_db_error() -> Any:
    """A backend fault as both backends report it since 3.16."""
    raise DbError("simulated backend fault")


_raise = raise_db_error


def marker_write_fault(config: Any, actor_id: str | None = None) -> Any:
    """``set_attr`` of ``_internal/auth_method`` raises ``DbError`` and
    writes nothing (a backend fault)."""
    return backend_fault(
        config,
        "set_attr",
        lambda a, b, n: (
            b == "_internal" and n == "auth_method" and actor_id in (None, a)
        ),
        raise_db_error,
    )


@contextmanager
def seam_fault(config: Config, module: str, model: str, method: str) -> Iterator[None]:
    """A backend fault at the lowest seam of whichever backend ``config``
    uses: DynamoDB's PynamoDB ``model.method`` raises, or PostgreSQL's
    ``get_connection`` raises for every call in ``module``. The backend's
    own handling then decides what the caller sees, which is what a
    regression test for the fault contract must exercise."""
    import importlib

    backend = type(get_attribute(config)).__module__.split(".")[2]
    if backend == "postgresql":
        target = importlib.import_module(f"actingweb.db.postgresql.{module}")

        def down(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError("connection refused (simulated)")

        with patch.object(target, "get_connection", down):
            yield
        return
    target_model = getattr(
        importlib.import_module(f"actingweb.db.dynamodb.{module}"), model
    )

    def throttled(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("ProvisionedThroughputExceededException (simulated)")

    owner: Any = target_model
    attr = method
    if "." in method:
        sub, attr = method.split(".", 1)
        owner = getattr(target_model, sub)
    with patch.object(owner, attr, throttled):
        yield
