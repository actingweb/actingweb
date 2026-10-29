"""The adoption rule (3.16): a sign-in that proves an address over an actor
nobody vouched for replaces it (``factory``) or cleans it in place (legacy,
``email_unverified``, pending verification).

Runs against DynamoDB Local; creators are uuid-based because the creator index
is shared across xdist workers.
"""

import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from actingweb import trust as trust_module
from actingweb.actor import Actor
from actingweb.deletion import DeletionStatus, get_deletion_status
from actingweb.interface.hooks import HookRegistry
from actingweb.oauth2 import OAuth2Authenticator, OAuth2Provider, adopt_actor
from actingweb.oauth_session import get_oauth2_session_manager
from tests._adoption_helpers import (
    PLANTED_SECRET,
    aid,
    create_core_actor,
    istore,
    make_config,
    plant_squat_state,
    uuid_email,
)

EVENTS = (
    "actor_created",
    "actor_deleted",
    "actor_deleted_complete",
    "actor_adopted",
)


@pytest.fixture
def provider() -> OAuth2Provider:
    return OAuth2Provider(
        "google",
        {
            "client_id": "cid",
            "client_secret": "csec",
            "auth_uri": "https://provider.test/auth",
            "token_uri": "https://provider.test/token",
            "userinfo_uri": "https://provider.test/userinfo",
            "scope": "openid email",
            "redirect_uri": "https://test.example.com/oauth/callback",
        },
    )


@pytest.fixture
def env(provider):
    """(config, authenticator, hooks, events) with every lifecycle event
    recorded in order."""
    hooks = HookRegistry()
    events: list[tuple[str, Any, dict[str, Any]]] = []
    for name in EVENTS:

        def record(actor, _name=name, **kwargs):
            events.append((_name, actor, kwargs))

        hooks.register_lifecycle_hook(name, record)
    config = make_config(hooks)
    return config, OAuth2Authenticator(config, provider), hooks, events


def _names(events) -> list[str]:
    return [e[0] for e in events]


def _plant_spa_token(config, actor_id: str, creator: str) -> str:
    token = f"spa-{actor_id}"
    get_oauth2_session_manager(config).store_access_token(token, actor_id, creator)
    return token


def _spa_valid(config, token: str) -> bool:
    return get_oauth2_session_manager(config).validate_access_token(token) is not None


class TestReplacement:
    def test_factory_actor_is_deleted_and_recreated(self, env, caplog) -> None:
        config, auth, _hooks, events = env
        creator = uuid_email()
        squat = create_core_actor(config, creator, auth_method="factory")
        plant_squat_state(config, squat)
        token = _plant_spa_token(config, aid(squat), creator)
        assert _spa_valid(config, token)
        old_id = aid(squat)

        caplog.set_level(logging.WARNING, logger="actingweb.oauth2")
        with patch("actingweb.actor.requests") as requests_mock:
            adopted = auth.lookup_or_create_actor_by_identifier(creator)
        requests_mock.delete.assert_not_called()

        assert adopted is not None
        assert adopted.id != old_id
        assert not Actor(actor_id=old_id, config=config).id
        assert get_deletion_status(old_id, config) == DeletionStatus.DELETED

        store = adopted.store
        assert store.auth_method == "google_oauth2"
        assert store.auth_method_adopted_from == "factory"
        assert store.auth_method_replaced_actor_id == old_id
        assert not trust_module.Trusts(actor_id=adopted.id, config=config).fetch()
        assert adopted.property["prefilled"] is None
        assert adopted.passphrase != "squatter-passphrase"
        assert not _spa_valid(config, token)

        assert _names(events) == [
            "actor_deleted",
            "actor_deleted_complete",
            "actor_created",
            "actor_adopted",
        ]
        by_name = {e[0]: e for e in events}
        for name in ("actor_deleted", "actor_deleted_complete"):
            kwargs = by_name[name][2]
            assert kwargs["reason"] == "replaced_at_adoption"
            assert kwargs["replaced_by_identifier"] == creator
        assert by_name["actor_deleted_complete"][1] is None
        assert by_name["actor_deleted_complete"][2]["actor_id"] == old_id

        adopted_kwargs = by_name["actor_adopted"][2]
        assert adopted_kwargs["mode"] == "replaced"
        assert adopted_kwargs["previous_auth_method"] == "factory"
        assert adopted_kwargs["previous_actor_id"] == old_id
        assert adopted_kwargs["provider"] == "google"
        assert adopted_kwargs["removed_subscription_peers"] == ["peer-squat"]
        assert adopted_kwargs["tokens_revoked"] >= 1
        removed = adopted_kwargs["removed_trusts"]
        assert [t["peerid"] for t in removed] == ["peer-squat"]
        assert all("secret" not in t for t in removed)

        text = caplog.text
        assert "peer-squat" in text
        assert "squatter-passphrase" not in text and PLANTED_SECRET not in text

    def test_second_login_changes_nothing(self, env) -> None:
        config, auth, _hooks, events = env
        creator = uuid_email()
        create_core_actor(config, creator, auth_method="factory")
        first = auth.lookup_or_create_actor_by_identifier(creator)
        events.clear()
        second = auth.lookup_or_create_actor_by_identifier(creator)
        assert second is not None and first is not None
        assert second.id == first.id
        assert events == []

    def test_delete_failure_fails_closed_then_next_login_completes(self, env) -> None:
        config, auth, _hooks, events = env
        creator = uuid_email()
        squat = create_core_actor(config, creator, auth_method="factory")
        with patch.object(Actor, "delete", side_effect=RuntimeError("boom")):
            assert auth.lookup_or_create_actor_by_identifier(creator) is None
        assert Actor(actor_id=aid(squat), config=config).id == aid(squat)
        assert "actor_adopted" not in _names(events)

        adopted = auth.lookup_or_create_actor_by_identifier(creator)
        assert adopted is not None and adopted.id != aid(squat)


class TestCleanedInPlace:
    def test_legacy_actor_keeps_id_and_data_loses_relationships(self, env) -> None:
        config, auth, _hooks, events = env
        creator = uuid_email()
        legacy = create_core_actor(config, creator, auth_method=None)
        plant_squat_state(config, legacy)
        token = _plant_spa_token(config, aid(legacy), creator)

        with patch("actingweb.actor.requests") as requests_mock:
            adopted = auth.lookup_or_create_actor_by_identifier(creator)
        requests_mock.delete.assert_not_called()

        assert adopted is not None and adopted.id == aid(legacy)
        assert adopted.passphrase != "squatter-passphrase"
        row = Actor(actor_id=aid(legacy), config=config)
        assert row.passphrase == adopted.passphrase
        assert not trust_module.Trusts(actor_id=aid(legacy), config=config).fetch()
        assert row.property is not None
        assert row.property["prefilled"] == "squatter-value"
        assert not _spa_valid(config, token)
        assert istore(row).auth_method == "google_oauth2"
        assert istore(row).auth_method_adopted_from == "legacy"

        assert _names(events) == ["actor_adopted"]
        kwargs = events[0][2]
        assert kwargs["mode"] == "cleaned"
        assert kwargs["previous_auth_method"] == "legacy"
        assert kwargs["previous_actor_id"] is None
        assert "prefilled" in kwargs["property_names"]

    def test_pre_316_free_text_actor_pending_verification(self, env) -> None:
        config, auth, _hooks, _events = env
        creator = uuid_email()
        actor = create_core_actor(config, creator, auth_method="google_oauth2")
        istore(actor).email_verified = "false"
        istore(actor).email_verification_token = "tok"
        plant_squat_state(config, actor)

        adopted = auth.lookup_or_create_actor_by_identifier(creator)

        assert adopted is not None and adopted.id == aid(actor)
        assert not trust_module.Trusts(actor_id=aid(actor), config=config).fetch()
        # Cleared only after the decision, so the evidence was not erased early.
        assert istore(adopted).email_verified is None
        assert istore(adopted).auth_method_adopted_from == "google_oauth2"

    def test_email_unverified_actor_is_cleaned_not_replaced(self, env) -> None:
        config, auth, _hooks, events = env
        creator = uuid_email()
        actor = create_core_actor(config, creator, auth_method="email_unverified")
        istore(actor).email_verified = "false"
        plant_squat_state(config, actor)

        adopted = auth.lookup_or_create_actor_by_identifier(creator)

        assert adopted is not None and adopted.id == aid(actor)
        assert adopted.property["prefilled"] == "squatter-value"
        assert "actor_deleted" not in _names(events)

    def test_verification_link_cleans_and_marks_email_verified(
        self, env, provider
    ) -> None:
        config, _auth, hooks, events = env
        creator = uuid_email()
        actor = create_core_actor(config, creator, auth_method="email_unverified")
        istore(actor).email_verified = "false"
        plant_squat_state(config, actor)
        token = _plant_spa_token(config, aid(actor), creator)

        result = adopt_actor(
            actor, provider=None, config=config, hooks=hooks, verified_by_email=True
        )

        assert result is actor
        assert not _spa_valid(config, token)
        assert istore(actor).auth_method == "email_verified"
        assert not trust_module.Trusts(actor_id=aid(actor), config=config).fetch()
        assert events[0][2]["provider"] is None


class TestVouchedActors:
    @pytest.mark.parametrize("marker", ["app", "google_oauth2", "operator"])
    def test_untouched(self, env, marker) -> None:
        config, auth, _hooks, events = env
        creator = uuid_email()
        actor = create_core_actor(config, creator, auth_method=marker)
        plant_squat_state(config, actor)
        before = actor.passphrase

        adopted = auth.lookup_or_create_actor_by_identifier(creator)

        assert adopted is not None and adopted.id == aid(actor)
        assert adopted.passphrase == before
        assert trust_module.Trusts(actor_id=aid(actor), config=config).fetch()
        assert events == []
        assert istore(adopted).oauth_provider == "google"

    def test_create_only_still_refuses_before_any_change(self, env) -> None:
        config, auth, _hooks, events = env
        creator = uuid_email()
        actor = create_core_actor(config, creator, auth_method="factory")
        assert (
            auth.lookup_or_create_actor_by_identifier(creator, create_only=True) is None
        )
        assert Actor(actor_id=aid(actor), config=config).id == aid(actor)
        assert events == []

    def test_hooks_none_fires_nothing_but_still_adopts(self, provider) -> None:
        config = make_config()
        creator = uuid_email()
        actor = create_core_actor(config, creator, auth_method=None)
        adopted = adopt_actor(actor, provider=provider, config=config, hooks=None)
        assert adopted is actor
        assert adopted is not None
        assert istore(adopted).auth_method == "google_oauth2"


class TestFailuresFailClosed:
    def _legacy(self, env):
        config, auth, _hooks, events = env
        creator = uuid_email()
        actor = create_core_actor(config, creator, auth_method=None)
        plant_squat_state(config, actor)
        return config, auth, events, creator, actor

    @pytest.mark.parametrize("failure", ["false", "raise"])
    def test_rotation_failure_changes_nothing(self, env, failure) -> None:
        config, auth, events, creator, actor = self._legacy(env)
        patcher = (
            patch.object(Actor, "modify", return_value=False)
            if failure == "false"
            else patch.object(Actor, "modify", side_effect=RuntimeError("boom"))
        )
        with patcher:
            assert auth.lookup_or_create_actor_by_identifier(creator) is None
        row = Actor(actor_id=aid(actor), config=config)
        assert row.passphrase == "squatter-passphrase"
        assert istore(row).auth_method is None
        assert trust_module.Trusts(actor_id=aid(actor), config=config).fetch()
        assert events == []

    def test_unconfirmed_wipe_leaves_actor_unvouched_but_rotated(
        self, env, caplog
    ) -> None:
        config, auth, events, creator, actor = self._legacy(env)
        caplog.set_level(logging.ERROR, logger="actingweb.oauth2")
        with (
            patch.object(trust_module.Trusts, "delete", return_value=True),
            patch.object(Actor, "delete_reciprocal_trust", return_value=True),
        ):
            assert auth.lookup_or_create_actor_by_identifier(creator) is None
        row = Actor(actor_id=aid(actor), config=config)
        assert row.passphrase != "squatter-passphrase"
        assert istore(row).auth_method is None
        assert events == []
        assert "remain after the wipe" in caplog.text

    def test_empty_token_aborts_before_any_write(self, env) -> None:
        config, auth, events, creator, actor = self._legacy(env)
        with patch.object(type(config), "new_token", return_value=""):
            assert auth.lookup_or_create_actor_by_identifier(creator) is None
        assert (
            Actor(actor_id=aid(actor), config=config).passphrase
            == "squatter-passphrase"
        )
        assert events == []

    def test_a_raising_hook_undoes_nothing(self, env, provider) -> None:
        config, auth, hooks, _events = env

        def boom(actor, **kwargs):
            raise RuntimeError("consumer bug")

        hooks.register_lifecycle_hook("actor_adopted", boom)
        creator = uuid_email()
        create_core_actor(config, creator, auth_method=None)
        adopted = auth.lookup_or_create_actor_by_identifier(creator)
        assert adopted is not None
        assert istore(adopted).auth_method == "google_oauth2"


class TestMcpTokens:
    def test_revoke_actor_tokens_removes_every_client(self) -> None:
        from actingweb.oauth2_server.token_manager import get_actingweb_token_manager

        config = make_config()
        creator = uuid_email()
        actor = create_core_actor(config, creator, auth_method="factory")
        manager = get_actingweb_token_manager(config)
        issued = [
            manager.create_access_token(aid(actor), client_id=f"client-{n}")
            for n in range(2)
        ]
        tokens = [t["access_token"] for t in issued if t]
        assert len(tokens) == 2
        assert all(manager.validate_access_token(t) for t in tokens)

        assert manager.revoke_actor_tokens(aid(actor)) >= 2
        assert not any(manager.validate_access_token(t) for t in tokens)


class TestBypassSites:
    """The sites that already hold the existing actor must run the rule too."""

    def _pre316_free_text(self, config):
        creator = uuid_email()
        actor = create_core_actor(config, creator, auth_method="google_oauth2")
        istore(actor).email_verified = "false"
        plant_squat_state(config, actor)
        return creator, actor

    def test_mcp_server_goes_through_the_authenticator(self, env) -> None:
        from actingweb.oauth2_server.oauth2_server import ActingWebOAuth2Server

        config, _auth, _hooks, events = env
        creator = uuid_email()
        actor = create_core_actor(config, creator, auth_method="factory")
        config.oauth = {"client_id": "cid", "client_secret": "csec"}
        server = ActingWebOAuth2Server(config)

        adopted = server._get_or_create_actor_for_email(creator, "google")

        assert adopted is not None and adopted.id != aid(actor)
        assert istore(adopted).oauth_provider == "google"
        assert "actor_adopted" in _names(events)

    def test_native_grant_tail_adopts_a_pre_316_free_text_actor(self, env) -> None:
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

        config, auth, hooks, events = env
        creator, actor = self._pre316_free_text(config)
        handler = OAuth2SPAHandler.__new__(OAuth2SPAHandler)
        handler.config = config
        handler.hooks = hooks

        result = handler._finalize_native_session(
            "google", auth, creator, {"email": creator}, {}, "json"
        )

        assert result.get("success") is True, result
        assert result["actor_id"] == aid(actor)
        assert not trust_module.Trusts(actor_id=aid(actor), config=config).fetch()
        assert "actor_adopted" in _names(events)

    def test_pending_state_is_cleared_only_inside_adopt_actor(self) -> None:
        """The inline clears erased ``email_verified == "false"`` before the
        vouching check; they are gone from every call site."""
        root = Path(__file__).resolve().parent.parent / "actingweb"
        callers = {
            str(p.relative_to(root))
            for p in root.rglob("*.py")
            if "clear_pending_email_verification(" in p.read_text()
            and p.name != "oauth2.py"
        }
        assert callers == set()

    @pytest.mark.parametrize(
        "module", ["handlers/oauth2_spa.py", "handlers/oauth2_callback.py"]
    )
    def test_handlers_holding_an_existing_actor_call_adopt_actor(self, module) -> None:
        root = Path(__file__).resolve().parent.parent / "actingweb"
        text = (root / module).read_text()
        assert text.count("adopt_actor(") >= (2 if "spa" in module else 1)


class TestEmailUnverifiedMarker:
    def test_marker_reaches_the_created_actor(self, env) -> None:
        """Threaded through lookup_or_create_actor_by_email ->
        lookup_or_create_actor_by_identifier -> ActorInterface.create; no
        ``Actor.create`` call site carries it, so the source-grep pin cannot
        see it."""
        _config, auth, _hooks, _events = env
        email = uuid_email()
        created = auth.lookup_or_create_actor_by_email(
            email, create_only=True, auth_method="email_unverified"
        )
        assert created is not None
        assert istore(created).auth_method == "email_unverified"

    def test_default_is_the_provider_marker(self, env) -> None:
        _config, auth, _hooks, _events = env
        created = auth.lookup_or_create_actor_by_email(uuid_email())
        assert created is not None
        assert istore(created).auth_method == "google_oauth2"


class TestIterationOneFindings:
    """Findings of the 2026-10-27 verification: registered clients, an
    unfinished replacement, a concurrent successor, the GSI lag and the
    provider tokens on the emailed-link path."""

    def test_clean_in_place_deletes_registered_clients_without_network(
        self, env
    ) -> None:
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.oauth2_server.client_registry import MCPClientRegistry

        config, auth, _hooks, events = env
        creator = uuid_email()
        legacy = create_core_actor(config, creator, auth_method=None)
        # Without its trust row (registration does not fail when the trust
        # cannot be created): deleting a trust already deletes its client.
        with patch.object(MCPClientRegistry, "_create_client_trust_relationship"):
            client = OAuth2ClientManager(aid(legacy), config).create_client("squat")
        registry = MCPClientRegistry(config)
        assert registry.load_client_strict(client["client_id"])

        with patch("requests.delete") as remote_delete:
            adopted = auth.lookup_or_create_actor_by_identifier(creator)

        assert adopted is not None and adopted.id == aid(legacy)
        assert registry.load_client_strict(client["client_id"]) is None
        assert not registry.list_clients_for_actor(aid(legacy))
        remote_delete.assert_not_called()
        adopted_kwargs = [e[2] for e in events if e[0] == "actor_adopted"][0]
        assert adopted_kwargs["removed_client_ids"] == [client["client_id"]]

    def test_replacement_removes_the_client_index_row(self, env) -> None:
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.oauth2_server.client_registry import MCPClientRegistry

        config, auth, _hooks, _events = env
        creator = uuid_email()
        squat = create_core_actor(config, creator, auth_method="factory")
        with patch.object(MCPClientRegistry, "_create_client_trust_relationship"):
            client = OAuth2ClientManager(aid(squat), config).create_client("squat")

        adopted = auth.lookup_or_create_actor_by_identifier(creator)

        assert adopted is not None and adopted.id != aid(squat)
        assert MCPClientRegistry(config).load_client_strict(client["client_id"]) is None
        # The bucket delete takes the client row; the index row lives under
        # the system actor and has to be removed by name.
        from actingweb.constants import CLIENT_INDEX_BUCKET, OAUTH2_SYSTEM_ACTOR
        from actingweb.db import get_attribute

        assert not get_attribute(config).get_attr(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=CLIENT_INDEX_BUCKET,
            name=client["client_id"],
        )

    def test_unconfirmed_row_delete_fails_closed_then_finishes(self, env) -> None:
        from actingweb.db import get_actor

        config, auth, _hooks, _events = env
        creator = uuid_email()
        squat = create_core_actor(config, creator, auth_method="factory")

        # The wipe runs and the buckets (the marker among them) go, but the
        # backend does not confirm the row removed (PostgreSQL's False).
        with patch.object(type(get_actor(config)), "delete", return_value=False):
            assert auth.lookup_or_create_actor_by_identifier(creator) is None
        assert Actor(actor_id=aid(squat), config=config).id == aid(squat)
        assert get_deletion_status(aid(squat), config) == DeletionStatus.DELETED

        # The next sign-in finishes the replacement instead of cleaning the
        # half-deleted actor in place under its tombstone.
        adopted = auth.lookup_or_create_actor_by_identifier(creator)
        assert adopted is not None and adopted.id != aid(squat)
        assert Actor(actor_id=aid(squat), config=config).id is None

    def test_concurrent_successor_is_reused_not_duplicated(self, env) -> None:
        from actingweb.db import get_actor

        config, auth, _hooks, _events = env
        creator = uuid_email()
        squat = Actor(config=config)
        assert squat.create(
            url="https://test.example.com/",
            creator=creator,
            passphrase="squatter-passphrase",
            actor_id=f"0000{uuid_email().split('@')[0]}",
            auth_method="factory",
        )
        winner = Actor(config=config)
        assert winner.create(
            url="https://test.example.com/",
            creator=creator,
            passphrase="",
            actor_id=f"ffff{uuid_email().split('@')[0]}",
            auth_method="google_oauth2",
        )

        adopted = auth.lookup_or_create_actor_by_identifier(creator)

        # The lookup prefers the vouched actor although the factory one has
        # the lower id; no successor is created, and the sign-in removes the
        # factory sibling it found.
        assert adopted is not None and adopted.id == winner.id
        remaining = get_actor(config).get_by_creator(creator=creator) or []
        assert sorted(r["id"] for r in remaining if r) == [str(winner.id)]

    def test_unique_creator_skips_an_index_entry_whose_row_is_gone(self) -> None:
        from actingweb.db import get_actor

        config = make_config()
        config.unique_creator = True
        creator = uuid_email()
        actor = Actor(config=config)
        # DynamoDB's creator index can still list a just-deleted actor; its
        # consistent read then answers None.
        with patch.object(
            type(get_actor(config)), "get_by_creator", return_value=[None]
        ):
            assert actor.create(
                url="https://test.example.com/",
                creator=creator,
                passphrase="",
                auth_method="google_oauth2",
            )
        assert actor.id

    def test_verification_link_clears_the_creators_provider_tokens(self, env) -> None:
        config, _auth, hooks, _events = env
        creator = uuid_email()
        actor = create_core_actor(config, creator, auth_method="email_unverified")
        store = istore(actor)
        store.email_verified = "false"
        store.oauth_token = "squatter-provider-token"
        store.oauth_refresh_token = "squatter-provider-refresh"

        assert adopt_actor(
            actor, provider=None, config=config, hooks=hooks, verified_by_email=True
        )

        row = istore(Actor(actor_id=aid(actor), config=config))
        assert row.oauth_token is None and row.oauth_refresh_token is None
