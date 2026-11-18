"""What a 3.15.1 peer sends, answered by this release.

The other wire rows are this library talking to itself. These rows play the
previous release by hand: each request is built in the form an application
on ``actingweb==3.15.1`` sent in a live pair with this tree
(``scripts/live_pair.py``; the table is in
``thoughts/research/2026-11-18-3-16-release-validation.md``), with the
scenario's own ids and secrets. The release no longer sends these forms and
still has to answer them:

- WV1: a data callback stamped ``YYYY-MM-DD HH:MM:SS.ffffff`` (no zone);
- WV2: a resync callback stamped with a ``+00:00`` offset;
- WV3: a write below a property, sent as the changed part only;
- WV4: a second trust request for a peer already trusted, sent without a
  bearer and with a new secret. Refused since 4.0 (the re-pair rule), and
  the trust the release holds is left as it was.

One file serves both backends; one topology, since the peer is the test.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import requests

from ._wire import Scenario, check
from .test_wire_peer_paths import _bearer, _put, _replica_settles, _subid

pytestmark = [pytest.mark.wire, pytest.mark.xdist_group(name="wire_peer_paths")]

# The two timestamp forms 3.15.1 put in a subscription callback: the data
# callback's ``str(datetime.utcnow())`` and the resync callback's
# ``datetime.now(UTC).isoformat()``.
V315_DATA_TIMESTAMP = "2026-01-20 12:00:00.123456"
V315_RESYNC_TIMESTAMP = "2026-01-20T12:00:01.123456+00:00"


def _callback_url(s: Scenario) -> str:
    a, b = s.publisher, s.subscribers[0]
    return f"{b.url}/callbacks/subscriptions/{a.id}/{_subid(s)}"


def _data_callback(s: Scenario, sequence: int, data: Any) -> dict[str, Any]:
    """A high-granularity callback as 3.15.1 built it for a whole-target
    subscription: no ``subtarget`` key, the space-separated timestamp."""
    return {
        "id": s.publisher.id,
        "subscriptionid": _subid(s),
        "target": "properties",
        "sequence": sequence,
        "timestamp": V315_DATA_TIMESTAMP,
        "granularity": "high",
        "data": data,
    }


def _post_callback(s: Scenario, body: dict[str, Any]) -> requests.Response:
    return requests.post(_callback_url(s), json=body, headers=_bearer(s))


def test_wv1_data_callback(wire_pair):
    """WV1: 3.15.1's data callback is accepted and applied."""
    s = wire_pair("same_host", grant=["*"])
    s.step(
        "a data callback in 3.15.1's form",
        lambda: _post_callback(s, _data_callback(s, 1, {"note": {"text": "pushed"}})),
        settle=_replica_settles(s, lambda r: "note" in r["scalars"]),
    )
    check("WV1", s.recording())


def test_wv2_resync_callback(wire_pair):
    """WV2: 3.15.1's resync callback is accepted; B fetches the baseline."""
    s = wire_pair("same_host", grant=["*"])
    a = s.publisher
    s.step(
        "A writes",
        lambda: _put(a, "note", {"text": "first"}),
        settle=_replica_settles(s, lambda r: "note" in r["scalars"]),
    )
    body = {
        "id": a.id,
        "subscriptionid": _subid(s),
        "target": "properties",
        "subtarget": "",
        "sequence": 2,
        "timestamp": V315_RESYNC_TIMESTAMP,
        "granularity": "high",
        "type": "resync",
        "url": f"{a.url}/properties",
    }
    s.step("a resync callback in 3.15.1's form", lambda: _post_callback(s, body))
    check("WV2", s.recording())


def test_wv3_nested_write(wire_pair):
    """WV3: 3.15.1 sent a write below a property as the changed part only.
    The release stores what it is sent, so its replica of a 3.15.1 publisher
    keeps the changed part until a poll rebuilds it (as a 3.15.1 subscriber
    did)."""
    s = wire_pair("same_host", grant=["*"])
    s.step(
        "the whole value",
        lambda: _post_callback(
            s, _data_callback(s, 1, {"doc": {"a": {"b": 1}, "c": 2}})
        ),
        settle=_replica_settles(s, lambda r: "doc" in r["scalars"]),
    )
    s.step(
        "a write below it, as the changed part",
        lambda: _post_callback(s, _data_callback(s, 2, {"doc": {"a": {"b": 2}}})),
        settle=_replica_settles(
            s, lambda r: (r["scalars"].get("doc") or {}).get("a") == {"b": 2}
        ),
    )
    check("WV3", s.recording())


def test_wv4_second_trust_request(wire_pair):
    """WV4: a 3.15.1 application asks again for a trust it already has: a
    plain request with a new secret and no bearer. Refused, and A's row for
    B stays approved with its secret."""
    s = wire_pair("same_host", grant=["*"])
    a, b = s.publisher, s.subscribers[0]
    new_secret = uuid.uuid4().hex + uuid.uuid4().hex
    verify = uuid.uuid4().hex
    s.name(new_secret, "trust:A-B#2", secret=True)
    s.name(verify, "verify:B", secret=True)
    body = {
        "baseuri": b.url,
        "id": b.id,
        "type": "urn:actingweb:test:integration",
        "secret": new_secret,
        "desc": "",
        "verify": verify,
    }
    s.step(
        "B's second request, as 3.15.1 sends it",
        lambda: requests.post(f"{a.url}/trust/friend", json=body),
    )
    check("WV4", s.recording())
