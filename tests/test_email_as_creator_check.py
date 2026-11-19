"""``check_ready()``'s fourth check, ``EmailAsCreatorNotReady`` (4.0): its
place among the other three. The check itself is tested against both
backends in ``tests/integration/test_email_as_creator_sweep.py``."""

from __future__ import annotations

import pytest

from actingweb.interface import (
    AttributeSchemaNotReady,
    EmailAsCreatorNotReady,
    PropertyLookupNotReady,
    StoreNotReady,
    UniqueCreatorNotReady,
)
from actingweb.interface.app import ActingWebApp


def _app(
    monkeypatch: pytest.MonkeyPatch, refusing: list[type[StoreNotReady]]
) -> ActingWebApp:
    app = ActingWebApp(aw_type="urn:actingweb:test:ready", fqdn="test.example.com")
    monkeypatch.setattr(app, "_prewarm_dynamodb_tables", lambda: None)
    checks = {
        PropertyLookupNotReady: "_check_property_lookup_ready",
        UniqueCreatorNotReady: "_check_unique_creator_ready",
        AttributeSchemaNotReady: "_check_attribute_schema_ready",
        EmailAsCreatorNotReady: "_check_email_as_creator_ready",
    }
    for cls, name in checks.items():

        def check(cls: type[StoreNotReady] = cls) -> None:
            if cls in refusing:
                raise cls(f"refused by {cls.__name__}")

        monkeypatch.setattr(app, name, check)
    return app


def test_all_four_refusing_carry_four_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    every = [
        PropertyLookupNotReady,
        UniqueCreatorNotReady,
        AttributeSchemaNotReady,
        EmailAsCreatorNotReady,
    ]
    with pytest.raises(StoreNotReady) as raised:
        _app(monkeypatch, every).check_ready()
    assert type(raised.value) is StoreNotReady
    for cls in every:
        assert f"refused by {cls.__name__}" in str(raised.value)


def test_alone_it_keeps_its_own_type(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(EmailAsCreatorNotReady):
        _app(monkeypatch, [EmailAsCreatorNotReady]).check_ready()


def test_it_is_a_store_not_ready() -> None:
    assert issubclass(EmailAsCreatorNotReady, StoreNotReady)
