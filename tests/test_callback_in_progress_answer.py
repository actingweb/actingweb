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
