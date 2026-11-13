"""``Actor.request_resync``, the list diff filtered as a unit, and the
two-diff full state (thoughts/plans/2026-11-13-attribute-list-v2-port.md,
Phase 4)."""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

import pytest

from actingweb.permission_evaluator import GrantSnapshot, PermissionEvaluator

RULES = {
    "patterns": ["*"],
    "operations": ["read"],
    "excluded_patterns": ["notes/operation", "*/secret", "fake/secret"],
}


def _grant(peer: str = "p1", rules: dict[str, Any] | None = None) -> GrantSnapshot:
    return GrantSnapshot(
        actor_id="a1",
        peer_id=peer,
        has_row=True,
        approved=True,
        relationship="friend",
        is_client=False,
        permissions={"properties": rules or RULES},
    )


def _evaluator() -> PermissionEvaluator:
    ev = object.__new__(PermissionEvaluator)
    ev.config = None  # type: ignore[assignment]
    ev.snapshot = lambda a, p: _grant(p)  # type: ignore[method-assign]
    return ev


@pytest.fixture
def actor() -> Any:
    from actingweb.actor import Actor

    a = object.__new__(Actor)
    a.config = mock.Mock()
    a.id = "a1"
    a.property_lists = mock.Mock()
    a.property_lists.exists.side_effect = lambda name: name == "notes"
    with mock.patch(
        "actingweb.actor.get_permission_evaluator", return_value=_evaluator()
    ):
        yield a


WHOLE = {"target": "properties", "subtarget": ""}
NOTES = {"target": "properties", "subtarget": "notes"}
DIFF = {
    "list": "notes",
    "operation": "append",
    "item": {"secret": 1, "ok": 2},
    "length": 1,
}


class TestFilterAListDiffAsAUnit:
    def test_whole_target_push_and_pull(self, actor) -> None:
        out = actor.filter_subscription_blob("p1", WHOLE, json.dumps({"notes": DIFF}))
        assert json.loads(out) == {"notes": DIFF}

    def test_subtarget_level(self, actor) -> None:
        out = actor.filter_subscription_blob("p1", NOTES, json.dumps(DIFF))
        assert json.loads(out) == DIFF
        state = {"notes": {**DIFF, "operation": "extend", "items": [{"secret": 1}]}}
        out = actor.filter_subscription_blob("p1", NOTES, json.dumps(state))
        assert json.loads(out) == state

    def test_a_scalar_shaped_like_a_list_diff_is_filtered_as_an_object(
        self, actor
    ) -> None:
        fake = {"list": "notes", "operation": "clear", "secret": "s", "ok": 1}
        out = actor.filter_subscription_blob("p1", WHOLE, json.dumps({"fake": fake}))
        assert json.loads(out) == {
            "fake": {"list": "notes", "operation": "clear", "ok": 1}
        }

    def test_a_clear_and_its_extend_are_both_served_or_both_withheld(
        self, actor
    ) -> None:
        clear = {"notes": {"list": "notes", "operation": "clear", "length": 0}}
        extend = {"notes": {**DIFF, "operation": "extend", "items": [1]}}
        served = [
            actor.filter_subscription_blob("p1", WHOLE, json.dumps(d))
            for d in (clear, extend)
        ]
        assert all(s is not None for s in served)
        denied = {"patterns": ["color"], "operations": ["read"]}
        with mock.patch.object(
            type(actor), "grant_for", return_value=_grant("p1", denied)
        ):
            withheld = [
                actor.filter_subscription_blob("p1", WHOLE, json.dumps(d))
                for d in (clear, extend)
            ]
        assert withheld == [None, None]


class TestRequestResync:
    def _subs(self) -> list[dict[str, Any]]:
        return [
            {"peerid": "p1", "subscriptionid": "s1", "target": "properties"},
            {"peerid": "p2", "subscriptionid": "s2", "target": "properties"},
            {
                "peerid": "p3",
                "subscriptionid": "s3",
                "target": "properties",
                "subtarget": "notes",
            },
        ]

    def _run(self, actor: Any, missed_ids: set[str] | None = None) -> Any:
        sent: list[str] = []
        written: list[list[str]] = []

        def subscriptions(**_: Any) -> list[dict[str, Any]]:
            assert actor.subs_list is None, "the memo is reset first"
            return self._subs()

        def send(target, subtarget, subs, suspension, *, missed, fold_faults, widen):  # noqa: ANN001
            assert suspension is None, "no suspension row"
            assert fold_faults, "a store fault is a miss, not a 503"
            assert widen, "a whole-target subscription gets the whole target's"
            for sub in subs:
                sent.append(f"{sub['subscriptionid']}:{subtarget}")
                if sub["subscriptionid"] in (missed_ids or set()):
                    missed.append(f"{sub['peerid']}:{sub['subscriptionid']}")
            return len(subs)

        def grant(peer: str) -> GrantSnapshot:
            if peer == "p2":
                return _grant(peer, {"patterns": ["color"], "operations": ["read"]})
            return _grant(peer)

        actor.subs_list = ["stale"]
        with (
            mock.patch.object(actor, "get_subscriptions", side_effect=subscriptions),
            mock.patch.object(actor, "_send_resync_callbacks", side_effect=send),
            mock.patch.object(actor, "grant_for", side_effect=grant),
            mock.patch.object(actor, "_resync_pending", return_value=None),
            mock.patch.object(
                actor,
                "_write_resync_pending",
                side_effect=lambda t, s, m: written.append(list(m)),
            ),
        ):
            count = actor.request_resync("properties", "notes")
        return count, sent, written

    def test_only_subscribers_that_may_read_the_list_are_sent_anything(
        self, actor
    ) -> None:
        count, sent, written = self._run(actor)
        assert sent == ["s1:notes", "s3:notes"] and count == 2
        assert written == []

    def test_a_missed_subscriber_is_recorded(self, actor) -> None:
        _, _, written = self._run(actor, missed_ids={"s3"})
        assert written == [["p3:s3"]]


class TestFullStateIsTwoDiffs:
    def _resync(
        self,
        actor: Any,
        state: dict[str, Any],
        keys: set[str],
        subtarget: str | None = None,
    ) -> tuple[list[tuple[int, Any]], list[dict[str, Any]]]:
        stored: list[tuple[int, Any]] = []
        payloads: list[dict[str, Any]] = []
        trust = mock.Mock()
        trust.get.return_value = {"baseuri": "https://peer.example/p1", "secret": "s"}
        caps = mock.Mock()
        caps.supports_resync_callbacks_cached.return_value = False
        actor.config.sync_subscription_callbacks = True
        actor.config.list_item_span_threshold = None
        seqs = iter([7, 8])
        with (
            mock.patch("actingweb.trust.Trust", return_value=trust),
            mock.patch(
                "actingweb.peer_capabilities.PeerCapabilities", return_value=caps
            ),
            mock.patch("actingweb.interface.actor_interface.ActorInterface"),
            mock.patch.object(
                actor,
                "_get_full_state_for_subscription",
                side_effect=lambda t, st, k: (k.update(keys), state)[1],
            ),
            mock.patch.object(
                actor, "_filter_full_state", side_effect=lambda p, s, st, k: st
            ),
            mock.patch.object(
                actor,
                "_store_subscription_diff",
                side_effect=lambda p, s, seq, d: stored.append((seq, d)) or "url",
            ),
            mock.patch.object(
                actor,
                "_increment_subscription_sequence",
                side_effect=lambda p, s: next(seqs),
            ),
            mock.patch.object(
                actor,
                "_send_resync_callback_sync",
                side_effect=lambda url, payload, secret, peer: (
                    payloads.append(payload) or True
                ),
            ),
        ):
            assert actor._callback_subscription_resync(  # noqa: SLF001
                {
                    "peerid": "p1",
                    "subscriptionid": "s1",
                    "target": "properties",
                    "subtarget": subtarget,
                }
            )
        return stored, payloads

    def test_a_clear_then_the_extend_under_consecutive_sequences(self, actor) -> None:
        state = {
            "notes": {
                "list": "notes",
                "operation": "extend",
                "items": [1],
                "length": 1,
            },
            "color": {"v": 1},
        }
        stored, payloads = self._resync(actor, state, {"notes"})
        assert stored == [
            (7, {"notes": {"list": "notes", "operation": "clear", "length": 0}}),
            (8, state),
        ]
        assert [p["sequence"] for p in payloads] == [7, 8]
        assert all(p["granularity"] == "low" for p in payloads)

    def test_a_list_that_became_a_reference_gets_no_clear(self, actor) -> None:
        state = {
            "notes": {
                "list": "notes",
                "operation": "extend",
                "spanned": True,
                "bytes": 9,
            }
        }
        stored, payloads = self._resync(actor, state, {"notes"})
        assert stored == [(7, state)]
        assert len(payloads) == 1

    def test_a_replica_already_holding_the_list_ends_with_it_once(self) -> None:
        from actingweb.remote_storage import RemotePeerStore
        from tests.mcp_token_double import make_config

        core = mock.MagicMock()
        core.id = "a" * 32
        core.config, _ = make_config()
        replica = RemotePeerStore(core, "b" * 32)
        replica.set_list("notes", [1, 2])
        replica.apply_callback_data(
            {"notes": {"list": "notes", "operation": "clear", "length": 0}}
        )
        replica.apply_callback_data(
            {
                "notes": {
                    "list": "notes",
                    "operation": "extend",
                    "items": [1, 2],
                    "length": 2,
                }
            }
        )
        assert replica.get_list("notes") == [1, 2]

    def test_a_subscription_to_the_list_gets_keyed_diffs(self, actor) -> None:
        """Keyed, for the pre-3.16 receivers the fallback serves
        (verification re-run 2, U1); a 3.16 receiver unwraps a keyed list."""
        extend = {"list": "notes", "operation": "extend", "items": [1], "length": 1}
        stored, _ = self._resync(actor, {"notes": extend}, {"notes"}, "notes")
        assert stored == [
            (7, {"notes": {"list": "notes", "operation": "clear", "length": 0}}),
            (8, {"notes": extend}),
        ]


class TestVerification2:
    """Verification re-run 2 (findings 1 and 8)."""

    @pytest.mark.parametrize(("own", "sent_subtarget"), [("", ""), ("notes", "notes")])
    def test_a_pushed_resync_of_a_subtarget_widens_for_a_whole_target_subscription(
        self, actor, own, sent_subtarget
    ) -> None:
        """A receiver resets the whole subscription's sequence on a resync:
        a subscription to the whole target gets the whole target's."""
        payloads: list[dict[str, Any]] = []
        trust = mock.Mock()
        trust.get.return_value = {"baseuri": "https://peer.example/p1", "secret": "s"}
        caps = mock.Mock()
        caps.supports_resync_callbacks_cached.return_value = True
        actor.config.sync_subscription_callbacks = True
        with (
            mock.patch("actingweb.trust.Trust", return_value=trust),
            mock.patch(
                "actingweb.peer_capabilities.PeerCapabilities", return_value=caps
            ),
            mock.patch("actingweb.interface.actor_interface.ActorInterface"),
            mock.patch.object(
                actor, "_increment_subscription_sequence", return_value=7
            ),
            mock.patch(
                "actingweb.actor._resync_url",
                side_effect=lambda c, a, t, st: f"{t}/{st}" if st else t,
            ),
            mock.patch.object(
                actor,
                "_send_resync_callback_sync",
                side_effect=lambda url, payload, secret, peer: (
                    payloads.append(payload) or True
                ),
            ),
        ):
            actor._callback_subscription_resync(  # noqa: SLF001
                {
                    "peerid": "p1",
                    "subscriptionid": "s1",
                    "target": "properties",
                    "subtarget": own,
                },
                "notes",
                widen=True,
            )
        (payload,) = payloads
        assert payload["subtarget"] == sent_subtarget

    def test_a_deleted_lists_delete_all_passes_a_sub_path_exclusion(
        self, actor
    ) -> None:
        actor.property_lists.exists.side_effect = lambda name: False
        gone = {"list": "notes", "operation": "delete_all", "length": 0}
        out = actor.filter_subscription_blob("p1", WHOLE, json.dumps({"notes": gone}))
        assert json.loads(out) == {"notes": gone}
        out = actor.filter_subscription_blob("p1", NOTES, json.dumps(gone))
        assert json.loads(out) == gone

    def test_a_whole_target_miss_is_not_recorded_under_the_subtarget(
        self, actor
    ) -> None:
        _, _, written = TestRequestResync()._run(actor, missed_ids={"s1", "s3"})
        assert written == [["p3:s3"]]


class TestVerification3:
    """Verification re-run 3 (OV8, OV9, CR6)."""

    def test_a_scalar_shaped_like_an_itemless_diff_with_an_object_is_filtered(
        self, actor
    ) -> None:
        actor.property_lists.exists.side_effect = lambda name: False
        rules = {
            "patterns": ["*"],
            "operations": ["read"],
            "excluded_patterns": ["profile/operation/secret"],
        }
        value = {"list": "x", "operation": {"secret": 1, "ok": 2}}
        with mock.patch.object(
            type(actor), "grant_for", return_value=_grant("p1", rules)
        ):
            out = actor.filter_subscription_blob(
                "p1", WHOLE, json.dumps({"profile": value})
            )
        assert json.loads(out) == {"profile": {"list": "x", "operation": {"ok": 2}}}

    def test_a_whole_target_record_stays(self, actor) -> None:
        test = TestRequestResync()
        written: list[list[str]] = []
        subs = test._subs()

        def send(target, subtarget, batch, suspension, *, missed, fold_faults, widen):  # noqa: ANN001
            return len(batch)

        actor.subs_list = None
        with (
            mock.patch.object(actor, "get_subscriptions", return_value=subs),
            mock.patch.object(actor, "_send_resync_callbacks", side_effect=send),
            mock.patch.object(actor, "grant_for", side_effect=lambda p: _grant(p)),
            mock.patch.object(actor, "_resync_pending", return_value=["p1:s1"]),
            mock.patch.object(
                actor,
                "_write_resync_pending",
                side_effect=lambda t, s, m: written.append(list(m)),
            ),
        ):
            actor.request_resync("properties", "notes")
        assert written == [["p1:s1"]]

    def test_repair_keys_announces_a_reference(self) -> None:
        from actingweb.interface.property_store import NotifyingListProperty

        core = mock.Mock()
        core.get_metadata.return_value = {"length": 2}
        core.config = mock.Mock(list_item_span_threshold=100)
        core.repair_keys.return_value = {}
        core.sweep_span_orphans.return_value = {}
        actor_ = mock.Mock()
        lst = NotifyingListProperty(core, "notes", actor_)
        lst.repair_keys()
        lst.sweep_span_orphans()
        for call in actor_.register_diffs.call_args_list:
            assert json.loads(call.kwargs["blob"])["spanned"] is True
