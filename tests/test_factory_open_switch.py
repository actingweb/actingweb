"""``with_open_factory(False)`` closes the actor factory (``POST /``) (4.0).

The gate sits at the top of ``RootFactoryHandler.post()``, so it also closes
the unauthenticated existing-creator redirect (an actor-id oracle).
"""

import json
from typing import Any

from actingweb.actor import Actor
from actingweb.aw_web_request import AWWebObj
from actingweb.handlers.factory import RootFactoryHandler
from actingweb.interface import ActingWebApp
from tests._adoption_helpers import create_core_actor, make_config, uuid_email


def _post(config, creator: str, *, as_json: bool, method: str = "POST") -> AWWebObj:
    if as_json:
        webobj = AWWebObj(
            url="https://test.example.com/",
            params={},
            body=json.dumps({"creator": creator}),
            headers={"Content-Type": "application/json"},
            cookies={},
        )
    else:
        webobj = AWWebObj(
            url="https://test.example.com/",
            params={"creator": creator, "_method": method},
            body=f"creator={creator}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            cookies={},
        )
    RootFactoryHandler(webobj, config, hooks=None).post()
    return webobj


def _closed():
    config = make_config()
    config.open_factory = False
    return config


class TestClosedFactory:
    def test_json_post_is_403_with_the_house_body_and_creates_nothing(self) -> None:
        config = _closed()
        creator = uuid_email()
        webobj = _post(config, creator, as_json=True)

        assert webobj.response.status_code == 403
        body = json.loads(webobj.response.body)
        assert body["error"] is True and body["status_code"] == 403
        assert "with_open_factory" in body["message"]
        assert not Actor(config=config).get_from_creator(creator)

    def test_form_post_is_403_with_error_template_value(self) -> None:
        config = _closed()
        creator = uuid_email()
        webobj = _post(config, creator, as_json=False)

        assert webobj.response.status_code == 403
        assert "with_open_factory" in webobj.response.template_values["error"]
        assert not Actor(config=config).get_from_creator(creator)

    def test_existing_creator_form_redirect_is_refused(self) -> None:
        """The redirect answers "does this address have an actor, and which
        id" to anyone; the closed factory no longer does."""
        config = _closed()
        creator = uuid_email()
        create_core_actor(config, creator, auth_method="app")
        webobj = _post(config, creator, as_json=False)

        assert webobj.response.status_code == 403
        assert not webobj.response.redirect

    def test_get_with_method_override_never_creates(self) -> None:
        # GET no longer honours _method=POST (a prefetcher or an <img> could
        # create actors with it), open factory or closed.
        from actingweb.actor import Actor

        config = _closed()
        config.open_factory = True  # open: the old override created here
        creator = uuid_email()
        webobj = AWWebObj(
            url="https://test.example.com/",
            params={"_method": "POST", "creator": creator},
            body=None,
            headers={},
            cookies={},
        )
        RootFactoryHandler(webobj, config, hooks=None).get()
        assert webobj.response.status_code != 201
        assert not Actor(config=config).get_from_creator(creator)

    def test_get_still_renders(self) -> None:
        config = _closed()
        webobj = AWWebObj(
            url="https://test.example.com/",
            params={},
            body=None,
            headers={},
            cookies={},
        )
        RootFactoryHandler(webobj, config, hooks=None).get()
        assert webobj.response.status_code != 403


class TestOpenFactory:
    def test_a_bare_config_is_open(self) -> None:
        """AC-19: no provider builder was called."""
        config = make_config()
        assert config.open_factory is True
        webobj = _post(config, uuid_email(), as_json=True)
        assert webobj.response.status_code == 201

    def test_default_creates(self) -> None:
        config = make_config()
        assert config.open_factory is True
        webobj = _post(config, uuid_email(), as_json=True)
        assert webobj.response.status_code == 201

    def test_duplicate_creator_403_carries_the_body(self) -> None:
        config = make_config()
        config.unique_creator = True
        creator = uuid_email()
        create_core_actor(config, creator, auth_method="app")
        webobj = _post(config, creator, as_json=True)

        assert webobj.response.status_code == 403
        body = json.loads(webobj.response.body)
        assert body["message"] == "Creator already exists"


class TestBuilder:
    def _app(self) -> ActingWebApp:
        return ActingWebApp(
            aw_type="urn:actingweb:test:open-factory",
            database="dynamodb",
            fqdn="test.example.com",
        )

    def test_default_is_open(self) -> None:
        assert self._app().get_config().open_factory is True

    def test_with_open_factory_false_closes_an_existing_config(self) -> None:
        app = self._app()
        config = app.get_config()
        app.with_open_factory(False)
        assert config.open_factory is False

    def test_value_assigned_on_config_survives_other_builder_calls(self) -> None:
        app = self._app()
        config = app.get_config()
        config.open_factory = False
        app.with_mcp(enable=True)
        assert config.open_factory is False

    def test_builder_value_wins_after_with_open_factory(self) -> None:
        app = self._app()
        config = app.get_config()
        config.open_factory = True
        app.with_open_factory(False)
        app.with_mcp(enable=True)
        assert config.open_factory is False

    def test_config_kwarg_is_honoured(self) -> None:
        from actingweb.config import Config

        assert Config(database="dynamodb", open_factory=False).open_factory is False


class TestOpenFactoryNormalisesTheCreator:
    def test_a_padded_mixed_case_address_is_stripped_and_lowercased(self) -> None:
        # The factory strips the form value before normalise_creator, which
        # does not strip.
        config = make_config()
        address = uuid_email()
        webobj = _post(config, f"  {address.upper()} ", as_json=True)

        assert webobj.response.status_code == 201
        assert Actor(config=config).get_from_creator(address)


class TestClosedByDefaultWithAProvider:
    """AC-18, AC-19, AC-47: a provider builder closes the factory unless the
    application opens it; the default page keeps its email form, which signs in."""

    def _app(self) -> ActingWebApp:
        return ActingWebApp(
            aw_type="urn:actingweb:test:factory-default",
            database="dynamodb",
            fqdn="test.example.com",
        )

    def test_closed_by_default_with_a_provider(self) -> None:
        app = self._app().with_oauth(client_id="cid", client_secret="sec")
        config = app.get_config()
        assert config.open_factory is False
        webobj = _post(config, uuid_email(), as_json=True)
        assert webobj.response.status_code == 403
        assert "with_open_factory(True)" in json.loads(webobj.response.body)["message"]

    def test_with_oauth_after_get_config_still_closes(self) -> None:
        app = self._app()
        config = app.get_config()
        app.with_oauth(client_id="cid", client_secret="sec")
        assert config.open_factory is False

    def test_an_empty_client_id_still_closes(self) -> None:
        app = self._app().with_oauth(client_id="", client_secret="")
        assert app.get_config().open_factory is False

    def test_apple_only_closes(self) -> None:
        from tests.test_actingweb_app import TestAppleSignIn

        app = self._app().with_apple_sign_in(
            client_id="com.example.web",
            audiences=["com.example.web"],
            team_id="TEAM123456",
            key_id="KEY1234567",
            private_key_pem=TestAppleSignIn._ec_pem(),
        )
        assert app.get_config().open_factory is False

    def test_github_and_google_native_close(self) -> None:
        assert self._app().with_github("id", "sec").get_config().open_factory is False
        assert (
            self._app()
            .with_google_native("id.apps.googleusercontent.com")
            .get_config()
            .open_factory
            is False
        )

    def test_open_without_a_provider(self) -> None:
        assert self._app().get_config().open_factory is True

    def test_explicit_open_wins(self) -> None:
        for app in (
            self._app()
            .with_oauth(client_id="cid", client_secret="sec")
            .with_open_factory(True),
            self._app()
            .with_open_factory(True)
            .with_oauth(client_id="cid", client_secret="sec"),
        ):
            assert app.get_config().open_factory is True

    def test_the_closed_default_is_warned_once(self, caplog) -> None:
        import logging

        from fastapi import FastAPI

        app = self._app().with_oauth(client_id="cid", client_secret="sec")
        with caplog.at_level(logging.WARNING):
            app.integrate_fastapi(FastAPI())
        lines = [
            r for r in caplog.records if "with_open_factory(True)" in r.getMessage()
        ]
        assert len(lines) == 1
        open_app = self._app().with_oauth(client_id="cid", client_secret="sec")
        open_app.with_open_factory(True)
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            open_app.integrate_fastapi(FastAPI())
        assert not [
            r for r in caplog.records if "with_open_factory(True)" in r.getMessage()
        ]

    def _rendered(self, build: Any, path: str) -> dict[str, str]:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from flask import Flask

        fastapi_app = FastAPI()
        build().integrate_fastapi(fastapi_app)
        flask_app = Flask(__name__)
        build().integrate_flask(flask_app)
        html = {"Accept": "text/html"}
        return {
            "fastapi": TestClient(fastapi_app).get(path, headers=html).text,
            "flask": flask_app.test_client()
            .get(path, headers=html)
            .get_data(as_text=True),
        }

    def test_with_a_provider_the_default_page_signs_in(self) -> None:
        """AC-47 (restated in iteration 1): with a provider, the email form
        signs in (a form POST redirects to the provider), so the page offers
        it and the provider button whether or not the factory is open."""
        for open_ in (False, True):

            def build(open_: bool = open_) -> ActingWebApp:
                app = self._app().with_oauth(client_id="cid", client_secret="sec")
                if open_:
                    app.with_open_factory(True)
                return app

            for path in ("/", "/login"):
                for integration, text in self._rendered(build, path).items():
                    where = f"{integration} {path} open={open_}"
                    assert 'name="creator"' in text, where
                    assert "Sign in with" in text, where

    def test_without_a_provider_a_closed_factory_offers_no_form(self) -> None:
        for integration, text in self._rendered(
            lambda: self._app().with_open_factory(False), "/"
        ).items():
            assert 'name="creator"' not in text, integration
        for integration, text in self._rendered(self._app, "/").items():
            assert 'name="creator"' in text, integration


class TestSignInPageValues:
    """Iteration 17 (second verification, issues 6 and 7): the email form
    follows the authenticator its POST uses, and one provider that fails is
    left out on its own."""

    def _config(self, *order: str) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(
            oauth_providers={name: {} for name in order or ("google", "github")},
            oauth={},
            oauth2_provider="google",
            open_factory=False,
            root="https://test.example.com/",
        )

    @staticmethod
    def _auth(enabled: bool, url: str = "https://idp.example/auth") -> Any:
        from unittest import mock

        auth = mock.Mock()
        auth.is_enabled.return_value = enabled
        auth.create_authorization_url.return_value = url
        return auth

    def test_the_form_follows_the_default_authenticator(self) -> None:
        from unittest import mock

        from actingweb.handlers.factory import sign_in_page_values

        def create(config: Any, name: str | None = None) -> Any:
            # The default (google) is not enabled; github is.
            return self._auth(name == "github")

        with mock.patch("actingweb.oauth2.create_oauth2_authenticator", create):
            values = sign_in_page_values(self._config())
        assert [p["name"] for p in values["oauth_providers"]] == ["github"]
        assert values["email_form"] is False

    def test_one_failing_provider_leaves_the_others(self) -> None:
        from unittest import mock

        from actingweb.handlers.factory import sign_in_page_values

        def create(config: Any, name: str | None = None) -> Any:
            if name == "github":
                raise RuntimeError("bad provider config")
            return self._auth(True)

        with mock.patch("actingweb.oauth2.create_oauth2_authenticator", create):
            values = sign_in_page_values(self._config("github", "google"))
        assert [p["name"] for p in values["oauth_providers"]] == ["google"]
        assert values["email_form"] is True
