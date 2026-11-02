"""A publisher's value-addressed list diffs keep a subscriber's replica equal.

Phase 4 of thoughts/plans/2026-11-02-3-16-small-followups.md, modelled on
``test_subscription_baseline_storage.py``. The publisher lives on the test
app; the subscriber lives on the subscriber app, which runs subscription
processing with ``auto_storage``. The publisher's list is changed in this
process through the notifying wrappers (``ActorInterface.property_lists``),
so each change registers a diff and sends its callback synchronously (no
running event loop) to the subscriber app, whose ``CallbackProcessor``
applies it to the subscriber's ``RemotePeerStore``. Nothing in this file
posts a callback by hand.
"""

import logging
import os
from collections.abc import Iterator
from typing import Any

import pytest
import requests

from actingweb.actor import Actor
from actingweb.config import Config
from actingweb.interface.actor_interface import ActorInterface
from actingweb.remote_storage import RemotePeerStore

pytestmark = pytest.mark.xdist_group(name="list_diff_peer_replica")

LIST = "replica_items"


def _backend() -> str:
    return os.environ.get("DATABASE_BACKEND", "dynamodb")


def _interface(actor_id: str, config: Config) -> ActorInterface:
    core = Actor(config=config)
    core.get(actor_id=actor_id)
    assert core.id == actor_id
    return ActorInterface(core)


@pytest.fixture
def peers(
    actor_factory: Any, trust_helper: Any, subscriber_app: str
) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """A publisher on the test app and a subscriber on the subscriber app,
    with approved trust, read access to ``LIST`` and a subscription from the
    subscriber to the publisher's properties."""
    publisher = actor_factory.create("replica_publisher@example.com")
    response = requests.post(
        f"{subscriber_app}/", json={"creator": "replica_subscriber@example.com"}
    )
    assert response.status_code == 201, response.text
    subscriber = {
        "id": response.json()["id"],
        "url": response.headers["Location"],
        "creator": response.json()["creator"],
        "passphrase": response.json()["passphrase"],
    }
    try:
        trust_helper.establish(publisher, subscriber, "friend", approve=True)
        response = requests.put(
            f"{publisher['url']}/trust/friend/{subscriber['id']}/permissions",
            json={"properties": [LIST]},
            auth=(publisher["creator"], publisher["passphrase"]),
            timeout=5,
        )
        assert response.status_code in (200, 201), response.text
        response = requests.post(
            f"{subscriber['url']}/subscriptions",
            json={
                "peerid": publisher["id"],
                "target": "properties",
                "subtarget": "",
                "resource": "",
                "granularity": "high",
            },
            auth=(subscriber["creator"], subscriber["passphrase"]),
            timeout=5,
        )
        assert response.status_code in (200, 201, 204), response.text
        yield publisher, subscriber
    finally:
        requests.delete(
            subscriber["url"],
            auth=(subscriber["creator"], subscriber["passphrase"]),
            timeout=5,
        )


def _replica(subscriber_id: str, publisher_id: str) -> list[Any]:
    store = RemotePeerStore(
        actor=_interface(subscriber_id, Config(database=_backend())),
        peer_id=publisher_id,
        validate_peer_id=False,
    )
    return store.get_list(LIST)


def _delivered(publisher: ActorInterface) -> None:
    """The last callback the publisher sent was accepted."""
    assert publisher._core_actor.last_response_code == 204, (
        publisher._core_actor.last_response_code,
        publisher._core_actor.last_response_message,
    )


def test_remove_where_and_update_where_keep_the_replica_equal(
    peers: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    publisher_ref, subscriber_ref = peers
    publisher = _interface(publisher_ref["id"], Config(database=_backend()))
    source = getattr(publisher.property_lists, LIST)

    for i, tag in enumerate(["a", "b", "c", "b", "d"]):
        source.append({"id": tag, "n": i})
        _delivered(publisher)
    assert _replica(subscriber_ref["id"], publisher_ref["id"]) == source.to_list()

    # Two rows match: two "remove" diffs, each carrying its item.
    assert source.remove_where("id", "b") == 2
    _delivered(publisher)
    assert source.to_list() == [
        {"id": "a", "n": 0},
        {"id": "c", "n": 2},
        {"id": "d", "n": 4},
    ]
    assert _replica(subscriber_ref["id"], publisher_ref["id"]) == source.to_list()

    # An "update" diff with old_item and no index: located by value.
    assert source.update_where("id", "c", {"id": "c", "n": 20}) == 1
    _delivered(publisher)
    assert source.to_list() == [
        {"id": "a", "n": 0},
        {"id": "c", "n": 20},
        {"id": "d", "n": 4},
    ]
    assert _replica(subscriber_ref["id"], publisher_ref["id"]) == source.to_list()


def test_a_spanned_items_diff_is_skipped_with_its_warning(
    peers: tuple[dict[str, Any], dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    """End to end: the publisher's SDK config sets a 2,000-byte span
    threshold, so a 5,000-byte item spans on the publisher and its diffs
    are references (no values). The subscriber app (same process, a uvicorn
    thread) logs the warning, applies nothing, and the replica stays as it
    was until a re-read."""
    publisher_ref, subscriber_ref = peers
    config = Config(
        database=_backend(), list_item_span_threshold=2_000, list_item_max_bytes=20_000
    )
    publisher = _interface(publisher_ref["id"], config)
    source = getattr(publisher.property_lists, LIST)

    source.append({"id": "small", "n": 0})
    _delivered(publisher)
    assert _replica(subscriber_ref["id"], publisher_ref["id"]) == [
        {"id": "small", "n": 0}
    ]

    big = {"id": "big", "body": "x" * 5_000}
    with caplog.at_level(logging.WARNING, logger="actingweb.remote_storage"):
        source.append(big)
        _delivered(publisher)
        assert source.update_where("id", "big", {**big, "n": 1}) == 1
        _delivered(publisher)
    skipped = [
        r.getMessage()
        for r in caplog.records
        if r.name == "actingweb.remote_storage"
        and "reference to values over the span threshold" in r.getMessage()
    ]
    assert len(skipped) == 2, skipped
    assert f"'{LIST}'" in skipped[0] and "'append'" in skipped[0]
    assert "'update'" in skipped[1]

    assert source.to_list() == [{"id": "small", "n": 0}, {**big, "n": 1}]
    assert _replica(subscriber_ref["id"], publisher_ref["id"]) == [
        {"id": "small", "n": 0}
    ]
