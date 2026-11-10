"""A trust delete removes only the row it was authorised against (3.16, plan
Phase 4, A13).

``Trust.delete(only_if_secret=)`` and ``delete_reciprocal_trust(
expected_secret=)``: a row a re-pair replaced (a new secret) between the
handler's read and the delete keeps its row, and the request answers 404. The
secret is compared before the remote DELETE, again before the local cascade,
and by the row delete itself; a re-pair landing after the second check keeps
its row but not what the cascade removed (the remaining window,
``thoughts/reference/trust-row-deletion-invariants.md``). Real storage; both
backends through ``DATABASE_BACKEND``.
"""

from __future__ import annotations

import asyncio
import base64
import uuid
from typing import Any
from unittest import mock

import pytest

from actingweb import trust as trust_module
from actingweb.actor import TrustReplaced
from actingweb.aw_web_request import AWWebObj
from actingweb.db import get_trust
from actingweb.db.exceptions import DbError
from actingweb.handlers.trust import TrustPeerHandler
from actingweb.subscription import Subscriptions
from actingweb.trust import Trust
from actingweb.trust_permissions import get_trust_permission_store
from tests._adoption_helpers import aid
from tests.test_trust_re_pair import PASSPHRASE, Receiver


def _repair(w: Receiver, peer: str) -> str:
    """A re-pair landing: the row now carries a new secret."""
    new = uuid.uuid4().hex
    assert Trust(actor_id=aid(w.a), peerid=peer, config=w.config).modify(secret=new)
    return new


def _subscribe(w: Receiver, peer: str) -> None:
    w.a.create_subscription(
        peerid=peer, target="properties", granularity="high", callback=False
    )


def _subs(w: Receiver, peer: str) -> list[Any]:
    """From the store (the actor caches its list)."""
    rows = Subscriptions(actor_id=aid(w.a), config=w.config).fetch() or []
    return [r for r in rows if r.get("peerid") == peer]


def _grant(w: Receiver, peer: str) -> Any:
    return get_trust_permission_store(w.config).get_permissions_uncached(aid(w.a), peer)


class TestTheRowDelete:
    def test_a_matching_secret_deletes(self) -> None:
        w = Receiver()
        handle = Trust(actor_id=aid(w.a), peerid=w.b, config=w.config)
        assert handle.delete(only_if_secret=w.secrets[w.b]) is True
        assert not w.row(w.b)

    def test_another_secret_keeps_the_row_and_its_grant(self) -> None:
        w = Receiver()
        handle = Trust(actor_id=aid(w.a), peerid=w.b, config=w.config)
        assert handle.delete(only_if_secret="not-the-secret") is False
        assert w.row(w.b)["secret"] == w.secrets[w.b]
        assert _grant(w, w.b) is not None

    def test_an_absent_row_is_deleted(self) -> None:
        w = Receiver()
        handle = Trust(actor_id=aid(w.a), peerid=w.b, config=w.config)
        handle.get()
        assert get_trust(w.config).get(actor_id=aid(w.a), peerid=w.b)
        assert Trust(actor_id=aid(w.a), peerid=w.b, config=w.config).delete()
        assert handle.delete(only_if_secret=w.secrets[w.b]) is True

    def test_an_absent_row_still_loses_its_leftover_grant(self) -> None:
        """Verification 2026-11-10: the conditional delete of a row already
        gone returned before the cleanup an unconditional one runs."""
        w = Receiver()
        handle = Trust(actor_id=aid(w.a), peerid=w.b, config=w.config)
        handle.get()
        db = get_trust(w.config)
        assert db.get(actor_id=aid(w.a), peerid=w.b)
        assert db.delete(only_if_secret=w.secrets[w.b])
        assert _grant(w, w.b) is not None  # left behind, as by a fault
        assert handle.delete(only_if_secret=w.secrets[w.b]) is True
        assert _grant(w, w.b) is None

    def test_the_store_delete_is_conditional(self) -> None:
        """Replaced after the fresh read: the store's own condition holds."""
        w = Receiver()
        db = get_trust(w.config)
        assert db.get(actor_id=aid(w.a), peerid=w.b)
        _repair(w, w.b)
        assert db.delete(only_if_secret=w.secrets[w.b]) is False
        assert w.row(w.b)
        assert db.delete(only_if_secret=w.row(w.b)["secret"]) is True
        assert not w.row(w.b)

    def test_a_fault_is_a_db_error(self) -> None:
        w = Receiver()
        with (
            mock.patch(
                "actingweb.db.get_trust",
                side_effect=DbError("trust read", aid(w.a)),
            ),
            pytest.raises(DbError),
        ):
            Trust(actor_id=aid(w.a), peerid=w.b, config=w.config).delete(
                only_if_secret=w.secrets[w.b]
            )
        assert w.row(w.b)


class TestTheActorDelete:
    def test_a_row_replaced_before_the_cascade_keeps_everything(self) -> None:
        w = Receiver()
        _subscribe(w, w.b)
        real_get = Trust.get
        calls = {"n": 0}

        def get_then_repair(self: Trust, *a: Any, **kw: Any) -> Any:
            # The re-pair lands after the listing, before the second check.
            calls["n"] += 1
            if calls["n"] == 1:
                _repair(w, w.b)
            return real_get(self, *a, **kw)

        with (
            mock.patch.object(Trust, "get", get_then_repair),
            pytest.raises(TrustReplaced),
        ):
            w.a.delete_reciprocal_trust(
                peerid=w.b, notify_peers=False, expected_secret=w.secrets[w.b]
            )
        assert w.row(w.b)
        assert _subs(w, w.b)
        assert _grant(w, w.b) is not None

    def test_a_row_replaced_inside_the_window_keeps_its_row(self) -> None:
        """After the second check: the cascade ran, the row stands."""
        w = Receiver()
        _subscribe(w, w.b)
        real_delete = trust_module.Trust.delete

        def repair_then_delete(self: Trust, **kw: Any) -> bool:
            _repair(w, w.b)
            return real_delete(self, **kw)

        with (
            mock.patch.object(trust_module.Trust, "delete", repair_then_delete),
            pytest.raises(TrustReplaced),
        ):
            w.a.delete_reciprocal_trust(
                peerid=w.b, notify_peers=False, expected_secret=w.secrets[w.b]
            )
        assert w.row(w.b)  # the new row stands
        assert not _subs(w, w.b)  # the documented window

    def test_the_async_twin_passes_the_secret(self) -> None:
        w = Receiver()
        _repair(w, w.b)
        with pytest.raises(TrustReplaced):
            asyncio.run(
                w.a.delete_reciprocal_trust_async(
                    peerid=w.b, expected_secret=w.secrets[w.b]
                )
            )
        assert w.row(w.b)

    def test_without_a_secret_it_deletes_as_before(self) -> None:
        w = Receiver()
        _repair(w, w.b)
        assert w.a.delete_reciprocal_trust(peerid=w.b, notify_peers=False)
        assert not w.row(w.b)


class TestTheHandler:
    def _delete(self, w: Receiver, headers: dict[str, str], **params: str) -> int:
        webobj = AWWebObj(
            url="https://test.example.com/x", params=params, headers=headers
        )
        TrustPeerHandler(webobj, w.config).delete(aid(w.a), "friend", w.b)
        return webobj.response.status_code

    def _creator(self, w: Receiver) -> dict[str, str]:
        token = base64.b64encode(f"{w.a.creator}:{PASSPHRASE}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def _repair_on_delete(self, w: Receiver) -> Any:
        """Wraps the delete the handler calls: the re-pair lands just after
        the handler read the row."""
        real = type(w.a).delete_reciprocal_trust

        def wrapped(actor: Any, *a: Any, **kw: Any) -> Any:
            if actor.id == aid(w.a):
                _repair(w, w.b)
            return real(actor, *a, **kw)

        return mock.patch.object(type(w.a), "delete_reciprocal_trust", wrapped)

    def test_the_creator_loses_to_a_re_pair_with_a_404(self) -> None:
        w = Receiver()
        _subscribe(w, w.b)
        with self._repair_on_delete(w):
            status = self._delete(w, self._creator(w), notify="false")
        assert status == 404
        assert w.row(w.b) and _subs(w, w.b) and _grant(w, w.b) is not None

    def test_a_stale_bearer_is_refused_by_the_consistent_check(self) -> None:
        """The peer's bearer authenticated against the row it had; the row
        was replaced before the delete: 404, the new row kept."""
        w = Receiver()
        with self._repair_on_delete(w):
            status = self._delete(w, {"Authorization": f"Bearer {w.secrets[w.b]}"})
        assert status == 404
        assert w.row(w.b)

    def test_an_unraced_delete_still_deletes(self) -> None:
        w = Receiver()
        assert self._delete(w, self._creator(w), notify="false") == 204
        assert not w.row(w.b)


class TestTheHookAfterTheLastCheck:
    """Verification 2026-11-10, Issue 7: ``trust_deleted`` fires after the
    delete's last secret check, so a delete that loses fires nothing."""

    def _setup(self) -> tuple[Receiver, list[dict[str, Any]]]:
        from actingweb.interface.hooks import HookRegistry

        registry = HookRegistry()
        seen: list[dict[str, Any]] = []
        registry.register_lifecycle_hook(
            "trust_deleted", lambda actor, **kw: seen.append(kw)
        )
        return Receiver(hooks=registry), seen

    def _delete(self, w: Receiver, **params: str) -> int:
        token = base64.b64encode(f"{w.a.creator}:{PASSPHRASE}".encode()).decode()
        webobj = AWWebObj(
            url="https://test.example.com/x",
            params=params,
            headers={"Authorization": f"Basic {token}"},
        )
        TrustPeerHandler(webobj, w.config, hooks=w.hooks).delete(
            aid(w.a), "friend", w.b
        )
        return webobj.response.status_code

    def test_a_lost_race_fires_no_hook(self) -> None:
        w, seen = self._setup()
        real = type(w.a).delete_reciprocal_trust

        def wrapped(actor: Any, *a: Any, **kw: Any) -> Any:
            if actor.id == aid(w.a):
                _repair(w, w.b)
            return real(actor, *a, **kw)

        with mock.patch.object(type(w.a), "delete_reciprocal_trust", wrapped):
            assert self._delete(w, notify="false") == 404
        assert seen == []
        assert w.row(w.b)

    def test_a_delete_fires_once_with_the_row_before_local_data_goes(self) -> None:
        w, seen = self._setup()
        _subscribe(w, w.b)
        subs_at_hook: list[int] = []
        w.hooks.register_lifecycle_hook(  # type: ignore[union-attr]
            "trust_deleted", lambda actor, **kw: subs_at_hook.append(len(_subs(w, w.b)))
        )
        assert self._delete(w, notify="false") == 204
        assert len(seen) == 1
        assert seen[0]["trust_data"]["peerid"] == w.b
        assert seen[0]["initiated_by_peer"] is False
        assert subs_at_hook == [1]  # the subscriptions were still there
        assert not w.row(w.b)
