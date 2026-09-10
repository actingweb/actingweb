"""
Tests for ``GET /oauth/email?verify=<token>``, the surviving email
verification mechanism.

After 3.14.5 removed the legacy ``/{actor_id}/www/verify_email`` handler
(GET and POST), this is the *only* way an email address gets verified, and
Phase 3 changed the token compare inside it to ``secret_equals``. Nothing
exercised the path before. Runs against DynamoDB Local like the rest of the
unit suite; creator addresses are uuid-based because the creator index is
shared across xdist workers, and each actor is torn down with its
token-index row.
"""

import time
import uuid

import pytest

from actingweb.attribute import Attributes
from actingweb.aw_web_request import AWWebObj
from actingweb.constants import ACTINGWEB_SYSTEM_ACTOR, EMAIL_VERIFY_TOKEN_INDEX_BUCKET
from actingweb.handlers.oauth_email import OAuth2EmailHandler
from actingweb.interface import ActingWebApp
from actingweb.interface.actor_interface import ActorInterface

VALID_TOKEN = "verify-token-that-is-long-enough-to-be-real"


@pytest.fixture
def config():
    return ActingWebApp(
        aw_type="urn:actingweb:test:oauth-email-verify",
        database="dynamodb",
        fqdn="test.example.com",
    ).get_config()


def _index(config) -> Attributes:
    return Attributes(
        actor_id=ACTINGWEB_SYSTEM_ACTOR,
        bucket=EMAIL_VERIFY_TOKEN_INDEX_BUCKET,
        config=config,
    )


def _store(actor):
    """actor.store is Optional on the core Actor; narrow it once here so the
    assertions below read as assertions and not as None-checks."""
    store = actor.store
    assert store is not None
    return store


def _reload_store(actor_id: str, config):
    from actingweb import actor as actor_module

    return _store(actor_module.Actor(actor_id=actor_id, config=config))


@pytest.fixture
def pending_actor(config):
    """An actor mid-verification: email_verified="false", a stored token, and
    the reverse-index row the GET handler looks the actor up through."""
    creator = f"{uuid.uuid4()}@example.com"
    actor = ActorInterface.create(creator=creator, config=config)
    core = actor.core_actor
    store = _store(core)
    store.email_verified = "false"
    store.email_verification_token = VALID_TOKEN
    store.email_verification_created_at = str(int(time.time()))
    _index(config).set_attr(VALID_TOKEN, data=core.id)

    yield core

    # Teardown runs even on assertion failure.
    _index(config).delete_attr(VALID_TOKEN)
    core.delete()


def _get(config, token: str, hooks=None) -> tuple[dict, AWWebObj]:
    webobj = AWWebObj(
        url=f"https://test.example.com/oauth/email?verify={token}",
        params={"verify": token},
        body="",
        headers={"Accept": "application/json"},
        cookies={},
    )
    result = OAuth2EmailHandler(webobj, config, hooks=hooks).get()
    return result, webobj


class TestVerifyLinkMarksActorVerified:
    def test_valid_token_verifies_and_deletes_the_index_row(
        self, config, pending_actor
    ):
        result, webobj = _get(config, VALID_TOKEN)

        assert result["success"] is True
        assert result["status"] == "verified"
        assert webobj.response.status_code == 200

        reloaded = _reload_store(pending_actor.id, config)
        assert reloaded.email_verified == "true"
        assert reloaded.email_verification_token is None
        assert reloaded.email_verified_at

        # The reverse index row is consumed, so the link cannot be replayed.
        assert not _index(config).get_attr(VALID_TOKEN)

    def test_email_verified_hook_fires_with_the_creator(self, config, pending_actor):
        calls: list[tuple[str, dict]] = []

        class _Hooks:
            def execute_lifecycle_hooks(self, name, _actor, **kwargs):
                calls.append((name, kwargs))
                return True

        _get(config, VALID_TOKEN, hooks=_Hooks())

        assert ("email_verified", {"email": pending_actor.creator}) in calls


class TestVerifyLinkRejections:
    def test_unknown_token_is_403_and_changes_nothing(self, config, pending_actor):
        result, _webobj = _get(config, "no-such-token")

        assert result["status_code"] == 403

        reloaded = _reload_store(pending_actor.id, config)
        assert reloaded.email_verified == "false"
        assert reloaded.email_verification_token == VALID_TOKEN

    def test_index_row_pointing_at_a_different_token_is_403(
        self, config, pending_actor
    ):
        """The stored-token compare (secret_equals) is the second gate: an
        index row can name the actor while the actor's own stored token has
        since been rotated."""
        _store(pending_actor).email_verification_token = "a-rotated-token"

        result, _webobj = _get(config, VALID_TOKEN)

        assert result["status_code"] == 403
        assert _reload_store(pending_actor.id, config).email_verified == "false"

    def test_expired_token_is_410(self, config, pending_actor):
        from actingweb.constants import EMAIL_VERIFICATION_TOKEN_EXPIRY

        _store(pending_actor).email_verification_created_at = str(
            int(time.time()) - EMAIL_VERIFICATION_TOKEN_EXPIRY - 60
        )

        result, _webobj = _get(config, VALID_TOKEN)

        assert result["status_code"] == 410
        assert _reload_store(pending_actor.id, config).email_verified == "false"
