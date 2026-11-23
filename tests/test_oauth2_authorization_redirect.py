"""The redirect back to an OAuth2 client keeps the registered URI intact.

4.0.0rc2 joined the code with a bare ``?``: a registered redirect URI that
already had a query got a second one, and the client's ``code`` and
``state`` landed inside the value of its last parameter. The denial path
picked ``&`` by a substring test, which a fragment defeats.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from actingweb.oauth2_server.oauth2_server import (
    ActingWebOAuth2Server,
    redirect_with_params,
)


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query, keep_blank_values=True)


def test_a_redirect_uri_with_a_query_keeps_it() -> None:
    url = redirect_with_params(
        "https://client.example.test/cb?tenant=a&mode=x",
        {"code": "c0de", "state": "s 9"},
    )
    assert url.count("?") == 1
    assert _query(url) == {
        "tenant": ["a"],
        "mode": ["x"],
        "code": ["c0de"],
        "state": ["s 9"],
    }
    assert url.startswith("https://client.example.test/cb?tenant=a&mode=x&")


def test_a_redirect_uri_without_a_query_is_unchanged() -> None:
    """The exact string rc2 produced."""
    url = redirect_with_params(
        "https://client.example.test/cb", {"code": "c0de", "state": "client-state-1"}
    )
    assert url == "https://client.example.test/cb?code=c0de&state=client-state-1"


@pytest.mark.parametrize(
    "registered",
    [
        "https://client.example.test/cb#frag",
        "https://client.example.test/cb?tenant=a#frag",
    ],
)
def test_a_fragment_does_not_swallow_the_code(registered: str) -> None:
    url = redirect_with_params(registered, {"code": "c0de"})
    parts = urlsplit(url)
    assert parse_qs(parts.query)["code"] == ["c0de"]
    assert parts.fragment == "frag"
    assert "code" not in parts.fragment


def test_a_fragment_and_an_existing_parameter_are_not_corrupted() -> None:
    """A registered URI that carries its own ``code`` keeps it; the
    authorization code is appended after it, in the query."""
    url = redirect_with_params(
        "https://client.example.test/cb?code=theirs&x=%26y#f", {"code": "ours"}
    )
    parts = urlsplit(url)
    assert parse_qs(parts.query) == {"code": ["theirs", "ours"], "x": ["&y"]}
    assert parts.query.startswith("code=theirs&x=%26y&")
    assert parts.fragment == "f"


def test_a_custom_scheme_and_a_loopback_port_survive() -> None:
    assert (
        redirect_with_params("com.example.app:/oauth", {"code": "c"})
        == "com.example.app:/oauth?code=c"
    )
    assert (
        redirect_with_params("http://127.0.0.1:53682/cb?a=1", {"code": "c"})
        == "http://127.0.0.1:53682/cb?a=1&code=c"
    )


def test_a_denial_keeps_the_query() -> None:
    server = object.__new__(ActingWebOAuth2Server)
    answer = server._denied("https://client.example.test/cb?tenant=a#f", "st-1")
    assert answer["action"] == "redirect"
    parts = urlsplit(answer["url"])
    assert parse_qs(parts.query) == {
        "tenant": ["a"],
        "error": ["access_denied"],
        "state": ["st-1"],
    }
    assert parts.fragment == "f"
