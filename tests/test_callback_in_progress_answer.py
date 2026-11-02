"""A callback whose sequence another delivery is handling answers 503, not
204 (3.16, owner-decided plan D13).

A 204 to a high-granularity callback clears the diff on the publisher, which
does not retry; if the delivery holding the claim then fails, the diff would
be lost. 503 with ``Retry-After`` keeps it.
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

import pytest

from actingweb.aw_web_request import AWWebObj
from actingweb.callback_processor import CallbackProcessor, ProcessResult
from actingweb.handlers.callbacks import CallbacksHandler
from actingweb.subscription import Subscription
from actingweb.subscription_config import SubscriptionProcessingConfig
from tests._adoption_helpers import aid, create_core_actor, make_config, uuid_email


@pytest.mark.parametrize(
    "result,status",
    [(ProcessResult.IN_PROGRESS, 503), (ProcessResult.DUPLICATE, 204)],
)
def test_the_answer_to_a_claimed_sequence(result: ProcessResult, status: int) -> None:
    config = make_config()
    config._subscription_config = SubscriptionProcessingConfig(  # type: ignore[attr-defined]
        enabled=True, auto_sequence=True, auto_storage=False
    )
    actor = create_core_actor(config, uuid_email())
    assert Subscription(
        actor_id=aid(actor), peerid="peer1", subid="sub1", callback=True, config=config
    ).create(target="properties", granularity="high")
    body = {"sequence": 1, "data": {"note": "x"}}
    webobj = AWWebObj(url="https://test.example.com/x", body=json.dumps(body))
    handler = CallbacksHandler(webobj, config)
    check = mock.Mock()
    check.check_authorisation.return_value = True
    handler._authenticate_dual_context = mock.Mock(  # type: ignore[method-assign]
        return_value=mock.Mock(actor=actor, auth_obj=check)
    )

    def answer(self: Any, **_k: Any) -> ProcessResult:
        return result

    with mock.patch.object(CallbackProcessor, "process_callback_sync", answer):
        handler.post(aid(actor), "subscriptions/peer1/sub1")

    assert webobj.response.status_code == status
    if status == 503:
        assert webobj.response.headers.get("Retry-After") == "5"
        assert (
            webobj.response.headers.get("X-ActingWeb-Error") == "callback_in_progress"
        )


def test_a_low_granularity_diff_that_cannot_be_fetched_is_not_processed() -> None:
    """A second delivery's fetch can find the diff gone (the first fetch
    deleted it): that is not an empty diff, so nothing advances and the
    answer is 503."""
    config = make_config()
    config._subscription_config = SubscriptionProcessingConfig(  # type: ignore[attr-defined]
        enabled=True, auto_sequence=True, auto_storage=False
    )
    actor = create_core_actor(config, uuid_email())
    assert Subscription(
        actor_id=aid(actor), peerid="peer1", subid="sub1", callback=True, config=config
    ).create(target="properties", granularity="low")
    body = {"sequence": 1, "url": "https://peer.example.com/diff/1"}
    webobj = AWWebObj(url="https://test.example.com/x", body=json.dumps(body))
    handler = CallbacksHandler(webobj, config)
    check = mock.Mock()
    check.check_authorisation.return_value = True
    handler._authenticate_dual_context = mock.Mock(  # type: ignore[method-assign]
        return_value=mock.Mock(actor=actor, auth_obj=check)
    )
    gone = mock.Mock(status_code=404)
    client = mock.MagicMock()
    client.__enter__.return_value.get.return_value = gone
    with (
        mock.patch("httpx.Client", return_value=client),
        mock.patch("actingweb.trust.Trust") as trust,
        mock.patch.object(CallbackProcessor, "process_callback_sync") as process,
    ):
        trust.return_value.get.return_value = {"secret": "s"}
        handler.post(aid(actor), "subscriptions/peer1/sub1")

    process.assert_not_called()
    assert webobj.response.status_code == 503


def _low_granularity_handler(granularity: str = "low") -> tuple[Any, Any, Any]:
    config = make_config()
    config._subscription_config = SubscriptionProcessingConfig(  # type: ignore[attr-defined]
        enabled=True, auto_sequence=True, auto_storage=False
    )
    actor = create_core_actor(config, uuid_email())
    assert Subscription(
        actor_id=aid(actor), peerid="peer1", subid="sub1", callback=True, config=config
    ).create(target="properties", granularity=granularity)
    body = {"sequence": 1, "url": "https://peer.example.com/diff/1"}
    webobj = AWWebObj(url="https://test.example.com/x", body=json.dumps(body))
    handler = CallbacksHandler(webobj, config)
    check = mock.Mock()
    check.check_authorisation.return_value = True
    handler._authenticate_dual_context = mock.Mock(  # type: ignore[method-assign]
        return_value=mock.Mock(actor=actor, auth_obj=check)
    )
    return handler, webobj, actor


@pytest.mark.parametrize(
    "early,status", [(ProcessResult.DUPLICATE, 204), (ProcessResult.IN_PROGRESS, 503)]
)
def test_a_low_granularity_callback_is_decided_before_its_fetch(
    early: ProcessResult, status: int
) -> None:
    """The publisher deletes a low-granularity diff when it is fetched: a
    redelivery of an applied sequence answers 204 and an in-progress one 503,
    both without fetching."""
    handler, webobj, actor = _low_granularity_handler()
    with (
        mock.patch("httpx.Client") as client,
        mock.patch.object(CallbackProcessor, "precheck", return_value=early),
        mock.patch.object(CallbackProcessor, "process_callback_sync") as process,
    ):
        handler.post(aid(actor), "subscriptions/peer1/sub1")
    client.assert_not_called()
    process.assert_not_called()
    assert webobj.response.status_code == status


def test_a_resync_whose_baseline_cannot_be_fetched_is_not_processed() -> None:
    """A failed baseline fetch is not an empty baseline: applying {} would
    reset the state and move the sequence past data never applied."""
    config = make_config()
    config._subscription_config = SubscriptionProcessingConfig(  # type: ignore[attr-defined]
        enabled=True, auto_sequence=True, auto_storage=True
    )
    actor = create_core_actor(config, uuid_email())
    assert Subscription(
        actor_id=aid(actor), peerid="peer1", subid="sub1", callback=True, config=config
    ).create(target="properties", granularity="high")
    body = {"sequence": 5, "type": "resync", "url": "https://peer.example.com/p"}
    webobj = AWWebObj(url="https://test.example.com/x", body=json.dumps(body))
    handler = CallbacksHandler(webobj, config)
    check = mock.Mock()
    check.check_authorisation.return_value = True
    handler._authenticate_dual_context = mock.Mock(  # type: ignore[method-assign]
        return_value=mock.Mock(actor=actor, auth_obj=check)
    )
    from actingweb.interface.subscription_manager import SubscriptionManager

    with (
        mock.patch.object(
            SubscriptionManager, "_fetch_and_transform_baseline", return_value=None
        ),
        mock.patch.object(CallbackProcessor, "process_callback_sync") as process,
    ):
        handler.post(aid(actor), "subscriptions/peer1/sub1")
    process.assert_not_called()
    assert webobj.response.status_code == 503
