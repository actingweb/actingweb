"""Payload summaries are built only when their log line will be emitted.

``summarize_payload`` sat inside eager f-strings and concatenations on
``logger.debug`` calls, so it ran at every level. The subscription callback
sender runs once per subscriber, so it is the site whose cost grows with load.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest import mock

import pytest

from actingweb import actor as actor_module
from actingweb import aw_proxy as aw_proxy_module


def _boom(*args: Any, **kwargs: Any) -> str:
    raise AssertionError("summarize_payload ran with DEBUG off")


@pytest.fixture
def debug_off() -> Any:
    loggers = [
        logging.getLogger("actingweb.actor"),
        logging.getLogger("actingweb.aw_proxy"),
    ]
    saved = [lg.level for lg in loggers]
    for lg in loggers:
        lg.setLevel(logging.WARNING)
    yield
    for lg, level in zip(loggers, saved, strict=True):
        lg.setLevel(level)


def test_a_sync_subscription_callback_does_not_summarise(debug_off: Any) -> None:
    me = actor_module.Actor.__new__(actor_module.Actor)
    me.id = "pub1"
    me.config = mock.Mock(sync_subscription_callbacks=True, root="https://me/")
    trust_rel = {"peerid": "sub1", "baseuri": "https://peer/sub1", "secret": "s"}
    sub = {
        "subscriptionid": "s1",
        "target": "resources",
        "subtarget": None,
        "resource": None,
        "granularity": "high",
        "peerid": "sub1",
    }
    diff = {"sequence": 1, "timestamp": "t"}
    with (
        mock.patch.object(actor_module, "summarize_payload", _boom),
        mock.patch.object(me, "get_trust_relationship", return_value=trust_rel),
        # The transport is tested here, not the grant (3.16 re-check admits).
        mock.patch.object(
            me, "filter_subscription_blob", side_effect=lambda p, s, b, **k: b
        ),
        mock.patch.object(actor_module.requests, "post") as post,
    ):
        post.return_value = mock.Mock(status_code=204, content=b"")
        me.callback_subscription(peerid="sub1", sub=sub, diff=diff, blob='{"a": 1}')
    post.assert_called_once()


def test_a_peer_request_does_not_summarise(debug_off: Any) -> None:
    class _Trust(dict[str, Any]):
        # AwProxy keeps the trust target itself and indexes it like a row.
        trust = True
        id = "me1"

    target = _Trust(baseuri="https://peer/p1", secret="s", peerid="p1")
    proxy = aw_proxy_module.AwProxy(trust_target=target, config=mock.Mock())
    with (
        mock.patch.object(aw_proxy_module, "summarize_payload", _boom),
        mock.patch.object(aw_proxy_module.requests, "post") as post,
    ):
        post.return_value = mock.Mock(status_code=201, content=b"{}", headers={})
        proxy.create_resource(path="trust/friend", params={"x": 1})
    post.assert_called_once()
