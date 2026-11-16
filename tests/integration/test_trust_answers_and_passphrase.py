"""Trust answers, the passphrase and the trustee route (specification 1.5,
``thoughts/plans/2026-11-06-spec-1-5.md`` Phase 2), over HTTP on the test
app, on both backends by the suite's parametrisation.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests

FLAGS = ("approved", "peer_approved", "verified")


def _owner(actor: dict) -> tuple[str, str]:
    return (actor["creator"], actor["passphrase"])


def test_the_creation_response_carries_booleans_as_a_get_does(
    actor_factory: Any,
) -> None:
    a = actor_factory.create("t13-a@example.com")
    b = actor_factory.create("t13-b@example.com")
    r = requests.post(
        f"{a['url']}/trust",
        json={"url": b["url"], "relationship": "friend"},
        auth=_owner(a),
    )
    assert r.status_code == 201, r.text
    created = r.json()
    got = requests.get(r.headers["Location"], auth=_owner(a)).json()
    for flag in FLAGS:
        assert isinstance(created[flag], bool), (flag, created[flag])
        assert type(created[flag]) is type(got[flag])
        assert created[flag] == got[flag]


@pytest.fixture
def pending(actor_factory: Any, trust_helper: Any) -> dict[str, Any]:
    """A trust B asked A for, not yet approved at A."""
    a = actor_factory.create("t14-a@example.com")
    b = actor_factory.create("t14-b@example.com")
    trust_helper.establish(b, a, "friend", approve=False)
    return {"a": a, "b": b, "url": f"{a['url']}/trust/friend/{b['id']}"}


def _row(pending: dict[str, Any]) -> dict[str, Any]:
    return requests.get(pending["url"], auth=_owner(pending["a"])).json()


@pytest.mark.parametrize("value", [False, "false", None, 1, "yes"])
def test_approved_other_than_true_is_400_with_nothing_changed(
    pending: dict[str, Any], value: Any
) -> None:
    before = _row(pending)
    r = requests.put(
        pending["url"], json={"approved": value}, auth=_owner(pending["a"])
    )
    assert r.status_code == 400, (value, r.status_code, r.text)
    assert _row(pending) == before


@pytest.mark.parametrize("value", ["false", "", "yes"])
def test_the_form_path_refuses_approved_other_than_true(
    pending: dict[str, Any], value: str
) -> None:
    before = _row(pending)
    r = requests.get(
        pending["url"],
        params={"_method": "PUT", "approved": value},
        auth=_owner(pending["a"]),
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert r.status_code == 400, (value, r.status_code, r.text)
    assert _row(pending) == before


@pytest.mark.parametrize("value", [True, "true"])
def test_approved_true_approves(pending: dict[str, Any], value: Any) -> None:
    r = requests.put(
        pending["url"], json={"approved": value}, auth=_owner(pending["a"])
    )
    assert r.status_code == 204, r.text
    assert _row(pending)["approved"] is True


# ---------------------------------------------------------------------------
# The passphrase and the trustee route
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_world(actor_factory: Any, trust_helper: Any) -> dict[str, Any]:
    a = actor_factory.create("pp-owner@example.com")
    d = actor_factory.create("pp-admin@example.com")
    f = actor_factory.create("pp-friend@example.com")
    d_secret = trust_helper.establish(d, a, "admin")["secret"]
    f_secret = trust_helper.establish(f, a, "friend")["secret"]
    return {"a": a, "d_secret": d_secret, "f_secret": f_secret}


def _bearer(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}", "Accept": "application/json"}


def test_the_creator_reads_the_passphrase_and_a_peer_does_not(
    admin_world: dict[str, Any],
) -> None:
    a = admin_world["a"]
    r = requests.get(a["url"], auth=_owner(a), headers={"Accept": "application/json"})
    assert r.status_code == 200
    assert r.json()["passphrase"] == a["passphrase"]
    for secret in (admin_world["d_secret"], admin_world["f_secret"]):
        r = requests.get(a["url"], headers=_bearer(secret))
        if r.status_code == 200:
            assert "passphrase" not in r.json()
        else:
            assert r.status_code in (302, 403)


def test_the_trustee_reads_the_passphrase(actor_factory: Any) -> None:
    """Trustee access: the trustee root set, the creator ``trustee``, the
    passphrase as bearer."""
    t = actor_factory.create("trustee")
    r = requests.put(
        f"{t['url']}/trust/trustee",
        json={"trustee_root": "https://trustee.example.com/t"},
        auth=_owner(t),
    )
    assert r.status_code == 204, r.text
    r = requests.get(t["url"], headers=_bearer(t["passphrase"]))
    assert r.status_code == 200, r.text
    assert r.json()["passphrase"] == t["passphrase"]


@pytest.mark.parametrize(
    "body",
    [
        {"trustee_root": "https://evil.example.com/t"},
        {"creator": "evil@example.com"},
        {"trustee_root": "https://evil.example.com/t", "creator": "evil@example.com"},
    ],
)
def test_an_admin_peer_cannot_change_the_trustee_root_or_the_creator(
    admin_world: dict[str, Any], body: dict[str, Any]
) -> None:
    a = admin_world["a"]
    before = requests.get(f"{a['url']}/meta/trustee_root", auth=_owner(a)).text
    r = requests.put(
        f"{a['url']}/trust/trustee", json=body, headers=_bearer(admin_world["d_secret"])
    )
    assert r.status_code == 403, r.text
    r = requests.delete(
        f"{a['url']}/trust/trustee", headers=_bearer(admin_world["d_secret"])
    )
    assert r.status_code == 403, r.text
    assert requests.get(f"{a['url']}/meta/trustee_root", auth=_owner(a)).text == before
    root = requests.get(
        a["url"], auth=_owner(a), headers={"Accept": "application/json"}
    )
    assert root.json()["creator"] == a["creator"]


def test_an_admin_peer_keeps_the_rest_of_trust(admin_world: dict[str, Any]) -> None:
    a = admin_world["a"]
    r = requests.get(f"{a['url']}/trust", headers=_bearer(admin_world["d_secret"]))
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# A relationship named as a role (review of Phase 2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["creator", "trustee", "owner", "any", "Creator"])
def test_a_trust_named_as_a_role_is_refused(actor_factory: Any, name: str) -> None:
    a = actor_factory.create("role-a@example.com")
    b = actor_factory.create("role-b@example.com")
    r = requests.post(
        f"{b['url']}/trust",
        json={"url": a["url"], "relationship": name},
        auth=_owner(b),
    )
    assert r.status_code == 400, r.text
    r = requests.post(
        f"{a['url']}/trust/{name}",
        json={"baseuri": b["url"], "id": b["id"], "secret": "x" * 40},
    )
    assert r.status_code == 400, r.text
    assert requests.get(f"{a['url']}/trust", auth=_owner(a)).json() in ([], {})


def test_a_peer_never_matches_the_creators_rows() -> None:
    from actingweb.access_table import access_table_admits, matching_access_row
    from actingweb.config import Config

    config = Config()
    assert matching_access_row(config, relationship="creator", path="www") is not None
    assert (
        matching_access_row(
            config, relationship="creator", path="www", caller_peerid="p1"
        )
        is None
    )
    assert not access_table_admits(
        config, relationship="creator", approved=True, path="www"
    )


def test_the_trustee_changes_and_clears_the_trustee_root(actor_factory: Any) -> None:
    """Verification 2026-11-16 (M6): every test called the route with the
    creator's Basic auth; the trustee's own branch was never run."""
    t = actor_factory.create("trustee")
    r = requests.put(
        f"{t['url']}/trust/trustee",
        json={"trustee_root": "https://trustee.example.com/t"},
        auth=_owner(t),
    )
    assert r.status_code == 204, r.text
    r = requests.put(
        f"{t['url']}/trust/trustee",
        json={"trustee_root": "https://trustee.example.com/t2"},
        headers=_bearer(t["passphrase"]),
    )
    assert r.status_code == 204, r.text
    root = requests.get(f"{t['url']}/meta/trustee_root", auth=_owner(t)).text
    assert root == "https://trustee.example.com/t2"
    r = requests.delete(f"{t['url']}/trust/trustee", headers=_bearer(t["passphrase"]))
    assert r.status_code == 204, r.text


def test_the_receivers_answer_carries_booleans(actor_factory: Any) -> None:
    """Verification 2026-11-16 (M6): only the initiator's answer, which was
    already boolean, had a test; the receiver's 201 or 202 is the one
    Phase 2 changed (T13)."""
    a = actor_factory.create("pp-requester@example.com")
    b = actor_factory.create("pp-receiver@example.com")
    r = requests.post(
        f"{b['url']}/trust/friend",
        json={
            "baseuri": a["url"],
            "id": a["id"],
            "secret": "s" * 40,
            "type": "urn:actingweb:test:integration",
            "desc": "receiver flags",
        },
    )
    assert r.status_code in (201, 202), r.text
    body = r.json()
    for flag in FLAGS:
        if flag in body:
            assert isinstance(body[flag], bool), (flag, body[flag])
    assert "approved" in body
