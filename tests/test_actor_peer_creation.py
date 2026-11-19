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
