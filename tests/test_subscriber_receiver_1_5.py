"""What a receiver does with a callback (specification 1.5, spec-1-5 Phase 3):
a failed resync fetch answers 503 and owes the rebuild, a baseline is told
apart from a failure by the wire, and a diff with data needs a sequence."""

from __future__ import annotations

import dataclasses
import json
from typing import Any
from unittest import mock

import pytest

from actingweb.aw_web_request import AWWebObj
from actingweb.callback_processor import CallbackProcessor, ProcessResult
from actingweb.handlers.callbacks import CallbacksHandler
from actingweb.interface.subscription_manager import SubscriptionManager
from actingweb.subscription import Subscription
from actingweb.subscription_config import SubscriptionProcessingConfig
from tests._adoption_helpers import aid, create_core_actor, make_config, uuid_email


def _setup(subtarget: str = "", resource: str = "") -> tuple[Any, Any]:
    config = make_config()
    config._subscription_config = SubscriptionProcessingConfig(  # type: ignore[attr-defined]
        enabled=True, auto_sequence=True, auto_storage=True
    )
    actor = create_core_actor(config, uuid_email())
    assert Subscription(
        actor_id=aid(actor), peerid="peer1", subid="sub1", callback=True, config=config
    ).create(
        target="properties", subtarget=subtarget, resource=resource, granularity="high"
    )
    return config, actor


def _post(config: Any, actor: Any, body: dict[str, Any]) -> AWWebObj:
    webobj = AWWebObj(url="https://test.example.com/x", body=json.dumps(body))
    handler = CallbacksHandler(webobj, config)
    check = mock.Mock()
    check.check_authorisation.return_value = True
    check.response = {"code": 200, "text": "Ok", "headers": {}}
    check.acl = {"authenticated": True, "peerid": "peer1", "relationship": "friend"}
    handler._authenticate_dual_context = mock.Mock(  # type: ignore[method-assign]
        return_value=mock.Mock(actor=actor, auth_obj=check)
    )
    handler.post(aid(actor), "subscriptions/peer1/sub1")
    return webobj


def _proxy(body: Any, code: int, redirected: bool = False) -> Any:
    proxy = mock.Mock()
    proxy.get_resource.return_value = body
    proxy.last_response_code = code
    proxy.last_response_redirected = redirected
    proxy.last_response_message = json.dumps(body).encode() if body is not None else b""
    proxy.last_response_content_type = "application/json"
    return proxy


@pytest.mark.parametrize(
    ("subtarget", "resource"), [("", ""), ("color", ""), ("color", "shade")]
)
@pytest.mark.parametrize(
    "proxy",
    [
        _proxy({"error": {"code": 502}}, 502),
        _proxy(None, 408),
        _proxy({"a": 1}, 200, redirected=True),
    ],
)
def test_a_resync_whose_fetch_fails_is_503_and_owes_the_rebuild(
    subtarget: str, resource: str, proxy: Any
) -> None:
    """The resource level added by the verification of 2026-11-16 (M6)."""
    config, actor = _setup(subtarget, resource)
    body = {"sequence": 5, "type": "resync", "url": "https://peer.example.com/p"}
    with (
        mock.patch.object(SubscriptionManager, "_get_peer_proxy", return_value=proxy),
        mock.patch.object(CallbackProcessor, "process_callback_sync") as process,
    ):
        webobj = _post(config, actor, body)
    assert webobj.response.status_code == 503
    assert webobj.response.headers.get("Retry-After")
    process.assert_not_called()
    from actingweb.interface.actor_interface import ActorInterface

    state = CallbackProcessor(ActorInterface(actor)).rebuild_state("peer1", "sub1")
    assert state["owed"] is True


def test_a_property_named_error_is_data() -> None:
    _config, actor = _setup()
    proxy = _proxy({"error": "a value", "other": 1}, 200)
    with mock.patch.object(SubscriptionManager, "_get_peer_proxy", return_value=proxy):
        got = SubscriptionManager(actor)._fetch_and_transform_baseline(  # noqa: SLF001
            "peer1", "properties"
        )
    assert got == {"error": "a value", "other": 1}


def test_an_empty_baseline_is_empty_not_failed() -> None:
    _config, actor = _setup()
    proxy = _proxy({}, 200)
    with mock.patch.object(SubscriptionManager, "_get_peer_proxy", return_value=proxy):
        got = SubscriptionManager(actor)._fetch_and_transform_baseline(  # noqa: SLF001
            "peer1", "properties"
        )
    assert got == {}


@pytest.mark.parametrize("sequence", [None, "3", True])
def test_data_without_an_integer_sequence_is_400(sequence: Any) -> None:
    config, actor = _setup()
    body: dict[str, Any] = {"data": {"x": 1}}
    if sequence is not None:
        body["sequence"] = sequence
    with mock.patch.object(
        CallbackProcessor, "process_callback_sync", return_value=ProcessResult.PROCESSED
    ) as process:
        webobj = _post(config, actor, body)
    assert webobj.response.status_code == 400
    process.assert_not_called()


def test_an_unknown_granularity_is_refused_before_it_is_sent() -> None:
    _config, actor = _setup()
    with mock.patch("requests.post") as post:
        assert (
            actor.create_remote_subscription(
                peerid="peer1", target="properties", granularity="medium"
            )
            is False
        )
    post.assert_not_called()


@pytest.mark.parametrize("content_type", ["text/html", ""])
def test_a_non_json_2xx_is_a_failed_fetch_not_an_empty_baseline(
    content_type: str,
) -> None:
    """The proxy reads any 2xx body that is not JSON as ``{}``; an empty
    baseline would make the sweep delete the whole replica."""
    _config, actor = _setup()
    proxy = _proxy({}, 200)
    proxy.last_response_content_type = content_type
    with mock.patch.object(SubscriptionManager, "_get_peer_proxy", return_value=proxy):
        got = SubscriptionManager(actor)._fetch_and_transform_baseline(  # noqa: SLF001
            "peer1", "properties"
        )
    assert got is None


@pytest.mark.parametrize("granularity", [["high"], {"a": 1}, 3])
def test_a_granularity_that_is_not_text_is_refused(granularity: Any) -> None:
    _config, actor = _setup()
    with mock.patch("requests.post") as post:
        assert (
            actor.create_remote_subscription(
                peerid="peer1", target="properties", granularity=granularity
            )
            is False
        )
    post.assert_not_called()


@pytest.mark.parametrize("auto_storage", [True, False])
def test_the_poll_runs_the_data_hooks_whether_or_not_it_stores(
    auto_storage: bool,
) -> None:
    """Verification 2026-11-16 (M4): with ``auto_storage`` off the poll gave
    the processor no handler, so an application that stores data itself
    never saw a polled diff (owner 2026-11-07: the gap resync runs the data
    hook for what it applies)."""
    config = make_config()
    seen: list[tuple[int, Any]] = []

    def hook(_a: Any, _p: str, _t: str, data: Any, seq: int, _c: str) -> None:
        seen.append((seq, data))

    sub_config = SubscriptionProcessingConfig(
        enabled=True,
        auto_sequence=True,
        auto_storage=auto_storage,
        subscription_data_hooks={"properties": [hook]},
    )
    config._subscription_config = sub_config  # type: ignore[attr-defined]
    actor = create_core_actor(config, uuid_email())
    assert Subscription(
        actor_id=aid(actor), peerid="peer1", subid="sub1", callback=True, config=config
    ).create(target="properties", granularity="high")
    proxy = mock.MagicMock()
    proxy.trust = {"baseuri": "https://peer.example.com/peer1", "secret": "s"}
    proxy.get_resource.return_value = {
        "sequence": 2,
        "data": [
            {"sequence": 1, "timestamp": "2026-11-16T00:00:00Z", "data": {"a": 1}},
            {"sequence": 2, "timestamp": "2026-11-16T00:00:01Z", "data": {"b": 2}},
        ],
    }
    proxy.change_resource.return_value = {}
    mgr = SubscriptionManager(actor)
    with mock.patch.object(mgr, "_get_peer_proxy", return_value=proxy):
        result = mgr.sync_subscription("peer1", "sub1", config=sub_config)
    assert result.success, result.error
    assert seen == [(1, {"a": 1}), (2, {"b": 2})]


@pytest.mark.parametrize("declared", [None, "10"])
def test_an_anonymous_body_over_the_cap_is_413_whatever_content_length_says(
    declared: str | None,
) -> None:
    """Verification 2026-11-16 (M6): only the Content-Length branch of the
    1 MB cap had a test; a body with none, or one that understates it, is
    measured."""
    from actingweb.handlers.callbacks import ANONYMOUS_CALLBACK_MAX_BYTES

    headers = {} if declared is None else {"Content-Length": declared}
    webobj = AWWebObj(
        url="https://test.example.com/x",
        body="x" * (ANONYMOUS_CALLBACK_MAX_BYTES + 1),
        headers=headers,
    )
    handler = CallbacksHandler(webobj, make_config())
    handler._post_anonymous("a" * 32, "incoming")  # noqa: SLF001
    assert webobj.response.status_code == 413


@pytest.mark.parametrize("seq", [None, [1], {"n": 1}, True, "x"])
def test_a_clearing_put_whose_sequence_is_not_a_number_is_400(seq: Any) -> None:
    """Verification 2026-11-16 (Low): specification 1.5 says a sequence that
    is not a number is 400; ``null`` and an array raised ``TypeError`` (a
    500) and ``true`` cleared through 1. (The publisher's side, kept here
    with the other 1.5 answers.)"""
    from actingweb.handlers import subscription as sub_handlers

    webobj = AWWebObj(
        url="https://test.example.com/x", body=json.dumps({"sequence": seq})
    )
    handler = sub_handlers.SubscriptionHandler(webobj, make_config())
    with (
        mock.patch.object(
            handler,
            "authenticate_actor",
            return_value=mock.Mock(success=True, actor=mock.Mock()),
        ),
        mock.patch.object(
            sub_handlers, "_authorize_subscription_write", return_value=True
        ),
        mock.patch.object(handler, "_get_actor_interface") as iface,
    ):
        handler.put("a" * 32, "peer1", "sub1")
    assert webobj.response.status_code == 400
    iface.assert_not_called()


def test_a_publisher_whose_bulk_read_faults_answers_500_not_an_empty_listing() -> None:
    """Verification 2026-11-16-3 (B2): ``GET /properties`` folded a fault
    other than ``DbError`` into 200 ``{}``, which a subscriber takes as a
    valid whole-target baseline and sweeps its whole replica of the peer.
    It answers 500, so the baseline fails and the rebuild stays owed."""
    from actingweb.handlers.properties import PropertiesHandler

    handler = PropertiesHandler(AWWebObj(params={}), mock.Mock())
    handler.hooks = None
    myself = mock.Mock()
    myself.id = "a1"
    broken = mock.Mock()
    broken.fetch_all_including_lists.side_effect = RuntimeError("cannot decode")
    with (
        mock.patch.object(handler, "_get_actor_interface", return_value=mock.Mock()),
        mock.patch(
            "actingweb.handlers.properties.get_property_list", return_value=broken
        ),
    ):
        handler.listall(myself, mock.Mock())
    assert handler.response.status_code == 500
    assert handler.response.body in (None, "", b"")


def _rebuild_on_the_callback(
    result: Any, *, auto_storage: bool = True, data_hooks: bool = True
) -> tuple[Any, list[Any], list[Any]]:
    """A diff arrives while a rebuild is owed and due; the rebuild returns
    ``result``. The data hook's and the legacy hook's calls are recorded."""
    from actingweb.interface.hooks import HookRegistry

    config, actor = _setup()
    config._subscription_config.auto_storage = auto_storage  # type: ignore[attr-defined]
    seen: list[Any] = []
    if data_hooks:
        config._subscription_config.subscription_data_hooks = {  # type: ignore[attr-defined]
            "properties": [lambda a, p, t, d, s, k: seen.append((p, t, d, s, k))]
        }
    legacy: list[Any] = []
    hooks = HookRegistry()
    hooks.register_callback_hook(
        "subscription", lambda a, n, d: legacy.append((d["data"], d["type"])) or True
    )
    webobj = AWWebObj(
        url="https://test.example.com/x",
        body=json.dumps({"sequence": 6, "data": {"status": "paid"}}),
    )
    handler = CallbacksHandler(webobj, config, hooks=hooks)
    check = mock.Mock()
    check.check_authorisation.return_value = True
    check.response = {"code": 200, "text": "Ok", "headers": {}}
    check.acl = {"authenticated": True, "peerid": "peer1", "relationship": "friend"}
    handler._authenticate_dual_context = mock.Mock(  # type: ignore[method-assign]
        return_value=mock.Mock(actor=actor, auth_obj=check)
    )
    with (
        mock.patch.object(
            SubscriptionManager, "_rebuild_owed_and_due", return_value=True
        ),
        mock.patch.object(
            SubscriptionManager, "rebuild_subscription", return_value=result
        ),
    ):
        handler.post(aid(actor), "subscriptions/peer1/sub1")
    return webobj, seen, legacy


def test_a_rebuild_run_on_a_callback_tells_both_hooks_its_baseline() -> None:
    """Verification 2026-11-16-3 (B1): the callback that ran a due rebuild
    answered 204 and no hook, data or legacy, saw its change."""
    from actingweb.interface.subscription_manager import SubscriptionSyncResult

    settled = SubscriptionSyncResult(
        subscription_id="sub1",
        success=True,
        diffs_fetched=0,
        diffs_processed=1,
        final_sequence=6,
        baseline={"status": "paid", "x": 1},
    )
    webobj, seen, legacy = _rebuild_on_the_callback(settled)
    assert webobj.response.status_code == 204
    assert seen == [("peer1", "properties", {"status": "paid", "x": 1}, 6, "resync")]
    assert legacy == [({"status": "paid", "x": 1}, "resync")]


def test_a_hooks_only_subscribers_owed_rebuild_runs_on_a_callback_and_is_told() -> None:
    """Re-run 3 (Issue 1): without ``auto_storage`` the owed rebuild was
    left to the processor's REBUILD answer, which runs it without telling
    any hook."""
    from actingweb.interface.subscription_manager import SubscriptionSyncResult

    settled = SubscriptionSyncResult(
        subscription_id="sub1",
        success=True,
        diffs_fetched=0,
        diffs_processed=1,
        final_sequence=6,
        baseline={"status": "paid"},
    )
    webobj, seen, _ = _rebuild_on_the_callback(settled, auto_storage=False)
    assert webobj.response.status_code == 204
    assert seen == [("peer1", "properties", {"status": "paid"}, 6, "resync")]


def test_a_legacy_hook_only_subscribers_owed_rebuild_runs_on_a_callback_and_is_told() -> (
    None
):
    """Re-run 4 (Issue 1): the gate counted data hooks only, so with the
    legacy ``subscription`` hook alone the owed rebuild was left to the
    processor's REBUILD answer and ran untold."""
    from actingweb.interface.subscription_manager import SubscriptionSyncResult

    settled = SubscriptionSyncResult(
        subscription_id="sub1",
        success=True,
        diffs_fetched=0,
        diffs_processed=1,
        final_sequence=6,
        baseline={"status": "paid"},
    )
    webobj, _, legacy = _rebuild_on_the_callback(
        settled, auto_storage=False, data_hooks=False
    )
    assert webobj.response.status_code == 204
    assert legacy == [({"status": "paid"}, "resync")]


def _owe(actor: Any) -> None:
    from actingweb.callback_processor import CallbackProcessor
    from actingweb.interface.actor_interface import ActorInterface

    CallbackProcessor(ActorInterface(actor)).settle_rebuild(
        "peer1", "sub1", rebuilt=False
    )


def test_an_owed_rebuild_the_processor_runs_tells_the_hooks() -> None:
    """Re-run 4 (Issue 3): the callback's check found the rebuild not yet
    due, the processor's claim a moment later found it due and answered
    REBUILD, and that branch ran it without telling anyone. The callback's
    own diff is told first, then the baseline as a resync."""
    from actingweb.interface.subscription_manager import SubscriptionSyncResult

    config, actor = _setup()
    seen: list[Any] = []
    config._subscription_config.subscription_data_hooks = {  # type: ignore[attr-defined]
        "properties": [lambda a, p, t, d, s, k: seen.append((d, k))]
    }
    _owe(actor)
    settled = SubscriptionSyncResult(
        subscription_id="sub1",
        success=True,
        diffs_fetched=0,
        diffs_processed=1,
        final_sequence=6,
        baseline={"status": "paid", "x": 1},
    )
    with (
        mock.patch.object(
            SubscriptionManager, "_rebuild_owed_and_due", return_value=False
        ),
        mock.patch.object(
            SubscriptionManager, "rebuild_subscription", return_value=settled
        ) as rebuild,
    ):
        webobj = _post(config, actor, {"sequence": 1, "data": {"status": "paid"}})
    assert webobj.response.status_code == 204
    rebuild.assert_called_once()
    assert seen == [
        ({"status": "paid"}, "diff"),
        ({"status": "paid", "x": 1}, "resync"),
    ]


@pytest.mark.parametrize(
    "hook_target,asked", [("properties", True), ("*", True), ("resources", False)]
)
def test_the_callback_gate_asks_for_a_hook_on_the_subscriptions_target(
    hook_target: str, asked: bool
) -> None:
    """Re-run 4 (Issue 6): without patching the owed check, a hooks-only
    subscriber's callback asks it with the subscription's target, and a
    hook on another target does not make it ask."""
    from actingweb.interface.subscription_manager import SubscriptionSyncResult

    config, actor = _setup()
    config._subscription_config.auto_storage = False  # type: ignore[attr-defined]
    config._subscription_config.subscription_data_hooks = {  # type: ignore[attr-defined]
        hook_target: [lambda *a: None]
    }
    _owe(actor)
    real = SubscriptionManager._rebuild_owed_and_due
    answers: list[Any] = []

    def spy(self: Any, *args: Any, **kwargs: Any) -> bool:
        answer = real(self, *args, **kwargs)
        answers.append((kwargs.get("target"), answer))
        return answer

    settled = SubscriptionSyncResult(
        subscription_id="sub1",
        success=True,
        diffs_fetched=0,
        diffs_processed=1,
        final_sequence=6,
        baseline={},
    )
    with (
        mock.patch.object(SubscriptionManager, "_rebuild_owed_and_due", spy),
        mock.patch.object(
            SubscriptionManager, "rebuild_subscription", return_value=settled
        ),
    ):
        _post(config, actor, {"sequence": 1, "data": {"status": "paid"}})
    assert answers == ([("properties", True)] if asked else [])


def test_a_covered_baseline_is_not_told_on_the_callback_path() -> None:
    """The audit (owner, 2026-11-17): a baseline another subscription's
    replica covers is never told; the covering subscription's own callbacks
    tell the same change."""
    from actingweb.interface.subscription_manager import SubscriptionSyncResult

    covered = SubscriptionSyncResult(
        subscription_id="sub1",
        success=True,
        diffs_fetched=0,
        diffs_processed=1,
        final_sequence=6,
        baseline={"status": "paid"},
        baseline_skipped=True,
    )
    webobj, seen, legacy = _rebuild_on_the_callback(covered)
    assert webobj.response.status_code == 204
    assert seen == [] and legacy == []


def test_a_rebuild_after_the_callbacks_own_list_diff_tells_the_baseline() -> None:
    """The audit (owner: a settled rebuild always tells): the processor's
    REBUILD answer for this callback's out-of-step diff ran the rebuild
    and told nobody."""
    from actingweb.interface.subscription_manager import SubscriptionSyncResult
    from actingweb.remote_storage import RemotePeerStore

    config, actor = _setup()
    seen: list[Any] = []
    config._subscription_config.subscription_data_hooks = {  # type: ignore[attr-defined]
        "properties": [lambda a, p, t, d, s, k: seen.append((d, k))]
    }
    settled = SubscriptionSyncResult(
        subscription_id="sub1",
        success=True,
        diffs_fetched=0,
        diffs_processed=1,
        final_sequence=1,
        baseline={"notes": ["a"]},
    )
    out_of_step = mock.MagicMock(
        out_of_step={"list": "notes", "operation": "insert"}, failed=[]
    )
    with (
        mock.patch.object(
            RemotePeerStore, "apply_callback_data", return_value=out_of_step
        ),
        mock.patch.object(
            SubscriptionManager, "rebuild_subscription", return_value=settled
        ) as rebuild,
    ):
        webobj = _post(
            config, actor, {"sequence": 1, "data": {"notes": {"operation": "insert"}}}
        )
    assert webobj.response.status_code == 204
    rebuild.assert_called_once()
    assert seen[-1] == ({"notes": ["a"]}, "resync")


@pytest.mark.parametrize(
    "storage,hook,owed",
    [(True, False, True), (False, True, True), (False, False, False)],
    ids=["replica", "hooks only", "neither"],
)
def test_a_failed_resync_fetch_owes_a_rebuild_only_when_it_has_work(
    storage: bool, hook: bool, owed: bool
) -> None:
    """The audit: a subscriber with no replica and no hook was owed a
    rebuild that later ran for nobody (a baseline fetch and a clearing PUT)."""
    from actingweb.callback_processor import CallbackProcessor
    from actingweb.interface.actor_interface import ActorInterface

    config, actor = _setup()
    config._subscription_config.auto_storage = storage  # type: ignore[attr-defined]
    if hook:
        config._subscription_config.subscription_data_hooks = {  # type: ignore[attr-defined]
            "properties": [lambda *a: None]
        }
    with mock.patch.object(
        SubscriptionManager, "_fetch_and_transform_baseline", return_value=None
    ):
        webobj = _post(
            config,
            actor,
            {"sequence": 1, "type": "resync", "url": "https://peer.example/x"},
        )
    assert webobj.response.status_code == 503
    state = CallbackProcessor(ActorInterface(actor)).rebuild_state("peer1", "sub1")
    assert state["owed"] is owed


def _rebuild_answered(
    rebuilt: Any,
    *,
    auto_storage: bool = True,
    data_hook: bool = True,
    legacy_hook: bool = False,
    result: ProcessResult = ProcessResult.REBUILD,
    sync_result: Any = None,
    owe: bool = False,
) -> tuple[Any, list[Any], list[Any], Any, Any]:
    """A diff (sequence 3) whose processing answers ``result``. Returns the
    answer, the data and legacy hooks' calls, the rebuild mock and the
    actor. ``owe`` marks the rebuild owed first."""
    from actingweb.interface.hooks import HookRegistry

    config, actor = _setup()
    config._subscription_config.auto_storage = auto_storage  # type: ignore[attr-defined]
    seen: list[Any] = []
    if data_hook:
        config._subscription_config.subscription_data_hooks = {  # type: ignore[attr-defined]
            "properties": [lambda a, p, t, d, s, k: seen.append((d, k))]
        }
    legacy: list[Any] = []
    hooks = HookRegistry()
    if legacy_hook:
        hooks.register_callback_hook(
            "subscription", lambda a, n, d: legacy.append(d["type"]) or True
        )

    def process(self: Any, **_: Any) -> ProcessResult:
        return result

    if owe:
        _owe(actor)

    webobj = AWWebObj(
        url="https://test.example.com/x",
        body=json.dumps({"sequence": 3, "data": {"status": "paid"}}),
    )
    handler = CallbacksHandler(webobj, config, hooks=hooks)
    check = mock.Mock()
    check.check_authorisation.return_value = True
    check.response = {"code": 200, "text": "Ok", "headers": {}}
    check.acl = {"authenticated": True, "peerid": "peer1", "relationship": "friend"}
    handler._authenticate_dual_context = mock.Mock(  # type: ignore[method-assign]
        return_value=mock.Mock(actor=actor, auth_obj=check)
    )
    with (
        mock.patch.object(CallbackProcessor, "process_callback_sync", process),
        mock.patch.object(
            SubscriptionManager, "_rebuild_owed_and_due", return_value=False
        ),
        mock.patch.object(
            SubscriptionManager, "rebuild_subscription", return_value=rebuilt
        ) as rebuild,
        mock.patch.object(
            SubscriptionManager, "sync_subscription", return_value=sync_result
        ),
    ):
        handler.post(aid(actor), "subscriptions/peer1/sub1")
    return webobj, seen, legacy, rebuild, actor


def _synced(success: bool, sequence: int, baseline: Any = None) -> Any:
    from actingweb.interface.subscription_manager import SubscriptionSyncResult

    return SubscriptionSyncResult(
        subscription_id="sub1",
        success=success,
        diffs_fetched=0,
        diffs_processed=1,
        final_sequence=sequence,
        baseline=baseline,
        error=None if success else "failed",
    )


def test_the_processors_rebuild_tells_no_covered_baseline() -> None:
    """Re-run 6 (Issue 6): the covered branch of the REBUILD answer."""
    covered = dataclasses.replace(
        _synced(True, 3, {"status": "paid"}), baseline_skipped=True
    )
    webobj, seen, _, _, _ = _rebuild_answered(covered)
    assert webobj.response.status_code == 204
    assert [k for _, k in seen] == []


def test_a_rebuild_answer_nobody_hears_drops_the_debt() -> None:
    """Re-run 6 (Issue 6): no replica and no hook: no rebuild runs, and
    the debt is dropped instead of answered again on every callback."""
    _, _, _, rebuild, actor = _rebuild_answered(
        _synced(True, 3, {}), auto_storage=False, data_hook=False
    )
    rebuild.assert_not_called()
    assert _state(actor)["owed"] is False


@pytest.mark.parametrize(
    "storage,data_hook,legacy_hook,owed",
    [
        (False, False, True, True),
        (True, True, True, True),
        (True, False, False, False),
        (False, True, False, False),
    ],
    ids=["legacy only", "replica, data and legacy", "replica only", "data only"],
)
def test_the_gap_resync_owes_a_rebuild_when_a_legacy_hook_hears(
    storage: bool, data_hook: bool, legacy_hook: bool, owed: bool
) -> None:
    """Re-run 6 (Issue 4), re-run 7 (Issue 1): the gap resync's poll tells
    data hooks only, so a registered legacy hook never heard the gap,
    whatever else the subscriber has. The rebuild is owed for it."""
    _, _, _, _, actor = _rebuild_answered(
        _synced(True, 9),
        auto_storage=storage,
        data_hook=data_hook,
        legacy_hook=legacy_hook,
        result=ProcessResult.RESYNC_TRIGGERED,
        sync_result=_synced(True, 9),
    )
    assert _state(actor)["owed"] is owed


def _state(actor: Any) -> Any:
    from actingweb.interface.actor_interface import ActorInterface

    return CallbackProcessor(ActorInterface(actor)).rebuild_state("peer1", "sub1")


def test_a_rebuild_that_did_not_settle_tells_no_hook() -> None:
    """Its callback answers 503; the rebuild stays owed and tells the
    baseline when the next callback or poll after the interval runs it."""
    from actingweb.interface.subscription_manager import SubscriptionSyncResult

    unsettled = SubscriptionSyncResult(
        subscription_id="sub1",
        success=False,
        diffs_fetched=0,
        diffs_processed=1,
        final_sequence=6,
        error="The rebuild stays owed",
    )
    webobj, seen, legacy = _rebuild_on_the_callback(unsettled)
    assert webobj.response.status_code == 503
    assert seen == [] and legacy == []
