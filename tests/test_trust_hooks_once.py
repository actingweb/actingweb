"""Trust hooks fire once, with the same arguments, on every route (3.16, plan
grant-enforcement-per-route, Phase 4, A14 to A16).

Approval: ``trust_fully_approved_local`` once, on the transition to approved
by both sides, with ``trust_data`` = the row; a repeat approval fires
nothing; ``trust_approved`` (deprecated) runs in its place only when no
canonical hook is registered. Deletion: ``trust_deleted`` before the delete,
with the row as ``trust_data`` and ``initiated_by_peer``. Real storage; both
backends through ``DATABASE_BACKEND``.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any
from unittest import mock

import pytest

from actingweb.actor import Actor
from actingweb.aw_web_request import AWWebObj
from actingweb.handlers.trust import TrustPeerHandler
from actingweb.interface.actor_interface import ActorInterface
from actingweb.interface.hooks import HookRegistry
from actingweb.interface.trust_manager import TrustManager
from tests._adoption_helpers import aid
from tests.test_trust_re_pair import PASSPHRASE, Receiver


class Recorder:
    def __init__(self, registry: HookRegistry, *events: str) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        for event in events:
            registry.register_lifecycle_hook(event, self._hook(event))

    def _hook(self, event: str) -> Any:
        def hook(actor: Any, **kwargs: Any) -> None:
            self.calls.append((event, kwargs))

        return hook

    def events(self) -> list[str]:
        return [e for e, _ in self.calls]


def _setup(*events: str) -> tuple[Receiver, Recorder]:
    registry = HookRegistry()
    recorder = Recorder(registry, *events)
    return Receiver(approved=False, hooks=registry), recorder


def _creator(w: Receiver) -> dict[str, str]:
    token = base64.b64encode(f"{w.a.creator}:{PASSPHRASE}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _put_approve(w: Receiver) -> int:
    webobj = AWWebObj(
        url="https://test.example.com/x",
        body=json.dumps({"approved": True}),
        headers=_creator(w),
    )
    TrustPeerHandler(webobj, w.config, hooks=w.hooks).put(aid(w.a), "friend", w.b)
    return webobj.response.status_code


def _manager(w: Receiver) -> TrustManager:
    return ActorInterface(w.a, hooks=w.hooks).trust


def _approve_api(w: Receiver) -> None:
    assert _manager(w).approve_relationship(w.b)


def _approve_api_async(w: Receiver) -> None:
    assert asyncio.run(_manager(w).approve_relationship_async(w.b))


def _approve_rest(w: Receiver) -> None:
    assert _put_approve(w) == 204


ROUTES = {"rest": _approve_rest, "api": _approve_api, "api_async": _approve_api_async}


@pytest.fixture(autouse=True)
def quiet_peer():
    with (
        mock.patch.object(Actor, "reverify_pending_trust", return_value=True),
        mock.patch(
            "actingweb.actor.requests.post", return_value=mock.Mock(status_code=204)
        ),
    ):
        yield


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_each_approving_route_fires_the_canonical_hook_once(route: str) -> None:
    w, rec = _setup("trust_fully_approved_local")
    ROUTES[route](w)
    assert rec.events() == ["trust_fully_approved_local"]
    kwargs = rec.calls[0][1]
    assert kwargs["peer_id"] == w.b and kwargs["relationship"] == "friend"
    assert kwargs["trust_data"]["peerid"] == w.b
    assert kwargs["trust_data"]["approved"] is True

    ROUTES[route](w)  # a repeat approval
    assert rec.events() == ["trust_fully_approved_local"]


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_only_the_deprecated_hook_registered_fires_once_and_warns(
    route: str, caplog: pytest.LogCaptureFixture
) -> None:
    TrustManager._warned_trust_approved = False
    w, rec = _setup("trust_approved")
    with caplog.at_level(logging.WARNING):
        ROUTES[route](w)
    assert rec.events() == ["trust_approved"]
    assert "trust_approved hook is deprecated" in caplog.text


def test_with_both_registered_only_the_canonical_one_fires() -> None:
    w, rec = _setup("trust_fully_approved_local", "trust_approved")
    _approve_rest(w)
    assert rec.events() == ["trust_fully_approved_local"]


class TestDeletion:
    def _delete(self, w: Receiver, headers: dict[str, str], **params: str) -> int:
        webobj = AWWebObj(
            url="https://test.example.com/x", params=params, headers=headers
        )
        TrustPeerHandler(webobj, w.config, hooks=w.hooks).delete(
            aid(w.a), "friend", w.b
        )
        return webobj.response.status_code

    def _seen_row(self, w: Receiver, rec: Recorder) -> Any:
        """The hook records whether the row was still there."""
        seen: list[Any] = []
        assert w.hooks is not None

        def hook(actor: Any, **kwargs: Any) -> None:
            seen.append(w.row(w.b))

        w.hooks.register_lifecycle_hook("trust_deleted", hook)
        return seen

    def test_the_creators_rest_delete(self) -> None:
        registry = HookRegistry()
        rec = Recorder(registry, "trust_deleted")
        w = Receiver(hooks=registry)
        seen = self._seen_row(w, rec)
        assert self._delete(w, _creator(w), notify="false") == 204
        assert rec.events() == ["trust_deleted"]
        kwargs = rec.calls[0][1]
        assert kwargs["trust_data"]["peerid"] == w.b
        assert kwargs["initiated_by_peer"] is False
        assert seen and seen[0]  # fired before the delete

    def test_the_peers_rest_delete(self) -> None:
        registry = HookRegistry()
        rec = Recorder(registry, "trust_deleted")
        w = Receiver(hooks=registry)
        assert self._delete(w, {"Authorization": f"Bearer {w.secrets[w.b]}"}) == 204
        assert rec.calls[0][1]["initiated_by_peer"] is True
        assert rec.calls[0][1]["trust_data"]["peerid"] == w.b

    def test_a_stale_bearer_fires_no_hook_and_deletes_nothing(self) -> None:
        """The bearer authenticated against a row a re-pair has since
        replaced (a stale index entry): 404, and the new row's hook does not
        run."""
        registry = HookRegistry()
        rec = Recorder(registry, "trust_deleted")
        w = Receiver(hooks=registry)
        real = Actor.get_trust_relationships

        def replaced(actor: Any, *a: Any, **kw: Any) -> Any:
            rows = real(actor, *a, **kw)
            return [{**r, "secret": "the-re-pairs-secret"} for r in rows]

        with mock.patch.object(Actor, "get_trust_relationships", replaced):
            status = self._delete(w, {"Authorization": f"Bearer {w.secrets[w.b]}"})
        assert status == 404
        assert rec.calls == []
        assert w.row(w.b)

    def test_delete_relationship(self) -> None:
        registry = HookRegistry()
        rec = Recorder(registry, "trust_deleted")
        w = Receiver(hooks=registry)
        seen = self._seen_row(w, rec)
        with mock.patch(
            "actingweb.actor.requests.delete",
            return_value=mock.Mock(status_code=204),
        ):
            assert _manager(w).delete_relationship(w.b)
        assert rec.events() == ["trust_deleted"]
        assert rec.calls[0][1]["trust_data"]["peerid"] == w.b
        assert rec.calls[0][1]["initiated_by_peer"] is False
        assert seen and seen[0]


def test_a_hook_without_kwargs_is_named_once(caplog: pytest.LogCaptureFixture) -> None:
    registry = HookRegistry()
    HookRegistry._signature_errors_reported.clear()

    def old_hook(actor: Any, peer_id: str, relationship: str) -> None:
        pass

    registry.register_lifecycle_hook("trust_deleted", old_hook)
    with caplog.at_level(logging.ERROR):
        for _ in range(2):
            registry.execute_lifecycle_hooks(
                "trust_deleted",
                mock.Mock(),
                peer_id="p",
                relationship="friend",
                trust_data={},
                initiated_by_peer=False,
            )
    named = [r for r in caplog.records if "must accept **kwargs" in r.getMessage()]
    assert len(named) == 1
    assert "old_hook" in named[0].getMessage()
    # Every later failure is still logged, as before.
    assert len(caplog.records) == 2
