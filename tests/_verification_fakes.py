"""Verification GETs through ``requests.get`` in tests that fake peers.

A verification reads its peer through ``actingweb.actor._verification_get``
(a session whose sockets the caller can shut down; 3.16). Tests that fake a
peer's answers patch ``actingweb.actor.requests.get``; this fixture routes
the verification there, with the same arguments, so those fakes see every
verification GET. The real path is tested on its own, against a real slow
socket (``tests/test_trust_re_pair.py``, ``TestTheSocketIsShutDown``).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest


@pytest.fixture
def verification_through_requests_get(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    from actingweb import actor as actor_module

    def through_requests_get(
        url: str, headers: dict[str, str], sockets: list[Any], timeout: Any
    ) -> Any:
        return actor_module.requests.get(
            url=url,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
            stream=True,
        )

    monkeypatch.setattr(actor_module, "_verification_get", through_requests_get)
    yield
