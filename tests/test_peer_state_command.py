"""``actingweb-peer-state``: report and prune peer state written before 3.16.

Plan: thoughts/plans/2026-11-06-peer-authorisation-fixes.md, Phase 4. Real
storage; both backends through ``DATABASE_BACKEND``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest

from actingweb.attribute import Attributes
from actingweb.constants import PEER_PERMISSIONS_BUCKET
from actingweb.db.exceptions import DbError
from actingweb.maintenance import peer_state as command
from actingweb.subscription import Subscription
from actingweb.trust import Trust
from tests._adoption_helpers import aid, create_core_actor, make_config, uuid_email

STATE = "_callback_state"


@pytest.fixture
def config() -> Any:
    return make_config()


@pytest.fixture(autouse=True)
def _same_backend(config: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    # The command builds its own Config from the environment, as an operator
    # would run it: point it at the suite's backend.
    monkeypatch.setenv("DATABASE_BACKEND", config.database)


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = command.main([*argv, "--rps", "0"])
    return code, capsys.readouterr().out


def _hex() -> str:
    return uuid.uuid4().hex


class World:
    """An actor with a live peer (trust and a subscription it made) whose id
    contains ``:``, a live hex peer, and one row of every stale kind."""

    def __init__(self, config: Any) -> None:
        self.config = config
        self.actor = create_core_actor(config, uuid_email())
        self.id = aid(self.actor)
        self.live = f"urn:peer:{_hex()[:8]}"  # a peer id with ':'
        self.live_hex = _hex()
        self.gone = _hex()
        for peer in (self.live, self.live_hex):
            assert Trust(actor_id=self.id, peerid=peer, config=config).create(
                baseuri=f"https://p.example.test/{_hex()}",
                peer_type="urn:test",
                relationship="friend",
                secret=_hex(),
                approved=True,
                verified=True,
                peer_approved=True,
            )
            assert Subscription(
                actor_id=self.id,
                peerid=peer,
                subid=f"sub-{peer[-4:]}",
                callback=True,
                config=config,
            ).create(target="properties", granularity="high")
        now = datetime.now(UTC).isoformat()
        self.perms = Attributes(
            actor_id=self.id, bucket=PEER_PERMISSIONS_BUCKET, config=config
        )
        self.states = Attributes(actor_id=self.id, bucket=STATE, config=config)
        # Live rows, kept.
        for peer in (self.live, self.live_hex):
            assert self.perms.set_attr(
                name=f"{self.id}:{peer}", data={"fetched_at": now, "peer_id": peer}
            )
            assert self.states.set_attr(
                name=f"state:{peer}:sub-{peer[-4:]}", data={"version": 1}
            )
        assert Attributes(
            actor_id=self.id, bucket=f"remote:{self.live_hex}", config=config
        ).set_attr(name="x", data={"value": 1})

    def plant_stale(self) -> None:
        ahead = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        # A row for a peer with no trust (a ':' in the name must not split).
        assert self.perms.set_attr(
            name=f"{self.id}:{self.gone}", data={"fetched_at": ahead}
        )
        # A live peer's row stamped a day ahead.
        assert self.perms.set_attr(
            name=f"{self.id}:{self.live_hex}",
            data={"fetched_at": ahead, "peer_id": self.live_hex},
        )
        # Callback state for a subscription never made.
        assert self.states.set_attr(name=f"pending:{self.gone}:forged", data=[1])
        # Peer data for a peer with no trust; and one this library never names.
        assert Attributes(
            actor_id=self.id, bucket=f"remote:{self.gone}", config=self.config
        ).set_attr(name="x", data={"value": 1})
        assert Attributes(
            actor_id=self.id, bucket="remote:not-a-peer-id", config=self.config
        ).set_attr(name="x", data={"value": 1})

    def permission_names(self) -> set[str]:
        return set(self.perms.get_bucket() or {})

    def state_names(self) -> set[str]:
        return set(self.states.get_bucket() or {})

    def has_bucket(self, bucket: str) -> bool:
        return bool(
            Attributes(actor_id=self.id, bucket=bucket, config=self.config).get_bucket()
        )


class TestReport:
    def test_nothing_stale_exits_0(self, config: Any, capsys: Any) -> None:
        w = World(config)
        code, out = _run(capsys, "report", w.id)
        assert code == 0
        assert "No peer state to remove." in out

    def test_every_kind_is_reported_and_nothing_changes(
        self, config: Any, capsys: Any
    ) -> None:
        w = World(config)
        w.plant_stale()
        code, out = _run(capsys, "report", w.id)
        assert code == 1
        assert f"peer-permissions\t{PEER_PERMISSIONS_BUCKET}\t{w.id}:{w.gone}" in out
        assert (
            f"future-permissions\t{PEER_PERMISSIONS_BUCKET}\t{w.id}:{w.live_hex}" in out
        )
        assert f"callback-state\t{STATE}\tpending:{w.gone}:forged" in out
        assert f"remote-data\tremote:{w.gone}" in out
        assert "remote-unknown\tremote:not-a-peer-id" in out
        # The live rows are not listed.
        assert f"{w.id}:{w.live}\n" not in out
        assert f"state:{w.live}" not in out
        assert f"remote:{w.live_hex}\t" not in out
        # Nothing changed.
        assert f"{w.id}:{w.gone}" in w.permission_names()
        assert w.has_bucket(f"remote:{w.gone}")

    def test_an_actor_id_limits_the_run(self, config: Any, capsys: Any) -> None:
        w = World(config)
        other = World(config)
        other.plant_stale()
        code, out = _run(capsys, "report", w.id)
        assert code == 0 and other.id not in out

    def test_an_unreadable_store_exits_2(self, config: Any, capsys: Any) -> None:
        w = World(config)
        with patch.object(
            command, "scan_actor", side_effect=command.StoreUnavailable("down")
        ):
            code = command.main(["report", w.id])
        assert code == 2

    def test_a_read_fault_raises_store_unavailable(self, config: Any) -> None:
        w = World(config)
        with (
            patch(
                "actingweb.db.get_trust_list",
                side_effect=DbError("trust list fetch", w.id),
            ),
            pytest.raises(command.StoreUnavailable),
        ):
            command.scan_actor(config, w.id, command.RateLimiter(0))


class TestPrune:
    def test_a_dry_run_changes_nothing(self, config: Any, capsys: Any) -> None:
        w = World(config)
        w.plant_stale()
        code, out = _run(capsys, "prune", w.id)
        assert code == 1 and "Dry run: would remove 4" in out
        assert f"{w.id}:{w.gone}" in w.permission_names()

    def test_apply_removes_the_stale_and_keeps_the_live(
        self, config: Any, capsys: Any
    ) -> None:
        w = World(config)
        w.plant_stale()
        code, out = _run(capsys, "prune", w.id, "--apply")
        assert code == 1
        assert "Restart the application's processes" in out
        assert w.permission_names() == {f"{w.id}:{w.live}"}
        assert w.state_names() == {
            f"state:{w.live}:sub-{w.live[-4:]}",
            f"state:{w.live_hex}:sub-{w.live_hex[-4:]}",
        }
        assert not w.has_bucket(f"remote:{w.gone}")
        assert w.has_bucket(f"remote:{w.live_hex}")
        assert w.has_bucket("remote:not-a-peer-id")
        # A second run finds only what it never removes.
        code, out = _run(capsys, "report", w.id)
        # Only an unknown bucket remains: information, not a finding.
        assert code == 0 and "remote-unknown" in out and "remote-data" not in out

    def test_a_delete_fault_exits_2(self, config: Any, capsys: Any) -> None:
        from actingweb.db import get_attribute

        w = World(config)
        w.plant_stale()
        with patch.object(
            type(get_attribute(config)),
            "delete_attr",
            side_effect=DbError("attribute delete", w.id),
        ):
            code = command.main(["prune", w.id, "--apply", "--rps", "0"])
        assert code == 2
        assert f"{w.id}:{w.gone}" in w.permission_names()


class TestThePermissionSenderLogsSuccess:
    """Found while writing the Phase 4 integration test: the sender read a
    204 (an empty answer) as a failure and logged a WARNING for it."""

    def test_an_empty_answer_is_not_a_failure(
        self, config: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        from actingweb.trust_permissions import TrustPermissions, TrustPermissionStore

        store = TrustPermissionStore(config)
        proxy = patch("actingweb.aw_proxy.AwProxy").start()
        try:
            proxy.return_value.trust = {"baseuri": "https://p.example.test/p"}
            proxy.return_value.create_resource.return_value = {}
            with caplog.at_level(logging.WARNING, logger="actingweb.trust_permissions"):
                store._notify_peer(  # noqa: SLF001
                    TrustPermissions(actor_id="a", peer_id="p", trust_type="friend")
                )
        finally:
            patch.stopall()
        assert not [r for r in caplog.records if "Failed to notify" in r.getMessage()]


class TestAllPermissions:
    """Verification of 2026-11-08, Issue 5: a forged copy for a trusted
    peer is removed only with --all-permissions."""

    def test_a_live_copy_is_listed_and_removed_only_on_request(
        self, config: Any, capsys: Any
    ) -> None:
        w = World(config)
        code, out = _run(capsys, "report", w.id)
        assert code == 0 and "permissions-copy" not in out
        code, out = _run(capsys, "prune", w.id, "--all-permissions", "--apply")
        assert code == 1 and "permissions-copy" in out
        assert w.permission_names() == set()
