"""A trust request for a peer that already has a row (Phase 3).

``thoughts/plans/2026-11-06-peer-authorisation-fixes.md``, Phase 3, with the
owner's re-pair decision (2026-11-08): a request for an existing peer is
accepted only with the trust's current secret as its bearer, and then only
the secret is swapped; anything else answers 403 and changes nothing. The
initiator writes nothing to a row it already has until the peer accepts.
The creator removes a dead peer locally with ``?notify=false``. Real
storage; both backends through ``DATABASE_BACKEND``.
"""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from typing import Any
from unittest import mock

import httpx
import pytest

from actingweb.aw_web_request import AWWebObj
from actingweb.handlers.trust import TrustPeerHandler, TrustRelationshipHandler
from actingweb.interface.hooks import HookRegistry
from actingweb.trust import Trust
from actingweb.trust_permissions import (
    TrustPermissions,
    get_trust_permission_store,
    initialize_trust_permission_store,
)
from tests._adoption_helpers import aid, create_core_actor, make_config, uuid_email

PASSPHRASE = "re-pair-test-passphrase"
KEPT = ("relationship", "approved", "baseuri", "desc", "created_at", "type")
# What a refused request must leave as it was (usage stamps such as
# last_accessed move whenever a bearer authenticates, and are not state).
STATE = (
    "secret",
    "verification_token",
    "relationship",
    "approved",
    "peer_approved",
    "verified",
    "baseuri",
    "desc",
    "type",
    "created_at",
)


def _state(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in STATE}


class Receiver:
    """A, with an approved friend trust to B (and to C)."""

    def __init__(self, *, approved: bool = True, hooks: Any = None) -> None:
        self.config = make_config()
        initialize_trust_permission_store(self.config)
        self.hooks = hooks
        self.a = create_core_actor(self.config, uuid_email(), passphrase=PASSPHRASE)
        tag = uuid.uuid4().hex[:8]
        self.b, self.c = f"peer-b-{tag}", f"peer-c-{tag}"
        self.secrets: dict[str, str] = {}
        for peer in (self.b, self.c):
            self.secrets[peer] = uuid.uuid4().hex
            assert Trust(actor_id=aid(self.a), peerid=peer, config=self.config).create(
                baseuri=f"https://{peer}.example.test/{peer}",
                peer_type="urn:test",
                relationship="friend",
                secret=self.secrets[peer],
                approved=approved,
                verified=True,
                peer_approved=True,
                desc="kept",
            )
        # A custom grant on B's row, which a swap must keep.
        assert get_trust_permission_store(self.config).store_permissions(
            TrustPermissions(
                actor_id=aid(self.a),
                peer_id=self.b,
                trust_type="friend",
                properties={"patterns": ["kept/*"], "operations": ["read"]},
            )
        )

    def row(self, peer: str) -> dict[str, Any]:
        return Trust(actor_id=aid(self.a), peerid=peer, config=self.config).get() or {}

    def request(
        self,
        peer: str,
        new_secret: str,
        *,
        relationship: str = "friend",
        bearer: str | None = None,
        baseuri: str | None = None,
    ) -> AWWebObj:
        headers: dict[str, str] = {}
        if bearer is not None:
            headers["Authorization"] = f"Bearer {bearer}"
        body = {
            "baseuri": baseuri or f"https://{peer}.example.test/{peer}",
            "id": peer,
            "type": "urn:test",
            "secret": new_secret,
            "verify": "whatever",
            "desc": "from the body",
        }
        webobj = AWWebObj(
            url=f"https://test.example.com/{aid(self.a)}/trust/{relationship}",
            body=json.dumps(body),
            headers=headers,
        )
        handler = TrustRelationshipHandler(webobj, self.config, hooks=self.hooks)
        handler.post(aid(self.a), relationship)
        return webobj


def _new_secret() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex


# ---------------------------------------------------------------------------
# The receiver
# ---------------------------------------------------------------------------


class TestTheReceiver:
    def test_a_proven_re_pair_swaps_the_secret_and_keeps_the_rest(self) -> None:
        w = Receiver()
        before = w.row(w.b)
        new = _new_secret()
        with mock.patch("actingweb.actor.requests.get") as verify:
            out = w.request(w.b, new, bearer=w.secrets[w.b])
        verify.assert_not_called()  # no verification round trip for a swap
        assert out.response.status_code == 201
        after = w.row(w.b)
        assert after["secret"] == new
        assert after["verification_token"] != before["verification_token"]
        assert after["verified"] is True and after["peer_approved"] is True
        for key in KEPT:
            assert after.get(key) == before.get(key), key
        grant = get_trust_permission_store(w.config).get_permissions(aid(w.a), w.b)
        assert grant and grant.properties == {
            "patterns": ["kept/*"],
            "operations": ["read"],
        }

    def test_the_status_follows_the_stored_approval(self) -> None:
        w = Receiver(approved=False)
        w.config.auto_accept_default_relationship = True
        w.config.default_relationship = "friend"
        out = w.request(w.b, _new_secret(), bearer=w.secrets[w.b])
        assert out.response.status_code == 202
        assert w.row(w.b)["approved"] is False

    @pytest.mark.parametrize("who", ["none", "nobody", "another peer"])
    def test_an_unproven_request_is_403_and_changes_nothing(self, who: str) -> None:
        w = Receiver()
        before = w.row(w.b)
        bearer = {
            "none": None,
            "nobody": uuid.uuid4().hex,
            "another peer": w.secrets[w.c],
        }[who]
        out = w.request(
            w.b,
            _new_secret(),
            bearer=bearer,
            baseuri="https://elsewhere.example.test/x",
        )
        assert out.response.status_code == 403
        assert _state(w.row(w.b)) == _state(before)

    def test_another_relationship_is_403(self) -> None:
        w = Receiver()
        before = w.row(w.b)
        out = w.request(w.b, _new_secret(), relationship="admin", bearer=w.secrets[w.b])
        assert out.response.status_code == 403
        assert _state(w.row(w.b)) == _state(before)

    @pytest.mark.parametrize("which", ["empty", "its own", "another row's"])
    def test_an_unusable_new_secret_is_403(self, which: str) -> None:
        w = Receiver()
        before = w.row(w.b)
        new = {"empty": "", "its own": w.secrets[w.b], "another row's": w.secrets[w.c]}[
            which
        ]
        out = w.request(w.b, new, bearer=w.secrets[w.b])
        assert out.response.status_code == 403
        assert _state(w.row(w.b)) == _state(before)

    def test_no_trust_request_received_on_a_swap_and_one_on_a_creation(self) -> None:
        hooks = HookRegistry()
        received = mock.Mock()
        hooks.register_lifecycle_hook("trust_request_received", received)
        w = Receiver(hooks=hooks)
        out = w.request(w.b, _new_secret(), bearer=w.secrets[w.b])
        assert out.response.status_code == 201
        received.assert_not_called()
        # A new peer: verified against its base URI, as before.
        new_peer = f"peer-n-{uuid.uuid4().hex[:8]}"
        verified = mock.Mock(status_code=200, content=b'{"verification_token": "t"}')
        with mock.patch("actingweb.actor.requests.get", return_value=verified):
            webobj = AWWebObj(
                url="https://test.example.com/x",
                body=json.dumps(
                    {
                        "baseuri": f"https://{new_peer}.example.test/{new_peer}",
                        "id": new_peer,
                        "type": "urn:test",
                        "secret": _new_secret(),
                        "verify": "t",
                    }
                ),
                headers={},
            )
            TrustRelationshipHandler(webobj, w.config, hooks=hooks).post(
                aid(w.a), "friend"
            )
        assert webobj.response.status_code in (201, 202)
        received.assert_called_once()

    def test_create_verified_trust_never_replaces_a_row(self) -> None:
        w = Receiver()
        before = w.row(w.b)
        with mock.patch("actingweb.actor.requests.get") as verify:
            assert (
                w.a.create_verified_trust(
                    baseuri="https://elsewhere.example.test/x",
                    peerid=w.b,
                    secret=_new_secret(),
                    verification_token="t",
                    relationship="admin",
                )
                is False
            )
        verify.assert_not_called()
        assert _state(w.row(w.b)) == _state(before)


# ---------------------------------------------------------------------------
# The initiator
# ---------------------------------------------------------------------------


class Initiator:
    """B, with an approved friend trust to A (peer-a)."""

    def __init__(self) -> None:
        self.config = make_config()
        self.b = create_core_actor(self.config, uuid_email(), passphrase=PASSPHRASE)
        self.a = f"peer-a-{uuid.uuid4().hex[:8]}"
        self.url = f"https://{self.a}.example.test/{self.a}"
        self.secret = uuid.uuid4().hex
        assert Trust(actor_id=aid(self.b), peerid=self.a, config=self.config).create(
            baseuri=self.url,
            peer_type="urn:test",
            relationship="friend",
            secret=self.secret,
            approved=True,
            verified=True,
            peer_approved=True,
        )
        self.peer_info = {
            "last_response_code": 200,
            "data": {"id": self.a, "type": "urn:test"},
        }

    def row(self) -> dict[str, Any]:
        return (
            Trust(actor_id=aid(self.b), peerid=self.a, config=self.config).get() or {}
        )


class TestTheInitiator:
    @pytest.mark.parametrize("status", [201, 202])
    def test_an_accepted_re_pair_stores_the_new_secret(self, status: int) -> None:
        w = Initiator()
        new = _new_secret()
        answer = mock.Mock(status_code=status, reason="OK", content=b"{}")
        with (
            mock.patch.object(w.b, "get_peer_info", return_value=w.peer_info),
            mock.patch("actingweb.actor.requests.post", return_value=answer) as post,
        ):
            result = w.b.create_reciprocal_trust(
                url=w.url, secret=new, relationship="friend"
            )
        assert result
        sent = post.call_args.kwargs
        assert sent["headers"]["Authorization"] == f"Bearer {w.secret}"
        assert json.loads(sent["data"])["secret"] == new
        row = w.row()
        assert row["secret"] == new and row["approved"] is True

    @pytest.mark.parametrize("outcome", ["403", "500", "no answer"])
    def test_a_refused_re_pair_leaves_the_row_as_it_was(self, outcome: str) -> None:
        w = Initiator()
        before = w.row()
        kwargs: dict[str, Any] = (
            {"side_effect": ConnectionError("down")}
            if outcome == "no answer"
            else {
                "return_value": mock.Mock(
                    status_code=int(outcome), reason="No", content=b""
                )
            }
        )
        with (
            mock.patch.object(w.b, "get_peer_info", return_value=w.peer_info),
            mock.patch("actingweb.actor.requests.post", **kwargs),
        ):
            assert (
                w.b.create_reciprocal_trust(
                    url=w.url, secret=_new_secret(), relationship="friend"
                )
                is False
            )
        assert _state(w.row()) == _state(before)

    def test_the_async_twin_does_the_same(self) -> None:
        w = Initiator()
        before = w.row()
        client = mock.MagicMock()
        client.__aenter__.return_value.post = mock.AsyncMock(
            return_value=mock.Mock(status_code=403, reason_phrase="Forbidden")
        )
        with (
            mock.patch.object(
                w.b, "get_peer_info_async", mock.AsyncMock(return_value=w.peer_info)
            ),
            mock.patch("httpx.AsyncClient", return_value=client),
        ):
            assert (
                asyncio.run(
                    w.b.create_reciprocal_trust_async(
                        url=w.url, secret=_new_secret(), relationship="friend"
                    )
                )
                is False
            )
        assert _state(w.row()) == _state(before)
        sent = client.__aenter__.return_value.post.call_args.kwargs
        assert sent["headers"]["Authorization"] == f"Bearer {w.secret}"

    def test_a_new_peers_row_is_still_removed_on_failure(self) -> None:
        w = Initiator()
        other = f"peer-x-{uuid.uuid4().hex[:8]}"
        info = {"last_response_code": 200, "data": {"id": other, "type": "urn:test"}}
        with (
            mock.patch.object(w.b, "get_peer_info", return_value=info),
            mock.patch(
                "actingweb.actor.requests.post",
                return_value=mock.Mock(status_code=403, reason="No", content=b""),
            ),
        ):
            assert (
                w.b.create_reciprocal_trust(
                    url=f"https://{other}.example.test/{other}",
                    secret=_new_secret(),
                    relationship="friend",
                )
                is False
            )
        assert not Trust(actor_id=aid(w.b), peerid=other, config=w.config).get()


# ---------------------------------------------------------------------------
# ?notify=false
# ---------------------------------------------------------------------------


class TestTheLocalDelete:
    def _delete(self, w: Receiver, headers: dict[str, str]) -> AWWebObj:
        webobj = AWWebObj(
            url="https://test.example.com/x",
            params={"notify": "false"},
            headers=headers,
        )
        TrustPeerHandler(webobj, w.config).delete(aid(w.a), "friend", w.b)
        return webobj

    def test_the_creator_removes_the_row_without_contacting_the_peer(self) -> None:
        w = Receiver()
        token = base64.b64encode(f"{w.a.creator}:{PASSPHRASE}".encode()).decode()
        with (
            mock.patch("requests.delete", side_effect=AssertionError("contacted")),
            mock.patch("requests.post", side_effect=AssertionError("contacted")),
            mock.patch("requests.get", side_effect=AssertionError("contacted")),
            mock.patch.object(
                httpx.Client, "send", side_effect=AssertionError("contacted")
            ),
        ):
            out = self._delete(w, {"Authorization": f"Basic {token}"})
        assert out.response.status_code == 204
        assert not w.row(w.b)

    def test_the_peer_itself_is_refused(self) -> None:
        w = Receiver()
        out = self._delete(w, {"Authorization": f"Bearer {w.secrets[w.b]}"})
        assert out.response.status_code == 403
        assert w.row(w.b)


# ---------------------------------------------------------------------------
# The outside voice on the Phase 3 commit
# ---------------------------------------------------------------------------


class TestPhase3ReviewFixes:
    def test_a_url_other_than_the_stored_base_uri_gets_nothing(self) -> None:
        """A server whose /meta claims the peer's id never receives the
        current secret."""
        w = Initiator()
        before = w.row()
        with (
            mock.patch.object(w.b, "get_peer_info", return_value=w.peer_info),
            mock.patch("actingweb.actor.requests.post") as post,
        ):
            assert (
                w.b.create_reciprocal_trust(
                    url="https://evil.example.test/claims-a",
                    secret=_new_secret(),
                    relationship="friend",
                )
                is False
            )
        post.assert_not_called()
        assert _state(w.row()) == _state(before)

    def test_the_async_twin_also_sends_nothing_elsewhere(self) -> None:
        w = Initiator()
        with (
            mock.patch.object(
                w.b, "get_peer_info_async", mock.AsyncMock(return_value=w.peer_info)
            ),
            mock.patch("httpx.AsyncClient") as client,
        ):
            assert (
                asyncio.run(
                    w.b.create_reciprocal_trust_async(
                        url="https://evil.example.test/claims-a",
                        secret=_new_secret(),
                        relationship="friend",
                    )
                )
                is False
            )
        client.assert_not_called()

    def test_another_relationship_is_refused_before_sending(self) -> None:
        w = Initiator()
        with (
            mock.patch.object(w.b, "get_peer_info", return_value=w.peer_info),
            mock.patch("actingweb.actor.requests.post") as post,
        ):
            assert (
                w.b.create_reciprocal_trust(
                    url=w.url, secret=_new_secret(), relationship="admin"
                )
                is False
            )
        post.assert_not_called()

    def test_a_202_leaves_the_peer_unapproved(self) -> None:
        w = Initiator()
        answer = mock.Mock(status_code=202, reason="Accepted", content=b"{}")
        with (
            mock.patch.object(w.b, "get_peer_info", return_value=w.peer_info),
            mock.patch("actingweb.actor.requests.post", return_value=answer),
        ):
            assert w.b.create_reciprocal_trust(
                url=w.url, secret=_new_secret(), relationship="friend"
            )
        assert w.row()["peer_approved"] is False

    def test_a_bearer_for_a_peer_with_no_row_is_403_and_creates_nothing(
        self,
    ) -> None:
        w = Receiver()
        lost = f"peer-l-{uuid.uuid4().hex[:8]}"
        with mock.patch("actingweb.actor.requests.get") as verify:
            out = w.request(lost, _new_secret(), bearer=uuid.uuid4().hex)
        assert out.response.status_code == 403
        verify.assert_not_called()
        assert not w.row(lost)

    def _squat(self, w: Receiver) -> str:
        """An unverified row for a peer id, as an unauthenticated request
        that failed verification leaves one."""
        squatted = f"peer-s-{uuid.uuid4().hex[:8]}"
        assert Trust(actor_id=aid(w.a), peerid=squatted, config=w.config).create(
            baseuri="https://squatter.example.test/x",
            peer_type="urn:test",
            relationship="friend",
            secret=uuid.uuid4().hex,
            verified=False,
        )
        assert get_trust_permission_store(w.config).store_permissions(
            TrustPermissions(
                actor_id=aid(w.a),
                peer_id=squatted,
                trust_type="friend",
                properties={"patterns": ["squatted/*"], "operations": ["read"]},
            )
        )
        return squatted

    def test_a_verifying_request_replaces_an_unverified_row(self) -> None:
        w = Receiver()
        squatted = self._squat(w)
        new = _new_secret()
        verified = mock.Mock(
            status_code=200, content=b'{"verification_token": "whatever"}'
        )
        with mock.patch("actingweb.actor.requests.get", return_value=verified) as get:
            out = w.request(squatted, new)
        assert out.response.status_code in (201, 202)
        assert get.call_args.kwargs["url"].startswith(
            f"https://{squatted}.example.test/{squatted}"
        )
        row = w.row(squatted)
        assert row["verified"] is True and row["secret"] == new
        assert row["baseuri"] == f"https://{squatted}.example.test/{squatted}"
        # The squatter's grant does not carry over.
        assert not get_trust_permission_store(w.config).get_permissions(
            aid(w.a), squatted
        )

    def test_a_request_that_does_not_verify_leaves_an_unverified_row(
        self,
    ) -> None:
        w = Receiver()
        squatted = self._squat(w)
        before = w.row(squatted)
        refused = mock.Mock(status_code=403, content=b"")
        with mock.patch("actingweb.actor.requests.get", return_value=refused):
            out = w.request(squatted, _new_secret())
        assert out.response.status_code == 403
        assert _state(w.row(squatted)) == _state(before)


class TestTheConditionalCreate:
    def test_only_if_absent_never_replaces_and_keeps_the_grant(self) -> None:
        w = Receiver()
        before = w.row(w.b)
        assert (
            Trust(actor_id=aid(w.a), peerid=w.b, config=w.config).create(
                baseuri="https://elsewhere.example.test/x",
                relationship="admin",
                secret=_new_secret(),
                verified=True,
                only_if_absent=True,
            )
            is False
        )
        assert _state(w.row(w.b)) == _state(before)
        assert get_trust_permission_store(w.config).get_permissions(aid(w.a), w.b)

    def test_only_if_absent_creates_a_new_row(self) -> None:
        w = Receiver()
        peer = f"peer-n-{uuid.uuid4().hex[:8]}"
        assert Trust(actor_id=aid(w.a), peerid=peer, config=w.config).create(
            baseuri="https://n.example.test/n",
            relationship="friend",
            secret=_new_secret(),
            only_if_absent=True,
        )
        assert w.row(peer)["baseuri"] == "https://n.example.test/n"


class TestOnlyAPendingRowIsReplaceable:
    """The outside voice on Phase 4 and the owner's narrowed rule: a
    verifying request replaces only a row that is neither verified nor
    approved, and a re-pair never marks a row verified."""

    def _pending(self, w: Receiver, *, approved: bool = False) -> tuple[str, str]:
        peer = f"peer-p-{uuid.uuid4().hex[:8]}"
        secret = uuid.uuid4().hex
        assert Trust(actor_id=aid(w.a), peerid=peer, config=w.config).create(
            baseuri="https://squatter.example.test/x",
            peer_type="urn:test",
            relationship="friend",
            secret=secret,
            verified=False,
            approved=approved,
        )
        return peer, secret

    def test_a_squatter_cannot_promote_its_own_row(self) -> None:
        w = Receiver()
        peer, secret = self._pending(w)
        out = w.request(peer, _new_secret(), bearer=secret)
        assert out.response.status_code in (201, 202)
        assert w.row(peer)["verified"] is False
        # The real peer's verifying request still replaces it.
        verified = mock.Mock(
            status_code=200, content=b'{"verification_token": "whatever"}'
        )
        with mock.patch("actingweb.actor.requests.get", return_value=verified):
            out = w.request(peer, _new_secret())
        assert out.response.status_code in (201, 202)
        row = w.row(peer)
        assert row["verified"] is True
        assert row["baseuri"] == f"https://{peer}.example.test/{peer}"

    def test_an_approved_unverified_row_is_not_replaced(self) -> None:
        w = Receiver()
        peer, _secret = self._pending(w, approved=True)
        before = w.row(peer)
        verified = mock.Mock(
            status_code=200, content=b'{"verification_token": "whatever"}'
        )
        with mock.patch("actingweb.actor.requests.get", return_value=verified) as get:
            out = w.request(peer, _new_secret())
        assert out.response.status_code == 403
        get.assert_not_called()
        assert _state(w.row(peer)) == _state(before)

    def test_the_conditional_replace_refuses_a_row_no_longer_pending(self) -> None:
        w = Receiver()
        peer, _secret = self._pending(w, approved=True)
        before = w.row(peer)
        assert (
            Trust(actor_id=aid(w.a), peerid=peer, config=w.config).create(
                baseuri="https://elsewhere.example.test/x",
                relationship="friend",
                secret=_new_secret(),
                verified=True,
                only_if_pending=True,
            )
            is False
        )
        assert _state(w.row(peer)) == _state(before)
