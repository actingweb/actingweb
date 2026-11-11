"""The grant filter sees stored objects that arrive as JSON text (3.16,
verification 2026-11-10 of the grant-enforcement plan, Issues 1 and 2).

The stores hand a property back as the text the database holds, and a
property can be written as the text of an object (a form post, an SDK write
of a JSON string). The filter only walks objects, so the developer views
read and overwrote excluded parts, and a diff carrying such a value reached
subscribers unfiltered, while a direct REST read (which parses) did not.
The view tests use real storage and a freshly loaded actor (the earlier test
used a store of dicts); both backends through ``DATABASE_BACKEND``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from actingweb.actor import _EMPTIED, Actor
from actingweb.interface.actor_interface import ActorInterface
from actingweb.interface.authenticated_views import PermissionError
from actingweb.trust_permissions import TrustPermissions, get_trust_permission_store
from tests._adoption_helpers import aid
from tests.test_grant_edges import UNDER, WHOLE
from tests.test_grant_edges import actor as actor  # the fixture, shared
from tests.test_trust_re_pair import Receiver

SETTINGS = {"theme": "x", "private": "s"}


def _world() -> tuple[Receiver, str]:
    """A with friend B granted every property but ``settings/private``, and
    ``settings`` stored by the owner."""
    w = Receiver()
    assert get_trust_permission_store(w.config).store_permissions(
        TrustPermissions(
            actor_id=aid(w.a),
            peer_id=w.b,
            trust_type="friend",
            properties={
                "patterns": ["*"],
                "operations": ["read", "write", "delete"],
                "excluded_patterns": ["settings/private"],
            },
        ),
        notify_peer=False,
    )
    assert w.a.property is not None
    w.a.property["settings"] = json.dumps(SETTINGS)
    w.a.property["color"] = "blue"
    return w, w.b


def _fresh_view(w: Receiver, peer: str) -> Any:
    """B's view on a freshly loaded A (nothing cached from the write)."""
    fresh = Actor(aid(w.a), config=w.config)
    return ActorInterface(fresh).as_peer(peer).properties


def _stored(w: Receiver) -> Any:
    fresh = Actor(aid(w.a), config=w.config)
    assert fresh.property is not None
    return json.loads(fresh.property["settings"])


class TestTheViews:
    def test_a_read_drops_the_excluded_part_and_keeps_the_type(self) -> None:
        w, peer = _world()
        view = _fresh_view(w, peer)
        value = view["settings"]
        assert isinstance(value, str)
        assert json.loads(value) == {"theme": "x"}
        assert json.loads(view.get("settings")) == {"theme": "x"}
        assert json.loads(view.to_dict()["settings"]) == {"theme": "x"}
        assert view["color"] == "blue"

    def test_a_write_over_a_stored_excluded_part_is_refused(self) -> None:
        w, peer = _world()
        view = _fresh_view(w, peer)
        with pytest.raises(PermissionError):
            view["settings"] = {"theme": "y"}
        with pytest.raises(PermissionError):
            del view["settings"]
        assert _stored(w) == SETTINGS
        view["color"] = "red"  # nothing excluded there


def _filtered(actor: Any, sub: dict[str, Any], blob: Any) -> Any:
    out = actor.filter_subscription_blob("p1", sub, json.dumps(blob))
    return json.loads(out) if out is not None else None


class TestTheDiffFilter:
    def test_a_whole_target_value_given_as_text_is_filtered(self, actor) -> None:
        blob = {"settings": json.dumps({"theme": "y", "private": "s"}), "c": 1}
        assert _filtered(actor, WHOLE, blob) == {
            "settings": json.dumps({"theme": "y"}),
            "c": 1,
        }

    def test_a_value_of_only_excluded_parts_is_not_sent(self, actor) -> None:
        assert (
            _filtered(actor, WHOLE, {"settings": json.dumps({"private": "s"})}) is None
        )

    def test_a_subtarget_value_given_as_text_is_filtered(self, actor) -> None:
        text = json.dumps({"theme": "y", "private": "s"})
        assert _filtered(actor, UNDER, text) == json.dumps({"theme": "y"})
        assert _filtered(actor, UNDER, json.dumps({"private": "s"})) is None

    def test_plain_text_is_sent_as_it_is(self, actor) -> None:
        assert _filtered(actor, WHOLE, {"settings": "not json"}) == {
            "settings": "not json"
        }
        assert _filtered(actor, UNDER, "plain") == "plain"


class TestOtherTargetsAtDelivery:
    """Verification Issue 3: a subscription to a target other than
    ``properties`` is asked the creation check again when a diff is
    delivered, so a grant narrowed after it was made delivers nothing."""

    @staticmethod
    def _grant(resources: dict[str, Any]) -> Any:
        from actingweb.permission_evaluator import GrantSnapshot

        return GrantSnapshot(
            actor_id="a1",
            peer_id="p1",
            has_row=True,
            approved=True,
            relationship="friend",
            is_client=False,
            permissions={"resources": resources},
        )

    def test_a_resource_the_grant_now_excludes_is_not_delivered(self, actor) -> None:
        sub = {"target": "resources", "subtarget": "x", "resource": ""}
        blob = json.dumps({"v": 1})
        allowed = self._grant({"patterns": ["*"], "operations": ["read"]})
        narrowed = self._grant(
            {"patterns": ["*"], "operations": ["read"], "excluded_patterns": ["x"]}
        )
        assert actor.filter_subscription_blob("p1", sub, blob, snapshot=allowed) == blob
        assert (
            actor.filter_subscription_blob("p1", sub, blob, snapshot=narrowed) is None
        )

    def test_an_unapproved_peer_gets_nothing(self, actor) -> None:
        from actingweb.permission_evaluator import GrantSnapshot

        unapproved = GrantSnapshot(
            actor_id="a1",
            peer_id="p1",
            has_row=True,
            approved=False,
            relationship="friend",
            is_client=False,
            permissions={},
        )
        sub = {"target": "resources", "subtarget": "x", "resource": ""}
        assert (
            actor.filter_subscription_blob("p1", sub, "{}", snapshot=unapproved) is None
        )


class TestListDiffObjects:
    """Verification 2026-11-10: a ``list:<name>`` diff object (list,
    operation, items) was walked as if its keys were property paths, so an
    exclusion such as ``*/items`` stripped the diff itself."""

    @staticmethod
    def _grant() -> Any:
        from actingweb.permission_evaluator import GrantSnapshot

        return GrantSnapshot(
            actor_id="a1",
            peer_id="p1",
            has_row=True,
            approved=True,
            relationship="friend",
            is_client=False,
            permissions={
                "properties": {
                    "patterns": ["*"],
                    "operations": ["read"],
                    "excluded_patterns": ["*/items", "*/operation", "secret"],
                }
            },
        )

    DIFF = {"list": "notes", "operation": "extend", "items": [{"t": "a"}]}

    @pytest.mark.parametrize("sub", [WHOLE, {"target": "properties", "subtarget": "x"}])
    def test_a_list_diff_passes_whole(self, actor, sub) -> None:
        blob = {"list:notes": self.DIFF}
        out = actor.filter_subscription_blob(
            "p1", sub, json.dumps(blob), snapshot=self._grant()
        )
        assert out is not None and json.loads(out) == blob

    def test_an_excluded_list_is_still_dropped(self, actor) -> None:
        blob = {"list:secret": self.DIFF, "list:notes": self.DIFF}
        out = actor.filter_subscription_blob(
            "p1", WHOLE, json.dumps(blob), snapshot=self._grant()
        )
        assert out is not None and json.loads(out) == {"list:notes": self.DIFF}


def test_a_refused_remote_subscription_is_logged(caplog) -> None:
    """Verification 2026-11-10 (plan: a refused whole-target creation is
    logged by the library's subscriber, not only returned as None)."""
    import logging
    from unittest import mock

    me = Actor.__new__(Actor)
    me.id = "sub1"
    me.config = mock.Mock()
    rows = [{"peerid": "pub1", "baseuri": "https://pub/pub1", "secret": "s"}]
    with (
        mock.patch.object(me, "get_trust_relationships", return_value=rows),
        mock.patch(
            "actingweb.actor.requests.post",
            return_value=mock.Mock(status_code=403, content=b'{"error":"forbidden"}'),
        ),
        caplog.at_level(logging.WARNING, logger="actingweb.actor"),
    ):
        assert me.create_remote_subscription(peerid="pub1", target="properties") is None
    assert any("refused a subscription" in r.getMessage() for r in caplog.records)


class TestApplicationTargetsAtDelivery:
    """Code review 2026-11-10: an application's own target was re-checked
    against the creation row (``subscriptions/<id>``), so a subscription the
    application made itself stopped delivering. It needs an approved trust."""

    @staticmethod
    def _grant(
        approved: bool, relationship: str = "friend", is_client: bool = False
    ) -> Any:
        from actingweb.permission_evaluator import GrantSnapshot

        return GrantSnapshot(
            actor_id="a1",
            peer_id="p1",
            has_row=True,
            approved=approved,
            relationship=relationship,
            is_client=is_client,
            permissions={},
        )

    def test_approval_alone_decides_after_a_downgrade(self, actor: Any) -> None:
        """Owner decision 2026-11-10 (verification re-run 1, Issue F): the
        grant has no category for an application's target, so approval alone
        decides at delivery. A relationship whose access table would not let
        it create the subscription, or a client row holding one the
        application made, still receives; withdrawing approval stops it."""
        sub = {"target": "meta", "subtarget": "", "resource": ""}
        for grant in (
            self._grant(True, relationship="no-such-type"),
            self._grant(True, relationship="mcp_client", is_client=True),
        ):
            assert (
                actor.filter_subscription_blob("p1", sub, "{}", snapshot=grant) == "{}"
            )

    def test_an_approved_peer_gets_its_application_diffs(self, actor: Any) -> None:
        sub = {"target": "meta", "subtarget": "", "resource": ""}
        out = actor.filter_subscription_blob(
            "p1", sub, "{}", snapshot=self._grant(True)
        )
        assert out == "{}"
        assert (
            actor.filter_subscription_blob("p1", sub, "{}", snapshot=self._grant(False))
            is None
        )


EXCLUDES = {"patterns": ["*"], "excluded_patterns": ["settings/private"]}


def _nested(depth: int) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for _ in range(depth):
        value = {"a": value}
    return value


def test_text_nested_beyond_the_parser_is_withheld() -> None:
    """Outside voice 2026-11-10: ``RecursionError`` from very deep JSON text
    escaped the filter; verification re-run 1 (Issue C): treated as text, it
    was then sent unfiltered. It is withheld."""
    from actingweb.permission_evaluator import TOO_DEEP, as_json_object

    deep = "[" * 200_000 + "]" * 200_000
    assert as_json_object(deep) is TOO_DEEP
    assert Actor._diff_part(EXCLUDES, "settings", deep) is _EMPTIED


def test_objects_nested_beyond_the_walk_are_withheld() -> None:
    """Verification re-run 1 (Issue C): an object nested 5000 deep parses,
    then the filter's walk raised ``RecursionError`` (only arrays were
    tested, which the walk does not descend)."""
    from actingweb.permission_evaluator import drop_excluded, holds_excluded

    deep = _nested(5000)
    text = json.dumps(deep)
    assert drop_excluded(EXCLUDES, "settings", deep) is None
    assert holds_excluded(EXCLUDES, "settings", deep)
    assert Actor._diff_part(EXCLUDES, "settings", deep) is _EMPTIED
    assert Actor._diff_part(EXCLUDES, "settings", text) is _EMPTIED
    # No exclusion stated: nothing is walked, the value passes as it is.
    assert drop_excluded({"patterns": ["*"]}, "settings", deep) is deep


def test_a_value_within_the_depth_is_filtered_as_before() -> None:
    from actingweb.permission_evaluator import MAX_FILTER_DEPTH, drop_excluded

    value = {"private": "s", "deep": _nested(MAX_FILTER_DEPTH - 2)}
    assert drop_excluded(EXCLUDES, "settings", value) == {
        "deep": _nested(MAX_FILTER_DEPTH - 2)
    }


def test_a_view_withholds_and_refuses_a_value_too_deep(actor: Any) -> None:
    """The developer view reads ``None`` for it and refuses to overwrite it
    (it held excluded parts the filter cannot see)."""
    w, peer = _world()
    assert w.a.property is not None
    w.a.property["settings"] = json.dumps(_nested(5000))
    view = _fresh_view(w, peer)
    assert view["settings"] is None
    with pytest.raises(PermissionError):
        view["settings"] = "{}"


def test_text_beyond_the_parser_is_withheld_with_no_exclusion() -> None:
    """Re-run 4 (Issue 7): the rule holds whatever the grant: with no
    exclusion stated the diff, the full state and the view still withhold
    text nested beyond the parser, and plain text and JSON pass."""
    from unittest import mock

    deep = "[" * 200_000 + "]" * 200_000
    none_excluded = {"patterns": ["*"]}
    assert Actor._diff_part(none_excluded, "p", deep) is _EMPTIED
    assert Actor._diff_part(None, "p", deep) is _EMPTIED
    assert Actor._diff_part(None, "p", "plain") == "plain"
    assert Actor._diff_part(None, "p", '{"a": 1}') == '{"a": 1}'
    actor = object.__new__(Actor)
    grant = TestApplicationTargetsAtDelivery._grant(True)
    with mock.patch.object(Actor, "grant_for", return_value=grant):
        assert actor._filter_full_state(
            "p1", "", {"deep": deep, "color": "b"}, set()
        ) == {"color": "b"}


def test_bytes_are_read_as_the_parser_reads_them() -> None:
    """Re-run 5 (Issue 6): the prefix check skipped bytes with a UTF-8 BOM
    or in UTF-16, which ``json.loads`` reads, so an SDK write of such bytes
    escaped the developer view's exclusion check."""
    from actingweb.permission_evaluator import as_json_object

    text = '{"private": "s"}'
    assert as_json_object(text.encode("utf-8-sig")) == {"private": "s"}
    assert as_json_object(text.encode("utf-16")) == {"private": "s"}
    assert as_json_object(b"plain") is None


def test_bytes_with_lone_surrogates_are_read_as_the_parser_reads_them() -> None:
    """Re-run 6 (Issue 7): ``json.loads`` decodes bytes with
    ``surrogatepass``; a strict decode treated these as not JSON."""
    from actingweb.permission_evaluator import as_json_object

    parsed = as_json_object(b'{"private":"s","x":"\xed\xa0\x80"}')
    assert isinstance(parsed, dict) and parsed["private"] == "s"


@pytest.mark.parametrize(
    "text",
    [
        "﻿" + json.dumps(SETTINGS),
        json.dumps(SETTINGS).encode("utf-16-le").decode("latin-1"),
        json.dumps(SETTINGS).encode("utf-16-be").decode("latin-1"),
    ],
)
def test_text_a_json_client_reads_as_an_object_is_one_everywhere(text: str) -> None:
    """Re-run 8 (Issue 1): only the direct read handled a byte-order mark;
    the diff, the full state, the views and the write check took such text
    (and UTF-16 in its bytes, which ``response.json()`` reads) for plain
    text and sent or overwrote it unfiltered."""
    from actingweb.handlers.properties import _parsed
    from actingweb.permission_evaluator import as_json_object

    rules = {"patterns": ["*"], "excluded_patterns": ["settings/private"]}
    assert as_json_object(text) == SETTINGS
    assert _parsed(text) == SETTINGS
    assert json.loads(Actor._diff_part(rules, "settings", text)) == {"theme": "x"}
    assert as_json_object("plain") is None and _parsed("plain") == "plain"


def test_a_view_does_not_let_a_peer_overwrite_bom_text_with_an_excluded_part(
    actor: Any,
) -> None:
    """Re-run 8 (Issue 1): the write check took BOM-prefixed JSON for text."""
    w, peer = _world()
    assert w.a.property is not None
    w.a.property["settings"] = "﻿" + json.dumps(SETTINGS)
    view = _fresh_view(w, peer)
    assert json.loads(view["settings"]) == {"theme": "x"}
    with pytest.raises(PermissionError):
        view["settings"] = "{}"
