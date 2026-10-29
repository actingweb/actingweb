"""``with_open_factory(False)`` closes the actor factory (``POST /``) (3.16).

The gate sits at the top of ``RootFactoryHandler.post()``, so it also closes
the unauthenticated existing-creator redirect (an actor-id oracle).
"""

import json

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
    def test_config_without_the_attribute_is_open(self) -> None:
        config = make_config()
        del config.open_factory
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
