"""Exclusions hold on the whole property tree (3.16).

``thoughts/plans/2026-11-10-grant-enforcement-per-route.md``, Phase 1: an
exclusion covers its node and the node's descendants, a pattern ending in
``/*`` names the node before it too, and a value read by a peer loses its
excluded descendants at any depth. The functions are pure; the real
evaluator applies them for properties and resources alike.
"""

from __future__ import annotations

from typing import Any

import pytest

from actingweb import permission_evaluator as pe
from actingweb.permission_evaluator import (
    PermissionEvaluator,
    PermissionResult,
    PermissionType,
    drop_excluded,
    holds_excluded,
    path_excluded,
)


def _rules(*excluded: str, **extra: Any) -> dict[str, Any]:
    return {
        "patterns": ["*"],
        "operations": ["read", "write"],
        "excluded_patterns": list(excluded),
        **extra,
    }


def _evaluator() -> PermissionEvaluator:
    ev = object.__new__(PermissionEvaluator)
    ev.config = None  # type: ignore[assignment]
    return ev


@pytest.mark.parametrize(
    ("pattern", "path", "excluded"),
    [
        ("private/*", "private", True),
        ("private/*", "private/a", True),
        ("private/*", "private/a/b", True),
        ("private/*", "privateer", False),
        ("settings/private", "settings/private", True),
        ("settings/private", "settings/private/x", True),
        ("settings/private", "settings", False),
        ("memory_personal", "memory_personal/0", True),
        ("memory_*", "memory_personal/x", True),
        ("*/deep/private", "settings/deep/private", True),
        ("*/deep/private", "settings/deep", False),
        ("*private*", "a/b/myprivatething/c", True),
        ("mem*/x", "memory/x/y", True),
        # Escaped: a literal star, and a literal "/*" names no node
        ("a\\*", "a*", True),
        ("a\\*", "ab", False),
        ("b/\\*", "b", False),
        ("b/\\*", "b/*", True),
    ],
)
def test_path_excluded(pattern: str, path: str, excluded: bool) -> None:
    assert path_excluded(_rules(pattern), path) is excluded


def test_denied_entries_exclude_too() -> None:
    assert path_excluded({"allowed": ["*"], "denied": ["secret/*"]}, "secret")


def test_no_exclusion_nothing_excluded() -> None:
    assert not path_excluded(_rules(), "anything/at/all")
    assert not path_excluded(["*"], "x")


SETTINGS = {"theme": "x", "private": "s", "deep": {"private": "d", "ok": 1}}


@pytest.mark.parametrize(
    ("excluded", "path", "value", "kept"),
    [
        (
            "settings/private",
            "settings",
            SETTINGS,
            {"theme": "x", "deep": SETTINGS["deep"]},
        ),
        ("*/deep/private", "settings", SETTINGS, {**SETTINGS, "deep": {"ok": 1}}),
        ("*/deep/private", "settings/deep", SETTINGS["deep"], {"ok": 1}),
        ("a/b/c", "a", {"b": {"c": {"d": 1}, "e": 2}}, {"b": {"e": 2}}),
        ("settings/*", "settings", SETTINGS, {}),
        ("x/*", "x", "a string", "a string"),
        ("x/0", "x", [{"a": 1}], [{"a": 1}]),  # arrays are not descended
        ("t/*", "", {"t": {"a": 1}, "u": 2}, {"u": 2}),
    ],
)
def test_drop_excluded(excluded: str, path: str, value: Any, kept: Any) -> None:
    assert drop_excluded(_rules(excluded), path, value) == kept


def test_drop_excluded_does_not_walk_without_exclusions(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(pe, "_excluded_by", lambda *a: calls.append(a) or False)
    value = {"a": {"b": {"c": 1}}}
    assert drop_excluded(_rules(), "p", value) is value
    assert calls == []


def test_drop_excluded_visits_each_node_once(monkeypatch) -> None:
    """The walk is linear in the value's size (a wide pattern on a large
    object): each node is decided once."""
    seen: list[str] = []
    real = pe._excluded_by
    monkeypatch.setattr(
        pe,
        "_excluded_by",
        lambda patterns, node: seen.append(node) or real(patterns, node),
    )
    value = {f"k{i}": {f"j{j}": j for j in range(10)} for i in range(10)}
    drop_excluded(_rules("*token*"), "p", value)
    assert len(seen) == 10 + 100
    assert len(set(seen)) == len(seen)


def test_holds_excluded() -> None:
    rules = _rules("settings/private")
    assert holds_excluded(rules, "settings", SETTINGS)
    assert not holds_excluded(rules, "settings", {"theme": "y"})
    assert holds_excluded(rules, "settings", {"theme": "y"}, {"private": "new"})
    assert not holds_excluded(rules, "color", "red")


@pytest.mark.parametrize("kind", [PermissionType.PROPERTIES, PermissionType.RESOURCES])
def test_the_evaluator_applies_the_tree_rule(kind: PermissionType) -> None:
    ev = _evaluator()
    rules = _rules("private/*")
    assert (
        ev.evaluate_rules_for(kind, rules, "private", "read") == PermissionResult.DENIED
    )
    assert (
        ev.evaluate_rules_for(kind, rules, "private/a/b", "read")
        == PermissionResult.DENIED
    )
    assert (
        ev.evaluate_rules_for(kind, rules, "public", "read") == PermissionResult.ALLOWED
    )


@pytest.mark.parametrize("kind", [PermissionType.PROPERTIES, PermissionType.RESOURCES])
def test_a_stated_rule_that_does_not_match_denies(kind: PermissionType) -> None:
    ev = _evaluator()
    assert (
        ev.evaluate_rules_for(kind, {"allowed": ["notes"]}, "color", "read")
        == PermissionResult.DENIED
    )
    assert ev.evaluate_rules_for(kind, {}, "color", "read") == PermissionResult.DENIED
    # A listing (empty target) is decided per name by the caller.
    assert (
        ev.evaluate_rules_for(
            kind, {"patterns": ["a"], "operations": ["read"]}, "", "read"
        )
        == PermissionResult.NOT_FOUND
    )


def test_methods_and_actions_keep_not_found_this_phase() -> None:
    ev = _evaluator()
    assert (
        ev.evaluate_rules_for(PermissionType.METHODS, [], "wire_import", "call")
        == PermissionResult.NOT_FOUND
    )
    assert (
        ev.evaluate_rules_for(
            PermissionType.ACTIONS, {"allowed": ["a"]}, "b", "execute"
        )
        == PermissionResult.NOT_FOUND
    )


def _grant(rules: dict[str, Any]):
    from actingweb.permission_evaluator import GrantSnapshot

    return GrantSnapshot(
        actor_id="a1",
        peer_id="p1",
        has_row=True,
        approved=True,
        relationship="friend",
        is_client=False,
        permissions={"properties": rules},
    )


def test_the_full_state_fallback_drops_excluded_children_at_their_paths() -> None:
    """The fallback's state for a subtarget is wrapped one level deeper than
    a diff (``{subtarget: value}``): filtered where it is built, at the
    true paths; a list's state is not descended."""
    import json as _json
    from unittest import mock

    from actingweb.actor import Actor

    actor = object.__new__(Actor)
    rules = _rules("settings/private", "notes/items")
    with mock.patch.object(Actor, "grant_for", return_value=_grant(rules)):
        state = {"settings": _json.dumps(SETTINGS)}
        kept = actor._filter_full_state("p1", "settings", state, set())
        assert _json.loads(kept["settings"]) == {"theme": "x", "deep": SETTINGS["deep"]}
        whole = {
            "settings": SETTINGS,
            "notes": {"list": "notes", "operation": "extend", "items": [1]},
        }
        kept = actor._filter_full_state("p1", "", whole, {"notes"})
        assert kept["settings"] == {"theme": "x", "deep": SETTINGS["deep"]}
        assert kept["notes"] == whole["notes"]
    with mock.patch.object(Actor, "grant_for", return_value=None):
        # No grant to read: left to the pull filter, which sends nothing.
        assert actor._filter_full_state("p1", "", whole, set()) == whole
