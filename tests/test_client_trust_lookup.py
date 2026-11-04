"""Client deletion removes exactly the client's trust row (3.16).

``_delete_client_trust_relationship`` matched ``pattern in peer_id or
peer_id.endswith(client_id)`` and deleted the first hit, so deleting client
``A`` could take an unrelated row whose peer id merely contained ``A``. It
now uses ``find_client_trust``, the authentication resolver's exact match,
plus a deletion-only arm for the real-email legacy rows
(``oauth2_client:<email>:<client_id>``).
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest

from actingweb.config import Config
from actingweb.oauth2_server.client_registry import MCPClientRegistry
from actingweb.oauth2_server.trust_lookup import find_client_trust
from tests.test_mcp_fail_closed_authorization import FakeTrust, FakeTrustManager


class _DeletingTrustManager(FakeTrustManager):
    def __init__(self, trusts: list[FakeTrust]) -> None:
        super().__init__(trusts)
        self.deleted: list[str] = []

    def delete_relationship(self, peer_id: str) -> bool:
        self.deleted.append(peer_id)
        self._trusts = [t for t in self._trusts if t.peerid != peer_id]
        return True


def _delete(client_id: str, trusts: list[FakeTrust]) -> list[str]:
    """Run the registry's deletion with the actor loading patched out."""
    manager = _DeletingTrustManager(trusts)
    registry = MCPClientRegistry.__new__(MCPClientRegistry)
    registry.config = Config(mcp=True, unique_creator=False)
    core = mock.Mock()
    core.actor = {"id": "actor-1"}
    interface = mock.Mock()
    interface.trust = manager
    with (
        mock.patch("actingweb.actor.Actor", return_value=core),
        mock.patch(
            "actingweb.interface.actor_interface.ActorInterface",
            return_value=interface,
        ),
    ):
        registry._delete_client_trust_relationship("actor-1", client_id)
    return manager.deleted


def test_a_decoy_alone_is_not_deleted() -> None:
    decoy = FakeTrust("oauth2_client:evilclient-A:evilclient-A", "oauth2_client")
    assert _delete("client-A", [decoy]) == []


def test_decoy_and_exact_row_deletes_only_the_exact_row() -> None:
    decoy = FakeTrust("oauth2_client:evilclient-A:evilclient-A", "oauth2_client")
    exact = FakeTrust(
        "oauth2_client:someone:client-A",
        established_via="oauth2_client",
        oauth_client_id="client-A",
    )
    assert _delete("client-A", [decoy, exact]) == [exact.peerid]


def test_a_real_email_legacy_row_is_deleted_but_never_authorises() -> None:
    legacy = FakeTrust("oauth2_client:user@example.com:mcp_abc", "oauth2_client")
    assert find_client_trust([legacy], "mcp_abc") is None  # resolver default
    assert find_client_trust([legacy], "mcp_abc", legacy_segment_match=True) is legacy
    assert _delete("mcp_abc", [legacy]) == [legacy.peerid]


def test_the_segment_arm_compares_the_last_segment_exactly() -> None:
    near = FakeTrust("oauth2_client:user@example.com:mcp_abcd", "oauth2_client")
    other_prefix = FakeTrust("oauth2:user@example.com:mcp_abc", "oauth2")
    tagged = FakeTrust(
        "oauth2_client:user@example.com:mcp_abc", oauth_client_id="mcp_other"
    )
    assert (
        find_client_trust(
            [near, other_prefix, tagged], "mcp_abc", legacy_segment_match=True
        )
        is None
    )


@pytest.mark.parametrize(
    "rows,client,expected",
    [
        (
            [
                ("oauth2_client:a:a", "oauth2_client", "client-A"),
                ("oauth2_client:b:b", "oauth2_client", "client-B"),
            ],
            "client-B",
            1,
        ),
        (
            [("oauth2_client:client-legacy:client-legacy", "oauth2_client", None)],
            "client-legacy",
            0,
        ),
        ([("oauth2:client-legacy:client-legacy", None, None)], "client-legacy", 0),
        (
            [
                (
                    "oauth2_client:client-Xclient-A:client-Xclient-A",
                    "oauth2_client",
                    None,
                )
            ],
            "client-A",
            None,
        ),
        ([("oauth2_client:client-A:client-A", "actingweb", None)], "client-A", None),
        (
            [("oauth2_client:a_at_b_dot_c:a_at_b_dot_c", "oauth2_client", None)],
            "a@b.c",
            0,
        ),
    ],
)
def test_the_default_matches_the_resolver(
    rows: list[tuple[str, str | None, str | None]], client: str, expected: int | None
) -> None:
    trusts = [FakeTrust(p, established_via=v, oauth_client_id=c) for p, v, c in rows]
    found: Any = find_client_trust(trusts, client)
    assert found is (None if expected is None else trusts[expected])
