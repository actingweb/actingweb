"""One glob engine: escapes, linear time, and the three entry points (3.16).

``\\*``, ``\\?`` and ``\\\\`` escape; there are no character classes; matching
is case-sensitive and linear in the pattern and target, because permission
callback and property-filter patterns come from peers.
"""

import time

import pytest

from actingweb.permission_evaluator import (
    _PATTERN_CACHE_MAX_ENTRIES,
    _compile_glob,
    glob_has_wildcard,
    glob_match,
)


@pytest.mark.parametrize(
    ("target", "pattern", "expected"),
    [
        ("a*b", "a\\*b", True),
        ("axb", "a\\*b", False),
        ("a\\*b", "a\\*b", False),  # the escape is not matched as text
        ("a?b", "a\\?b", True),
        ("axb", "a\\?b", False),
        ("a\\b", "a\\\\b", True),
        ("a\\", "a\\", True),  # a trailing lone backslash is literal
        ("\\anything", "\\\\*", True),
        ("anything", "\\\\*", False),
        ("", "", True),
        ("x", "", False),
        ("anything\nat all", "*", True),
        ("[abc]", "[abc]", True),
        ("a", "[abc]", False),
        ("ABC", "abc", False),  # case-sensitive
        ("notes://work/x", "notes://", True),
        ("a*://zz", "a\\*://", True),  # an escaped star is not a wildcard
        ("a\n", "a*", True),
        ("abab", "a*b", True),
        ("abc", "a?c", True),
    ],
)
def test_glob_match(target: str, pattern: str, expected: bool) -> None:
    assert glob_match(target, pattern) is expected


def test_the_equality_shortcut_still_answers_for_a_plain_pattern() -> None:
    assert glob_match("plain", "plain") is True


def test_escaped_wildcards_are_not_wildcards() -> None:
    assert glob_has_wildcard("a*") is True
    assert glob_has_wildcard("a\\*") is False
    assert glob_has_wildcard("a\\\\*") is True  # an escaped backslash, then a star


def test_many_stars_do_not_backtrack() -> None:
    pattern = "*" * 40 + "a"
    target = "x" * 4000
    start = time.perf_counter()
    assert glob_match(target, pattern) is False
    assert time.perf_counter() - start < 0.05


def test_the_cache_is_an_lru_not_a_clear_all() -> None:
    _compile_glob.cache_clear()
    for i in range(_PATTERN_CACHE_MAX_ENTRIES + 1):
        glob_match("x", f"p{i}_*")
    assert _compile_glob.cache_info().currsize == _PATTERN_CACHE_MAX_ENTRIES


def test_two_threads_matching_concurrently_raise_nothing() -> None:
    import threading

    errors: list[BaseException] = []

    def run() -> None:
        try:
            for i in range(300):
                glob_match("abc", f"a*{i % 7}c")
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


class TestEntryPoints:
    """The peer-permission and callbacks matchers use the same engine."""

    def test_peer_permissions_glob_match(self) -> None:
        from actingweb.peer_permissions import PeerPermissions

        peer = object.__new__(PeerPermissions)
        assert peer._glob_match("a*b", "a\\*b") is True
        assert peer._glob_match("axb", "a\\*b") is False
        assert peer._glob_match("[abc]", "[abc]") is True
        assert peer._glob_match("ABC", "abc") is False  # no case folding

    def test_peer_permissions_is_linear_time(self) -> None:
        from actingweb.peer_permissions import PeerPermissions

        peer = object.__new__(PeerPermissions)
        start = time.perf_counter()
        assert peer._glob_match("x" * 4000, "*" * 40 + "a") is False
        assert time.perf_counter() - start < 0.05

    def test_callbacks_handler_uses_the_engine(self) -> None:
        from actingweb.handlers import callbacks

        assert callbacks.glob_match is glob_match
        assert callbacks._has_wildcard("a*") is True
        assert callbacks._has_wildcard("plain") is False
        assert callbacks._has_wildcard("[abc]") is False  # no character classes
        assert callbacks._has_wildcard("a\\*b") is True  # goes through the matcher

    def _revoke(self, lists: list[str], patterns: list[str]) -> list[str]:
        """Run the callbacks revoke path over a fake peer store; return the
        list names it deleted."""
        from unittest import mock

        from actingweb.handlers.callbacks import CallbacksHandler

        handler = object.__new__(CallbacksHandler)
        store = mock.MagicMock()
        store.list_all_lists.return_value = lists
        with mock.patch("actingweb.remote_storage.RemotePeerStore", return_value=store):
            handler._delete_revoked_peer_data(mock.MagicMock(), "peer1", patterns)
        return [c.args[0] for c in store.delete_list.call_args_list]

    def test_callbacks_revoke_reads_brackets_literally(self) -> None:
        deleted = self._revoke(["[abc]", "a", "b"], ["[abc]"])
        assert deleted == ["[abc]"]

    def test_callbacks_revoke_is_linear_time(self) -> None:
        start = time.perf_counter()
        assert self._revoke(["x" * 4000], ["*" * 40 + "a"]) == []
        assert time.perf_counter() - start < 0.05

    def test_no_fnmatch_left_in_the_library(self) -> None:
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parent.parent / "actingweb"
        offenders = [
            str(path)
            for path in root.rglob("*.py")
            if re.search(r"^\s*(import fnmatch|from fnmatch)", path.read_text(), re.M)
        ]
        assert offenders == []
