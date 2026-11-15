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


def _setup(subtarget: str = "") -> tuple[Any, Any]:
    config = make_config()
    config._subscription_config = SubscriptionProcessingConfig(  # type: ignore[attr-defined]
        enabled=True, auto_sequence=True, auto_storage=True
    )
    actor = create_core_actor(config, uuid_email())
    assert Subscription(
        actor_id=aid(actor), peerid="peer1", subid="sub1", callback=True, config=config
    ).create(target="properties", subtarget=subtarget, granularity="high")
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


@pytest.mark.parametrize("subtarget", ["", "color"])
@pytest.mark.parametrize(
    "proxy",
    [
        _proxy({"error": {"code": 502}}, 502),
        _proxy(None, 408),
        _proxy({"a": 1}, 200, redirected=True),
    ],
)
def test_a_resync_whose_fetch_fails_is_503_and_owes_the_rebuild(
    subtarget: str, proxy: Any
) -> None:
    config, actor = _setup(subtarget)
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
