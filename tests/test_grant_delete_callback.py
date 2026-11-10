"""Deleting a peer's grant tells the peer (3.16, plan Phase 4, C10).

``DELETE /<actor>/trust/<rel>/<peer>/permissions`` puts the peer back on its
trust type's default grant. It sends the permission callback with that
grant, as a PUT of the grant sends its own; a delete of nothing answers 404
and sends nothing. The store's own delete, used where the row goes or a new
grant follows, sends nothing. Real storage; both backends through
``DATABASE_BACKEND``.
"""

from __future__ import annotations

import base64
from typing import Any
from unittest import mock

import pytest

from actingweb.aw_web_request import AWWebObj
from actingweb.handlers.trust import TrustPermissionHandler
from actingweb.trust import Trust
from actingweb.trust_permissions import get_trust_permission_store
from tests._adoption_helpers import aid
from tests.test_trust_re_pair import PASSPHRASE, Receiver


class _Proxy:
    """``AwProxy`` as the permission sender sees it: answers ``codes`` in
    turn and records each body sent."""

    codes: list[int] = []
    sent: list[dict[str, Any]] = []

    def __init__(self, peer_target: dict[str, Any], config: Any) -> None:
        self.trust = {"peerid": peer_target["peerid"]}
        self.last_response_code: int | None = None

    def create_resource(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        _Proxy.sent.append({"path": path, **params})
        self.last_response_code = _Proxy.codes.pop(0) if _Proxy.codes else 204
        return {}


@pytest.fixture
def sender():
    _Proxy.codes, _Proxy.sent = [], []
    with (
        mock.patch("actingweb.aw_proxy.AwProxy", _Proxy),
        mock.patch("actingweb.trust_permissions.time.sleep"),
    ):
        yield _Proxy


def _receiver() -> Receiver:
    """A with friends B (custom grant) and C; what storing B's grant sent is
    not this test's."""
    w = Receiver()
    _Proxy.sent.clear()
    return w


def _delete(w: Receiver) -> AWWebObj:
    token = base64.b64encode(f"{w.a.creator}:{PASSPHRASE}".encode()).decode()
    webobj = AWWebObj(
        url="https://test.example.com/x",
        headers={"Authorization": f"Basic {token}"},
    )
    TrustPermissionHandler(webobj, w.config).delete(aid(w.a), "friend", w.b)
    return webobj


def test_a_deleted_grant_sends_the_default_once_then_404(sender) -> None:
    w = _receiver()  # B's row carries a custom grant
    out = _delete(w)
    assert out.response.status_code == 204
    assert (
        get_trust_permission_store(w.config).get_permissions_uncached(aid(w.a), w.b)
        is None
    )
    assert len(sender.sent) == 1
    body = sender.sent[0]
    assert body["path"] == f"callbacks/permissions/{aid(w.a)}"
    assert body["type"] == "permission" and body["id"] == aid(w.a)
    # The default grant, not the deleted override's pattern.
    assert "kept/*" not in repr(body["data"])

    again = _delete(w)
    assert again.response.status_code == 404
    assert len(sender.sent) == 1


def test_a_stale_cache_does_not_hide_the_delete(sender) -> None:
    w = _receiver()
    store = get_trust_permission_store(w.config)
    assert store.get_permissions(aid(w.a), w.b) is not None  # cached
    assert store.delete_permissions(aid(w.a), w.b)
    store._cache[f"{aid(w.a)}:{w.b}"] = mock.Mock()  # stale entry
    assert _delete(w).response.status_code == 404
    assert sender.sent == []


def test_a_503_is_resent_and_the_delete_stands(sender) -> None:
    w = _receiver()
    sender.codes = [503, 503, 503, 503, 503, 503]
    assert _delete(w).response.status_code == 204
    assert len(sender.sent) > 1
    assert len({s["timestamp"] for s in sender.sent}) == 1  # the same body
    assert (
        get_trust_permission_store(w.config).get_permissions_uncached(aid(w.a), w.b)
        is None
    )


def test_notification_off_sends_nothing(sender) -> None:
    w = _receiver()
    w.config.notify_peer_on_change = False
    assert _delete(w).response.status_code == 204
    assert sender.sent == []


def test_the_store_delete_and_the_row_routes_send_nothing(sender) -> None:
    w = _receiver()
    store = get_trust_permission_store(w.config)
    assert store.delete_permissions(aid(w.a), w.b)
    # The row's own delete takes its (other) peer's override with it.
    assert Trust(actor_id=aid(w.a), peerid=w.c, config=w.config).delete()
    assert Trust(actor_id=aid(w.a), peerid=w.c, config=w.config).create(
        baseuri=f"https://{w.c}.example.test/{w.c}",
        peer_type="urn:test",
        relationship="friend",
        secret="s" * 40,
    )
    assert sender.sent == []
