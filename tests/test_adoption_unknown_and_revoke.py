"""Sign-in adoption follow-ups of 3.16 (owner-decided plan, Phase 2).

- K: a clean in place refuses an UNKNOWN deletion status (503).
- J: the clean revokes tokens again after the client registrations go.
- The seeding: a vouched sign-in writes a missing ``store.email``.

``unique_creator`` off (the duplicate-tolerant path), either backend.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from actingweb import oauth2 as oauth2_module
from actingweb import trust as trust_module
from actingweb.actor import Actor
from actingweb.db.exceptions import DbError
from actingweb.deletion import DeletionStatus
from actingweb.oauth2 import OAuth2Authenticator, OAuth2Provider
from tests._adoption_helpers import (
    aid,
    create_core_actor,
    istore,
    make_config,
    plant_squat_state,
    uuid_email,
)


@pytest.fixture
def auth() -> OAuth2Authenticator:
    provider = OAuth2Provider(
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
    return OAuth2Authenticator(make_config(), provider)


def _unknown() -> Any:
    return patch(
        "actingweb.deletion.get_deletion_status", return_value=DeletionStatus.UNKNOWN
    )


class TestUnknownDeletionStatus:
    @pytest.mark.parametrize("marker", [None, "creator_changed"])
    def test_a_clean_in_place_refuses_and_changes_nothing(
        self, auth: OAuth2Authenticator, marker: str | None
    ) -> None:
        config = auth.config
        creator = uuid_email()
        actor = create_core_actor(config, creator, auth_method=marker)
        plant_squat_state(config, actor)
        with _unknown():
            with pytest.raises(DbError):
                auth.lookup_or_create_actor_by_identifier(creator)
        kept = Actor(actor_id=aid(actor), config=config)
        assert kept.passphrase == "squatter-passphrase"
        assert istore(kept).auth_method == marker
        trusts = trust_module.Trusts(actor_id=aid(actor), config=config).fetch()
        assert trusts and len(trusts) == 1

    def test_a_vouched_actor_still_signs_in(self, auth: OAuth2Authenticator) -> None:
        config = auth.config
        creator = uuid_email()
        owner = create_core_actor(config, creator, auth_method="google_oauth2")
        with _unknown():
            result = auth.lookup_or_create_actor_by_identifier(creator)
        assert result is not None and result.id == owner.id


def test_an_actor_unvouched_by_a_pending_verification_refuses_too(
    auth: OAuth2Authenticator,
) -> None:
    config = auth.config
    creator = uuid_email()
    actor = create_core_actor(config, creator, auth_method="google_oauth2")
    istore(actor).email_verified = "false"
    with _unknown():
        with pytest.raises(DbError):
            auth.lookup_or_create_actor_by_identifier(creator)
    assert Actor(actor_id=aid(actor), config=config).passphrase == "squatter-passphrase"


class TestSecondRevoke:
    def test_the_clean_revokes_again_after_the_clients_go(
        self, auth: OAuth2Authenticator
    ) -> None:
        config = auth.config
        creator = uuid_email()
        create_core_actor(config, creator, auth_method=None)
        order: list[str] = []
        real_revoke = oauth2_module._revoke_all_actor_tokens
        real_delete = oauth2_module._delete_actor_clients

        def revoke(*a: Any, **k: Any) -> int:
            order.append("revoke")
            real_revoke(*a, **k)
            return 2

        def delete_clients(*a: Any, **k: Any) -> None:
            order.append("delete_clients")
            real_delete(*a, **k)

        with (
            patch.object(oauth2_module, "_revoke_all_actor_tokens", revoke),
            patch.object(oauth2_module, "_delete_actor_clients", delete_clients),
        ):
            result = auth.lookup_or_create_actor_by_identifier(creator)
        assert result is not None
        assert order == ["revoke", "delete_clients", "revoke"]

    def test_a_fault_in_the_second_revoke_fails_the_sign_in(
        self, auth: OAuth2Authenticator
    ) -> None:
        config = auth.config
        creator = uuid_email()
        create_core_actor(config, creator, auth_method=None)
        calls = {"n": 0}
        real_revoke = oauth2_module._revoke_all_actor_tokens

        def revoke(*a: Any, **k: Any) -> int:
            calls["n"] += 1
            if calls["n"] == 2:
                raise DbError("token revoke")
            return real_revoke(*a, **k)

        with patch.object(oauth2_module, "_revoke_all_actor_tokens", revoke):
            with pytest.raises(DbError):
                auth.lookup_or_create_actor_by_identifier(creator)


class TestSeedMissingEmail:
    def test_a_vouched_actor_without_an_email_gets_its_creator(
        self, auth: OAuth2Authenticator
    ) -> None:
        config = auth.config
        creator = uuid_email()
        owner = create_core_actor(config, creator, auth_method="google_oauth2")
        istore(owner).email = None
        result = auth.lookup_or_create_actor_by_identifier(
            creator, user_info={"email": "other@example.com"}
        )
        assert result is not None and result.id == owner.id
        assert istore(Actor(actor_id=aid(owner), config=config)).email == creator

    def test_a_provider_id_creator_gets_the_provider_email(
        self, auth: OAuth2Authenticator
    ) -> None:
        config = auth.config
        creator = f"google:{uuid_email().split('@')[0]}"
        owner = create_core_actor(config, creator, auth_method="google_oauth2")
        istore(owner).email = None
        auth.lookup_or_create_actor_by_identifier(
            creator, user_info={"email": "Shown@Example.com"}
        )
        assert (
            istore(Actor(actor_id=aid(owner), config=config)).email
            == "shown@example.com"
        )

    def test_an_existing_email_is_never_overwritten(
        self, auth: OAuth2Authenticator
    ) -> None:
        config = auth.config
        creator = f"google:{uuid_email().split('@')[0]}"
        owner = create_core_actor(config, creator, auth_method="google_oauth2")
        istore(owner).email = "kept@example.com"
        auth.lookup_or_create_actor_by_identifier(
            creator, user_info={"email": "new@example.com"}
        )
        assert (
            istore(Actor(actor_id=aid(owner), config=config)).email
            == "kept@example.com"
        )

    def test_a_seeding_fault_does_not_fail_the_sign_in(
        self, auth: OAuth2Authenticator
    ) -> None:
        config = auth.config
        creator = uuid_email()
        owner = create_core_actor(config, creator, auth_method="google_oauth2")
        istore(owner).email = None
        from actingweb.attribute import InternalStore

        with patch.object(
            InternalStore, "set_if_absent", side_effect=DbError("email write")
        ):
            result = auth.lookup_or_create_actor_by_identifier(creator)
        assert result is not None and result.id == owner.id

    def test_a_value_stored_meanwhile_is_not_overwritten(
        self, auth: OAuth2Authenticator
    ) -> None:
        config = auth.config
        creator = uuid_email()
        owner = create_core_actor(config, creator, auth_method="google_oauth2")
        istore(owner).email = None
        from actingweb.attribute import Attributes

        real = Attributes.create_attr_if_absent

        def raced(self: Any, name: str | None = None, **k: Any) -> bool:
            if name == "email":
                # Another writer stores an address between the read and the
                # create.
                Attributes.set_attr(self, name="email", data="raced@example.com")
            return real(self, name=name, **k)

        with patch.object(Attributes, "create_attr_if_absent", raced):
            auth.lookup_or_create_actor_by_identifier(creator)
        assert (
            istore(Actor(actor_id=aid(owner), config=config)).email
            == "raced@example.com"
        )
