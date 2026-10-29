"""The default (non-enforced) adoption path after the fault contract (3.16,
Phase 2: BR, BU and BS of
``thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md``).

- **BR:** an actor whose marker cannot be read is never ranked like an
  unvouched one: the lookup fails closed, and the successor step creates
  nothing while one stays unreadable.
- **BU:** the per-sign-in cap on the replace path.
- **BS:** one sign-in's reads are bounded by the ranked prefix plus the cap,
  not by how many factory actors share the address.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest import mock

import pytest

from actingweb import oauth2 as oauth2_module
from actingweb.actor import Actor
from actingweb.db import get_actor, get_attribute
from actingweb.db.exceptions import DbError
from actingweb.oauth2 import OAuth2Authenticator, OAuth2Provider, classify_marker
from tests._adoption_helpers import (
    aid,
    backend_fault,
    istore,
    make_config,
    raise_db_error,
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


def _with_id(config: Any, creator: str, prefix: str, auth_method: str | None) -> Actor:
    actor = Actor(config=config)
    assert actor.create(
        url="https://test.example.com/",
        creator=creator,
        passphrase="pass",
        actor_id=f"{prefix}{uuid.uuid4().hex}",
        auth_method=auth_method or "app",
    )
    if auth_method is None:
        istore(actor).auth_method = None
    return actor


def _ids(config: Any, creator: str) -> set[str]:
    """The actors with this creator that exist (each listed id is loaded, so
    an id the index still lists after its deletion is left out)."""
    rows: Any = get_actor(config).get_by_creator(creator=creator) or []
    listed = {str(r["id"]) for r in rows if r and r.get("id")}
    return {i for i in listed if Actor(actor_id=i, config=config).id}


def _marker_fault(config: Any, actor_id: str) -> Any:
    return backend_fault(
        config,
        "get_bucket",
        lambda a, b, _n: a == actor_id and b == "_internal",
        raise_db_error,
    )


class TestBRUnreadableMarker:
    def test_lookup_fails_closed_and_never_strands_the_vouched_actor(
        self, auth: OAuth2Authenticator
    ) -> None:
        config = auth.config
        creator = uuid_email()
        unvouched = _with_id(config, creator, "00", None)
        vouched = _with_id(config, creator, "10", "google_oauth2")

        with _marker_fault(config, aid(vouched)), pytest.raises(DbError):
            auth.lookup_or_create_actor_by_identifier(creator)

        # Nothing was cleaned or created: the unvouched sibling was not
        # picked in the vouched actor's place.
        assert _ids(config, creator) == {aid(unvouched), aid(vouched)}
        assert classify_marker(config, aid(unvouched)) == "unvouched"
        assert classify_marker(config, aid(vouched)) == "vouched"

    def test_without_the_fault_the_vouched_actor_wins(
        self, auth: OAuth2Authenticator
    ) -> None:
        config = auth.config
        creator = uuid_email()
        _with_id(config, creator, "00", None)
        vouched = _with_id(config, creator, "10", "google_oauth2")

        signed_in = auth.lookup_or_create_actor_by_identifier(creator)

        assert signed_in is not None and signed_in.id == aid(vouched)


class TestBUReplaceCap:
    """``SWEEP_LIMIT`` patched to 2, five factory actors."""

    @pytest.fixture(autouse=True)
    def small_cap(self) -> Iterator[None]:
        with mock.patch.object(oauth2_module, "SWEEP_LIMIT", 2):
            yield

    def _factories(self, config: Any, creator: str, n: int = 5) -> list[Actor]:
        return [_with_id(config, creator, f"0{i}", "factory") for i in range(n)]

    def test_leftovers_and_an_unvouched_owner_clean_the_owner(
        self, auth: OAuth2Authenticator
    ) -> None:
        config = auth.config
        creator = uuid_email()
        squat, *_ = self._factories(config, creator)
        owner = _with_id(config, creator, "ff", None)

        result = oauth2_module.adopt_actor(
            squat, provider=auth.provider, config=config, hooks=None
        )

        assert result is not None and result.id == aid(owner)
        assert classify_marker(config, aid(owner)) == "vouched"
        # Never stranded: no new actor beside it.
        assert aid(owner) in _ids(config, creator)
        assert len(_ids(config, creator)) == 1 + 2  # owner + 2 leftovers

    def test_leftovers_and_no_owner_create_exactly_one_successor(
        self, auth: OAuth2Authenticator
    ) -> None:
        config = auth.config
        creator = uuid_email()
        actors = self._factories(config, creator)
        before = {aid(a) for a in actors}

        result = oauth2_module.adopt_actor(
            actors[0], provider=auth.provider, config=config, hooks=None
        )

        assert result is not None and result.id not in before
        after = _ids(config, creator)
        new = after - before
        assert new == {result.id}
        assert classify_marker(config, str(result.id)) == "vouched"
        assert len(after & before) == 2  # the leftovers beyond the cap

    def test_an_unreadable_leftover_creates_nothing(
        self, auth: OAuth2Authenticator
    ) -> None:
        config = auth.config
        creator = uuid_email()
        actors = self._factories(config, creator)
        before = {aid(a) for a in actors}

        with _marker_fault(config, aid(actors[4])):
            result = oauth2_module.adopt_actor(
                actors[0], provider=auth.provider, config=config, hooks=None
            )

        assert result is None
        assert _ids(config, creator) <= before  # nothing created


@contextmanager
def _counting(config: Any) -> Iterator[Counter[str]]:
    """Count actor-row reads and ``_internal`` bucket reads at the backend."""
    counts: Counter[str] = Counter()
    actor_cls = type(get_actor(config))
    attr_cls = type(get_attribute(config))
    real_get = actor_cls.get
    real_bucket = attr_cls.get_bucket

    def get(self: Any, *a: Any, **k: Any) -> Any:
        counts["actor_get"] += 1
        return real_get(self, *a, **k)

    def get_bucket(*a: Any, **k: Any) -> Any:
        if a and isinstance(a[0], attr_cls):
            a = a[1:]
        bucket = k.get("bucket", a[1] if len(a) > 1 else None)
        if bucket == "_internal":
            counts["marker_read"] += 1
        return real_bucket(*a, **k)

    with (
        mock.patch.object(actor_cls, "get", get),
        mock.patch.object(attr_cls, "get_bucket", staticmethod(get_bucket)),
    ):
        yield counts


class TestBSBoundedReads:
    N = 50

    def _crowd(self, config: Any, creator: str) -> tuple[Actor, list[Actor]]:
        owner = _with_id(config, creator, "00", "google_oauth2")
        factories = [
            _with_id(config, creator, f"{i:02d}", "factory") for i in range(1, self.N)
        ]
        return owner, factories

    def test_reads_are_bounded_by_the_prefix_and_the_cap(
        self, auth: OAuth2Authenticator
    ) -> None:
        config = auth.config
        creator = uuid_email()
        owner, _factories = self._crowd(config, creator)
        cap = oauth2_module.SWEEP_LIMIT

        with _counting(config) as counts:
            signed_in = auth.lookup_or_create_actor_by_identifier(creator)

        assert signed_in is not None and signed_in.id == aid(owner)
        # Prefix of one (the owner at 00), the cap's tail, then per removed
        # actor the sweep's two marker reads, one load and one read during
        # its wipe, plus a constant. Linear in the cap, independent of N.
        constant = 10
        assert counts["actor_get"] <= 1 + cap + constant, counts
        assert counts["marker_read"] <= 1 + cap + 3 * cap + constant, counts
        assert len(_ids(config, creator)) == self.N - cap

    def test_a_fault_beyond_the_cap_does_not_block_the_sweep(
        self, auth: OAuth2Authenticator
    ) -> None:
        config = auth.config
        creator = uuid_email()
        owner, factories = self._crowd(config, creator)
        cap = oauth2_module.SWEEP_LIMIT
        far = factories[30]  # past the owner and the cap's tail

        with _marker_fault(config, aid(far)):
            signed_in = auth.lookup_or_create_actor_by_identifier(creator)

        assert signed_in is not None and signed_in.id == aid(owner)
        assert len(_ids(config, creator)) == self.N - cap
        assert aid(far) in _ids(config, creator)
