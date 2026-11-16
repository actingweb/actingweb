"""What a receiver does with a callback (specification 1.5, spec-1-5 Phase 3):
a failed resync fetch answers 503 and owes the rebuild, a baseline is told
apart from a failure by the wire, and a diff with data needs a sequence."""

from __future__ import annotations

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
