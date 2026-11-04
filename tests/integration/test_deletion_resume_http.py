"""Resumable deletion over HTTP and under ``with_unique_creator()`` (3.16).

A ``DELETE /<id>`` whose wipe stopped part-way answers 503 and is finished by
its retry; a re-sign-up after a stalled wipe finishes it and creates the new
actor, the creator released with the row; ``actingweb-deletions resume``
does the same for a wipe nobody comes back for. ``unique_creator`` xdist
group: the isolated store swaps process-wide table names.

Plan: thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md, Phase 1.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any
from unittest import mock

import pytest
import requests

from actingweb import attribute, deletion
from actingweb.actor import Actor
from actingweb.db.exceptions import DbError
from actingweb.maintenance import deletions as deletions_command
from actingweb.oauth2 import OAuth2Authenticator, OAuth2Provider

pytestmark = pytest.mark.xdist_group(name="unique_creator")

_PAST = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)


def _email() -> str:
    return f"{uuid.uuid4().hex[:12]}@example.com"


def _factory(url: str, creator: str) -> dict[str, Any]:
    response = requests.post(
        f"{url}/",
        json={"creator": creator, "passphrase": "pw"},
        headers={"Accept": "application/json"},
        timeout=10,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _delete(url: str, created: dict[str, Any]) -> requests.Response:
    return requests.delete(
        f"{url}/{created['id']}",
        auth=(created["creator"], created["passphrase"]),
        timeout=10,
    )


def _stalled(config: Any, creator: str) -> str:
    actor = Actor(config=config)
    assert actor.create(
        url="https://test.example.com/",
        creator=creator,
        passphrase="p",
        auth_method="google_oauth2",
    )
    assert actor.id
    data = deletion.create_leased_tombstone(
        actor.id,
        config,
        reason="deleted",
        notify_peers=True,
        hook_kwargs={},
        client_ids=[],
        now=_PAST,
    )
    assert deletion.update_tombstone(actor.id, config, data, {"hook_fired": True})
    return actor.id


class TestDeleteRetry:
    def test_a_stalled_delete_is_finished_by_its_retry(
        self, unique_creator_app: str, enforced_store: Any
    ) -> None:
        created = _factory(unique_creator_app, _email())
        with mock.patch.object(
            attribute.Buckets, "delete", side_effect=DbError("bucket delete")
        ):
            first = _delete(unique_creator_app, created)
        assert first.status_code == 503
        assert Actor(actor_id=created["id"], config=enforced_store).id == created["id"]

        retry = _delete(unique_creator_app, created)

        assert retry.status_code == 204, retry.text
        assert Actor(actor_id=created["id"], config=enforced_store).id is None

    def test_a_retry_under_the_lease_answers_retry_after(
        self, unique_creator_app: str, enforced_store: Any
    ) -> None:
        created = _factory(unique_creator_app, _email())
        deletion.create_leased_tombstone(
            created["id"],
            enforced_store,
            reason="deleted",
            notify_peers=True,
            hook_kwargs={},
            client_ids=[],
        )
        response = _delete(unique_creator_app, created)
        assert response.status_code == 503
        assert int(response.headers["Retry-After"]) >= 1


class TestReSignUp:
    def test_a_sign_in_finishes_the_wipe_and_takes_the_creator(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        old = _stalled(enforced_store, creator)
        provider = OAuth2Provider(
            "google",
            {
                "client_id": "c",
                "client_secret": "s",
                "auth_uri": "https://p/a",
                "token_uri": "https://p/t",
                "userinfo_uri": "https://p/u",
                "scope": "openid email",
                "redirect_uri": "https://test.example.com/oauth/callback",
            },
        )
        new = OAuth2Authenticator(
            enforced_store, provider
        ).lookup_or_create_actor_by_identifier(creator, finish_stalled_deletion=True)

        assert new is not None and new.id != old
        assert Actor(actor_id=old, config=enforced_store).id is None


class TestOperatorCommand:
    def test_resume_releases_the_creator(
        self, enforced_store: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        creator = _email()
        old = _stalled(enforced_store, creator)

        code = deletions_command.main(["resume", old, "--apply"])
        out = capsys.readouterr().out

        assert code == 0, out
        again = Actor(config=enforced_store)
        assert again.create(
            url="https://test.example.com/",
            creator=creator,
            passphrase="p",
            auth_method="google_oauth2",
        )
