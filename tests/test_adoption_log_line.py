"""AC-12: every adoption logs exactly one ``ACTOR_ADOPTED:`` WARNING line an
operator can grep to tell a user why their connections are gone, with no
creator or email in it; an adoption announced by a later sign-in included.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from unittest.mock import patch

import pytest

from actingweb import oauth2 as oauth2_module
from actingweb.db.exceptions import DbError
from actingweb.interface.hooks import HookRegistry
from actingweb.oauth2 import OAuth2Authenticator, OAuth2Provider
from tests._adoption_helpers import aid, create_core_actor, make_config, uuid_email

LINE = re.compile(
    r"ACTOR_ADOPTED: actor=(?P<actor>\S+) mode=(?P<mode>cleaned|replaced) "
    r"previous_auth_method=(?P<prev>\S+) previous_actor=(?P<prev_actor>\S+)"
)


@pytest.fixture
def env() -> Any:
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
    hooks = HookRegistry()
    hooks.register_lifecycle_hook("actor_adopted", lambda actor, **kw: None)
    config = make_config(hooks)
    return config, OAuth2Authenticator(config, provider)


def _lines(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if "ACTOR_ADOPTED:" in r.getMessage()]


@pytest.mark.parametrize("case", ["cleaned", "replaced", "announced later"])
def test_one_line_per_adoption(
    env: Any, case: str, caplog: pytest.LogCaptureFixture
) -> None:
    config, auth = env
    creator = uuid_email()
    caplog.set_level(logging.WARNING, logger="actingweb.oauth2")
    if case == "cleaned":
        legacy = create_core_actor(config, creator, auth_method=None)
        adopted = auth.lookup_or_create_actor_by_identifier(creator)
        assert adopted is not None
        expected = ("cleaned", aid(legacy), "legacy", "-")
    elif case == "replaced":
        squat = create_core_actor(config, creator, auth_method="factory")
        adopted = auth.lookup_or_create_actor_by_identifier(creator)
        assert adopted is not None
        expected = ("replaced", adopted.id, "factory", aid(squat))
    else:
        squat = create_core_actor(config, creator, auth_method="factory")
        real_create = oauth2_module._create_actor_for_identifier  # pyright: ignore[reportPrivateUsage]
        calls = {"n": 0}

        def flaky(*a: Any, **k: Any) -> Any:
            calls["n"] += 1
            if calls["n"] == 1:
                raise DbError("create")
            return real_create(*a, **k)

        with patch.object(oauth2_module, "_create_actor_for_identifier", flaky):
            with pytest.raises(DbError):
                auth.lookup_or_create_actor_by_identifier(creator)
            assert _lines(caplog) == []
            adopted = auth.lookup_or_create_actor_by_identifier(creator)
        assert adopted is not None
        expected = ("replaced", adopted.id, "factory", aid(squat))

    records = _lines(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    match = LINE.search(records[0].getMessage())
    assert match is not None, records[0].getMessage()
    mode, actor, prev, prev_actor = expected
    assert match["mode"] == mode
    assert match["actor"] == actor
    assert match["prev"] == prev
    assert match["prev_actor"] == prev_actor


def test_the_line_carries_no_address(
    env: Any, caplog: pytest.LogCaptureFixture
) -> None:
    config, auth = env
    creator = uuid_email()
    create_core_actor(config, creator, auth_method="factory")
    caplog.set_level(logging.WARNING, logger="actingweb.oauth2")
    assert auth.lookup_or_create_actor_by_identifier(creator) is not None
    (record,) = _lines(caplog)
    message = record.getMessage()
    assert creator not in message
    assert creator.split("@")[0] not in message
    assert "@" not in message
