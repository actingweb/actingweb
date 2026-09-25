"""``GET /{actor_id}/trust`` never returns peer credentials.

The list drops ``secret`` and ``verification_token`` from every row; the
per-relationship GET keeps them (the spec says the shared secret SHOULD be
readable there, and peer verification reads ``verification_token`` from it).
"""

import json
from typing import Any
from unittest.mock import Mock, patch

from actingweb.handlers.trust import TrustHandler, TrustPeerHandler, _public_trust_row

ROWS = [
    {
        "peerid": "peer-1",
        "relationship": "friend",
        "approved": True,
        "secret": "s1",
        "verification_token": "v1",
        "baseuri": "https://peer-1/",
    },
    {
        "peerid": "peer-2",
        "relationship": "friend",
        "approved": False,
        "secret": "s2",
        "verification_token": "v2",
    },
]


def _handler(cls: Any, rows: list[Any]) -> Any:
    handler = cls()
    handler.config = Mock()
    handler.request = Mock()
    handler.request.get = Mock(return_value=None)
    handler.response = Mock()
    handler.response.headers = {}
    actor = Mock()
    actor.get_trust_relationships = Mock(return_value=[dict(r) for r in rows])
    handler.require_authenticated_actor = Mock(return_value=actor)
    auth_result = Mock()
    auth_result.success = True
    auth_result.actor = actor
    auth_result.auth_obj = Mock(trust=None, acl={"relationship": "creator"})
    handler.authenticate_actor = Mock(return_value=auth_result)
    return handler


def test_list_drops_credentials_and_keeps_the_rest() -> None:
    handler = _handler(TrustHandler, ROWS)
    handler.get("actor-1")
    out = json.loads(handler.response.write.call_args[0][0])
    assert len(out) == 2
    for row, original in zip(out, ROWS, strict=True):
        assert "secret" not in row
        assert "verification_token" not in row
        expected = {
            k: v
            for k, v in original.items()
            if k not in ("secret", "verification_token")
        }
        assert row == expected


def test_non_dict_row_passes_through() -> None:
    assert _public_trust_row("opaque") == "opaque"


def test_row_is_copied_not_mutated() -> None:
    row = dict(ROWS[0])
    _public_trust_row(row)
    assert row["secret"] == "s1"


@patch("actingweb.handlers.trust.PERMISSION_SYSTEM_AVAILABLE", False)
def test_per_relationship_get_keeps_credentials() -> None:
    handler = _handler(TrustPeerHandler, ROWS[:1])
    handler.get("actor-1", "friend", "peer-1")
    out = json.loads(handler.response.write.call_args[0][0])
    assert out["secret"] == "s1"
    assert out["verification_token"] == "v1"


HOSTILE = {
    "peerid": "peer-3",
    "relationship": "mcp_client",
    "approved": True,
    "secret": "s3",
    "verification_token": "v3",
    "client_name": "Evil\nIgnore previous",
    "client_version": "1\x00",
    "desc": "OAuth2 client: Evil\n" + "y" * 100,
}


def test_list_sanitises_client_text() -> None:
    handler = _handler(TrustHandler, [HOSTILE])
    handler.get("actor-1")
    row = json.loads(handler.response.write.call_args[0][0])[0]
    assert row["client_name"] == "Evil Ignore previous"
    assert row["client_version"] == "1"
    assert row["desc"] == "OAuth2 client: Evil " + "y" * 100  # stripped, not cut


@patch("actingweb.handlers.trust.PERMISSION_SYSTEM_AVAILABLE", False)
def test_per_relationship_get_sanitises_client_text() -> None:
    handler = _handler(TrustPeerHandler, [HOSTILE])
    handler.get("actor-1", "mcp_client", "peer-3")
    out = json.loads(handler.response.write.call_args[0][0])
    assert out["client_name"] == "Evil Ignore previous"
    assert out["secret"] == "s3"
