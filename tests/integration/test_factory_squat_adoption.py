"""End-to-end: the factory squat and the owner's first OAuth login (3.16).

An unauthenticated ``POST /`` creates an actor for any address nobody has
claimed, with a passphrase of the caller's choosing. Before 3.16 the address
owner's first OAuth login adopted that actor with the squatter's credentials
still live: the passphrase and any ``admin`` trust made with a chosen secret.
Now the login replaces it.
"""

import os

import requests

from actingweb import config as config_module
from actingweb import trust as trust_module
from actingweb.oauth2 import OAuth2Authenticator, OAuth2Provider

DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")

SQUAT_PASSPHRASE = "squatter-chosen-passphrase"
PLANTED_SECRET = "squatter-chosen-trust-secret"


def _oauth_authenticator(test_app: str) -> OAuth2Authenticator:
    """An in-process authenticator against the same backend the server uses."""
    config = config_module.Config(database=DATABASE_BACKEND)
    config.fqdn = test_app.replace("http://", "").replace("https://", "")
    config.proto = "http://" if test_app.startswith("http://") else "https://"
    provider = OAuth2Provider(
        "google",
        {
            "client_id": "cid",
            "client_secret": "csec",
            "auth_uri": "https://provider.test/auth",
            "token_uri": "https://provider.test/token",
            "userinfo_uri": "https://provider.test/userinfo",
            "scope": "openid email",
            "redirect_uri": f"{config.proto}{config.fqdn}/oauth/callback",
        },
    )
    return OAuth2Authenticator(config, provider)


class TestFactorySquatAdoption:
    def test_login_replaces_the_squatted_actor(self, test_app, actor_factory) -> None:
        squat = actor_factory.create("victim@example.com", passphrase=SQUAT_PASSPHRASE)
        old_id, creator = squat["id"], squat["creator"]
        basic = (creator, SQUAT_PASSPHRASE)

        # Every creation path records how the actor came to exist.
        marker = requests.get(
            f"{test_app}/{old_id}/devtest/attributes/_internal/auth_method", auth=basic
        )
        assert marker.status_code == 200
        assert marker.json()["data"] == "factory"

        # The squatter's prepared position: a property and an admin trust with
        # a secret of their own choosing.
        assert requests.put(
            f"{test_app}/{old_id}/properties/squat",
            data="planted",
            auth=basic,
        ).status_code in (200, 204)
        authenticator = _oauth_authenticator(test_app)
        assert trust_module.Trust(
            actor_id=old_id, peerid="squatter-peer", config=authenticator.config
        ).create(
            baseuri=test_app,
            peer_type="urn:actingweb:test:peer",
            relationship="admin",
            secret=PLANTED_SECRET,
            approved=True,
            verified=True,
        )
        before = requests.get(
            f"{test_app}/{old_id}/properties",
            headers={"Authorization": f"Bearer {PLANTED_SECRET}"},
        )
        assert before.status_code == 200, "the exploit precondition must be real"

        # The address owner signs in with OAuth.
        adopted = authenticator.lookup_or_create_actor_by_identifier(creator)
        assert adopted is not None
        new_id = adopted.id
        assert new_id != old_id

        # The squatter's credentials open nothing, on either id. (/meta is
        # public, so credentials are checked against /properties.)
        assert requests.get(
            f"{test_app}/{old_id}/properties", auth=basic
        ).status_code in (
            403,
            404,
        )
        assert requests.get(
            f"{test_app}/{new_id}/properties", auth=basic
        ).status_code in (
            401,
            403,
        )
        for actor_id in (old_id, new_id):
            leaked = requests.get(
                f"{test_app}/{actor_id}/properties",
                headers={"Authorization": f"Bearer {PLANTED_SECRET}"},
            )
            assert leaked.status_code in (401, 403, 404)

        # The owner's actor is a clean slate with their own passphrase.
        assert adopted.passphrase
        fresh = (creator, adopted.passphrase)
        assert (
            requests.get(f"{test_app}/{new_id}/properties", auth=fresh).status_code
            == 200
        )
        trusts = requests.get(f"{test_app}/{new_id}/trust", auth=fresh)
        assert trusts.status_code == 200 and trusts.json() == []
        assert (
            "squat"
            not in requests.get(f"{test_app}/{new_id}/properties", auth=fresh).text
        )

        adopted_from = requests.get(
            f"{test_app}/{new_id}/devtest/attributes/_internal/auth_method_adopted_from",
            auth=fresh,
        )
        assert adopted_from.json()["data"] == "factory"
        new_marker = requests.get(
            f"{test_app}/{new_id}/devtest/attributes/_internal/auth_method", auth=fresh
        )
        assert new_marker.json()["data"] == "google_oauth2"


class TestCreatorRenameUnvouches:
    def test_renamed_actor_is_cleaned_at_the_new_owners_login(
        self, test_app, actor_factory
    ) -> None:
        import uuid

        auth = _oauth_authenticator(test_app)
        attacker_email = f"attacker-{uuid.uuid4()}@example.com"
        victim_email = f"victim-{uuid.uuid4()}@example.com"

        # The attacker signs in with their own account: a vouched actor.
        own = auth.lookup_or_create_actor_by_identifier(attacker_email)
        assert own is not None and own.id and own.passphrase
        basic = (attacker_email, own.passphrase)

        # ...then points its creator at the victim's address over HTTP.
        renamed = requests.put(
            f"{test_app}/{own.id}/trust/trustee",
            json={"creator": victim_email},
            auth=basic,
        )
        assert renamed.status_code == 204
        marker = requests.get(
            f"{test_app}/{own.id}/devtest/attributes/_internal/auth_method",
            auth=(victim_email, own.passphrase),
        )
        assert marker.json()["data"] == "creator_changed"

        # The victim's first login lands on that actor and cleans it: the
        # attacker's passphrase no longer opens it.
        adopted = auth.lookup_or_create_actor_by_identifier(victim_email)
        assert adopted is not None and adopted.id == own.id
        assert adopted.passphrase != own.passphrase
        assert requests.get(
            f"{test_app}/{own.id}/properties", auth=(victim_email, own.passphrase)
        ).status_code in (401, 403)
