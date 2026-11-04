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
    other_prefix = FakeTrust("actingweb:user@example.com:mcp_abc", None)
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


@pytest.mark.parametrize(
    "source,via",
    [
        ("oauth2", None),
        ("oauth2", "oauth2"),
        ("oauth2_interactive", "oauth2_interactive"),
        ("oauth2_client", "oauth2_client"),
    ],
)
def test_real_email_legacy_rows_of_every_oauth2_source_are_deleted(
    source: str, via: str | None
) -> None:
    """Trust creation writes ``{established_via or "oauth2"}:<email>:<client>``;
    the old ``endswith`` deleted every such row (verification 2026-11-04,
    Issue 2)."""
    legacy = FakeTrust(f"{source}:alice_at_x_dot_com:mcp_ab12", established_via=via)
    assert find_client_trust([legacy], "mcp_ab12") is None
    assert _delete("mcp_ab12", [legacy]) == [legacy.peerid]


def test_the_segment_arm_skips_a_peer_protocol_row_of_that_shape() -> None:
    """Arm 3 is gated on OAuth2 origin like arm 2 (Issue 9): a peer-protocol
    row shaped like a legacy client row is never the one deleted."""
    peer = FakeTrust("oauth2_client:x:mcp_ab12", established_via="actingweb")
    real = FakeTrust("oauth2_interactive:alice_at_x_dot_com:mcp_ab12")
    assert _delete("mcp_ab12", [peer, real]) == [real.peerid]


def test_trust_creation_and_lookup_share_the_normaliser() -> None:
    from actingweb.oauth2_server.trust_lookup import normalize_client_id

    assert normalize_client_id("a@b.c:d") == "a_at_b_dot_c_colon_d"
