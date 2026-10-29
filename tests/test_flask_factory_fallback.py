"""Flask: the factory form fallback without OAuth (3.16).

No Flask factory POST test existed before ``with_open_factory``. The refused
creation must render ``aw-root-failed.html`` with the handler's status, not an
empty page.
"""

from flask import Flask

from actingweb.interface import ActingWebApp
from tests._adoption_helpers import uuid_email


def _client(*, open_factory: bool):
    aw_app = (
        ActingWebApp(
            aw_type="urn:actingweb:test:flask-factory",
            database="dynamodb",
            fqdn="test.example.com",
            proto="https://",
        )
        .with_web_ui(enable=True)
        .with_open_factory(enable=open_factory)
    )
    app = Flask(__name__)
    aw_app.integrate_flask(app)
    return app.test_client()


class TestFlaskFactoryFallback:
    def test_closed_factory_form_post_renders_error_page_with_403(self) -> None:
        response = _client(open_factory=False).post(
            "/", data={"creator": "someone@example.com"}
        )
        assert response.status_code == 403
        assert b"with_open_factory" in response.data

    def test_closed_factory_json_post_is_403_json(self) -> None:
        response = _client(open_factory=False).post(
            "/", json={"creator": "someone@example.com"}
        )
        assert response.status_code == 403
        assert response.get_json()["error"] is True

    def test_open_factory_form_post_still_creates(self) -> None:
        response = _client(open_factory=True).post("/", data={"creator": uuid_email()})
        assert response.status_code in (200, 201)

    def test_closed_factory_form_post_asking_for_json_gets_the_json_body(
        self,
    ) -> None:
        response = _client(open_factory=False).post(
            "/",
            data={"creator": "someone@example.com"},
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 403
        body = response.get_json()
        assert body and body["status_code"] == 403
        assert "with_open_factory" in body["message"]


class TestFlaskFactoryJsonConfig:
    """``GET /`` asking for JSON returns the handler's configuration document;
    the Flask route used to render the page for every GET."""

    def test_format_json(self) -> None:
        response = _client(open_factory=True).get("/?format=json")
        assert response.status_code == 200
        assert response.get_json()["prompt_values"] == ["select_account"]

    def test_accept_json(self) -> None:
        response = _client(open_factory=True).get(
            "/", headers={"Accept": "application/json"}
        )
        assert response.get_json()["spa_mode_supported"] is True

    def test_browser_still_gets_the_page(self) -> None:
        response = _client(open_factory=True).get("/")
        assert response.status_code == 200
        assert "text/html" in response.content_type

    def test_json_get_never_creates_an_actor(self) -> None:
        # RootFactoryHandler.get() honours _method=POST; a GET a prefetcher
        # or an <img> can send must not create a factory actor.
        from actingweb.actor import Actor
        from tests._adoption_helpers import make_config

        creator = uuid_email()
        response = _client(open_factory=True).get(
            f"/?format=json&_method=POST&creator={creator}"
        )

        assert response.get_json()["spa_mode_supported"] is True
        assert not Actor(config=make_config()).get_from_creator(creator)
