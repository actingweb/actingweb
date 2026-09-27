"""Peer request and response bodies are summarised in ``actor.py`` logs.

The async reciprocal-trust request carries the new trust secret and the
verification token, and logged them at INFO; subscription bodies and peer-info
responses were logged whole at DEBUG.
"""

import logging
from typing import Any
from unittest import mock

import httpx
import pytest

from actingweb.actor import Actor

SECRET = "s3cr3t-trust-secret"
VERIFY = "v3rify-token"


def _actor() -> Actor:
    actor = Actor.__new__(Actor)
    actor.id = "a1"
    actor.config = mock.Mock(
        root="https://me.example.com/",
        aw_type="urn:actingweb:test",
        default_relationship="friend",
    )
    return actor


async def test_async_trust_request_logs_no_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    actor = _actor()
    peer_info = {
        "last_response_code": 200,
        "data": {"id": "peer1", "type": "urn:actingweb:test"},
    }
    dbtrust = mock.Mock()
    dbtrust.create.return_value = True
    dbtrust.get.return_value = {"verification_token": VERIFY}

    class _FailingClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "_FailingClient":
            raise httpx.ConnectError("no peer")

        async def __aexit__(self, *args: Any) -> None:
            return None

    with (
        mock.patch.object(
            actor, "get_peer_info_async", mock.AsyncMock(return_value=peer_info)
        ),
        mock.patch("actingweb.actor.trust.Trust", return_value=dbtrust),
        mock.patch("httpx.AsyncClient", _FailingClient),
        caplog.at_level(logging.DEBUG, logger="actingweb.actor"),
    ):
        ok = await actor.create_reciprocal_trust_async(
            url="https://peer.example.com/peer1",
            secret=SECRET,
            desc="d",
            relationship="friend",
        )

    assert ok is False
    assert "Requesting trust relationship async" in caplog.text
    assert "keys=[baseuri, desc, id, secret, type, verify]" in caplog.text
    assert SECRET not in caplog.text
    assert VERIFY not in caplog.text


def test_peer_info_body_is_summarised(caplog: pytest.LogCaptureFixture) -> None:
    actor = _actor()
    response = mock.Mock(status_code=200, content=b'{"id": "p", "token": "tok123"}')
    with (
        mock.patch("actingweb.actor.requests.get", return_value=response),
        caplog.at_level(logging.DEBUG, logger="actingweb.actor"),
    ):
        res = actor.get_peer_info("https://peer.example.com/p")
    assert res["data"]["token"] == "tok123"
    assert "keys=[id, token]" in caplog.text
    assert "tok123" not in caplog.text
