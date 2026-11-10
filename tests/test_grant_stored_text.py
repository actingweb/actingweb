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

from actingweb.actor import Actor
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
    def _grant(approved: bool) -> Any:
        from actingweb.permission_evaluator import GrantSnapshot

        return GrantSnapshot(
            actor_id="a1",
            peer_id="p1",
            has_row=True,
            approved=approved,
            relationship="friend",
            is_client=False,
            permissions={},
        )

    def test_an_approved_peer_gets_its_application_diffs(self, actor) -> None:
        sub = {"target": "meta", "subtarget": "", "resource": ""}
        out = actor.filter_subscription_blob(
            "p1", sub, "{}", snapshot=self._grant(True)
        )
        assert out == "{}"
        assert (
            actor.filter_subscription_blob("p1", sub, "{}", snapshot=self._grant(False))
            is None
        )


def test_text_nested_beyond_the_parser_is_text() -> None:
    """Outside voice 2026-11-10: ``RecursionError`` from very deep JSON text
    escaped the filter (a dropped diff, a view raising)."""
    from actingweb.permission_evaluator import as_json_object

    deep = "[" * 200_000 + "]" * 200_000
    assert as_json_object(deep) is None
