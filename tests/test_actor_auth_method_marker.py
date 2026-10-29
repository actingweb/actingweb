"""``auth_method`` is recorded on every creation path (3.16).

Runs against DynamoDB Local like the rest of the unit suite.
"""

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

from actingweb.actor import Actor
from actingweb.interface.actor_interface import ActorInterface
from actingweb.oauth2 import is_vouched_actor
from tests._adoption_helpers import (
    aid,
    create_core_actor,
    istore,
    make_config,
    uuid_email,
)


class TestActorCreateMarker:
    def test_default_is_app(self) -> None:
        config = make_config()
        actor = Actor(config=config)
        assert actor.create(
            url="https://test.example.com/", creator=uuid_email(), passphrase="p"
        )
        assert actor.store is not None
        assert istore(actor).auth_method == "app"
        # Persisted, not just cached on the instance.
        assert istore(Actor(actor_id=aid(actor), config=config)).auth_method == "app"  # type: ignore[union-attr]

    def test_explicit_value_written(self) -> None:
        actor = create_core_actor(make_config(), uuid_email(), auth_method="factory")
        assert actor.store is not None
        assert istore(actor).auth_method == "factory"

    def test_marker_visible_inside_actor_created_hook(self) -> None:
        seen: list[str | None] = []
        hooks = MagicMock()
        hooks.execute_lifecycle_hooks.side_effect = lambda event, a, **kw: seen.append(
            a.core_actor.store.auth_method
        )
        actor = Actor(config=make_config())
        assert actor.create(
            url="https://test.example.com/",
            creator=uuid_email(),
            passphrase="p",
            hooks=hooks,
            auth_method="factory",
        )
        assert seen == ["factory"]

    def test_nothing_written_when_row_not_persisted(self) -> None:
        config = make_config()
        victim = create_core_actor(config, uuid_email(), auth_method="google_oauth2")
        handle = MagicMock()
        handle.create.return_value = False
        other = Actor(config=config)
        other.handle = handle
        other.create(
            url="https://test.example.com/",
            creator=uuid_email(),
            passphrase="p",
            actor_id=aid(victim),
            auth_method="factory",
        )
        assert istore(Actor(actor_id=aid(victim), config=config)).auth_method == (  # type: ignore[union-attr]
            "google_oauth2"
        )


class TestActorInterfaceMarker:
    def test_default_and_explicit(self) -> None:
        config = make_config()
        default = ActorInterface.create(creator=uuid_email(), config=config)
        assert default.core_actor.store.auth_method == "app"  # type: ignore[union-attr]
        explicit = ActorInterface.create(
            creator=uuid_email(), config=config, auth_method="factory"
        )
        assert explicit.core_actor.store.auth_method == "factory"  # type: ignore[union-attr]


class TestCreationPathsPassAMarker:
    def test_factory_handler_writes_factory(self) -> None:
        from actingweb.aw_web_request import AWWebObj
        from actingweb.handlers.factory import RootFactoryHandler

        config = make_config()
        creator = uuid_email()
        webobj = AWWebObj(
            url="https://test.example.com/",
            params={},
            body=f'{{"creator": "{creator}"}}',
            headers={"Content-Type": "application/json"},
            cookies={},
        )
        RootFactoryHandler(webobj, config, hooks=None).post()
        actor = Actor(config=config)
        assert actor.get_from_creator(creator)
        assert actor.store is not None
        assert istore(actor).auth_method == "factory"

    def test_system_actors_pass_system(self) -> None:
        """The system actors already exist in the shared test prefix, so the
        creation call is pinned on mocked kwargs."""
        from actingweb.oauth2_server.system_actor import ensure_oauth2_system_actor
        from actingweb.trust_type_registry import TrustTypeRegistry

        for module in (
            "actingweb.oauth2_server.system_actor",
            "actingweb.trust_type_registry",
        ):
            fake = MagicMock()
            fake.actor = None
            fake.id = None
            fake.create.return_value = True
            with patch("actingweb.actor.Actor", return_value=fake):
                if module.endswith("system_actor"):
                    ensure_oauth2_system_actor(make_config())
                else:
                    TrustTypeRegistry(make_config())._get_system_actor()
            assert fake.create.call_args.kwargs["auth_method"] == "system", module

    def test_every_library_create_call_passes_auth_method(self) -> None:
        """A seventh creation path without the keyword would default to
        vouched; this fails it at review time."""
        root = Path(__file__).resolve().parent.parent / "actingweb"
        pattern = re.compile(
            r"\b(?:sys_actor|new_actor|myself|core_actor)\.create\(([^)]*)\)", re.S
        )
        found = 0
        for path in root.rglob("*.py"):
            for match in pattern.finditer(path.read_text()):
                if "url=" not in match.group(1):
                    continue
                found += 1
                assert "auth_method" in match.group(1), f"{path}: {match.group(0)}"
        assert found >= 4


class TestIsVouchedActor:
    def _actor(self, auth_method: object, email_verified: object = None) -> MagicMock:
        actor = MagicMock()
        istore(actor).auth_method = auth_method
        istore(actor).email_verified = email_verified
        return actor

    def test_vouched(self) -> None:
        for value in ("app", "google_oauth2", "operator", "email_verified", "system"):
            assert is_vouched_actor(self._actor(value))

    def test_unvouched(self) -> None:
        for value in (None, "", "factory", "email_unverified", 7):
            assert not is_vouched_actor(self._actor(value))

    def test_pending_email_verification_is_unvouched(self) -> None:
        assert not is_vouched_actor(self._actor("google_oauth2", "false"))
        assert is_vouched_actor(self._actor("google_oauth2", "true"))

    def test_no_store(self) -> None:
        actor = MagicMock()
        actor.store = None
        assert not is_vouched_actor(actor)


class TestActorModifyPassphrase:
    def test_rotates_stored_and_in_memory(self) -> None:
        config = make_config()
        actor = create_core_actor(config, uuid_email(), passphrase="old-pass")
        assert actor.modify(passphrase="new-pass") is True
        assert actor.passphrase == "new-pass"
        assert Actor(actor_id=aid(actor), config=config).passphrase == "new-pass"

    def test_neither_argument_is_false(self) -> None:
        actor = create_core_actor(make_config(), uuid_email())
        assert actor.modify() is False

    def test_backend_failure_leaves_memory_untouched(self) -> None:
        actor = create_core_actor(make_config(), uuid_email(), passphrase="old-pass")
        actor.handle = MagicMock()
        actor.handle.modify.return_value = False
        assert actor.modify(passphrase="new-pass") is False
        assert actor.passphrase == "old-pass"

    def test_postgres_zero_rows_is_failure(self) -> None:
        from actingweb.db.postgresql.actor import DbActor

        cursor = MagicMock()
        cursor.rowcount = 0
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        ctx = MagicMock()
        ctx.__enter__.return_value = conn
        db = DbActor()
        db.handle = {"id": "gone"}
        with patch("actingweb.db.postgresql.actor.get_connection", return_value=ctx):
            assert db.modify(passphrase=b"x") is False
