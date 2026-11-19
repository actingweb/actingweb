"""``actingweb.maintenance.mark_actors_vouched``: the operator's opt-out of the 4.0
clean-slate adoption for actors known to be legitimate."""

from typing import Any
from unittest.mock import patch

import pytest

from actingweb.actor import Actor
from actingweb.maintenance import mark_actors_vouched as script
from tests._adoption_helpers import (
    aid,
    create_core_actor,
    istore,
    make_config,
    uuid_email,
)


def _marker(config, actor_id: str):
    return istore(Actor(actor_id=actor_id, config=config)).auth_method


class TestMarkActors:
    def test_dry_run_writes_nothing(self) -> None:
        config = make_config()
        creator = uuid_email()
        legacy = create_core_actor(config, creator, auth_method=None)
        counts = script.mark_actors(config, creator=creator, dry_run=True)
        assert counts["marked"] == 1
        assert _marker(config, aid(legacy)) is None

    def test_marks_unmarked_and_skips_vouched_and_factory(self) -> None:
        config = make_config()
        legacy_creator = uuid_email()
        legacy = create_core_actor(config, legacy_creator, auth_method=None)
        script.mark_actors(config, creator=legacy_creator, marker="operator")
        assert _marker(config, aid(legacy)) == "operator"

        for method in ("app", "factory"):
            creator = uuid_email()
            actor = create_core_actor(config, creator, auth_method=method)
            counts = script.mark_actors(config, creator=creator)
            assert counts["marked"] == 0 and counts["skipped"] == 1
            assert _marker(config, aid(actor)) == method

    def test_include_factory_remarks_factory_actors(self) -> None:
        config = make_config()
        creator = uuid_email()
        actor = create_core_actor(config, creator, auth_method="factory")
        script.mark_actors(config, creator=creator, include_factory=True)
        assert _marker(config, aid(actor)) == "operator"

    def test_creator_filter_restricts_the_run(self) -> None:
        config = make_config()
        mine, other = uuid_email(), uuid_email()
        a = create_core_actor(config, mine, auth_method=None)
        b = create_core_actor(config, other, auth_method=None)
        script.mark_actors(config, creator=mine)
        assert _marker(config, aid(a)) == "operator"
        assert _marker(config, aid(b)) is None

    def test_start_after_skips_earlier_ids(self) -> None:
        config = make_config()
        creator = uuid_email()
        actor = create_core_actor(config, creator, auth_method=None)
        counts = script.mark_actors(config, creator=creator, start_after="z" * 40)
        assert counts["scanned"] == 0
        assert _marker(config, aid(actor)) is None


class TestStreamedCollection:
    """The actor list is streamed through ``iter_rows`` (4.0)."""

    def _fake_list(self, rows: list[dict[str, str]]) -> tuple[Any, list[Any]]:
        calls: list[Any] = []

        class _List:
            def iter_rows(self, **kwargs: Any) -> Any:
                calls.append(kwargs)
                yield from rows

        return _List(), calls

    def test_rate_limit_parses_and_reaches_a_consistent_scan(self) -> None:
        fake, calls = self._fake_list([])
        with patch("actingweb.db.get_actor_list", lambda config: fake):
            assert script.main(["--dry-run", "--rate-limit", "50"]) == 0
        assert calls == [{"consistent": True, "rate_limit": 50.0}]

    def test_filters_apply_at_collection_and_order_is_sorted(self) -> None:
        rows = [
            {"id": "c3", "creator": "Me@Example.com"},
            {"id": "a1", "creator": "me@example.com"},
            {"id": "b2", "creator": "other@example.com"},
            {"id": "d4", "creator": "me@example.com"},
        ]
        fake, _calls = self._fake_list(rows)
        seen: list[str] = []
        with (
            patch("actingweb.db.get_actor_list", lambda config: fake),
            patch.object(
                script,
                "_mark_one",
                lambda config, actor_id, **kw: seen.append(actor_id),
            ),
        ):
            counts = script.mark_actors(
                make_config(), creator="ME@example.com", start_after="a1"
            )
        assert seen == ["c3", "d4"]
        assert counts["scanned"] == 2


class TestEmailAsCreator:
    """``--email-as-creator`` (4.0): an actor whose stored email differs from
    its creator gets the creator as its email before it is marked, so the
    creator-to-email sweep has nothing to move it to."""

    def _differing(self, config: Any, creator: str) -> Any:
        from actingweb.db import get_attribute

        actor = create_core_actor(config, creator, auth_method=None)
        get_attribute(config).set_attr(
            aid(actor), "_internal", "email", "planted@example.com"
        )
        return actor

    def test_with_the_option_the_email_becomes_the_creator(self) -> None:
        config = make_config()
        creator = uuid_email()
        actor = self._differing(config, creator)
        counts = script.mark_actors(config, creator=creator, email_as_creator=True)
        assert counts["marked"] == 1 and counts["email_reset"] == 1
        loaded = Actor(actor_id=aid(actor), config=config)
        assert istore(loaded).auth_method == "operator"
        assert istore(loaded).email == creator
        assert loaded.creator == creator

    @pytest.mark.parametrize("kind", ["provider-id", "default"])
    def test_a_creator_that_is_not_an_address_keeps_its_email(self, kind: str) -> None:
        """The default creator's email is what ``resolve
        --default-creator-to-email`` moves it to; a provider id's is not the
        tool's to drop."""
        config = make_config()
        creator = (
            f"github:{uuid_email().split('@')[0]}"
            if kind == "provider-id"
            else "creator"
        )
        actor = self._differing(config, creator)
        counts = script.mark_actors(config, creator=creator, email_as_creator=True)
        assert counts["email_reset"] == 0 and counts["email_differs"] >= 1
        loaded = Actor(actor_id=aid(actor), config=config)
        assert istore(loaded).email == "planted@example.com"

    def test_without_it_the_email_is_left_and_counted(self) -> None:
        config = make_config()
        creator = uuid_email()
        actor = self._differing(config, creator)
        counts = script.mark_actors(config, creator=creator)
        assert counts["marked"] == 1 and counts["email_differs"] == 1
        loaded = Actor(actor_id=aid(actor), config=config)
        assert istore(loaded).email == "planted@example.com"
        assert loaded.creator == creator

    def test_a_dry_run_counts_the_reset_and_writes_nothing(self) -> None:
        config = make_config()
        creator = uuid_email()
        actor = self._differing(config, creator)
        counts = script.mark_actors(
            config, creator=creator, email_as_creator=True, dry_run=True
        )
        assert counts["email_reset"] == 1
        assert istore(Actor(actor_id=aid(actor), config=config)).email == (
            "planted@example.com"
        )


class TestScopeAndDetail:
    """4.0.0rc1 adoption findings: system actors are never marked (AC-2), a dry
    run shows what it would mark on stdout (AC-3), and ``--ids-file`` limits
    the run (AC-4)."""

    def _fake_list(self, rows: list[dict[str, str]]) -> Any:
        class _List:
            def iter_rows(self, **kwargs: Any) -> Any:
                yield from rows

        return _List()

    def _ids_file(self, tmp_path: Any, ids: list[str]) -> str:
        path = tmp_path / "ids.txt"
        path.write_text("\n".join(ids) + "\n")
        return str(path)

    def test_system_actors_are_never_marked(self, tmp_path: Any) -> None:
        rows = [
            {"id": "_actingweb_oauth2", "creator": "oauth2-system"},
            {"id": "_actingweb_system", "creator": "system"},
            {"id": "u1", "creator": "me@example.com"},
        ]
        seen: list[str] = []
        with (
            patch("actingweb.db.get_actor_list", lambda config: self._fake_list(rows)),
            patch.object(
                script,
                "_mark_one",
                lambda config, actor_id, **kw: seen.append(actor_id),
            ),
        ):
            counts = script.mark_actors(make_config(), ids=["_actingweb_oauth2", "u1"])
            assert seen == ["u1"]
            assert counts["system"] == 1
            all_counts = script.mark_actors(make_config())
        assert "_actingweb_oauth2" not in seen[1:] and "_actingweb_system" not in seen
        assert all_counts["system"] == 2

    def test_dry_run_prints_marker_and_hides_addresses(self, capsys: Any) -> None:
        config = make_config()
        creator = uuid_email()
        actor = create_core_actor(config, creator, auth_method=None)
        script.mark_actors(config, creator=creator, dry_run=True)
        out = capsys.readouterr().out
        line = next(ln for ln in out.splitlines() if aid(actor) in ln)
        assert "marker=-" in line
        assert creator not in out

    def test_show_addresses_prints_creator_and_email(self, capsys: Any) -> None:
        config = make_config()
        creator = uuid_email()
        actor = create_core_actor(config, creator, auth_method="factory")
        script.mark_actors(
            config,
            creator=creator,
            dry_run=True,
            include_factory=True,
            show_addresses=True,
        )
        out = capsys.readouterr().out
        line = next(ln for ln in out.splitlines() if aid(actor) in ln)
        assert "marker=factory" in line
        assert f"creator={creator}" in line
        assert "email=" in line

    def test_ids_file_limits_the_run(self, tmp_path: Any) -> None:
        config = make_config()
        mine, other = uuid_email(), uuid_email()
        a = create_core_actor(config, mine, auth_method=None)
        b = create_core_actor(config, other, auth_method=None)
        counts = script.mark_actors(config, ids=[aid(a)])
        assert counts["scanned"] == 1 and counts["marked"] == 1
        assert _marker(config, aid(a)) == "operator"
        assert _marker(config, aid(b)) is None

    def test_a_listed_id_not_in_the_store_is_counted_missing(
        self, tmp_path: Any
    ) -> None:
        rows = [{"id": "u1", "creator": "me@example.com"}]
        seen: list[str] = []
        with (
            patch("actingweb.db.get_actor_list", lambda config: self._fake_list(rows)),
            patch.object(
                script,
                "_mark_one",
                lambda config, actor_id, **kw: seen.append(actor_id),
            ),
        ):
            assert (
                script.main(
                    [
                        "--dry-run",
                        "--ids-file",
                        self._ids_file(tmp_path, ["u1", "gone"]),
                    ]
                )
                == 0
            )
            counts = script.mark_actors(make_config(), ids=["u1", "gone"])
        assert seen == ["u1", "u1"]
        assert counts["missing"] == 1

    def test_unreadable_ids_file_is_a_usage_error(self, tmp_path: Any) -> None:
        def _no_read(config: Any) -> Any:
            raise AssertionError("the store was read")

        with patch("actingweb.db.get_actor_list", _no_read):
            with pytest.raises(SystemExit) as exc:
                script.main(["--dry-run", "--ids-file", str(tmp_path / "nope.txt")])
        assert exc.value.code == 2

    def test_ids_file_and_creator_are_exclusive(self, tmp_path: Any) -> None:
        with pytest.raises(SystemExit) as exc:
            script.main(
                [
                    "--dry-run",
                    "--creator",
                    "me@example.com",
                    "--ids-file",
                    self._ids_file(tmp_path, ["u1"]),
                ]
            )
        assert exc.value.code == 2
