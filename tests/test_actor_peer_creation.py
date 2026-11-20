"""AC-46: a peer whose factory is closed answers 403 to a trustee creation;
the calling side says so at WARNING, naming the factory and the status, so
the operator of a 4.0 deployment can open it (with_open_factory(True))."""

from __future__ import annotations

import logging
from typing import Any
from unittest import mock

import pytest
import requests

from tests._adoption_helpers import create_core_actor, make_config, uuid_email

FACTORY = "https://peer.example.test/"


def _response(status: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = b'{"error": true, "message": "closed"}'  # noqa: SLF001
    return response


def test_a_closed_factory_is_warned(caplog: pytest.LogCaptureFixture) -> None:
    config = make_config()
    config.actors = {"peerapp": {"type": "urn:test:peer", "factory": FACTORY}}
    actor = create_core_actor(config, uuid_email())
    with (
        mock.patch("actingweb.actor.requests.post", return_value=_response(403)),
        caplog.at_level(logging.WARNING, logger="actingweb.actor"),
    ):
        assert actor.get_peer_trustee(shorttype="peerapp") is None
    assert actor.last_response_code == 403
    lines: list[Any] = [r for r in caplog.records if FACTORY in r.getMessage()]
    assert len(lines) == 1
    assert lines[0].levelno == logging.WARNING
    assert "403" in lines[0].getMessage()


def test_a_refused_trust_approval_is_recorded() -> None:
    """The approving PUT after a trustee creation: a 403 is recorded, not
    hidden behind the earlier 201 (a 4xx ``Response`` is falsy)."""
    config = make_config()
    config.actors = {
        "peerapp": {
            "type": "urn:test:peer",
            "factory": FACTORY,
            "relationship": "friend",
        }
    }
    actor = create_core_actor(config, uuid_email())
    created = requests.Response()
    created.status_code = 201
    created._content = b'{"id": "peer-ok", "passphrase": "pp"}'  # noqa: SLF001
    created.headers["Location"] = "https://peer.example.test/peer-ok"
    peer_id = f"peer-{uuid_email().split('@')[0]}"
    with (
        mock.patch("actingweb.actor.requests.post", return_value=created),
        mock.patch("actingweb.actor.requests.put", return_value=_response(403)),
        mock.patch.object(
            type(actor),
            "get_peer_info",
            return_value={
                "last_response_code": 200,
                "data": {"id": peer_id, "type": "urn:test:peer"},
            },
        ),
        mock.patch.object(
            type(actor), "create_reciprocal_trust", return_value={"peerid": peer_id}
        ),
    ):
        peer = actor.get_peer_trustee(shorttype="peerapp")
    assert peer is not None
    assert actor.last_response_code == 403
