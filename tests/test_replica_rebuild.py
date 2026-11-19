"""``SubscriptionManager.rebuild_subscription`` and the owed-rebuild state
(thoughts/plans/2026-11-13-attribute-list-v2-port.md, Phase 3, outside-voice
findings): the attempt is reserved and throttled whether it succeeds or not,
the baseline is matched to a sequence that did not move, the sequence is never
moved backwards, a whole-target rebuild deletes what the baseline no longer
carries, and an entry that cannot be stored leaves the rebuild owed."""

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from actingweb.callback_processor import CallbackProcessor
from actingweb.interface.actor_interface import ActorInterface
from actingweb.interface.subscription_manager import SubscriptionManager
from actingweb.remote_storage import RemotePeerStore
from tests.mcp_token_double import make_config

ACTOR = "a" * 32
PEER = "b" * 32
SUB = "sub1"


class _Env:
    def __init__(self) -> None:
        self.config, self.store = make_config()
        self.core = MagicMock()
        self.core.id = ACTOR
        self.core.config = self.config
        self.manager = SubscriptionManager(self.core)
        self.processor = CallbackProcessor(actor=ActorInterface(self.core))
        self.replica = RemotePeerStore(
            ActorInterface(self.core), PEER, validate_peer_id=False
        )
        self.sequences: list[int] = [5]
        self.baselines: list[Any] = [{}]
        self.recorded = {"sequence": 0}
        self.proxy = MagicMock()
        self.proxy.trust = {"peerid": PEER}
        self.proxy.get_resource.side_effect = self._sequence
        self.sub = MagicMock(target="properties", subtarget="", resource="")

    def _sequence(self, path: str) -> dict[str, Any]:
        seq = self.sequences.pop(0) if len(self.sequences) > 1 else self.sequences[0]
        return {"sequence": seq}

    def _baseline(self, **_: Any) -> Any:
        return self.baselines.pop(0) if len(self.baselines) > 1 else self.baselines[0]

    def rebuild(self, **kwargs: Any) -> Any:
        def subscription(**_: Any) -> Any:
            # As the real class: the first read is served from a copy taken
            # at construction.
            sub_obj = MagicMock()
            snapshot = dict(self.recorded)
            sub_obj.get.side_effect = lambda: dict(snapshot)
            sub_obj.handle.modify.side_effect = lambda seqnr: self.recorded.update(
                sequence=seqnr
            )
            return sub_obj

        with (
            patch.object(
                self.manager, "get_callback_subscription", return_value=self.sub
            ),
            patch.object(self.manager, "_get_peer_proxy", return_value=self.proxy),
            patch.object(
                self.manager,
                "_fetch_and_transform_baseline",
                side_effect=self._baseline,
            ),
            patch("actingweb.subscription.Subscription", side_effect=subscription),
        ):
            return self.manager.rebuild_subscription(PEER, SUB, **kwargs)

    def owe(self, lists: list[str] | None = None) -> None:
        self.processor.settle_rebuild(PEER, SUB, rebuilt=False, lists=lists)


@pytest.fixture
def env() -> _Env:
    return _Env()


class TestReservation:
    def test_one_attempt_per_interval_even_when_it_fails(self, env, monkeypatch):
        env.owe(["notes"])
        env.proxy.get_resource.side_effect = lambda path: None  # fails
        first = env.rebuild()
        assert first.success is False and first.error_code == 502
        assert env.processor.rebuild_state(PEER, SUB)["owed"] is True
        # A second callback inside the interval does not rebuild again.
        second = env.rebuild()
        assert second.success is False and second.error_code == 429
        assert env.proxy.get_resource.call_count == 1
        real = time.time
        monkeypatch.setattr(
            "actingweb.callback_processor.time.time", lambda: real() + 61
        )
        env.rebuild()
        assert env.proxy.get_resource.call_count == 2

    def test_force_skips_the_interval(self, env):
        env.owe()
        env.rebuild()
        env.owe()
        assert env.rebuild().error_code == 429
        assert env.rebuild(force=True).success is True

    def test_two_concurrent_attempts_reserve_once(self, env):
        env.owe()
        assert env.processor.begin_rebuild(PEER, SUB) is True
        assert env.processor.begin_rebuild(PEER, SUB) is False

    def test_a_sync_runs_an_owed_rebuild(self, env):
        env.owe(["notes"])
        with (
            patch.object(
                env.manager, "get_callback_subscription", return_value=env.sub
            ),
            patch.object(env.manager, "rebuild_subscription") as rebuild,
        ):
            env.manager.sync_subscription(PEER, SUB)
        rebuild.assert_called_once()


class TestSequence:
    def test_a_moving_sequence_is_read_again(self, env):
        env.owe()
        env.sequences = [5, 6, 6, 6]
        env.baselines = [{"a": {"v": 1}}, {"a": {"v": 2}}]
        result = env.rebuild()
        assert result.success is True and result.final_sequence == 6
        assert env.replica.get_value("a") == {"v": 2}
        assert env.recorded["sequence"] == 6

    def test_a_sequence_that_keeps_moving_stays_owed(self, env):
        env.owe()
        env.sequences = [1, 2, 3, 4, 5, 6, 7]
        result = env.rebuild()
        assert result.success is False
        assert env.processor.rebuild_state(PEER, SUB)["owed"] is True

    def test_the_sequence_never_moves_backwards(self, env):
        env.owe()
        env.recorded["sequence"] = 9
        env.rebuild()
        assert env.recorded["sequence"] == 9


class TestWhatTheBaselineNoLongerCarries:
    def test_a_whole_target_rebuild_deletes_names_it_lacks(self, env):
        env.replica.set_value("kept", {"v": 1})
        env.replica.set_value("secret_note", {"v": 2})
        env.replica.set_list("gone", ["x"])
        env.replica.set_list("notes", ["old"])
        env.owe()
        env.baselines = [{"kept": {"v": 1}, "notes": {"_list": True, "items": ["new"]}}]
        assert env.rebuild().success is True
        assert env.replica.get_value("secret_note") is None
        assert env.replica.list_all_lists() == ["notes"]
        assert env.replica.get_list("notes") == ["new"]
        assert env.replica.get_value("kept") == {"v": 1}

    def test_a_subtarget_rebuild_deletes_only_its_subtarget(self, env):
        env.sub.subtarget = "notes"
        env.replica.set_list("notes", ["old"])
        env.replica.set_value("other", {"v": 1})
        env.owe(["notes"])
        env.baselines = [{}]
        env.rebuild()
        assert env.replica.list_all_lists() == []
        assert env.replica.get_value("other") == {"v": 1}

    def test_an_entry_that_cannot_be_stored_leaves_it_owed(self, env):
        env.config.list_item_max_bytes = 100
        env.owe()
        env.baselines = [{"big": {"_list": True, "items": ["x" * 500]}}]
        result = env.rebuild()
        assert result.success is False
        assert env.processor.rebuild_state(PEER, SUB)["owed"] is True


class TestALostMark:
    def test_a_mark_that_loses_still_rebuilds_and_is_recorded(self):
        config, _store = make_config()
        core = MagicMock()
        core.id = ACTOR
        core.config = config
        processor = CallbackProcessor(actor=ActorInterface(core))
        with patch.object(processor, "_mark_out_of_step", return_value=None):
            assert processor._mark_or_owe(  # noqa: SLF001
                PEER, SUB, {"version": 0}, 1, ["notes"]
            )
        state = processor.rebuild_state(PEER, SUB)
        assert state["owed"] and state["lists"] == ["notes"]

    def test_a_mark_that_faults_twice_still_rebuilds(self):
        from actingweb.db.exceptions import DbError

        config, _store = make_config()
        core = MagicMock()
        core.id = ACTOR
        core.config = config
        processor = CallbackProcessor(actor=ActorInterface(core))
        with (
            patch.object(processor, "_mark_out_of_step", return_value=None),
            patch.object(processor, "settle_rebuild", side_effect=DbError("x")),
        ):
            assert processor._mark_or_owe(  # noqa: SLF001
                PEER, SUB, {"version": 0}, 1, ["notes"]
            )


class TestAnotherTarget:
    def test_a_rebuild_of_another_target_deletes_no_property(self, env):
        env.replica.set_value("kept", {"v": 1})
        env.replica.set_list("notes", ["a"])
        env.sub.target = "resources"
        env.owe()
        env.baselines = [{}]
        env.rebuild()
        assert env.replica.get_value("kept") == {"v": 1}
        assert env.replica.list_all_lists() == ["notes"]


class TestVerification2:
    """Verification re-run 2 (findings 4, 5, 7, 9)."""

    def test_a_properties_rebuild_spares_a_bucket_another_target_stores_into(self, env):
        env.replica.set_value("from_resources", {"v": 1})
        env.owe()
        env.baselines = [{}]
        with patch(
            "actingweb.replica_revocation.stores_another_target", return_value=True
        ):
            env.rebuild()
        assert env.replica.get_value("from_resources") == {"v": 1}

    def test_revocation_of_a_shared_bucket_needs_a_dropped_pattern(self, env):
        from actingweb.peer_permissions import PeerPermissions
        from actingweb.replica_revocation import NotEvaluated, plan_cleanup

        env.config.auto_delete_on_revocation = True
        grant = PeerPermissions(
            actor_id=ACTOR,
            peer_id=PEER,
            properties={"patterns": ["memory_*"], "operations": ["read"]},
        )
        with (
            patch(
                "actingweb.replica_revocation.subscribes_to_properties",
                return_value=True,
            ),
            patch(
                "actingweb.replica_revocation.stores_another_target", return_value=True
            ),
        ):
            plan = plan_cleanup(env.config, ACTOR, env.replica, None, grant)
        # No old grant, so no dropped pattern: not evaluated, and it says so.
        assert isinstance(plan, NotEvaluated)

    @pytest.mark.parametrize("meanwhile", [9, 5, 3])
    def test_a_callback_processed_during_the_rebuild_leaves_it_owed(
        self, env, meanwhile
    ):
        """Above, at or below the baseline's sequence (5): any callback
        recorded while the rebuild ran may be applied twice or overwritten."""
        env.owe()
        env.recorded["sequence"] = 1

        def bump(**_: Any) -> Any:
            env.recorded["sequence"] = meanwhile
            return {}

        env.baselines = [{}]
        with patch.object(env, "_baseline", side_effect=bump):
            result = env.rebuild()
        assert result.success is False
        assert env.processor.rebuild_state(PEER, SUB)["owed"] is True

    def test_a_list_marked_during_the_rebuild_leaves_it_owed(self, env):
        env.owe(["a"])

        def mark(**_: Any) -> Any:
            env.processor.settle_rebuild(PEER, SUB, rebuilt=False, lists=["b"])
            return {}

        with patch.object(env, "_baseline", side_effect=mark):
            env.rebuild()
        assert env.processor.rebuild_state(PEER, SUB)["owed"] is True

    def test_a_lost_mark_releases_the_claim(self):
        config, _store = make_config()
        core = MagicMock()
        core.id = ACTOR
        core.config = config
        processor = CallbackProcessor(actor=ActorInterface(core))
        processor.settle_rebuild(PEER, SUB, rebuilt=False)
        row = processor._read_state_row(PEER, SUB)  # noqa: SLF001
        assert row is not None
        processor._cas_state(PEER, SUB, row, {**row, "claimed_seq": 10, "version": 50})  # noqa: SLF001
        with patch.object(processor, "_mark_out_of_step", return_value=None):
            processor._mark_or_owe(  # noqa: SLF001
                PEER, SUB, {"version": 0, "claimed_seq": 10}, 7, ["n"]
            )
        row = processor._read_state_row(PEER, SUB)  # noqa: SLF001
        assert row is not None and row["claimed_seq"] == 7


class TestVerification3:
    """Verification re-run 3 (OV3, the claim note)."""

    def test_a_dropped_batch_owes_what_it_deleted(self):
        from actingweb.callback_processor import _deleted_names

        assert sorted(
            _deleted_names(
                {
                    "foo": "",
                    "bar": None,
                    "keep": {"v": 1},
                    "notes": {"list": "notes", "operation": "delete_all"},
                    "list:old": "",
                }
            )
        ) == ["bar", "foo", "notes", "old"]
        assert _deleted_names("not a dict") == []

    def test_a_lost_mark_leaves_another_deliverys_claim_alone(self):
        config, _store = make_config()
        core = MagicMock()
        core.id = ACTOR
        core.config = config
        processor = CallbackProcessor(actor=ActorInterface(core))
        # Another delivery claimed through 20 after this batch's claim (10).
        processor.settle_rebuild(PEER, SUB, rebuilt=False)
        row = processor._read_state_row(PEER, SUB)  # noqa: SLF001
        assert row is not None
        processor._cas_state(PEER, SUB, row, {**row, "claimed_seq": 20, "version": 99})  # noqa: SLF001
        with patch.object(processor, "_mark_out_of_step", return_value=None):
            processor._mark_or_owe(  # noqa: SLF001
                PEER, SUB, {"version": 0, "claimed_seq": 10}, 7, ["n"]
            )
        row = processor._read_state_row(PEER, SUB)  # noqa: SLF001
        assert row is not None and row["claimed_seq"] == 20


class TestVerification4:
    """Verification re-run 4 (findings 1 and 2)."""

    def test_a_callback_recorded_during_the_rebuild_is_never_written_back(self, env):
        env.owe()

        def bump(**_: Any) -> Any:
            env.recorded["sequence"] = 9
            return {}

        with patch.object(env, "_baseline", side_effect=bump):
            result = env.rebuild()
        assert env.recorded["sequence"] == 9
        assert result.success is False

    def test_a_skipped_subtarget_rebuild_deletes_nothing(self, env):
        env.sub.subtarget = "notes"
        env.replica.set_list("notes", ["kept"])
        env.owe(["notes"])
        env.baselines = [{}]
        with patch(
            "actingweb.replica_revocation.subscribes_to_whole_properties",
            return_value=True,
        ):
            env.rebuild(force=True)
        assert env.replica.get_list("notes") == ["kept"]


class TestVerification4Covered:
    """Verification re-run 4 (finding 3, the dropped batch's level, the
    tool's owed rebuild)."""

    def test_a_polled_whole_target_subscription_covers_too(self):
        from actingweb.replica_revocation import subscribes_to_whole_properties

        listing = MagicMock()
        listing.fetch.return_value = [
            {
                "peerid": PEER,
                "callback": True,
                "target": "properties",
                "granularity": "none",
            }
        ]
        with patch("actingweb.db.get_subscription_list", return_value=listing):
            # Polled by sync_peer into the same replica: covering it is what
            # keeps a pushed subtarget change from being stored twice.
            assert subscribes_to_whole_properties(MagicMock(), ACTOR, PEER) is True

    def test_deleting_a_covering_subscription_owes_the_covered_a_rebuild(self):
        from actingweb.actor import Actor

        actor = object.__new__(Actor)
        actor.id = ACTOR
        actor.config = MagicMock()
        actor.subs_list = None
        rows = [
            {"peerid": PEER, "subscriptionid": "whole", "target": "properties"},
            {
                "peerid": PEER,
                "subscriptionid": "one",
                "target": "properties",
                "subtarget": "notes",
            },
        ]
        sub = MagicMock()
        sub.delete.return_value = True
        with (
            patch.object(actor, "get_subscriptions", return_value=rows),
            patch("actingweb.subscription.Subscription", return_value=sub),
            patch.object(actor, "_owe_covered_rebuilds") as owe,
            patch("actingweb.remote_storage.RemotePeerStore"),
            patch("actingweb.interface.actor_interface.ActorInterface"),
        ):
            assert actor.delete_subscription(PEER, "whole", callback=True)
        owe.assert_called_once()
        assert [s["subscriptionid"] for s in owe.call_args.args[1]] == ["one"]

    @pytest.mark.parametrize(
        "processing,owed", [("unconfigured", True), ("hooks only", False)]
    )
    def test_without_a_replica_deleting_a_covering_subscription_owes_nothing(
        self, processing: str, owed: bool
    ) -> None:
        """Re-run 4 (Issue 4): with no replica there is nothing to rebuild;
        a hooks-only subscriber's next diff was told as a resync instead.
        Re-run 5 (Issue 5): with no processing configuration a poll keeps a
        replica (the defaults), so the covered ones are owed, as before."""
        from actingweb.actor import Actor
        from actingweb.subscription_config import SubscriptionProcessingConfig

        actor = object.__new__(Actor)
        actor.id = ACTOR
        actor.config = MagicMock()
        actor.config._subscription_config = (
            None
            if processing == "unconfigured"
            else SubscriptionProcessingConfig(enabled=True, auto_storage=False)
        )
        actor.subs_list = None
        rows = [
            {"peerid": PEER, "subscriptionid": "whole", "target": "properties"},
            {
                "peerid": PEER,
                "subscriptionid": "one",
                "target": "properties",
                "subtarget": "notes",
            },
        ]
        sub = MagicMock()
        sub.delete.return_value = True
        with (
            patch.object(actor, "get_subscriptions", return_value=rows),
            patch("actingweb.subscription.Subscription", return_value=sub),
            patch.object(actor, "_owe_covered_rebuilds") as owe,
            patch("actingweb.remote_storage.RemotePeerStore"),
            patch("actingweb.interface.actor_interface.ActorInterface"),
        ):
            assert actor.delete_subscription(PEER, "whole", callback=True)
        assert owe.called is owed

    def test_a_subtarget_subscriptions_dropped_batch_owes_no_names(self, env):
        env.sub.subtarget = "profile"
        with patch.object(
            env.processor._actor.subscriptions,  # noqa: SLF001
            "get_callback_subscription",
            return_value=env.sub,
        ):
            assert env.processor._whole_target(PEER, SUB) is False  # noqa: SLF001
        env.sub.subtarget = ""
        env.sub.resource = ""
        with patch.object(
            env.processor._actor.subscriptions,  # noqa: SLF001
            "get_callback_subscription",
            return_value=env.sub,
        ):
            assert env.processor._whole_target(PEER, SUB) is True  # noqa: SLF001

    def test_the_tool_owes_a_rebuild_after_deleting_a_damaged_replica(self, env):
        from actingweb.maintenance.verify_property_lists import _owe_replica_rebuild

        listing = MagicMock()
        listing.fetch.return_value = [
            {
                "peerid": PEER,
                "subscriptionid": SUB,
                "callback": True,
                "target": "properties",
            },
            {
                "peerid": PEER,
                "subscriptionid": "other",
                "callback": True,
                "target": "properties",
                "subtarget": "email",
            },
            {
                "peerid": PEER,
                "subscriptionid": "meta",
                "callback": True,
                "target": "meta",
            },
        ]
        lst = MagicMock(actor_id=ACTOR, config=env.config)
        lst.name = "notes"
        with patch("actingweb.db.get_subscription_list", return_value=listing):
            assert _owe_replica_rebuild(lst, f"remote:{PEER}") == 1
        state = env.processor.rebuild_state(PEER, SUB)
        assert state["owed"] and state["lists"] == ["notes"]


class TestVerification4Fetch:
    """Verification re-run 4: an array baseline asks the publisher."""

    @pytest.mark.parametrize(
        ("meta", "code", "expected"),
        [
            ({"description": ""}, 200, {"notes": {"_list": True, "items": [1]}}),
            ({"error": {"code": 404}}, 404, [1]),
            ({"error": {"code": 500}}, 500, None),
        ],
    )
    def test_list_scalar_or_failure(self, env, meta, code, expected):
        proxy = MagicMock()
        proxy.last_response_redirected = False

        def get(path: str) -> Any:
            if path.endswith("/metadata"):
                proxy.last_response_code = code
                return meta
            proxy.last_response_code = 200
            return [1]

        proxy.get_resource.side_effect = get
        with patch.object(env.manager, "_get_peer_proxy", return_value=proxy):
            got = env.manager._fetch_and_transform_baseline(  # noqa: SLF001
                PEER, "properties", subtarget="notes"
            )
        assert got == expected


def test_a_known_list_needs_no_probe() -> None:
    env = _Env()
    proxy = MagicMock()
    proxy.get_resource.return_value = [1]
    proxy.last_response_code = 200
    with patch.object(env.manager, "_get_peer_proxy", return_value=proxy):
        got = env.manager._fetch_and_transform_baseline(  # noqa: SLF001
            PEER, "properties", subtarget="notes", known_list=True
        )
    assert got == {"notes": {"_list": True, "items": [1]}}
    proxy.get_resource.assert_called_once()


class TestRealSubscription:
    """The rebuild's sequence check against the real ``Subscription`` (its
    first read is cached at construction), on DynamoDB Local: the double that
    re-read on every call hid a regression (verification re-run 4)."""

    def test_a_callback_recorded_during_the_rebuild_is_kept(self, env):
        import os
        import uuid

        from actingweb.subscription import Subscription

        if os.getenv("DATABASE_BACKEND", "dynamodb") != "dynamodb":
            pytest.skip("DynamoDB-only test")
        actor_id = f"rebuildseq-{uuid.uuid4().hex}"
        env.core.id = actor_id
        processor = CallbackProcessor(actor=ActorInterface(env.core))
        env.processor = processor
        row = Subscription(
            actor_id=actor_id,
            peerid=PEER,
            subid=SUB,
            callback=True,
            config=env.config,
        )
        assert row.create(target="properties", granularity="high", seqnr=1)
        try:
            processor.settle_rebuild(PEER, SUB, rebuilt=False)

            def callback_meanwhile(**_: Any) -> Any:
                Subscription(
                    actor_id=actor_id,
                    peerid=PEER,
                    subid=SUB,
                    callback=True,
                    config=env.config,
                ).handle.modify(seqnr=9)  # type: ignore[union-attr]
                return {}

            env.sequences = [5]
            with (
                patch.object(
                    env.manager, "get_callback_subscription", return_value=env.sub
                ),
                patch.object(env.manager, "_get_peer_proxy", return_value=env.proxy),
                patch.object(
                    env.manager,
                    "_fetch_and_transform_baseline",
                    side_effect=callback_meanwhile,
                ),
            ):
                result = env.manager.rebuild_subscription(PEER, SUB)
            fresh = Subscription(
                actor_id=actor_id,
                peerid=PEER,
                subid=SUB,
                callback=True,
                config=env.config,
            )
            assert fresh.get()["sequence"] == 9
            assert result.success is False
            assert processor.rebuild_state(PEER, SUB)["owed"] is True
        finally:
            row.delete()


def test_a_subtarget_answering_404_is_gone() -> None:
    env = _Env()
    proxy = MagicMock()
    proxy.last_response_redirected = False

    def get(path: str) -> Any:
        proxy.last_response_code = 404
        return {"error": {"code": 404}}

    proxy.get_resource.side_effect = get
    with patch.object(env.manager, "_get_peer_proxy", return_value=proxy):
        got = env.manager._fetch_and_transform_baseline(  # noqa: SLF001
            PEER, "properties", subtarget="notes"
        )
    assert got == {"notes": ""}


@pytest.mark.parametrize(
    ("body", "raw", "code", "ctype", "redirected", "expected"),
    [
        ({}, b"plain text", 200, "application/json", False, "plain text"),
        ({}, b"", 200, "application/json", False, {"notes": ""}),
        ({}, b"{}", 200, "application/json", False, {"notes": ""}),
        ({}, b"{ \n }", 200, "application/json", False, {"notes": ""}),
        (0, b"0", 200, "application/json", False, 0),
        (False, b"false", 200, "application/json", False, False),
        ({"v": 1}, b'{"v": 1}', 200, "application/json", False, {"v": 1}),
        ({"error": {"code": 500}}, b"", 500, "", False, None),
        ({"error": {"code": 408}}, b"", 408, "", False, None),
        # A login page behind a proxy is not the value (outside voice,
        # iteration 26): a redirect followed, or not the publisher's JSON.
        ({}, b"<html>sign in</html>", 200, "text/html", True, None),
        ({}, b"<html>sign in</html>", 200, "text/html", False, None),
        # Outside voice, iteration 27: the media type exactly, any case,
        # parameters ignored.
        ({}, b"blue", 200, "Application/JSON; charset=utf-8", False, "blue"),
        ({}, b"blue", 200, "application/jsonx", False, None),
        ({}, b"blue", 200, "", False, None),
        # Specification 1.5: a value that is not JSON is labelled
        # text/plain by a 4.0 publisher; still not through a redirect.
        ({}, b"blue", 200, "text/plain; charset=utf-8", False, "blue"),
        ({}, b"blue", 200, "Text/Plain", False, "blue"),
        ({}, b"blue", 200, "text/plain", True, None),
    ],
)
def test_a_single_propertys_baseline_is_what_the_wire_says(
    body: Any, raw: bytes, code: int, ctype: str, redirected: bool, expected: Any
) -> None:
    """Verification re-run 5, the owner's decision (the spec reads
    properties as untyped values): text is text, an empty body is empty, a
    falsy value is a value, a non-2xx is a failed fetch."""
    env = _Env()
    proxy = MagicMock()
    proxy.get_resource.return_value = body
    proxy.last_response_code = code
    proxy.last_response_message = raw
    proxy.last_response_content_type = ctype
    proxy.last_response_redirected = redirected
    with patch.object(env.manager, "_get_peer_proxy", return_value=proxy):
        got = env.manager._fetch_and_transform_baseline(  # noqa: SLF001
            PEER, "properties", subtarget="notes"
        )
    assert got == expected


class TestIteration27OutsideVoice:
    """Outside voice on iteration 27: a redirect never decides gone or a
    list."""

    def test_a_404_reached_through_a_redirect_is_a_failed_fetch(self, env):
        proxy = MagicMock()
        proxy.last_response_redirected = True

        def get(path: str) -> Any:
            proxy.last_response_code = 404
            return {"error": {"code": 404}}

        proxy.get_resource.side_effect = get
        with patch.object(env.manager, "_get_peer_proxy", return_value=proxy):
            got = env.manager._fetch_and_transform_baseline(  # noqa: SLF001
                PEER, "properties", subtarget="notes"
            )
        assert got is None

    @pytest.mark.parametrize(
        ("meta", "redirected"),
        [({}, False), ({"description": ""}, True)],
    )
    def test_a_metadata_answer_that_is_not_the_publishers_confirms_nothing(
        self, env, meta, redirected
    ):
        proxy = MagicMock()
        proxy.last_response_redirected = False

        def get(path: str) -> Any:
            if path.endswith("/metadata"):
                proxy.last_response_code = 200
                proxy.last_response_redirected = redirected
                return meta
            proxy.last_response_code = 200
            return [1]

        proxy.get_resource.side_effect = get
        with patch.object(env.manager, "_get_peer_proxy", return_value=proxy):
            got = env.manager._fetch_and_transform_baseline(  # noqa: SLF001
                PEER, "properties", subtarget="notes"
            )
        assert got is None


class TestVerification2026_11_16:
    """thoughts/verifications/2026-11-16-spec-1-5-3.md (B1): a rebuild that
    settled returns the baseline it applied, for the callback that ran it to
    tell the hooks; one that did not settle returns none, and the rebuild
    itself tells no hook (every path would, before it knows it settled)."""

    def test_a_settled_rebuild_returns_its_baseline(self, env: _Env) -> None:
        env.baselines = [{"status": "paid"}]
        result = env.rebuild(force=True)
        assert result.success
        assert result.baseline == {"status": "paid"}

    def test_an_unsettled_rebuild_returns_no_baseline(self, env: _Env) -> None:
        env.sequences = [5, 6, 7, 8, 9, 10]  # keeps moving: stays owed
        env.baselines = [{"status": "paid"}]
        result = env.rebuild(force=True)
        assert not result.success
        assert result.baseline is None

    def test_the_rebuild_itself_tells_no_hook(self, env: _Env) -> None:
        from actingweb.subscription_config import SubscriptionProcessingConfig

        seen: list[Any] = []
        config = SubscriptionProcessingConfig(
            enabled=True,
            subscription_data_hooks={"*": [lambda *a: seen.append(a)]},
        )
        env.baselines = [{"status": "paid"}]
        assert env.rebuild(config=config, force=True).success
        assert seen == []


# -- a poll that replaced the replica tells the data hooks (4.0) ------------


def _hooked(seen: list[Any], **kwargs: Any) -> Any:
    from actingweb.subscription_config import SubscriptionProcessingConfig

    return SubscriptionProcessingConfig(
        enabled=True,
        subscription_data_hooks={"*": [lambda *a: seen.append(a[1:])]},
        **kwargs,
    )


def _poll(env: _Env, config: Any, diffs: list[dict[str, Any]], *, loop: bool) -> Any:
    """``sync_subscription`` (or its async twin) against ``env``: the
    publisher answers ``diffs`` at sequence 5, baselines come from
    ``env.baselines``."""
    import asyncio
    from unittest.mock import AsyncMock

    def answer(path: str = "") -> dict[str, Any]:
        seq = env.sequences.pop(0) if len(env.sequences) > 1 else env.sequences[0]
        return {"sequence": seq, "data": list(diffs)}

    env.proxy.get_resource.side_effect = answer
    env.proxy.get_resource_async = AsyncMock(side_effect=answer)
    env.proxy.change_resource_async = AsyncMock(return_value={})

    def subscription(**_: Any) -> Any:
        sub_obj = MagicMock()
        snapshot = dict(env.recorded)
        sub_obj.get.side_effect = lambda: dict(snapshot)
        sub_obj.handle.modify.side_effect = lambda seqnr: env.recorded.update(
            sequence=seqnr
        )
        return sub_obj

    with (
        patch.object(env.manager, "get_callback_subscription", return_value=env.sub),
        patch.object(env.manager, "_get_peer_proxy", return_value=env.proxy),
        patch.object(
            env.manager, "_fetch_and_transform_baseline", side_effect=env._baseline
        ),
        patch.object(
            env.manager,
            "_fetch_and_transform_baseline_async",
            AsyncMock(side_effect=env._baseline),
        ),
        patch("actingweb.subscription.Subscription", side_effect=subscription),
    ):
        if not loop:
            return env.manager.sync_subscription(PEER, SUB, config=config)

        async def run() -> Any:
            from actingweb.handlers import callbacks

            result = await env.manager.sync_subscription_async(PEER, SUB, config=config)
            await asyncio.gather(*list(callbacks._HOOK_TASKS))
            return result

        return asyncio.run(run())


_OUT_OF_STEP = MagicMock(out_of_step={"list": "notes", "operation": "insert"})


class TestAPollTellsTheDataHooks:
    """thoughts/plans/2026-11-16-3-16-pre-validation-fixes.md, Phase 2: a
    poll that replaced the replica from a baseline calls the data hooks once
    with it, as ``"resync"``, whichever path fetched the baseline."""

    @pytest.mark.parametrize("loop", [False, True], ids=["sync", "async"])
    @pytest.mark.parametrize("path", ["owed", "marker", "out of step", "none applied"])
    def test_a_poll_that_replaced_the_replica_tells_the_data_hooks(
        self, env: _Env, path: str, loop: bool
    ) -> None:
        seen: list[Any] = []
        env.baselines = [{"status": "paid"}]
        diffs: list[dict[str, Any]] = []
        config = _hooked(seen)
        if path == "owed":
            env.owe(["notes"])
        elif path == "marker":
            diffs = [{"sequence": 5, "type": "resync", "url": "https://p/x"}]
        elif path == "out of step":
            # No sequence tracking: the diff that could not be applied told
            # no hook, so the baseline is the first the application hears.
            config = _hooked(seen, auto_sequence=False)
            diffs = [{"sequence": 5, "data": {"notes": {"operation": "insert"}}}]
        elif path == "none applied":
            env.recorded["sequence"] = 5
            diffs = [{"sequence": 3, "data": {"old": 1}}]
        with patch.object(
            RemotePeerStore, "apply_callback_data", return_value=_OUT_OF_STEP
        ):
            result = _poll(env, config, diffs, loop=loop)
        assert result.success
        assert seen == [(PEER, "properties", {"status": "paid"}, 5, "resync")]

    def test_a_polled_rebuild_that_did_not_settle_tells_no_hook(
        self, env: _Env
    ) -> None:
        seen: list[Any] = []
        env.owe(["notes"])
        env.sequences = [5, 6, 7, 8, 9, 10]  # keeps moving: stays owed
        env.baselines = [{"status": "paid"}]
        result = _poll(env, _hooked(seen), [], loop=False)
        assert not result.success
        assert seen == []

    def test_the_async_poll_runs_a_coroutine_hook_on_its_loop(self, env: _Env) -> None:
        import asyncio

        from actingweb.subscription_config import SubscriptionProcessingConfig

        loops: list[Any] = []
        types: list[str] = []

        async def hook(*args: Any) -> None:
            loops.append(asyncio.get_running_loop())
            types.append(args[-1])

        config = SubscriptionProcessingConfig(
            enabled=True, subscription_data_hooks={"properties": [hook]}
        )
        env.owe(["notes"])
        env.baselines = [{"status": "paid"}]
        callers: list[Any] = []
        real_run = asyncio.run

        def run(coro: Any) -> Any:
            async def wrapped() -> Any:
                callers.append(asyncio.get_running_loop())
                return await coro

            return real_run(wrapped())

        with patch("asyncio.run", run):
            _poll(env, config, [], loop=True)
        assert types == ["resync"]
        assert loops == callers[:1]  # the caller's loop, not a worker thread's

    def test_a_settled_empty_baseline_is_told(self, env: _Env) -> None:
        seen: list[Any] = []
        env.owe(["notes"])
        env.baselines = [{}]
        assert _poll(env, _hooked(seen), [], loop=False).success
        assert seen == [(PEER, "properties", {}, 5, "resync")]

    @pytest.mark.parametrize("loop", [False, True], ids=["sync", "async"])
    def test_a_rebuild_after_a_list_diff_the_poll_told_tells_the_baseline_too(
        self, env: _Env, loop: bool
    ) -> None:
        """The audit (2026-11-17): the poll stops at the diff it could not
        apply; the diffs after it are never run and the rebuild clears them
        on the publisher, so the baseline is the only way the hooks hear
        them. A settled rebuild always tells (owner)."""
        seen: list[Any] = []
        env.baselines = [{"status": "paid", "later": 2}]
        diffs = [
            {"sequence": 1, "data": {"notes": {"operation": "insert"}}},
            {"sequence": 2, "data": {"later": 2}},
        ]
        with patch.object(
            RemotePeerStore, "apply_callback_data", return_value=_OUT_OF_STEP
        ):
            _poll(env, _hooked(seen), diffs, loop=loop)
        assert [call[-1] for call in seen] == ["diff", "resync"]
        assert seen[-1][2] == {"status": "paid", "later": 2}
        assert env.processor.rebuild_state(PEER, SUB)["owed"] is False  # it ran

    @pytest.mark.parametrize("loop", [False, True], ids=["sync", "async"])
    def test_a_poll_uses_the_applications_configuration_when_given_none(
        self, env: _Env, loop: bool
    ) -> None:
        """The audit: ``sync_subscription(config=None)`` used a default with
        ``auto_storage`` on and built a replica the application never
        configured."""
        from actingweb.subscription_config import SubscriptionProcessingConfig

        env.config._subscription_config = SubscriptionProcessingConfig(  # type: ignore[attr-defined]
            enabled=True, auto_storage=False
        )
        env.baselines = [{"status": "paid"}]
        env.recorded["sequence"] = 5  # level: a quiet poll
        assert _poll(env, None, [], loop=loop).success
        assert env.replica.get_value("status") is None

    @pytest.mark.parametrize("loop", [False, True], ids=["sync", "async"])
    def test_a_poll_without_a_configuration_tells_the_applications_hooks(
        self, env: _Env, loop: bool
    ) -> None:
        """Re-run 6 (Issue 1): the poll resolved the application's
        configuration, the baseline teller got the raw None and told
        nobody; the owed rebuild was settled and its change lost."""
        from actingweb.subscription_config import SubscriptionProcessingConfig

        seen: list[Any] = []
        env.config._subscription_config = SubscriptionProcessingConfig(  # type: ignore[attr-defined]
            enabled=True,
            subscription_data_hooks={"*": [lambda *a: seen.append(a[1:])]},
        )
        env.owe(["notes"])
        env.baselines = [{"status": "paid"}]
        assert _poll(env, None, [], loop=loop).success
        assert seen == [(PEER, "properties", {"status": "paid"}, 5, "resync")]

    @pytest.mark.parametrize("loop", [False, True], ids=["sync", "async"])
    def test_a_polled_marker_owes_nothing_a_poll_cannot_tell(
        self, env: _Env, loop: bool
    ) -> None:
        """Re-run 7 (Issue 2): markers are stored only for subscribers that
        get no callbacks, so a debt owed for a callback's legacy hook was
        never collected. With no replica and no data hook a polled marker
        is applied as an empty diff and owes nothing."""
        from actingweb.subscription_config import SubscriptionProcessingConfig

        config = SubscriptionProcessingConfig(enabled=True, auto_storage=False)
        marker = [{"sequence": 5, "type": "resync", "url": "https://p/x", "data": {}}]
        assert _poll(env, config, marker, loop=loop).success
        assert env.processor.rebuild_state(PEER, SUB)["owed"] is False

    @pytest.mark.parametrize("loop", [False, True], ids=["sync", "async"])
    def test_a_poll_leaves_a_rebuild_only_the_legacy_hook_hears_owed(
        self, env: _Env, loop: bool
    ) -> None:
        """The audit (re-run 5, Issue 2): a poll tells data hooks only, so
        it must not consume a rebuild that only a callback's legacy hook
        would hear; the next callback runs and tells it."""
        from actingweb.subscription_config import SubscriptionProcessingConfig

        env.owe()  # owed and due (never reserved)
        config = SubscriptionProcessingConfig(enabled=True, auto_storage=False)
        with patch.object(env.manager, "rebuild_subscription") as rebuild:
            result = _poll(env, config, [{"sequence": 1, "data": {"a": 1}}], loop=loop)
        rebuild.assert_not_called()
        assert result.success
        assert env.processor.rebuild_state(PEER, SUB)["owed"] is True

    @pytest.mark.parametrize("loop", [False, True], ids=["sync", "async"])
    def test_a_polled_marker_rebuilds_for_a_hooks_only_subscriber(
        self, env: _Env, loop: bool
    ) -> None:
        """The audit: without ``auto_storage`` the marker was applied as an
        empty diff, so the hooks never heard the state it asked for."""
        seen: list[Any] = []
        env.baselines = [{"status": "paid"}]
        marker = [{"sequence": 5, "type": "resync", "url": "https://p/x", "data": {}}]
        result = _poll(env, _hooked(seen, auto_storage=False), marker, loop=loop)
        assert result.success
        assert seen == [(PEER, "properties", {"status": "paid"}, 5, "resync")]

    @pytest.mark.parametrize("loop", [False, True], ids=["sync", "async"])
    def test_duplicates_while_a_rebuild_is_owed_tell_no_baseline(
        self, env: _Env, loop: bool
    ) -> None:
        """The audit: the all-duplicates path told a baseline while a
        rebuild was owed, which the rebuild then told again."""
        seen: list[Any] = []
        assert env.processor.begin_rebuild(PEER, SUB, force=True)  # owed, not due
        env.baselines = [{"status": "paid"}]
        env.recorded["sequence"] = 5
        result = _poll(
            env, _hooked(seen), [{"sequence": 3, "data": {"old": 1}}], loop=loop
        )
        assert result.baseline is None
        assert seen == []

    @pytest.mark.parametrize("loop", [False, True], ids=["sync", "async"])
    def test_a_quiet_poll_tells_no_hook(self, env: _Env, loop: bool) -> None:
        """Nothing to fetch and the subscriber level with the publisher: the
        replica is refreshed from a baseline, which is the state the hooks
        already heard about (owner, 2026-11-16)."""
        seen: list[Any] = []
        env.baselines = [{"status": "paid"}]
        env.recorded["sequence"] = 5  # the publisher answers 5
        result = _poll(env, _hooked(seen), [], loop=loop)
        assert result.success and result.baseline is None
        assert env.replica.get_value("status") is not None  # still applied
        assert seen == []

    @pytest.mark.parametrize("loop", [False, True], ids=["sync", "async"])
    def test_a_poll_with_nothing_to_fetch_that_was_behind_tells_the_hook(
        self, env: _Env, loop: bool
    ) -> None:
        """Verification 2026-11-16 (Issue 2): after a gap resync the sequence
        is 0 and the queued callbacks are gone, unseen by any hook. When the
        publisher retains no diff, the poll that follows has nothing to fetch
        and its baseline is the first the application hears of the change."""
        seen: list[Any] = []
        env.baselines = [{"status": "paid"}]
        env.recorded["sequence"] = 0  # reset by the gap resync; publisher at 5
        result = _poll(env, _hooked(seen), [], loop=loop)
        assert result.success
        assert seen == [(PEER, "properties", {"status": "paid"}, 5, "resync")]

    @pytest.mark.parametrize("loop", [False, True], ids=["sync", "async"])
    def test_a_behind_poll_whose_baseline_was_not_stored_whole_stays_owed(
        self, env: _Env, loop: bool
    ) -> None:
        """Not told, and not forgotten: the rebuild stays owed, so the next
        poll after the interval runs it again and tells it then (re-run 1,
        Issue 3: the poll was recorded as level and nothing was owed)."""
        seen: list[Any] = []
        env.baselines = [{"status": "paid"}]
        result = MagicMock(skipped=False, failed=["status"])
        with patch.object(RemotePeerStore, "apply_resync_data", return_value=result):
            polled = _poll(env, _hooked(seen), [], loop=loop)
        assert not polled.success
        assert seen == []
        assert env.processor.rebuild_state(PEER, SUB)["owed"] is True

    def test_without_sequence_tracking_a_quiet_poll_is_never_behind(
        self, env: _Env
    ) -> None:
        """Without ``auto_sequence`` callbacks record no sequence, so the
        recorded one says nothing about what was missed: no rebuild, no
        hook, on every quiet poll."""
        seen: list[Any] = []
        env.baselines = [{"status": "paid"}]
        result = _poll(env, _hooked(seen, auto_sequence=False), [], loop=False)
        assert result.success and result.baseline is None
        assert seen == []

    @pytest.mark.parametrize("loop", [False, True], ids=["sync", "async"])
    def test_a_behind_poll_tells_an_empty_baseline_and_empties_the_replica(
        self, env: _Env, loop: bool
    ) -> None:
        """Re-run 1 (Issue 1): the lost callbacks deleted the publisher's
        last properties. The baseline is ``{}``: the hook is told it, and
        the replica no longer holds what the publisher deleted."""
        seen: list[Any] = []
        env.replica.set_value("status", {"value": "paid"})
        env.baselines = [{}]
        assert _poll(env, _hooked(seen), [], loop=loop).success
        assert seen == [(PEER, "properties", {}, 5, "resync")]
        assert env.replica.get_value("status") is None

    @pytest.mark.parametrize("sequence", [None, "5", float("nan"), True])
    def test_a_publisher_sequence_that_is_no_integer_is_not_behind(
        self, env: _Env, sequence: Any
    ) -> None:
        """Re-run 1 (Issue 6): a ``NaN`` raised in the comparison."""
        seen: list[Any] = []
        env.baselines = [{"status": "paid"}]
        env.sequences = [sequence]
        # Re-run 2: a text or null sequence raised later, at the quiet
        # path's own comparison; it is now not recorded either.
        assert _poll(env, _hooked(seen), [], loop=False).success
        assert seen == []
        assert env.recorded["sequence"] == 0

    @pytest.mark.parametrize("loop", [False, True], ids=["sync", "async"])
    def test_a_behind_poll_of_a_covered_subscription_tells_no_hook(
        self, env: _Env, loop: bool
    ) -> None:
        """Re-run 2 (Issue 1): a baseline skipped because another
        subscription covers the replica is not told on the behind path
        either; the rebuild returned it as settled."""
        seen: list[Any] = []
        env.baselines = [{"status": "paid"}]
        skipped = MagicMock(skipped=True, failed=[])
        with patch.object(RemotePeerStore, "apply_resync_data", return_value=skipped):
            polled = _poll(env, _hooked(seen), [], loop=loop)
        assert polled.success and polled.baseline_skipped
        assert seen == []

    def test_a_skipped_rebuild_still_returns_its_baseline(self, env: _Env) -> None:
        """The callback path tells the baseline that answered for its
        callback whatever the replica stored; only a poll leaves a skipped
        one untold, by the result's ``baseline_skipped``."""
        env.baselines = [{"status": "paid"}]
        skipped = MagicMock(skipped=True, failed=[])
        with patch.object(RemotePeerStore, "apply_resync_data", return_value=skipped):
            result = env.rebuild(force=True)
        assert result.success and result.baseline == {"status": "paid"}
        assert result.baseline_skipped is True

    @pytest.mark.parametrize("loop", [False, True], ids=["sync", "async"])
    def test_an_interval_another_path_started_does_not_hold_the_behind_poll(
        self, env: _Env, loop: bool
    ) -> None:
        """A pushed resync's sweep stamps the interval without owing a
        rebuild; the behind poll that follows still rebuilds and tells."""
        assert env.processor.begin_rebuild(PEER, SUB, force=True)
        env.processor.settle_rebuild(PEER, SUB, rebuilt=True)
        seen: list[Any] = []
        env.baselines = [{"status": "paid"}]
        env.recorded["sequence"] = 0
        assert _poll(env, _hooked(seen), [], loop=loop).success
        assert seen == [(PEER, "properties", {"status": "paid"}, 5, "resync")]

    @pytest.mark.parametrize("storage", [True, False], ids=["replica", "hooks-only"])
    @pytest.mark.parametrize("loop", [False, True], ids=["sync", "async"])
    def test_a_failing_behind_rebuild_is_attempted_once_a_minute(
        self, env: _Env, loop: bool, storage: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Re-run 2 (Issue 2): the behind path forced its rebuild past the
        interval, so a baseline that could not be fetched was fetched again
        on every poll. Re-run 3 (Issue 5): also without ``auto_storage``."""
        fetched: list[Any] = []

        def baseline(**_: Any) -> Any:
            fetched.append(1)
            return None  # the fetch fails

        env._baseline = baseline  # type: ignore[method-assign]
        env.recorded["sequence"] = 0  # behind the publisher's 5
        config = _hooked([], auto_storage=storage)
        first = _poll(env, config, [], loop=loop)
        second = _poll(env, config, [], loop=loop)
        assert not first.success and not second.success
        assert second.error_code == 429
        assert len(fetched) == 1
        real = time.time
        monkeypatch.setattr(
            "actingweb.callback_processor.time.time", lambda: real() + 61
        )
        _poll(env, config, [], loop=loop)
        assert len(fetched) == 2

    @pytest.mark.parametrize("loop", [False, True], ids=["sync", "async"])
    def test_a_hooks_only_rebuild_owed_after_a_failure_is_told_when_it_runs(
        self, env: _Env, loop: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Re-run 3 (Issue 1): a failed behind rebuild leaves it owed. A
        callback then records its sequence, so the next poll is level: the
        owed rebuild must still run there and tell the hook, not wait for
        a path that runs it without telling."""
        seen: list[Any] = []
        env.baselines = [None, {"status": "paid"}]
        env.recorded["sequence"] = 0
        config = _hooked(seen, auto_storage=False)
        assert not _poll(env, config, [], loop=loop).success
        env.recorded["sequence"] = 5  # a callback recorded meanwhile
        real = time.time
        monkeypatch.setattr(
            "actingweb.callback_processor.time.time", lambda: real() + 61
        )
        assert _poll(env, config, [], loop=loop).success
        assert seen == [(PEER, "properties", {"status": "paid"}, 5, "resync")]
        assert env.processor.rebuild_state(PEER, SUB)["owed"] is False

    @pytest.mark.parametrize("loop", [False, True], ids=["sync", "async"])
    def test_a_hook_on_another_target_does_not_make_a_behind_poll_rebuild(
        self, env: _Env, loop: bool
    ) -> None:
        """Re-run 3 (Issue 2): nobody would be told, so the poll stays one
        request and records the sequence, as without any hook."""
        from actingweb.subscription_config import SubscriptionProcessingConfig

        config = SubscriptionProcessingConfig(
            enabled=True,
            auto_storage=False,
            subscription_data_hooks={"resources": [lambda *a: None]},
        )
        result = _poll(env, config, [], loop=loop)
        assert result.success
        assert env.recorded["sequence"] == 5
        # One request: the poll's own (a rebuild reads the sequence again).
        proxy = env.proxy
        assert proxy.get_resource.call_count + proxy.get_resource_async.call_count == 1

    @pytest.mark.parametrize("loop", [False, True], ids=["sync", "async"])
    def test_duplicates_under_a_sequence_that_is_no_integer_tell_no_hook(
        self, env: _Env, loop: bool
    ) -> None:
        """Re-run 3 (Issue 3): nothing is recorded or cleared, so the same
        duplicates come back on every poll; telling them would repeat."""
        seen: list[Any] = []
        env.baselines = [{"status": "paid"}]
        env.recorded["sequence"] = 5
        env.sequences = [None]  # type: ignore[list-item]
        result = _poll(
            env, _hooked(seen), [{"sequence": 3, "data": {"old": 1}}], loop=loop
        )
        assert result.baseline is None
        assert seen == []

    @pytest.mark.parametrize("loop", [False, True], ids=["sync", "async"])
    def test_a_behind_poll_without_auto_storage_tells_the_hook(
        self, env: _Env, loop: bool
    ) -> None:
        """Re-run 2 (Issue 3): a subscriber with hooks and sequence tracking
        but no replica was told nothing after a gap resync; the hook is its
        only record."""
        seen: list[Any] = []
        env.baselines = [{"status": "paid"}]
        env.recorded["sequence"] = 0
        result = _poll(env, _hooked(seen, auto_storage=False), [], loop=loop)
        assert result.success
        assert seen == [(PEER, "properties", {"status": "paid"}, 5, "resync")]
        assert env.recorded["sequence"] == 5

    def test_a_level_poll_without_auto_storage_tells_no_hook(self, env: _Env) -> None:
        seen: list[Any] = []
        env.baselines = [{"status": "paid"}]
        env.recorded["sequence"] = 5
        assert _poll(env, _hooked(seen, auto_storage=False), [], loop=False).success
        assert seen == []

    @pytest.mark.parametrize("loop", [False, True], ids=["sync", "async"])
    @pytest.mark.parametrize("outcome", ["skipped", "failed"])
    def test_a_baseline_that_was_not_applied_whole_is_not_told(
        self, env: _Env, outcome: str, loop: bool
    ) -> None:
        """Skipped (another subscription covers the replica) or with an
        entry that could not be stored: the hook would hear of data the
        replica does not hold."""
        seen: list[Any] = []
        env.baselines = [{"status": "paid"}]
        env.recorded["sequence"] = 5
        result = MagicMock(
            skipped=outcome == "skipped",
            failed=["status"] if outcome == "failed" else [],
        )
        with patch.object(RemotePeerStore, "apply_resync_data", return_value=result):
            polled = _poll(
                env, _hooked(seen), [{"sequence": 3, "data": {"old": 1}}], loop=loop
            )
        assert polled.success and polled.baseline is None
        assert seen == []
