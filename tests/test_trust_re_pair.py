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
from tests._verification_fakes import (
    verification_through_requests_get as verification_through_requests_get,
)

pytestmark = pytest.mark.usefixtures("verification_through_requests_get")

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


def _peer_answers(
    peer: str,
    token: str = "whatever",
    meta_id: str | None = None,
    approved: bool = True,
) -> Any:
    """``requests.get`` as a peer at its base URI answers: its trust row with
    ``token`` on the verification GET, and its ``/meta`` naming ``meta_id``
    (the peer itself unless given)."""

    def get(url: str, **_kw: Any) -> Any:
        if url.rstrip("/").endswith("/meta"):
            body = json.dumps({"id": meta_id or peer, "type": "urn:test"})
            return mock.Mock(
                status_code=200,
                content=body.encode(),
                json=lambda: json.loads(body),
                iter_content=lambda chunk_size=1: iter([body.encode()]),
            )
        # The initiator's own row: created approved before it sent the request.
        answer = json.dumps({"verification_token": token, "approved": approved})
        return mock.Mock(
            status_code=200,
            content=answer.encode(),
            iter_content=lambda chunk_size=1: iter([answer.encode()]),
        )

    return get


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
            # The probe after a lost answer or a 5xx: the peer does not hold
            # the new secret.
            mock.patch(
                "actingweb.actor.requests.get",
                return_value=mock.Mock(status_code=403),
            ),
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
        with mock.patch(
            "actingweb.actor.requests.get", side_effect=_peer_answers(squatted)
        ) as get:
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
        # Audit A2: a pending row is never re-paired; its holder's request is
        # a creation request, refused unless it verifies.
        before = w.row(peer)
        out = w.request(peer, _new_secret(), bearer=secret)
        assert out.response.status_code not in (201, 202)
        assert _state(w.row(peer)) == _state(before)
        assert w.row(peer)["secret"] == secret
        # The real peer's verifying request still replaces it.
        with mock.patch(
            "actingweb.actor.requests.get", side_effect=_peer_answers(peer)
        ):
            out = w.request(peer, _new_secret())
        assert out.response.status_code in (201, 202)
        row = w.row(peer)
        assert row["verified"] is True
        assert row["baseuri"] == f"https://{peer}.example.test/{peer}"

    def test_an_approved_unverified_row_is_not_replaced(self) -> None:
        w = Receiver()
        peer, _secret = self._pending(w, approved=True)
        before = w.row(peer)
        with mock.patch(
            "actingweb.actor.requests.get", side_effect=_peer_answers(peer)
        ) as get:
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


class TestTheClaimIsBound:
    """Verification of 2026-11-08, Issue 4: a request verifies only when its
    base URI serves the peer id it claims."""

    def test_a_base_uri_serving_another_id_is_stored_unverified(self) -> None:
        w = Receiver()
        claimed = f"peer-v-{uuid.uuid4().hex[:8]}"
        with mock.patch(
            "actingweb.actor.requests.get",
            side_effect=_peer_answers(claimed, meta_id="someone-else"),
        ):
            out = w.request(claimed, _new_secret())
        assert out.response.status_code in (201, 202)
        assert w.row(claimed)["verified"] is False

    def test_a_squat_from_a_foreign_base_uri_cannot_replace_a_pending_row(
        self,
    ) -> None:
        w = Receiver()
        peer = f"peer-p-{uuid.uuid4().hex[:8]}"
        assert Trust(actor_id=aid(w.a), peerid=peer, config=w.config).create(
            baseuri="https://first.example.test/x",
            peer_type="urn:test",
            relationship="friend",
            secret=uuid.uuid4().hex,
            verified=False,
        )
        before = w.row(peer)
        with mock.patch(
            "actingweb.actor.requests.get",
            side_effect=_peer_answers(peer, meta_id="the-squatters-own-id"),
        ):
            out = w.request(peer, _new_secret())
        assert out.response.status_code == 403
        assert _state(w.row(peer)) == _state(before)


class TestTheSwapIsNotWrittenBack:
    """Verification of 2026-11-08, Issue 2: a modify writes only the
    attributes it is given, on a row that still exists."""

    def test_a_usage_write_loaded_before_the_swap_keeps_the_new_secret(
        self,
    ) -> None:
        w = Receiver()
        stale = Trust(actor_id=aid(w.a), peerid=w.b, config=w.config)
        assert stale.get()  # loaded with the old secret
        new = _new_secret()
        swapped, reason = w.a.replace_trust_secret(
            peerid=w.b, relationship="friend", secret=new
        )
        assert swapped, reason
        # A request authenticated just before the swap records its usage.
        assert stale.modify(last_accessed="2026-11-08T12:00:00+00:00")
        assert w.row(w.b)["secret"] == new

    def test_a_modify_after_a_delete_does_not_recreate_the_row(self) -> None:
        w = Receiver()
        stale = Trust(actor_id=aid(w.a), peerid=w.b, config=w.config)
        assert stale.get()
        assert Trust(actor_id=aid(w.a), peerid=w.b, config=w.config).delete()
        assert stale.modify(last_accessed="2026-11-08T12:00:00+00:00") is False
        assert not w.row(w.b)


class TestALostAnswerIsProbed:
    """Verification of 2026-11-08, Issue 3: when the re-pair's answer is lost,
    the initiator asks the peer with the new secret."""

    def test_a_lost_answer_the_peer_confirms_stores_the_new_secret(self) -> None:
        w = Initiator()
        new = _new_secret()
        confirmed = mock.Mock(
            status_code=200, json=lambda: {"peerid": aid(w.b), "approved": True}
        )
        with (
            mock.patch.object(w.b, "get_peer_info", return_value=w.peer_info),
            mock.patch(
                "actingweb.actor.requests.post", side_effect=ConnectionError("lost")
            ),
            mock.patch("actingweb.actor.requests.get", return_value=confirmed) as get,
        ):
            assert w.b.create_reciprocal_trust(
                url=w.url, secret=new, relationship="friend"
            )
        probe = get.call_args.kwargs
        assert probe["url"] == f"{w.url}/trust/friend/{aid(w.b)}"
        assert probe["headers"]["Authorization"] == f"Bearer {new}"
        assert w.row()["secret"] == new

    def test_a_server_error_the_peer_does_not_confirm_changes_nothing(
        self,
    ) -> None:
        w = Initiator()
        before = w.row()
        with (
            mock.patch.object(w.b, "get_peer_info", return_value=w.peer_info),
            mock.patch(
                "actingweb.actor.requests.post",
                return_value=mock.Mock(status_code=502, reason="Bad Gateway"),
            ),
            mock.patch(
                "actingweb.actor.requests.get", return_value=mock.Mock(status_code=403)
            ),
        ):
            assert (
                w.b.create_reciprocal_trust(
                    url=w.url, secret=_new_secret(), relationship="friend"
                )
                is False
            )
        assert _state(w.row()) == _state(before)

    @pytest.mark.parametrize(
        "answer",
        [
            mock.Mock(status_code=200, json=mock.Mock(side_effect=ValueError("html"))),
            mock.Mock(status_code=200, json=lambda: {"peerid": "someone-else"}),
            mock.Mock(status_code=202, json=lambda: ["not", "a", "row"]),
        ],
        ids=["not-json", "another-row", "not-an-object"],
    )
    def test_an_answer_that_is_not_our_trust_row_confirms_nothing(
        self, answer: Any
    ) -> None:
        """Reverify-2, Issue 6: a proxy or catch-all page answering 200 does
        not prove the peer holds the new secret."""
        w = Initiator()
        before = w.row()
        with (
            mock.patch.object(w.b, "get_peer_info", return_value=w.peer_info),
            mock.patch(
                "actingweb.actor.requests.post", side_effect=ConnectionError("lost")
            ),
            mock.patch("actingweb.actor.requests.get", return_value=answer),
        ):
            assert (
                w.b.create_reciprocal_trust(
                    url=w.url, secret=_new_secret(), relationship="friend"
                )
                is False
            )
        assert _state(w.row()) == _state(before)

    def test_the_async_twin_probes_too(self) -> None:
        w = Initiator()
        new = _new_secret()
        client = mock.MagicMock()
        client.__aenter__.return_value.post = mock.AsyncMock(
            side_effect=httpx.ConnectError("lost")
        )
        client.__aenter__.return_value.get = mock.AsyncMock(
            return_value=mock.Mock(
                status_code=200,
                json=lambda: {"peerid": aid(w.b), "approved": False},
            )
        )
        with (
            mock.patch.object(
                w.b, "get_peer_info_async", mock.AsyncMock(return_value=w.peer_info)
            ),
            mock.patch("httpx.AsyncClient", return_value=client),
        ):
            assert asyncio.run(
                w.b.create_reciprocal_trust_async(
                    url=w.url, secret=new, relationship="friend"
                )
            )
        row = w.row()
        assert row["secret"] == new and row["peer_approved"] is False


# ---------------------------------------------------------------------------
# Verification of 2026-11-08 (reverify-1)
# ---------------------------------------------------------------------------


def _create(w: Receiver, peer: str, meta_id: str | None = None) -> AWWebObj:
    with mock.patch(
        "actingweb.actor.requests.get",
        side_effect=_peer_answers(peer, meta_id=meta_id),
    ):
        return w.request(peer, _new_secret())


class TestAutoAcceptNeedsAVerifiedRequest:
    """Issue 1: auto-accept approves only a creation that verified (owner),
    so an unverified squat stays pending and the real peer replaces it."""

    def _auto(self) -> Receiver:
        w = Receiver()
        w.config.auto_accept_default_relationship = True
        w.config.default_relationship = "friend"
        return w

    def test_a_verified_creation_is_approved(self) -> None:
        w = self._auto()
        peer = f"peer-v-{uuid.uuid4().hex[:8]}"
        out = _create(w, peer)
        assert out.response.status_code == 201
        assert w.row(peer)["approved"] is True

    def test_an_unverified_creation_waits_for_the_owner(self) -> None:
        w = self._auto()
        peer = f"peer-u-{uuid.uuid4().hex[:8]}"
        out = _create(w, peer, meta_id="someone-else")
        assert out.response.status_code == 202
        row = w.row(peer)
        assert row["approved"] is False and row["verified"] is False

    def test_the_real_peer_then_replaces_the_squat(self) -> None:
        w = self._auto()
        peer = f"peer-s-{uuid.uuid4().hex[:8]}"
        assert _create(w, peer, meta_id="the-squatter").response.status_code == 202
        out = _create(w, peer)
        assert out.response.status_code == 201
        row = w.row(peer)
        assert row["approved"] is True and row["verified"] is True


class TestTheOwnPeerReadsItsPendingRow:
    """Issue 3: the trust GET answers the row's own peer while the owner has
    not approved it (the spec's "approved, pending"), so a lost re-pair
    answer can be confirmed; another peer still gets 403."""

    def _get(self, w: Receiver, bearer: str) -> AWWebObj:
        webobj = AWWebObj(
            url=f"https://test.example.com/{aid(w.a)}/trust/friend/{w.b}",
            headers={"Authorization": f"Bearer {bearer}"},
        )
        TrustPeerHandler(webobj, w.config).get(aid(w.a), "friend", w.b)
        return webobj

    def test_the_own_peer_gets_the_status(self) -> None:
        w = Receiver(approved=False)
        out = self._get(w, w.secrets[w.b])
        assert out.response.status_code == 202  # pending, as the creator sees it
        assert json.loads(out.response.body)["approved"] is False

    def test_another_peer_does_not(self) -> None:
        w = Receiver(approved=False)
        out = self._get(w, w.secrets[w.c])
        assert out.response.status_code == 403

    def test_a_lost_202_is_confirmed_by_the_probe(self) -> None:
        w = Initiator()
        new = _new_secret()
        pending = mock.Mock(
            status_code=202, json=lambda: {"peerid": aid(w.b), "approved": False}
        )
        with (
            mock.patch.object(w.b, "get_peer_info", return_value=w.peer_info),
            mock.patch(
                "actingweb.actor.requests.post", side_effect=ConnectionError("lost")
            ),
            mock.patch("actingweb.actor.requests.get", return_value=pending),
        ):
            assert w.b.create_reciprocal_trust(
                url=w.url, secret=new, relationship="friend"
            )
        row = w.row()
        assert row["secret"] == new and row["peer_approved"] is False


class TestARefusedModifyKeepsTheCopy:
    """Issue 6: a modify that finds the row gone leaves the object as it
    was, not showing values that were never written."""

    def test_the_local_copy_is_unchanged(self) -> None:
        w = Receiver()
        stale = Trust(actor_id=aid(w.a), peerid=w.b, config=w.config)
        before = dict(stale.get() or {})
        assert Trust(actor_id=aid(w.a), peerid=w.b, config=w.config).delete()
        assert stale.modify(secret=_new_secret(), desc="never written") is False
        assert stale.trust == before


# ---------------------------------------------------------------------------
# Verification of 2026-11-08 (reverify-2)
# ---------------------------------------------------------------------------


class TestTheMetaCheckAndThePendingReplacement:
    def test_the_meta_check_is_two_short_tries(self) -> None:
        """Issue 8: an unauthenticated request chooses the host, so the
        /meta check bounds how long it can hold a worker."""
        import requests

        from actingweb.actor import META_CHECK_TIMEOUT, META_CHECK_TRIES

        w = Receiver()
        peer = f"peer-m-{uuid.uuid4().hex[:8]}"
        answers = _peer_answers(peer)
        meta_calls: list[Any] = []

        def get(url: str, **kw: Any) -> Any:
            if url.rstrip("/").endswith("/meta"):
                meta_calls.append(kw)
                raise requests.exceptions.ConnectTimeout("slow host")
            return answers(url, **kw)

        with (
            mock.patch("actingweb.actor.requests.get", side_effect=get),
            mock.patch("time.sleep"),
        ):
            out = w.request(peer, _new_secret())
        assert out.response.status_code == 202
        assert w.row(peer)["verified"] is False
        assert len(meta_calls) == META_CHECK_TRIES == 2
        assert all(kw["timeout"] == META_CHECK_TIMEOUT for kw in meta_calls)

    def test_replacing_a_pending_row_is_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Issue 7: the previous requester's secret stops working here."""
        import logging

        w = Receiver()
        peer = f"peer-r-{uuid.uuid4().hex[:8]}"
        assert _create(w, peer, meta_id="the-squatter").response.status_code == 202
        with caplog.at_level(logging.WARNING, logger="actingweb.actor"):
            _create(w, peer)
        assert any("replaced its pending row" in r.getMessage() for r in caplog.records)

    def test_a_replacement_that_loses_is_not_logged_as_one(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Reverify-3, Issue 5: the WARNING follows the conditional write."""
        import logging

        from actingweb.trust import Trust as TrustRow

        w = Receiver()
        peer = f"peer-l-{uuid.uuid4().hex[:8]}"
        assert _create(w, peer, meta_id="the-squatter").response.status_code == 202
        with (
            mock.patch.object(TrustRow, "create", return_value=False),
            caplog.at_level(logging.WARNING, logger="actingweb.actor"),
        ):
            _create(w, peer)
        messages = [r.getMessage() for r in caplog.records]
        assert not any("its pending row (base URI" in m for m in messages)
        assert any("a row was created meanwhile" in m for m in messages)


# ---------------------------------------------------------------------------
# Verification of 2026-11-08 (reverify-4, the whole-branch review)
# ---------------------------------------------------------------------------


class TestTheInitiatorAfterTheWholeBranchReview:
    def test_creating_the_trust_approves_a_pending_request(self) -> None:
        """Issue 1: the owner creating the trust toward a peer whose request
        waits approves it, as before 3.16, instead of a re-pair."""
        w = Initiator()
        assert Trust(actor_id=aid(w.b), peerid=w.a, config=w.config).modify(
            approved=False
        )
        notified = mock.Mock(status_code=204, reason="No Content", content=b"")
        with (
            mock.patch.object(w.b, "get_peer_info", return_value=w.peer_info),
            mock.patch("actingweb.actor.requests.post", return_value=notified) as post,
        ):
            result = w.b.create_reciprocal_trust(
                url=w.url, secret=_new_secret(), relationship="friend"
            )
        assert result
        row = w.row()
        assert row["approved"] is True
        assert row["secret"] == w.secret  # no re-pair: the secret stays
        assert all(
            "Bearer" not in str(c.kwargs.get("headers", {}).get("Authorization", ""))
            or w.secret in str(c.kwargs["headers"]["Authorization"])
            for c in post.call_args_list
        )

    def test_a_row_written_meanwhile_is_not_replaced(self) -> None:
        """Issue 3: the initiator's create is conditional."""
        config = make_config()
        b = create_core_actor(config, uuid_email(), passphrase=PASSPHRASE)
        peer = f"peer-n-{uuid.uuid4().hex[:8]}"
        info = {"last_response_code": 200, "data": {"id": peer, "type": "urn:test"}}
        theirs = uuid.uuid4().hex
        real_create = Trust.create
        raced: list[int] = []

        def racing(self: Trust, *args: Any, **kwargs: Any) -> Any:
            if not raced:
                raced.append(1)
                # The peer's own request lands between the read and the write.
                assert real_create(
                    Trust(actor_id=aid(b), peerid=peer, config=config),
                    baseuri=f"https://{peer}.example.test/{peer}",
                    peer_type="urn:test",
                    relationship="friend",
                    secret=theirs,
                )
            return real_create(self, *args, **kwargs)

        with (
            mock.patch.object(b, "get_peer_info", return_value=info),
            mock.patch.object(Trust, "create", racing),
            mock.patch("actingweb.actor.requests.post") as post,
        ):
            result = b.create_reciprocal_trust(
                url=f"https://{peer}.example.test/{peer}",
                secret=_new_secret(),
                relationship="friend",
            )
        assert result is False
        post.assert_not_called()
        row = Trust(actor_id=aid(b), peerid=peer, config=config).get() or {}
        assert row.get("secret") == theirs

    def test_a_refused_attempt_keeps_a_row_another_request_wrote(self) -> None:
        """Issue 3: on a refusal, only this attempt's own row is deleted."""
        config = make_config()
        b = create_core_actor(config, uuid_email(), passphrase=PASSPHRASE)
        peer = f"peer-k-{uuid.uuid4().hex[:8]}"
        url = f"https://{peer}.example.test/{peer}"
        info = {"last_response_code": 200, "data": {"id": peer, "type": "urn:test"}}
        theirs = uuid.uuid4().hex

        def refuse_after_a_replacement(**_kwargs: Any) -> Any:
            # Another request swaps the row's secret while ours is in flight.
            assert Trust(actor_id=aid(b), peerid=peer, config=config).modify(
                secret=theirs
            )
            return mock.Mock(status_code=403, reason="Forbidden", content=b"")

        with (
            mock.patch.object(b, "get_peer_info", return_value=info),
            mock.patch(
                "actingweb.actor.requests.post", side_effect=refuse_after_a_replacement
            ),
        ):
            assert (
                b.create_reciprocal_trust(
                    url=url, secret=_new_secret(), relationship="friend"
                )
                is False
            )
        row = Trust(actor_id=aid(b), peerid=peer, config=config).get() or {}
        assert row.get("secret") == theirs

    def test_the_async_re_pair_probes_after_any_send_error(self) -> None:
        """Issue 8: an error that is not an ``httpx.HTTPError`` (an invalid
        URL) reaches the probe too."""
        w = Initiator()
        new = _new_secret()
        client = mock.MagicMock()
        client.__aenter__.return_value.post = mock.AsyncMock(
            side_effect=httpx.InvalidURL("bad")
        )
        client.__aenter__.return_value.get = mock.AsyncMock(
            return_value=mock.Mock(
                status_code=200,
                json=lambda: {"peerid": aid(w.b), "approved": True},
            )
        )
        with (
            mock.patch.object(
                w.b, "get_peer_info_async", mock.AsyncMock(return_value=w.peer_info)
            ),
            mock.patch("httpx.AsyncClient", return_value=client),
        ):
            assert asyncio.run(
                w.b.create_reciprocal_trust_async(
                    url=w.url, secret=new, relationship="friend"
                )
            )
        assert w.row()["secret"] == new


class TestTheTrustStoreAfterTheWholeBranchReview:
    def test_a_stale_handle_still_writes_what_it_is_given(self) -> None:
        """Issue 10: a modify writes every attribute passed, not only those
        that differ from what this handle last read."""
        w = Initiator()
        stale = Trust(actor_id=aid(w.b), peerid=w.a, config=w.config)
        assert (stale.get() or {})["approved"] is True
        assert Trust(actor_id=aid(w.b), peerid=w.a, config=w.config).modify(
            approved=False
        )
        assert stale.modify(approved=True) is True
        assert w.row()["approved"] is True

    def test_a_failed_write_leaves_the_handle_as_it_was(self) -> None:
        """Reverify-5, Issue 8: a fault that is not the row-exists condition
        leaves the object holding what it read, not what was never written."""
        from actingweb.db.exceptions import DbError

        w = Initiator()
        handle = Trust(actor_id=aid(w.b), peerid=w.a, config=w.config)
        assert (handle.get() or {})["approved"] is True
        db: Any = handle.handle
        model: Any = getattr(db, "handle", None)
        if model is None or not hasattr(model, "update"):
            pytest.skip("DynamoDB's handle only")
        with (
            mock.patch.object(
                type(model), "update", side_effect=RuntimeError("throttled")
            ),
            pytest.raises(DbError),
        ):
            db.modify(approved=False)
        assert model.approved is True

    def test_replacing_a_pending_row_renews_its_creation_time(self) -> None:
        """Issue 12: both backends write the replacement's created_at."""
        w = Receiver()
        peer = f"peer-c-{uuid.uuid4().hex[:8]}"
        assert _create(w, peer, meta_id="the-squatter").response.status_code == 202
        first = w.row(peer).get("created_at")
        import time

        time.sleep(1.1)
        _create(w, peer)
        assert w.row(peer).get("created_at") != first


class TestTheInitiatorAfterReverify5:
    """reverify-5 Issues 1, 5 and 6."""

    @staticmethod
    def _pending(w: Initiator, *, verified: bool) -> None:
        assert Trust(actor_id=aid(w.b), peerid=w.a, config=w.config).modify(
            approved=False, verified=verified, peer_approved=True
        )

    def test_an_unverified_pending_row_is_replaced_by_the_owners_request(
        self,
    ) -> None:
        """Issue 1: a request nobody proved is never approved as it is; the
        owner's own request, with the owner's secret, replaces it."""
        w = Initiator()
        self._pending(w, verified=False)
        new = _new_secret()
        accepted = mock.Mock(status_code=202, reason="Accepted", content=b"{}")
        with (
            mock.patch.object(w.b, "get_peer_info", return_value=w.peer_info),
            mock.patch("actingweb.actor.requests.post", return_value=accepted) as post,
        ):
            result = w.b.create_reciprocal_trust(
                url=w.url, secret=new, relationship="friend"
            )
        assert result
        row = w.row()
        assert row["secret"] == new  # the requester's secret no longer works
        assert row["approved"] is True and row["verified"] is True
        sent = post.call_args.kwargs
        assert "Authorization" not in sent["headers"]  # a creation, not a re-pair
        assert json.loads(sent["data"])["secret"] == new

    def test_the_async_twin_replaces_it_too(self) -> None:
        w = Initiator()
        self._pending(w, verified=False)
        new = _new_secret()
        client = mock.MagicMock()
        client.__aenter__.return_value.post = mock.AsyncMock(
            return_value=mock.Mock(status_code=202, content=b"{}")
        )
        with (
            mock.patch.object(
                w.b, "get_peer_info_async", mock.AsyncMock(return_value=w.peer_info)
            ),
            mock.patch("httpx.AsyncClient", return_value=client),
        ):
            assert asyncio.run(
                w.b.create_reciprocal_trust_async(
                    url=w.url, secret=new, relationship="friend"
                )
            )
        row = w.row()
        assert row["secret"] == new and row["approved"] is True

    def test_a_verified_pending_row_is_approved_and_the_peer_told(self) -> None:
        w = Initiator()
        self._pending(w, verified=True)
        told = mock.Mock(status_code=204, reason="No Content", content=b"")
        with (
            mock.patch.object(w.b, "get_peer_info", return_value=w.peer_info),
            mock.patch("actingweb.actor.requests.post", return_value=told) as post,
        ):
            assert w.b.create_reciprocal_trust(
                url=w.url, secret=_new_secret(), relationship="friend"
            )
        post.assert_called_once()
        row = w.row()
        assert row["approved"] is True and row["secret"] == w.secret

    @pytest.mark.parametrize("asynchronous", [False, True])
    def test_approving_on_create_runs_the_local_approval_hook(
        self, asynchronous: bool
    ) -> None:
        """Issue 5: the same hook an approval through PUT runs."""
        from actingweb.interface.trust_manager import TrustManager

        w = Initiator()
        self._pending(w, verified=True)
        hooks = HookRegistry()
        approved = mock.Mock()
        hooks.register_lifecycle_hook("trust_fully_approved_local", approved)
        manager = TrustManager(w.b, hooks=hooks)
        told = mock.Mock(status_code=204, reason="No Content", content=b"")
        with (
            mock.patch.object(w.b, "get_peer_info", return_value=w.peer_info),
            mock.patch.object(
                w.b, "get_peer_info_async", mock.AsyncMock(return_value=w.peer_info)
            ),
            mock.patch("actingweb.actor.requests.post", return_value=told),
        ):
            if asynchronous:
                rel = asyncio.run(
                    manager.create_relationship_async(
                        peer_url=w.url, relationship="friend"
                    )
                )
            else:
                rel = manager.create_relationship(peer_url=w.url, relationship="friend")
        assert rel is not None
        approved.assert_called_once()
        assert approved.call_args.kwargs["peer_id"] == w.a

    def test_a_plain_creation_runs_no_approval_hook(self) -> None:
        from actingweb.interface.trust_manager import TrustManager

        config = make_config()
        b = create_core_actor(config, uuid_email(), passphrase=PASSPHRASE)
        peer = f"peer-p-{uuid.uuid4().hex[:8]}"
        info = {"last_response_code": 200, "data": {"id": peer, "type": "urn:test"}}
        hooks = HookRegistry()
        approved = mock.Mock()
        hooks.register_lifecycle_hook("trust_fully_approved_local", approved)
        accepted = mock.Mock(status_code=201, reason="Created", content=b"{}")
        with (
            mock.patch.object(b, "get_peer_info", return_value=info),
            mock.patch("actingweb.actor.requests.post", return_value=accepted),
        ):
            assert TrustManager(b, hooks=hooks).create_relationship(
                peer_url=f"https://{peer}.example.test/{peer}", relationship="friend"
            )
        approved.assert_not_called()

    def test_a_failed_attempt_keeps_a_row_the_peer_approved(self) -> None:
        """Issue 6: the peer approved (its answer was lost): the row stays."""
        config = make_config()
        b = create_core_actor(config, uuid_email(), passphrase=PASSPHRASE)
        peer = f"peer-l-{uuid.uuid4().hex[:8]}"
        info = {"last_response_code": 200, "data": {"id": peer, "type": "urn:test"}}

        def approved_then_lost(**_kwargs: Any) -> Any:
            assert Trust(actor_id=aid(b), peerid=peer, config=config).modify(
                peer_approved=True
            )
            raise ConnectionError("answer lost")

        with (
            mock.patch.object(b, "get_peer_info", return_value=info),
            mock.patch("actingweb.actor.requests.post", side_effect=approved_then_lost),
        ):
            assert (
                b.create_reciprocal_trust(
                    url=f"https://{peer}.example.test/{peer}",
                    secret=_new_secret(),
                    relationship="friend",
                )
                is False
            )
        assert Trust(actor_id=aid(b), peerid=peer, config=config).get()


class TestTheCreateRoutesAfterReverify5:
    """The HTTP create and the web form approve a verified pending request
    with the same hooks as the API: ``trust_fully_approved_local``, and no
    ``trust_initiated`` (no request went out)."""

    @staticmethod
    def _world() -> tuple[Initiator, HookRegistry, mock.Mock, mock.Mock]:
        w = Initiator()
        assert Trust(actor_id=aid(w.b), peerid=w.a, config=w.config).modify(
            approved=False, verified=True, peer_approved=True
        )
        hooks = HookRegistry()
        approved, initiated = mock.Mock(), mock.Mock()
        hooks.register_lifecycle_hook("trust_fully_approved_local", approved)
        hooks.register_lifecycle_hook("trust_initiated", initiated)
        return w, hooks, approved, initiated

    @staticmethod
    def _patched(w: Initiator) -> Any:
        told = mock.Mock(status_code=204, reason="No Content", content=b"")
        stack = mock.patch.multiple(
            "actingweb.actor.Actor",
            get_peer_info=mock.Mock(return_value=w.peer_info),
        )
        return stack, mock.patch("actingweb.actor.requests.post", return_value=told)

    def test_the_http_create(self) -> None:
        from actingweb.handlers.trust import TrustHandler

        w, hooks, approved, initiated = self._world()
        token = base64.b64encode(f"{w.b.creator}:{PASSPHRASE}".encode()).decode()
        webobj = AWWebObj(
            url=f"https://test.example.com/{aid(w.b)}/trust",
            body=json.dumps({"url": w.url, "relationship": "friend"}),
            headers={"Authorization": f"Basic {token}"},
        )
        info, post = self._patched(w)
        with info, post:
            TrustHandler(webobj, w.config, hooks=hooks).post(aid(w.b))
        assert webobj.response.status_code == 201
        approved.assert_called_once()
        initiated.assert_not_called()

    def test_the_web_form(self) -> None:
        from actingweb.handlers.www import WwwHandler

        w, hooks, approved, _ = self._world()
        webobj = AWWebObj(
            url=f"https://test.example.com/{aid(w.b)}/www/trust/new",
            params={"peer_url": w.url, "trust_type": "friend"},
            headers={},
        )
        info, post = self._patched(w)
        with info, post:
            WwwHandler(webobj, w.config, hooks=hooks)._handle_new_trust_relationship(
                w.b, aid(w.b)
            )
        assert webobj.response.status_code == 302
        approved.assert_called_once()
        assert w.row()["approved"] is True


def _reverse_answers(answer_peerid: str | None, meta_id: str) -> Any:
    """``requests.get`` for a second verification: the reverse URL answers
    our trust row there (``peerid``) when the host holds the secret, else
    404; ``/meta`` names ``meta_id``."""

    def get(url: str, **_kw: Any) -> Any:
        if url.rstrip("/").endswith("/meta"):
            body = json.dumps({"id": meta_id, "type": "urn:test"})
        elif answer_peerid:
            body = json.dumps({"peerid": answer_peerid, "approved": True})
        else:
            return mock.Mock(
                status_code=404,
                content=b"",
                json=lambda: {},
                iter_content=lambda chunk_size=1: iter([b""]),
            )
        return mock.Mock(
            status_code=200,
            content=body.encode(),
            json=lambda: json.loads(body),
            iter_content=lambda chunk_size=1: iter([body.encode()]),
        )

    return get


class TestIdentityAfterTheAudit:
    """Audit A2 and A3, reverify-6 Issues 1 and 2: a secret an unproven
    requester chose never becomes usable, whatever the route."""

    @staticmethod
    def _unverified(w: Receiver) -> tuple[str, str]:
        """A stranger's request under a peer's id, with that peer's real base
        URI and the stranger's secret."""
        peer = f"peer-q-{uuid.uuid4().hex[:8]}"
        secret = uuid.uuid4().hex
        assert Trust(actor_id=aid(w.a), peerid=peer, config=w.config).create(
            baseuri=f"https://{peer}.example.test/{peer}",
            peer_type="urn:test",
            relationship="friend",
            secret=secret,
            verified=False,
            approved=False,
            peer_approved=True,
        )
        return peer, secret

    def test_the_swap_is_conditioned_on_the_authenticating_secret(self) -> None:
        w = Receiver()
        before = w.row(w.b)
        swapped, reason = w.a.replace_trust_secret(
            peerid=w.b,
            relationship="friend",
            secret=_new_secret(),
            proven_secret="a secret the row no longer holds",
        )
        assert swapped is None and "changed" in reason
        assert _state(w.row(w.b)) == _state(before)
        swapped, reason = w.a.replace_trust_secret(
            peerid=w.b,
            relationship="friend",
            secret=_new_secret(),
            proven_secret=w.secrets[w.b],
        )
        assert swapped, reason

    def test_a_pending_row_is_never_re_paired(self) -> None:
        w = Receiver()
        peer, secret = self._unverified(w)
        swapped, reason = w.a.replace_trust_secret(
            peerid=peer, relationship="friend", secret=_new_secret()
        )
        assert swapped is None and "pending" in reason
        assert w.row(peer)["secret"] == secret

    def test_a_row_replaced_after_the_bearer_authenticated_keeps_its_secret(
        self,
    ) -> None:
        """A2: the holder of a pending row authenticates, the owner's own
        request replaces the row, then the re-pair is decided: it must not
        land the holder's new secret on the owner's row."""
        from actingweb.actor import Actor

        w = Receiver()
        peer, secret = self._unverified(w)
        owners = uuid.uuid4().hex
        real_read = Actor.get_trust_relationship

        def replaced_first(self: Actor, peerid: str | None = None) -> Any:
            assert Trust(actor_id=aid(w.a), peerid=peer, config=w.config).create(
                baseuri=f"https://{peer}.example.test/{peer}",
                peer_type="urn:test",
                relationship="friend",
                secret=owners,
                approved=True,
                verified=True,
                only_if_pending=True,
            )
            return real_read(self, peerid=peerid)

        with mock.patch.object(Actor, "get_trust_relationship", replaced_first):
            out = w.request(peer, _new_secret(), bearer=secret)
        assert out.response.status_code == 403
        assert w.row(peer)["secret"] == owners

    def test_every_approval_route_refuses_an_unverified_row(self) -> None:
        """A3, reverify-6 Issue 1: the stranger's secret is not held at the
        base URI, so the second verification fails on every route."""
        from actingweb.interface.trust_manager import TrustManager

        w = Receiver()
        peer, secret = self._unverified(w)
        token = base64.b64encode(f"{w.a.creator}:{PASSPHRASE}".encode()).decode()
        put = AWWebObj(
            url=f"https://test.example.com/{aid(w.a)}/trust/friend/{peer}",
            body=json.dumps({"approved": True}),
            headers={"Authorization": f"Basic {token}"},
        )
        with (
            mock.patch(
                "actingweb.actor.requests.get", side_effect=_reverse_answers(None, peer)
            ),
            mock.patch("actingweb.actor.requests.post") as notify,
        ):
            TrustPeerHandler(put, w.config).put(aid(w.a), "friend", peer)
            assert put.response.status_code == 403
            assert not TrustManager(w.a).approve_relationship(peer)
            assert not w.a.modify_trust_and_notify(
                relationship="friend", peerid=peer, approved=True
            )
            assert not TrustManager(w.a).modify_trust(peer, approved=True)
            assert not Trust(actor_id=aid(w.a), peerid=peer, config=w.config).modify(
                approved=True
            )
        notify.assert_not_called()
        row = w.row(peer)
        assert row["approved"] is False and row["secret"] == secret

    def test_a_request_that_verifies_on_a_second_check_is_approved(self) -> None:
        from actingweb.interface.trust_manager import TrustManager

        w = Receiver()
        peer, secret = self._unverified(w)
        told = mock.Mock(status_code=204, reason="No Content", content=b"")
        with (
            mock.patch(
                "actingweb.actor.requests.get",
                side_effect=_reverse_answers(aid(w.a), peer),
            ),
            mock.patch("actingweb.actor.requests.post", return_value=told),
        ):
            assert TrustManager(w.a).approve_relationship(peer)
        row = w.row(peer)
        assert row["approved"] is True and row["verified"] is True
        assert row["secret"] == secret

    def test_a_meta_that_names_another_id_fails_the_second_check(self) -> None:
        w = Receiver()
        peer, _ = self._unverified(w)
        with mock.patch(
            "actingweb.actor.requests.get",
            side_effect=_reverse_answers(aid(w.a), "someone-else"),
        ):
            assert w.a.reverify_pending_trust(peer) is False
        assert w.row(peer)["verified"] is False

    def test_the_owners_create_approves_a_request_that_verifies_now(self) -> None:
        """Reverify-6 Issue 2: a genuine request whose first verification
        failed is approved in place, not replaced, so both sides still hold
        the same secret."""
        w = Initiator()
        assert Trust(actor_id=aid(w.b), peerid=w.a, config=w.config).modify(
            approved=False, verified=False, peer_approved=True
        )
        told = mock.Mock(status_code=204, reason="No Content", content=b"")
        with (
            mock.patch.object(w.b, "get_peer_info", return_value=w.peer_info),
            mock.patch(
                "actingweb.actor.requests.get",
                side_effect=_reverse_answers(aid(w.b), w.a),
            ),
            mock.patch("actingweb.actor.requests.post", return_value=told) as post,
        ):
            assert w.b.create_reciprocal_trust(
                url=w.url, secret=_new_secret(), relationship="friend"
            )
        row = w.row()
        assert row["approved"] is True and row["verified"] is True
        assert row["secret"] == w.secret  # not replaced
        # The approval notification, not a new creation request.
        assert post.call_args.kwargs["url"].endswith(f"/trust/friend/{aid(w.b)}")


class TestTheApprovalFlagAfterReverify6:
    def test_each_create_starts_with_the_flag_cleared(self) -> None:
        """Reverify-6 Issue 9: the flag the hook reads belongs to one call,
        whichever route made it (not only TrustManager's)."""
        w = Initiator()
        w.b.last_trust_approved_on_create = "a stale peer"
        with mock.patch.object(w.b, "get_peer_info", return_value=None):
            assert not w.b.create_reciprocal_trust(
                url=w.url, secret=_new_secret(), relationship="friend"
            )
        assert w.b.last_trust_approved_on_create is None


class TestTheMirroredRequestAfterReverify7:
    """Reverify-7 Issue 1: a third party files a pending request at A under
    B's id, reads A's token with its own secret, then files a request at B
    under A's id with that token. B's verification (and A's second check)
    read the planted row at the other side, which answered with the secret
    the third party chose. A verification is answered only by a row its host
    approved, and a pending row's own peer never reads its token."""

    @staticmethod
    def _route(config: Any) -> Any:
        """``requests.get`` answered by this process's handlers, so two
        actors on one config verify each other for real."""
        from actingweb.handlers.trust import TrustPeerHandler

        def get(url: str, headers: dict[str, str] | None = None, **_kw: Any) -> Any:
            path = url.split("https://test.example.com/", 1)[1].strip("/")
            parts = path.split("/")
            if parts[-1] == "meta":
                body = json.dumps({"id": parts[0], "type": "urn:test"})
                return mock.Mock(
                    status_code=200,
                    content=body.encode(),
                    json=lambda: json.loads(body),
                    iter_content=lambda chunk_size=1: iter([body.encode()]),
                )
            actor_id, _, rel, peer = parts[:4]
            webobj = AWWebObj(url=url, headers=dict(headers or {}))
            TrustPeerHandler(webobj, config).get(actor_id, rel, peer)
            raw = webobj.response.body or b""
            text = raw.decode() if isinstance(raw, bytes) else str(raw)
            code = webobj.response.status_code
            return mock.Mock(
                status_code=code,
                content=text.encode(),
                json=lambda: json.loads(text),
                iter_content=lambda chunk_size=1: iter([text.encode()]),
            )

        return get

    @staticmethod
    def _file(config: Any, at: str, as_peer: str, secret: str, verify: str) -> int:
        webobj = AWWebObj(
            url=f"https://test.example.com/{at}/trust/friend",
            body=json.dumps(
                {
                    "baseuri": f"https://test.example.com/{as_peer}",
                    "id": as_peer,
                    "type": "urn:test",
                    "secret": secret,
                    "verify": verify,
                }
            ),
            headers={},
        )
        TrustRelationshipHandler(webobj, config).post(at, "friend")
        return webobj.response.status_code

    def _mirror(self) -> tuple[Any, Any, Any, str]:
        """Both planted requests; returns (config, A, B, the third party's
        secret). B auto-accepts ``friend``, as the demo does."""
        config = make_config()
        initialize_trust_permission_store(config)
        config.auto_accept_default_relationship = True
        config.default_relationship = "friend"
        a = create_core_actor(config, uuid_email(), passphrase=PASSPHRASE)
        b = create_core_actor(config, uuid_email(), passphrase=PASSPHRASE)
        secret = uuid.uuid4().hex
        with mock.patch(
            "actingweb.actor.requests.get", side_effect=self._route(config)
        ):
            self._file(config, aid(a), aid(b), secret, "chosen")
            read = self._route(config)(
                f"https://test.example.com/{aid(a)}/trust/friend/{aid(b)}",
                headers={"Authorization": f"Bearer {secret}"},
            )
            token = json.loads(read.content.decode()).get("verification_token", "")
            self._file(config, aid(b), aid(a), secret, token)
        return config, a, b, secret

    def test_the_mirrored_request_is_not_verified_or_approved(self) -> None:
        config, a, b, secret = self._mirror()
        at_b = Trust(actor_id=aid(b), peerid=aid(a), config=config).get() or {}
        assert at_b.get("secret") == secret
        assert at_b.get("verified") is False and at_b.get("approved") is False

    def test_the_second_check_refuses_the_planted_request(self) -> None:
        config, a, b, _ = self._mirror()
        with (
            mock.patch("actingweb.actor.requests.get", side_effect=self._route(config)),
            mock.patch("actingweb.actor.requests.post") as notify,
        ):
            assert a.reverify_pending_trust(aid(b)) is False
            assert not a.modify_trust_and_notify(
                relationship="friend", peerid=aid(b), approved=True
            )
        notify.assert_not_called()
        at_a = Trust(actor_id=aid(a), peerid=aid(b), config=config).get() or {}
        assert at_a.get("verified") is False and at_a.get("approved") is False

    def test_a_pending_rows_own_peer_reads_no_token(self) -> None:
        w = Receiver(approved=False)
        webobj = AWWebObj(
            url=f"https://test.example.com/{aid(w.a)}/trust/friend/{w.b}",
            headers={"Authorization": f"Bearer {w.secrets[w.b]}"},
        )
        TrustPeerHandler(webobj, w.config).get(aid(w.a), "friend", w.b)
        assert webobj.response.status_code == 202
        assert "verification_token" not in json.loads(webobj.response.body)

    def test_an_approved_rows_own_peer_still_reads_it(self) -> None:
        w = Receiver(approved=True)
        webobj = AWWebObj(
            url=f"https://test.example.com/{aid(w.a)}/trust/friend/{w.b}",
            headers={"Authorization": f"Bearer {w.secrets[w.b]}"},
        )
        TrustPeerHandler(webobj, w.config).get(aid(w.a), "friend", w.b)
        assert webobj.response.status_code == 200
        assert "verification_token" in json.loads(webobj.response.body)

    def test_an_unapproved_answer_does_not_verify_a_creation(self) -> None:
        w = Receiver()
        peer = f"peer-m-{uuid.uuid4().hex[:8]}"
        with mock.patch(
            "actingweb.actor.requests.get",
            side_effect=_peer_answers(peer, approved=False),
        ):
            out = w.request(peer, _new_secret())
        assert out.response.status_code == 202
        assert w.row(peer)["verified"] is False


class TestTheApprovalPathAfterReverify7:
    """Reverify-7 Issues 3 to 9 on the approval path."""

    @staticmethod
    def _basic(w: Receiver) -> dict[str, str]:
        token = base64.b64encode(f"{w.a.creator}:{PASSPHRASE}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def _put(
        self, w: Receiver, peer: str, body: dict[str, Any] | None, **params: str
    ) -> AWWebObj:
        webobj = AWWebObj(
            url=f"https://test.example.com/{aid(w.a)}/trust/friend/{peer}",
            # A browser form sends no JSON body: the handler then reads the
            # query parameters.
            body=json.dumps(body) if body is not None else "",
            params=params or None,
            headers=self._basic(w),
        )
        TrustPeerHandler(webobj, w.config).put(aid(w.a), "friend", peer)
        return webobj

    def test_a_failed_approval_write_tells_the_peer_nothing(self) -> None:
        """Issue 3: the write is conditioned on the row read, and a write
        that did not land notifies nobody."""
        from actingweb.actor import Actor

        w = Receiver(approved=False)
        stale = dict(w.row(w.b), secret="the secret of a row since replaced")
        with (
            mock.patch.object(Actor, "get_trust_relationships", return_value=[stale]),
            mock.patch("actingweb.actor.requests.post") as notify,
        ):
            assert not w.a.modify_trust_and_notify(
                relationship="friend", peerid=w.b, approved=True
            )
        notify.assert_not_called()
        assert w.row(w.b)["approved"] is False

    def test_an_approved_unverified_row_takes_a_repeated_approval(self) -> None:
        """Issue 4: a row approved before 3.16 without a verification: an
        idempotent approval with another change neither probes nor fails."""
        w = Receiver()
        assert Trust(actor_id=aid(w.a), peerid=w.b, config=w.config).modify(
            verified=False
        )
        with mock.patch("actingweb.actor.requests.get") as probe:
            assert w.a.modify_trust_and_notify(
                relationship="friend", peerid=w.b, approved=True, desc="changed"
            )
            out = self._put(w, w.b, {"approved": True, "desc": "again"})
        probe.assert_not_called()
        assert out.response.status_code == 204
        assert w.row(w.b)["desc"] == "again"

    def test_the_refusal_says_why(self) -> None:
        """Issue 5: the web UI's Approve form gets a page with a way back, an
        API client a JSON error."""
        w = Receiver()
        peer, _ = TestIdentityAfterTheAudit._unverified(w)
        with mock.patch(
            "actingweb.actor.requests.get", side_effect=_reverse_answers(None, peer)
        ):
            form = self._put(w, peer, None, _method="PUT", approved="true")
            api = self._put(w, peer, {"approved": True})
        assert form.response.status_code == 403
        page = form.response.body
        page = page.decode() if isinstance(page, bytes) else str(page)
        assert "not verified" in page and f"/{aid(w.a)}/www/trust" in page
        assert api.response.status_code == 403
        assert "not verified" in json.loads(api.response.body)["error"]

    def test_modify_trust_repeats_the_verification(self) -> None:
        """Issue 6: ``TrustManager.modify_trust(approved=True)`` approves a
        request that verifies on a second check, as the other routes do."""
        from actingweb.interface.trust_manager import TrustManager

        w = Receiver()
        peer, _ = TestIdentityAfterTheAudit._unverified(w)
        with mock.patch(
            "actingweb.actor.requests.get",
            side_effect=_reverse_answers(aid(w.a), peer),
        ):
            assert TrustManager(w.a).modify_trust(peer, approved=True)
        assert w.row(peer)["approved"] is True

    def test_another_relationship_replaces_the_request_unprobed(self) -> None:
        """Issue 7: the owner's create for another relationship than the
        pending request's replaces it; it is not verified and then
        refused."""
        w = Initiator()
        TestTheInitiatorAfterReverify5._pending(w, verified=False)
        new = _new_secret()
        accepted = mock.Mock(status_code=202, reason="Accepted", content=b"{}")
        with (
            mock.patch.object(w.b, "get_peer_info", return_value=w.peer_info),
            mock.patch("actingweb.actor.requests.get") as probe,
            mock.patch("actingweb.actor.requests.post", return_value=accepted),
        ):
            assert w.b.create_reciprocal_trust(
                url=w.url, secret=new, relationship="associate"
            )
        probe.assert_not_called()
        row = w.row()
        assert row["secret"] == new and row["relationship"] == "associate"

    def test_a_missing_row_is_404_and_a_move_with_an_approval_400(self) -> None:
        """Issue 8."""
        w = Receiver()
        assert self._put(w, "peer-gone", {"approved": True}).response.status_code == (
            404
        )
        peer, _ = TestIdentityAfterTheAudit._unverified(w)
        with mock.patch("actingweb.actor.requests.get") as probe:
            out = self._put(
                w,
                peer,
                {"approved": True, "baseuri": "https://moved.example.test/x"},
            )
        probe.assert_not_called()
        assert out.response.status_code == 400
        assert w.row(peer)["approved"] is False

    def test_a_peer_with_no_trust_row_gets_nothing(self) -> None:
        """Issue 9: a permission override with no trust row (a delete that
        faulted half way) grants nothing."""
        from actingweb.permission_evaluator import (
            PermissionResult,
            PermissionType,
            get_permission_evaluator,
        )
        from actingweb.trust_permissions import create_permission_override

        w = Receiver()
        ghost = f"peer-g-{uuid.uuid4().hex[:8]}"
        assert get_trust_permission_store(w.config).store_permissions(
            create_permission_override(
                actor_id=aid(w.a),
                peer_id=ghost,
                trust_type="friend",
                permission_updates={
                    "properties": {"patterns": ["*"], "operations": ["read"]}
                },
            )
        )
        result = get_permission_evaluator(w.config).evaluate_permission(
            aid(w.a), ghost, PermissionType.PROPERTIES, "anything", "read"
        )
        assert result == PermissionResult.DENIED


class TestTheSecondCheckIsBounded:
    """Reverify-7 Issue 10: the second verification's GET goes to a base
    URI the requester chose: no redirect is followed, and an answer larger
    than the cap does not verify."""

    def test_no_redirect_and_a_capped_answer(self) -> None:
        from actingweb import actor as actor_module

        w = Receiver()
        peer, _ = TestIdentityAfterTheAudit._unverified(w)
        body = json.dumps(
            {"peerid": aid(w.a), "approved": True, "pad": "x" * (70 * 1024)}
        ).encode()
        big = mock.Mock(
            status_code=200,
            iter_content=lambda chunk_size=1: iter(
                [body[i : i + 4096] for i in range(0, len(body), 4096)]
            ),
        )
        with mock.patch("actingweb.actor.requests.get", return_value=big) as get:
            assert w.a.reverify_pending_trust(peer) is False
        assert get.call_args.kwargs["allow_redirects"] is False
        assert len(body) > actor_module._REVERIFY_MAX_BYTES
        assert w.row(peer)["verified"] is False


class TestTheClientViewAfterReverify8:
    """Reverify-8 Issue 2: ``as_client(client_id)`` evaluates as the
    client's trust row (``oauth2_client:<email>:<client>``), not as the raw
    client id, which has no row and so is granted nothing."""

    @staticmethod
    def _client(w: Receiver, client_id: str) -> str:
        peer = f"oauth2_client:user@example.test:{client_id}"
        trust = Trust(actor_id=aid(w.a), peerid=peer, config=w.config)
        assert trust.create(
            baseuri="",
            peer_type="mcp",
            relationship="friend",
            secret=uuid.uuid4().hex,
            approved=True,
            verified=True,
            peer_approved=True,
            established_via="oauth2_client",
        )
        assert trust.modify(oauth_client_id=client_id)
        from actingweb.trust_permissions import create_permission_override

        assert get_trust_permission_store(w.config).store_permissions(
            create_permission_override(
                actor_id=aid(w.a),
                peer_id=peer,
                trust_type="friend",
                permission_updates={
                    "properties": {
                        "patterns": ["notes"],
                        "operations": ["read", "write"],
                        # Overrides add to the friend grant: exclude to narrow.
                        "excluded_patterns": ["secret"],
                    }
                },
            )
        )
        return peer

    def test_a_client_view_reads_and_writes_what_its_trust_grants(self) -> None:
        from actingweb.interface.actor_interface import ActorInterface
        from actingweb.interface.authenticated_views import PermissionError

        w = Receiver()
        client_id = f"mcp_{uuid.uuid4().hex[:8]}"
        self._client(w, client_id)
        view = ActorInterface(w.a).as_client(client_id)
        view.properties["notes"] = "from the client"
        assert view.properties["notes"] == "from the client"
        with pytest.raises(PermissionError):
            view.properties["secret"] = "not granted"

    def test_a_client_with_no_trust_row_gets_nothing(self) -> None:
        from actingweb.interface.actor_interface import ActorInterface
        from actingweb.interface.authenticated_views import PermissionError

        w = Receiver()
        view = ActorInterface(w.a).as_client("mcp_unknown_client")
        with pytest.raises(PermissionError):
            view.properties["notes"] = "x"


class TestTheDeadlineHoldsAfterReverify8:
    """Reverify-8 Issues 1 and 3: both verifications return within their
    deadline whatever the peer does (a body trickled, an answer that never
    starts), and the first verification, which an unauthenticated request
    triggers, goes through the same bounded read."""

    def _timed(self, w: Receiver, peer: str, get: Any) -> float:
        import time

        with (
            mock.patch("actingweb.actor._REVERIFY_DEADLINE_SECONDS", 0.5),
            mock.patch("actingweb.actor.requests.get", side_effect=get),
        ):
            started = time.monotonic()
            assert w.a.reverify_pending_trust(peer) is False
            return time.monotonic() - started

    def test_a_trickled_body_is_cut_at_the_deadline(self) -> None:
        import time

        w = Receiver()
        peer, _ = TestIdentityAfterTheAudit._unverified(w)

        def trickle(chunk_size: int = 1) -> Any:
            # As a socket read does: a chunk is handed over only once it is
            # full (or the body ends), however slowly its bytes arrive.
            buffered = b""
            for _ in range(60):
                time.sleep(0.1)
                buffered += b" "
                if len(buffered) >= chunk_size:
                    yield buffered
                    buffered = b""
            if buffered:
                yield buffered

        slow = mock.Mock(status_code=200, iter_content=trickle)
        assert self._timed(w, peer, lambda *a, **k: slow) < 2.0
        assert w.row(peer)["verified"] is False

    def test_an_answer_that_never_starts_is_cut_at_the_deadline(self) -> None:
        import time

        w = Receiver()
        peer, _ = TestIdentityAfterTheAudit._unverified(w)

        def stalled(*_a: Any, **_k: Any) -> Any:
            time.sleep(3)
            raise ConnectionError("too late")

        assert self._timed(w, peer, stalled) < 2.0

    def test_the_first_verification_is_bounded_too(self) -> None:
        w = Receiver()
        peer = f"peer-f-{uuid.uuid4().hex[:8]}"
        with mock.patch(
            "actingweb.actor.requests.get", side_effect=_peer_answers(peer)
        ) as get:
            w.request(peer, _new_secret())
        verify_calls = [
            c for c in get.call_args_list if not str(c.kwargs["url"]).endswith("/meta")
        ]
        assert verify_calls
        assert all(c.kwargs["allow_redirects"] is False for c in verify_calls)
        assert all(c.kwargs["stream"] is True for c in verify_calls)


class TestTheEdgesAfterReverify8:
    """Reverify-8 Issues 4 to 7."""

    def test_modify_trust_approves_only_the_row_it_re_verified(self) -> None:
        """Issue 4: a row replaced between the second check and the write is
        not approved unseen."""
        from actingweb.actor import Actor
        from actingweb.interface.trust_manager import TrustManager

        w = Receiver()
        peer, _ = TestIdentityAfterTheAudit._unverified(w)

        def replaced_meanwhile(self: Actor, peerid: str) -> bool:
            # A verified request replaced the row after it was read.
            assert Trust(actor_id=aid(w.a), peerid=peer, config=w.config).modify(
                secret="the replacing request's secret", verified=True
            )
            return True

        with mock.patch.object(Actor, "reverify_pending_trust", replaced_meanwhile):
            assert not TrustManager(w.a).modify_trust(peer, approved=True)
        assert w.row(peer)["approved"] is False

    def test_a_string_approval_meets_the_same_gates(self) -> None:
        """Issue 5: ``approved="true"`` is an approval, gated as one."""
        from actingweb.interface.trust_manager import TrustManager

        w = Receiver()
        peer, _ = TestIdentityAfterTheAudit._unverified(w)
        with mock.patch(
            "actingweb.actor.requests.get", side_effect=_reverse_answers(None, peer)
        ):
            assert not TrustManager(w.a).modify_trust(peer, approved="true")
        assert not Trust(actor_id=aid(w.a), peerid=peer, config=w.config).modify(
            approved="true"  # type: ignore[arg-type]
        )
        assert w.row(peer)["approved"] is False

    def _put(self, w: Receiver, rel: str, peer: str, body: Any) -> AWWebObj:
        token = base64.b64encode(f"{w.a.creator}:{PASSPHRASE}".encode()).decode()
        webobj = AWWebObj(
            url=f"https://test.example.com/{aid(w.a)}/trust/{rel}/{peer}",
            body=json.dumps(body),
            headers={"Authorization": f"Basic {token}"},
        )
        TrustPeerHandler(webobj, w.config).put(aid(w.a), rel, peer)
        return webobj

    def test_a_put_for_another_relationship_is_404_and_checks_nothing(self) -> None:
        """Issue 6."""
        w = Receiver()
        peer, _ = TestIdentityAfterTheAudit._unverified(w)
        with mock.patch("actingweb.actor.requests.get") as probe:
            out = self._put(w, "admin", peer, {"approved": True})
        assert out.response.status_code == 404
        probe.assert_not_called()
        assert w.row(peer)["verified"] is False

    def test_a_base_uri_that_is_not_text_is_400(self) -> None:
        """Issue 6."""
        w = Receiver()
        peer, _ = TestIdentityAfterTheAudit._unverified(w)
        out = self._put(w, "friend", peer, {"approved": True, "baseuri": 5})
        assert out.response.status_code == 400

    def test_a_pending_requests_answer_carries_no_token(self) -> None:
        """Issue 7: the 202 answer to a trust request that waits."""
        w = Receiver()
        peer = f"peer-p-{uuid.uuid4().hex[:8]}"
        out = _create(w, peer, meta_id="someone-else")
        assert out.response.status_code == 202
        body = json.loads(out.response.body)
        assert "verification_token" not in body and "secret" not in body


class TestFlagsAfterReverify9:
    """Reverify-9 Issue 3: a trust flag is a bool, ``"true"`` or
    ``"false"``; anything else raises instead of being read as False, which
    revoked an approval."""

    @pytest.mark.parametrize("value", [1, 0, "1", "yes", "", "on"])
    def test_anything_else_raises_and_writes_nothing(self, value: Any) -> None:
        from actingweb.interface.trust_manager import TrustManager

        w = Receiver()
        before = _state(w.row(w.b))
        with pytest.raises(ValueError):
            TrustManager(w.a).modify_trust(w.b, approved=value)
        with pytest.raises(ValueError):
            Trust(actor_id=aid(w.a), peerid=w.b, config=w.config).modify(approved=value)
        assert _state(w.row(w.b)) == before

    def test_text_true_and_false_are_flags(self) -> None:
        w = Receiver()
        assert Trust(actor_id=aid(w.a), peerid=w.b, config=w.config).modify(
            peer_approved="FALSE "  # type: ignore[arg-type]
        )
        assert w.row(w.b)["peer_approved"] is False
        assert Trust(actor_id=aid(w.a), peerid=w.b, config=w.config).modify(
            peer_approved="True"  # type: ignore[arg-type]
        )
        assert w.row(w.b)["peer_approved"] is True


class TestTheClientViewAfterReverify9:
    """Reverify-9 Issue 5: a client view's identity is its own trust row,
    resolved on first use."""

    def test_a_peer_id_passed_in_grants_nothing(self) -> None:
        """A trust dict naming another peer's row does not make the client
        that peer."""
        from actingweb.interface.actor_interface import ActorInterface
        from actingweb.interface.authenticated_views import PermissionError

        w = Receiver()  # B is an approved friend that may read kept/*
        as_b = ActorInterface(w.a).as_peer(w.b, {"peerid": w.b})
        assert as_b.properties["kept/x"] is None  # B may read it
        view = ActorInterface(w.a).as_client("mcp_stranger", {"peerid": w.b})
        with pytest.raises(PermissionError):
            _ = view.properties["kept/x"]

    def test_a_clients_subscription_is_kept_under_its_trust(self) -> None:
        from actingweb.interface.actor_interface import ActorInterface

        w = Receiver()
        client_id = f"mcp_{uuid.uuid4().hex[:8]}"
        peer = TestTheClientViewAfterReverify8._client(w, client_id)
        view = ActorInterface(w.a).as_client(client_id)
        with mock.patch(
            "actingweb.interface.authenticated_views.AuthenticatedSubscriptionManager._check_subscription_permission"
        ):
            assert view.subscriptions.create_local_subscription("properties")
        assert {s.peer_id for s in view.subscriptions.all_subscriptions} == {peer}

    def test_building_a_view_reads_no_trust(self) -> None:
        from actingweb.interface.actor_interface import ActorInterface
        from actingweb.interface.authenticated_views import PermissionError

        w = Receiver()
        with mock.patch(
            "actingweb.oauth2_server.trust_lookup.find_client_trust",
            return_value=None,
        ) as lookup:
            view = ActorInterface(w.a).as_client("mcp_lazy")
            lookup.assert_not_called()
            with pytest.raises(PermissionError):
                view.properties["notes"] = "x"
            lookup.assert_called_once()


class TestTheClientViewAfterReverify10:
    """Reverify-10 Issues 5 to 7."""

    def test_a_clients_subscription_gets_no_push(self) -> None:
        """Issue 5: a client's subscription is kept under its trust row, which
        has no endpoint to push to; a write sends nothing."""
        from actingweb.interface.actor_interface import ActorInterface

        w = Receiver()
        client_id = f"mcp_{uuid.uuid4().hex[:8]}"
        TestTheClientViewAfterReverify8._client(w, client_id)
        view = ActorInterface(w.a).as_client(client_id)
        with mock.patch(
            "actingweb.interface.authenticated_views.AuthenticatedSubscriptionManager._check_subscription_permission"
        ):
            assert view.subscriptions.create_local_subscription("properties")
        with (
            mock.patch("actingweb.actor.requests.post") as post,
            mock.patch("httpx.AsyncClient.post") as async_post,
        ):
            ActorInterface(w.a).properties["notes"] = "changed"
        post.assert_not_called()
        async_post.assert_not_called()

    def test_a_peers_subscription_is_still_pushed(self) -> None:
        """The control: a peer with an endpoint is pushed to."""
        w = Receiver()
        assert w.a.create_subscription(
            peerid=w.b, target="properties", granularity="high"
        )
        with mock.patch("actingweb.actor.requests.post") as post:
            w.a.register_diffs(target="properties", subtarget="kept", blob='{"x": 1}')
        assert post.called

    def test_a_listing_ignores_a_peer_id_passed_in(self) -> None:
        """Issue 6: a trust dict naming another peer does not list that
        peer's subscriptions."""
        from actingweb.interface.actor_interface import ActorInterface

        w = Receiver()
        assert w.a.create_subscription(
            peerid=w.b, target="properties", granularity="high"
        )
        view = ActorInterface(w.a).as_client("mcp_stranger", {"peerid": w.b})
        assert view.subscriptions.all_subscriptions == []

    def test_a_fault_while_resolving_is_retried(self) -> None:
        """Issue 7: a DbError on the first lookup leaves the view able to
        resolve its row on the next check."""
        from actingweb.db.exceptions import DbError
        from actingweb.interface.actor_interface import ActorInterface

        w = Receiver()
        client_id = f"mcp_{uuid.uuid4().hex[:8]}"
        peer = TestTheClientViewAfterReverify8._client(w, client_id)
        view = ActorInterface(w.a).as_client(client_id)
        with (
            mock.patch(
                "actingweb.oauth2_server.trust_lookup.find_client_trust",
                side_effect=DbError("down"),
            ),
            pytest.raises(DbError),
        ):
            _ = view._auth_context.permission_id
        assert view._auth_context.permission_id == peer


class TestTheResyncAfterReverify11:
    """Reverify-11 Issue 1: a resume sends nothing to a client's trust row
    and records no miss for it. Reverify-12 Issue 1 and reverify-13 Issue 1
    (owner: option 1): its resync is a marker stored as its next diff, and
    the client re-reads the target under its own grant; no data is stored,
    so nothing escapes the grant."""

    @staticmethod
    def _client_sub(
        w: Receiver, via: str, baseuri: str, subtarget: str = ""
    ) -> tuple[str, str, str]:
        """A client's trust row and its subscription: (peer, subid, secret)."""
        peer = f"{via}:user@example.test:{uuid.uuid4().hex[:8]}"
        secret = uuid.uuid4().hex
        trust = Trust(actor_id=aid(w.a), peerid=peer, config=w.config)
        assert trust.create(
            baseuri=baseuri,
            peer_type="mcp",
            relationship="friend",
            secret=secret,
            approved=True,
            verified=True,
            peer_approved=True,
            established_via=via,
        )
        assert w.a.create_subscription(
            peerid=peer, target="properties", subtarget=subtarget, granularity="high"
        )
        subs = w.a.get_subscriptions(peerid=peer, target="properties")
        assert subs
        return peer, str(subs[0]["subscriptionid"]), secret

    @staticmethod
    def _resume_after_a_write(w: Receiver, name: str, value: str) -> int:
        assert w.a.suspend_subscriptions("properties")
        w.a.set_property(name, value)
        with (
            mock.patch("actingweb.actor.requests.post") as post,
            mock.patch("httpx.AsyncClient.post") as async_post,
        ):
            count = w.a.resume_subscriptions("properties")
        post.assert_not_called()
        async_post.assert_not_called()
        return count

    @pytest.mark.parametrize(
        "via,own_uri",
        [("oauth2_client", False), ("oauth2_interactive", True)],
    )
    def test_a_clients_row_gets_a_resync_marker(self, via: str, own_uri: bool) -> None:
        w = Receiver()
        baseuri = f"{w.config.root}{aid(w.a)}" if own_uri else ""
        peer, subid, _ = self._client_sub(w, via, baseuri)
        assert self._resume_after_a_write(w, "during", "the suspension") == 1
        sub_obj = w.a.get_subscription_obj(peerid=peer, subid=subid)
        assert sub_obj
        diffs = sub_obj.get_diffs()
        assert len(diffs) == 1
        assert json.loads(diffs[0]["diff"]) == {
            "type": "resync",
            "url": f"{w.config.proto}{w.config.fqdn}/{aid(w.a)}/properties",
        }
        assert w.a._resync_pending("properties", None) is None

    def _client_reads(
        self, w: Receiver, peer: str, subid: str, secret: str, seq: int | None
    ) -> Any:
        from actingweb.handlers.subscription import (
            SubscriptionDiffHandler,
            SubscriptionHandler,
        )

        webobj = AWWebObj(
            url=f"https://test.example.com/{aid(w.a)}/x",
            params={},
            body=None,
            headers={"Authorization": f"Bearer {secret}"},
        )
        if seq is None:
            SubscriptionHandler(webobj, w.config).get(aid(w.a), peer, subid)
        else:
            SubscriptionDiffHandler(webobj, w.config).get(aid(w.a), peer, subid, seq)
        assert webobj.response.status_code == 200, webobj.response.status_code
        return webobj.response.body

    @pytest.mark.parametrize("by_sequence", [False, True])
    def test_the_marker_carries_nothing_the_grant_excludes(
        self, by_sequence: bool
    ) -> None:
        """Reverify-13 Issue 1: a client subscribed to one property, its
        grant excluding a key of it. The resync as the client reads it
        (``GET /subscriptions/<peer>/<sub>`` and ``/<seq>``): the marker,
        empty data, and the excluded value nowhere."""
        from actingweb.trust_permissions import (
            create_permission_override,
            get_trust_permission_store,
        )

        w = Receiver()
        peer, subid, secret = self._client_sub(w, "oauth2_client", "", "notes")
        assert get_trust_permission_store(w.config).store_permissions(
            create_permission_override(
                actor_id=aid(w.a),
                peer_id=peer,
                trust_type="friend",
                permission_updates={
                    "properties": {"excluded_patterns": ["notes/private"]}
                },
            )
        )
        value = json.dumps({"public": "open", "private": "hidden-value"})
        assert self._resume_after_a_write(w, "notes", value) == 1
        body = self._client_reads(w, peer, subid, secret, 1 if by_sequence else None)
        assert "hidden-value" not in body
        answer = json.loads(body)
        served = answer if by_sequence else answer["data"][0]
        assert served["type"] == "resync"
        assert served["url"].endswith(f"/{aid(w.a)}/properties/notes")
        assert served["data"] == {}

    def test_a_peer_still_gets_its_resync(self) -> None:
        """The control: a peer's subscription is resynced."""
        w = Receiver()
        assert w.a.create_subscription(
            peerid=w.b, target="properties", granularity="high"
        )
        missed: list[str] = []
        with mock.patch.object(
            w.a, "_send_resync_callback_sync", return_value=True
        ) as send:
            count = w.a._send_resync_callbacks("properties", None, missed=missed)
        assert send.called
        assert count == 1


class TestTheRePairAnswerAfterReverify9:
    def test_a_re_pair_of_an_unapproved_row_answers_without_its_token(
        self,
    ) -> None:
        """Reverify-9 Issue 4: the re-pair's 202 follows the same rule as a
        creation's (one answer body for both)."""
        w = Receiver(approved=False)  # verified, not approved
        out = w.request(w.b, _new_secret(), bearer=w.secrets[w.b])
        assert out.response.status_code == 202
        body = json.loads(out.response.body)
        assert "verification_token" not in body and "secret" not in body


class TestFlagsAfterReverify10:
    """Reverify-10 Issue 8: ``modify_trust_and_notify`` parses its flags as
    the other routes do."""

    def test_text_true_meets_the_gate(self) -> None:
        w = Receiver()
        peer, _ = TestIdentityAfterTheAudit._unverified(w)
        with mock.patch.object(
            type(w.a), "reverify_pending_trust", return_value=False
        ) as gate:
            assert (
                w.a.modify_trust_and_notify(
                    relationship="friend", peerid=peer, approved="true"
                )
                is False
            )
        gate.assert_called_once_with(peer)

    @pytest.mark.parametrize("value", [1, "yes"])
    def test_anything_else_raises(self, value: Any) -> None:
        w = Receiver()
        with pytest.raises(ValueError):
            w.a.modify_trust_and_notify(
                relationship="friend", peerid=w.b, approved=value
            )
        assert w.row(w.b)["approved"] is True
