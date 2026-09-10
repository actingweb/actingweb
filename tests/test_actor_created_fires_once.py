"""
Regression tests for 3.14.5 Phase 2: ``actor_created`` fires exactly once per
new actor, from inside ``Actor.create()`` (via the ``hooks=`` kwarg threaded
through ``lookup_or_create_actor_by_identifier``/``lookup_or_create_actor_by_email``
and ``OAuth2SessionManager.complete_session``), not from a second call at
handler level. Before this fix, every OAuth-created actor fired the hook
twice since v3.5.1.

Runs against DynamoDB Local (`docker compose -f docker-compose.test.yml up
dynamodb-test`) like the rest of the unit suite; creator identifiers are
uuid-based since the creator index is shared across xdist workers.
"""

import uuid
from unittest.mock import MagicMock

import pytest

from actingweb.interface import ActingWebApp
from actingweb.oauth2 import OAuth2Authenticator, OAuth2Provider


@pytest.fixture
def mock_oauth_provider():
    return OAuth2Provider(
        "test_provider",
        {
            "client_id": "test_client",
            "client_secret": "test_secret",
            "auth_uri": "https://provider.test/auth",
            "token_uri": "https://provider.test/token",
            "userinfo_uri": "https://provider.test/userinfo",
            "scope": "openid email",
            "redirect_uri": "https://test.example.com/oauth/callback",
        },
    )


def _uuid_email() -> str:
    return f"{uuid.uuid4()}@example.com"


@pytest.fixture
def app_and_counter():
    app = ActingWebApp(
        aw_type="urn:actingweb:test:actor-created-once",
        database="dynamodb",
        fqdn="test.example.com",
    )
    calls: list[str] = []

    @app.lifecycle_hook("actor_created")
    def handle_created(actor):
        calls.append(actor.id)

    config = app.get_config()
    yield app, config, calls


class TestCoreFiringSite:
    def test_new_identifier_fires_hook_exactly_once(
        self, app_and_counter, mock_oauth_provider
    ):
        _app, config, calls = app_and_counter
        authenticator = OAuth2Authenticator(config, mock_oauth_provider)
        identifier = _uuid_email()

        actor = authenticator.lookup_or_create_actor_by_identifier(identifier)
        assert actor is not None
        assert calls == [actor.id]

    def test_existing_identifier_fires_hook_zero_times_on_second_call(
        self, app_and_counter, mock_oauth_provider
    ):
        _app, config, calls = app_and_counter
        authenticator = OAuth2Authenticator(config, mock_oauth_provider)
        identifier = _uuid_email()

        first = authenticator.lookup_or_create_actor_by_identifier(identifier)
        assert first is not None
        assert len(calls) == 1

        second = authenticator.lookup_or_create_actor_by_identifier(identifier)
        assert second is not None
        assert second.id == first.id
        # No new firing for the returning-actor lookup.
        assert len(calls) == 1

    def test_bare_config_with_explicit_hooks_still_fires_once(
        self, mock_oauth_provider
    ):
        """A handler built with a bare Config (no config._hooks) must pass
        hooks= explicitly, or actor_created silently fires zero times. This
        is the scenario the additive `hooks=` kwarg exists for."""
        from actingweb.config import Config
        from actingweb.interface.hooks import HookRegistry

        config = Config(
            fqdn="test.example.com",
            proto="https://",
            database="dynamodb",
            aw_type="urn:actingweb:test:bare-config-hooks",
            devtest=True,
        )
        assert getattr(config, "_hooks", None) is None

        hooks = HookRegistry()
        calls: list[str] = []

        def handle_created(actor):
            calls.append(actor.id)

        hooks.register_lifecycle_hook("actor_created", handle_created)

        authenticator = OAuth2Authenticator(config, mock_oauth_provider)
        identifier = _uuid_email()

        actor = authenticator.lookup_or_create_actor_by_identifier(
            identifier, hooks=hooks
        )
        assert actor is not None
        assert calls == [actor.id]


class TestHandlerLevelSitesDoNotDoubleFire:
    """The four former handler-level actor_created call sites now thread
    hooks= through instead of firing their own copy. Pins that no
    handler-level "actor_created" execute_lifecycle_hooks call remains, and
    that lookup_or_create_actor_by_identifier is called with hooks=self.hooks.

    The email-form site is pinned in tests/test_oauth_email_handler.py::
    TestFreeTextNewAddressFiresOauthSuccess::
    test_no_handler_level_actor_created_call. The SPA token-exchange site
    deletes an is_new_actor block of the same shape as the native-grant tail
    pinned below."""

    def test_oauth2_callback_web_path_no_direct_actor_created_call(self):
        import json
        from unittest.mock import patch

        from actingweb.aw_web_request import AWWebObj
        from actingweb.handlers.oauth2_callback import OAuth2CallbackHandler

        config = MagicMock()
        config.proto = "https://"
        config.fqdn = "test.example.com"
        config.oauth2_provider = "google"
        config.force_email_prop_as_creator = False
        config.service_registry = None

        auth = MagicMock()
        auth.is_enabled.return_value = True
        auth.provider.name = "google"
        auth.provider.mobile_deep_link = ""
        auth.exchange_code_for_token.return_value = {
            "access_token": "at",
            "expires_in": 3600,
        }
        auth.provider.extract_user_info_from_token_response.return_value = None
        auth.validate_token_and_get_user_info.return_value = {
            "email": "user@example.com"
        }
        auth.get_email_from_user_info.return_value = "user@example.com"
        actor = MagicMock()
        actor.id = "actor-web-1"
        actor.creator = "user@example.com"
        actor.store = MagicMock()
        auth.lookup_or_create_actor_by_identifier.return_value = actor

        calls: list[tuple[str, dict]] = []
        hooks = MagicMock()
        hooks.execute_lifecycle_hooks.side_effect = lambda name, _ai, **kw: (
            calls.append((name, kw)),
            True,
        )[1]

        state = json.dumps({"provider": "google"})
        webobj = AWWebObj(
            url="https://test.example.com/oauth/callback?code=c&state=...",
            params={"code": "c", "state": state},
            body="",
            headers={},
            cookies={},
        )

        with (
            patch(
                "actingweb.handlers.oauth2_callback.create_oauth2_authenticator",
                return_value=auth,
            ),
            patch(
                "actingweb.interface.actor_interface.ActorInterface",
                return_value=MagicMock(),
            ),
        ):
            OAuth2CallbackHandler(webobj, config, hooks=hooks).get()

        # No handler-level actor_created call.
        assert not any(name == "actor_created" for name, _ in calls)
        # The lookup/create call threads hooks= through for the core site.
        _args, kwargs = auth.lookup_or_create_actor_by_identifier.call_args
        assert kwargs.get("hooks") is hooks

    def test_oauth2_spa_native_grant_tail_no_direct_actor_created_call(self):
        import json
        from unittest.mock import patch

        from actingweb.aw_web_request import AWWebObj
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

        config = MagicMock()
        config.proto = "https://"
        config.fqdn = "test.example.com"
        config.oauth2_provider = "google"
        config.force_email_prop_as_creator = False
        config.service_registry = None
        config.devtest = False
        config.spa_cors_origins = ["*"]

        actor = MagicMock()
        actor.id = "actor-spa-1"
        actor.creator = "user@example.com"
        actor.store = MagicMock()

        existing_check = MagicMock()
        existing_check.get_from_creator.return_value = False  # new actor

        authenticator = MagicMock()
        authenticator.is_enabled.return_value = True
        authenticator.provider.name = "google"
        authenticator.lookup_or_create_actor_by_identifier.return_value = actor

        calls: list[tuple[str, dict]] = []
        hooks = MagicMock()
        hooks.execute_lifecycle_hooks.side_effect = lambda name, _ai, **kw: (
            calls.append((name, kw)),
            True,
        )[1]

        webobj = AWWebObj(
            url="https://test.example.com/oauth/spa/token",
            params={},
            body=json.dumps(
                {
                    "grant_type": "authorization_code",
                    "code": "c",
                    "state": "s",
                }
            ),
            headers={"Accept": "application/json"},
            cookies={},
        )

        handler = OAuth2SPAHandler(webobj, config, hooks=hooks)

        with patch("actingweb.actor.Actor", return_value=existing_check):
            handler._finalize_native_session(
                "google",
                authenticator,
                "user@example.com",
                {},
                {},
                "json",
            )

        assert not any(name == "actor_created" for name, _ in calls)
        _args, kwargs = authenticator.lookup_or_create_actor_by_identifier.call_args
        assert kwargs.get("hooks") is hooks
