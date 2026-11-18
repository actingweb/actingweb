"""A granted text property reaches the subscriber's replica as text (4.0).

When A widens its grant to B by a property whose value is text that is not
JSON, B's permission callback fetches the property; the proxy answers such a
body as ``{}``, which was stored. Both backends; both topologies.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests

from ._wire import Scenario, wait_until

pytestmark = [pytest.mark.xdist_group(name="wire_peer_paths")]

TEXT = "hello there, not JSON"


def _grant(*, excluding: list[str]) -> dict[str, Any]:
    # An override unions with the trust type's patterns ("*" for a friend):
    # the property is kept out by an exclusion, then granted by name.
    patterns = ["*"] if excluding else ["*", "note"]
    return {
        "patterns": patterns,
        "operations": ["read"],
        "excluded_patterns": excluding,
    }


def _replica_value(s: Scenario) -> Any:
    from actingweb.remote_storage import RemotePeerStore

    a, b = s.publisher, s.subscribers[0]
    return RemotePeerStore(b.interface(), a.id, validate_peer_id=False).get_value(
        "note"
    )


@pytest.mark.parametrize("topology", ["same_host", "two_hosts"])
def test_grant_of_a_text_property(wire_pair: Any, topology: str) -> None:
    s = wire_pair(topology, grant=_grant(excluding=["note"]))
    a, b = s.publisher, s.subscribers[0]
    put = requests.put(
        f"{a.url}/properties/note",
        data=TEXT,
        headers={"Content-Type": "text/plain"},
        auth=a.basic,
    )
    assert put.status_code in (200, 201, 204), put.text
    assert _replica_value(s) is None
    granted = requests.put(
        f"{a.url}/trust/{s.relationship}/{b.id}/permissions",
        json={"properties": _grant(excluding=[])},
        auth=a.basic,
    )
    assert granted.status_code in (200, 201, 204), granted.text
    wait_until(lambda: _replica_value(s) is not None)
    assert _replica_value(s) == {"value": TEXT}
