"""The 3.14.4 exclusion-bypass chain, end to end.

Before 3.14.4 a ``friend`` peer could ``POST /{actor}/properties`` with a JSON
key of ``private/\\nx`` and land a property inside the ``private/`` namespace
its trust type excludes, because ``excluded_patterns: ["private/*"]``
compiled to a regex that could not cross the newline. Verified live against
the harness at the pre-fix tree: ``private/\\nx`` and ``_internal/\\nx`` both
answered 201 and appeared in the owner's listing.

The URL-path form (``PUT .../properties/private/%0Asecret``) is *not* a
vector: both routers' path converters stop at a newline and answer 404
before any handler runs. Other control characters (tab, NUL, CR) do reach the
handler through the path, and ``*`` already matched them, so they were never
a bypass -- they are covered here as the write-time rejection's surface.

Two things now stand in the way, both checked against the live FastAPI
harness: the evaluator denies any identifier carrying a control character,
and the REST layer refuses to create one. A name that already exists stays
readable and deletable by its owner, so a deployment that has one is not
locked out of cleaning up. The Flask integration's owner-side check runs
through Flask's test client at the bottom.
"""

import base64
import os

import pytest
import requests
from flask import Flask

from actingweb.db import get_property
from actingweb.interface import ActingWebApp

DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")

# A tab, not a newline: a newline in a URL path never reaches the handler
# (router 404), so a pre-existing name has to carry something routable to
# be reachable for cleanup at all.
ENCODED_TAB_NAME = "pre%09seeded"
TAB_NAME = "pre\tseeded"


def _owner_auth(actor: dict) -> tuple[str, str]:
    return (actor["creator"], actor["passphrase"])


def _peer_headers(trust: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {trust['secret']}"}


@pytest.fixture
def db_config(test_app, worker_info):  # noqa: ARG001 -- test_app sets the env
    """A Config bound to the same tables/schema the harness serves from.

    The harness runs in this process, so the environment ``test_app``
    exported is what the library reads here too.
    """
    return ActingWebApp(
        aw_type="urn:actingweb:test:property_path_control_chars",
        database=DATABASE_BACKEND,
        fqdn="test.example.com",
        proto="http://",
    ).get_config()


class TestPeerBypassIsClosed:
    def test_friend_cannot_post_into_excluded_namespace_via_newline(
        self, actor_factory, trust_helper
    ):
        owner = actor_factory.create("owner@example.com")
        peer = actor_factory.create("peer@example.com")
        trust = trust_helper.establish(owner, peer, "friend")

        for key in ("private/\nx", "_internal/\nx", "security/\nx"):
            response = requests.post(
                f"{owner['url']}/properties",
                json={key: "injected"},
                headers=_peer_headers(trust),
            )
            assert response.status_code == 400, repr(key)

        # The ordinary form of the same write is denied as before.
        response = requests.post(
            f"{owner['url']}/properties",
            json={"private/x": "injected"},
            headers=_peer_headers(trust),
        )
        assert response.status_code == 403

        # Nothing landed.
        response = requests.get(f"{owner['url']}/properties", auth=_owner_auth(owner))
        assert response.status_code in (200, 404)
        assert not (response.json() if response.status_code == 200 else {})

    def test_newline_in_url_path_never_reaches_a_handler(
        self, actor_factory, trust_helper
    ):
        """Pinned so a router change that starts matching newlines is noticed."""
        owner = actor_factory.create("owner@example.com")
        peer = actor_factory.create("peer@example.com")
        trust = trust_helper.establish(owner, peer, "friend")

        response = requests.put(
            f"{owner['url']}/properties/private/%0Asecret",
            data="injected",
            headers={"Content-Type": "text/plain", **_peer_headers(trust)},
        )
        assert response.status_code == 404

    def test_friend_tab_in_path_is_denied_by_evaluator(
        self, actor_factory, trust_helper
    ):
        owner = actor_factory.create("owner@example.com")
        peer = actor_factory.create("peer@example.com")
        trust = trust_helper.establish(owner, peer, "friend")

        # Not an excluded namespace, so only the control-character guard
        # can be what denies this.
        response = requests.put(
            f"{owner['url']}/properties/shared/%09note",
            data="hello",
            headers={"Content-Type": "text/plain", **_peer_headers(trust)},
        )
        assert response.status_code == 403

    def test_friend_still_writes_ordinary_paths(self, actor_factory, trust_helper):
        owner = actor_factory.create("owner@example.com")
        peer = actor_factory.create("peer@example.com")
        trust = trust_helper.establish(owner, peer, "friend")

        response = requests.put(
            f"{owner['url']}/properties/shared/note",
            data="hello",
            headers={"Content-Type": "text/plain", **_peer_headers(trust)},
        )
        assert response.status_code == 204


class TestOwnerWriteIsRefused:
    def test_put_with_control_character_in_path_is_400(self, actor_factory):
        owner = actor_factory.create("owner@example.com")
        for path in ("private/%09secret", "no%00nul", "cr%0Dhere", "%7Fdel"):
            response = requests.put(
                f"{owner['url']}/properties/{path}",
                data="x",
                headers={"Content-Type": "text/plain"},
                auth=_owner_auth(owner),
            )
            assert response.status_code == 400, path

    def test_post_with_control_character_in_key_is_400_and_atomic(self, actor_factory):
        owner = actor_factory.create("owner@example.com")
        response = requests.post(
            f"{owner['url']}/properties",
            json={"fine": "1", "bad\nname": "2"},
            auth=_owner_auth(owner),
        )
        assert response.status_code == 400
        # The good key in the same batch was not applied either.
        response = requests.get(
            f"{owner['url']}/properties/fine", auth=_owner_auth(owner)
        )
        assert response.status_code == 404

    def test_list_creation_with_control_character_is_400(self, actor_factory):
        owner = actor_factory.create("owner@example.com")
        response = requests.post(
            f"{owner['url']}/properties",
            json={"bad\nlist": {"_type": "list"}},
            auth=_owner_auth(owner),
        )
        assert response.status_code == 400


class TestPreExistingNameStaysManageable:
    def test_owner_can_read_and_delete_but_peer_cannot_read(
        self, actor_factory, trust_helper, db_config
    ):
        owner = actor_factory.create("owner@example.com")
        peer = actor_factory.create("peer@example.com")
        trust = trust_helper.establish(owner, peer, "friend")

        # Seed below the REST layer, the way a pre-3.14.4 deployment would
        # have come to hold such a name.
        get_property(db_config).set(actor_id=owner["id"], name=TAB_NAME, value="legacy")

        response = requests.get(
            f"{owner['url']}/properties/{ENCODED_TAB_NAME}",
            auth=_owner_auth(owner),
        )
        assert response.status_code == 200
        assert response.text == "legacy"

        response = requests.get(
            f"{owner['url']}/properties/{ENCODED_TAB_NAME}",
            headers=_peer_headers(trust),
        )
        assert response.status_code == 403

        response = requests.delete(
            f"{owner['url']}/properties/{ENCODED_TAB_NAME}",
            auth=_owner_auth(owner),
        )
        assert response.status_code == 204

        response = requests.get(
            f"{owner['url']}/properties/{ENCODED_TAB_NAME}",
            auth=_owner_auth(owner),
        )
        assert response.status_code == 404


@pytest.fixture
def flask_client(worker_info):  # noqa: ARG001 -- ensures docker_services/setup_database ran
    if DATABASE_BACKEND == "postgresql":
        os.environ["PG_DB_HOST"] = os.environ.get("PG_DB_HOST", "localhost")
        os.environ["PG_DB_PORT"] = os.environ.get("PG_DB_PORT", "5433")
        os.environ["PG_DB_NAME"] = os.environ.get("PG_DB_NAME", "actingweb_test")
        os.environ["PG_DB_USER"] = os.environ.get("PG_DB_USER", "actingweb")
        os.environ["PG_DB_PASSWORD"] = os.environ.get("PG_DB_PASSWORD", "testpassword")
        os.environ["PG_DB_PREFIX"] = worker_info["db_prefix"]
        os.environ["PG_DB_SCHEMA"] = "public"

    aw_app = ActingWebApp(
        aw_type="urn:actingweb:test:flask_control_chars",
        database=DATABASE_BACKEND,
        fqdn="flask-control-chars.example.com",
        proto="http://",
    ).with_web_ui(enable=False)
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    aw_app.integrate_flask(flask_app)
    return flask_app.test_client()


class TestFlaskOwnerWriteIsRefused:
    def test_control_characters_are_400_and_newline_path_is_404(self, flask_client):
        response = flask_client.post("/", json={"creator": "flask-cc@example.com"})
        assert response.status_code == 201
        actor = response.get_json()
        token = base64.b64encode(
            f"{actor['creator']}:{actor['passphrase']}".encode()
        ).decode()
        headers = {"Authorization": f"Basic {token}"}
        try:
            response = flask_client.put(
                f"/{actor['id']}/properties/private/%09secret",
                data="x",
                headers={"Content-Type": "text/plain", **headers},
            )
            assert response.status_code == 400
            response = flask_client.post(
                f"/{actor['id']}/properties",
                json={"private/\nsecret": "x"},
                headers=headers,
            )
            assert response.status_code == 400
            response = flask_client.put(
                f"/{actor['id']}/properties/private/%0Asecret",
                data="x",
                headers={"Content-Type": "text/plain", **headers},
            )
            assert response.status_code == 404
        finally:
            flask_client.delete(f"/{actor['id']}", headers=headers)
