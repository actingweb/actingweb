"""``/resources`` follows the peer's ``resources`` grant (3.16, plan Phase 2).

GET is ``read``, PUT and POST ``write``, DELETE ``delete``, on the same
decision as every other route; the test app registers no resource hook, so
an allowed request reaches the (absent) hook and answers 404, a refused one
403 before it.
"""

from __future__ import annotations

import pytest
import requests

pytestmark = pytest.mark.xdist_group(name="resources_grant")

ALLOWED, REFUSED = 404, 403


@pytest.fixture
def world(actor_factory, trust_helper):
    a = actor_factory.create("res-owner@example.com")
    peers = {}
    for name, relationship in (
        ("friend", "friend"),
        ("associate", "associate"),
        ("partner", "partner"),
        ("admin", "admin"),
    ):
        p = actor_factory.create(f"res-{name}@example.com")
        peers[name] = trust_helper.establish(p, a, relationship)["secret"]
    return a, peers


def _call(a, secret, method, name):
    return requests.request(
        method,
        f"{a['url']}/resources/{name}",
        json={} if method in ("PUT", "POST") else None,
        headers={"Authorization": f"Bearer {secret}"},
    ).status_code


@pytest.mark.parametrize(
    ("peer", "method", "name", "status"),
    [
        ("friend", "GET", "x", ALLOWED),
        ("friend", "PUT", "x", ALLOWED),
        ("friend", "DELETE", "x", REFUSED),  # friend's rule has no delete
        ("friend", "GET", "private/x", REFUSED),
        ("friend", "GET", "private", REFUSED),  # private/* names private
        ("partner", "GET", "security/x", REFUSED),
        ("partner", "GET", "x", ALLOWED),
        ("associate", "GET", "public/x", ALLOWED),
        ("associate", "GET", "x", REFUSED),
        ("associate", "PUT", "public/x", REFUSED),
        ("admin", "DELETE", "private/x", ALLOWED),
    ],
)
def test_the_grant_decides(world, peer, method, name, status) -> None:
    a, peers = world
    assert _call(a, peers[peer], method, name) == status


def test_a_refusal_says_little(world) -> None:
    a, peers = world
    r = requests.get(
        f"{a['url']}/resources/private/x",
        headers={"Authorization": f"Bearer {peers['friend']}"},
    )
    assert r.status_code == 403
    assert r.json() == {"error": "forbidden"}


def test_the_creator_is_not_a_peer(world) -> None:
    a, _ = world
    r = requests.get(
        f"{a['url']}/resources/private/x", auth=(a["creator"], a["passphrase"])
    )
    assert r.status_code == ALLOWED
