"""Run the property-list suites against ``ListAttribute`` too
(thoughts/plans/2026-11-13-attribute-list-v2-port.md, Phase 2, "Parity").

A suite imports ``list_class`` from here; the autouse fixture runs each of
its tests twice. In the ``attribute`` run the module's ``ListProperty`` name
(and the one in ``tests.test_property_list_integrity``, whose helpers other
suites import) is rebound to ``AttributeParityList``: a ``ListAttribute``
with the property constructor ``(actor_id, name, config)``, whose attribute
backend is ``PropertyBackedAttributeDb``. That adapter implements the
attribute list primitives by delegating to whatever
``actingweb.property_list.get_property`` returns while the test runs (the
suite's patched fake, with its fault, crash and counting subclasses), and
maps the list's bucket to the actor's property partition and its side bucket
to ``{actor}$aux``. So the raw store a suite asserts on holds the same rows
under the same keys in both runs.

A test that cannot hold for an attribute list says why with
``@pytest.mark.property_only("reason")``: the property v1 format and its
migration, a write that answers ``False`` (an attribute write never does; a
fault raises), a spy on the property model.
"""

from typing import Any

import pytest

from actingweb.attribute_list import ListAttribute
from actingweb.property_list_span import AUX_SUFFIX

PARITY_BUCKET = "parity"


def _prop(config: Any) -> Any:
    import actingweb.property_list as property_list

    return property_list.get_property(config)


class PropertyBackedAttributeDb:
    """The attribute list primitives over the patched property fake."""

    def __init__(self, config: Any) -> None:
        self._config = config

    @staticmethod
    def _partition(actor_id: str, bucket: str) -> str:
        if bucket == PARITY_BUCKET:
            return actor_id
        if bucket == PARITY_BUCKET + AUX_SUFFIX:
            return actor_id + AUX_SUFFIX
        raise AssertionError(f"unexpected bucket {bucket!r}")

    def get_attr(self, actor_id: str, bucket: str, name: str) -> Any:
        value = _prop(self._config).get(
            actor_id=self._partition(actor_id, bucket), name=name
        )
        return None if value is None else {"data": value, "timestamp": None}

    def get_attr_range(
        self,
        actor_id: str,
        bucket: str,
        lower: str,
        upper: str,
        *,
        keys_only: bool = False,
        consistent_read: bool = True,
    ) -> dict[str, Any]:
        return _prop(self._config).get_range(
            actor_id=self._partition(actor_id, bucket),
            lower=lower,
            upper=upper,
            keys_only=keys_only,
            consistent_read=consistent_read,
        )

    def get_attr_prefix(
        self,
        actor_id: str,
        bucket: str,
        prefix: str,
        *,
        keys_only: bool = False,
        consistent_read: bool = True,
    ) -> dict[str, Any]:
        return _prop(self._config).get_prefix(
            actor_id=self._partition(actor_id, bucket),
            prefix=prefix,
            keys_only=keys_only,
            consistent_read=consistent_read,
        )

    def get_last_attr_in_range(
        self, actor_id: str, bucket: str, lower: str, upper: str
    ) -> str | None:
        return _prop(self._config).get_last_in_range(
            actor_id=self._partition(actor_id, bucket), lower=lower, upper=upper
        )

    def create_attr_if_not_exists(
        self, actor_id: str, bucket: str, name: str, data: Any
    ) -> bool:
        return bool(
            _prop(self._config).create_if_not_exists(
                actor_id=self._partition(actor_id, bucket), name=name, value=data
            )
        )

    def create_attrs_if_not_exist(
        self, actor_id: str, bucket: str, rows: dict[str, Any]
    ) -> set[str]:
        return {
            name
            for name, data in rows.items()
            if self.create_attr_if_not_exists(actor_id, bucket, name, data)
        }

    def set_attr_if_data_equals(
        self, actor_id: str, bucket: str, name: str, expected: str, data: Any
    ) -> bool:
        return bool(
            _prop(self._config).set_if_value_equals(
                actor_id=self._partition(actor_id, bucket),
                name=name,
                expected=expected,
                value=data,
            )
        )

    def delete_attr_if_data_equals(
        self, actor_id: str, bucket: str, name: str, expected: str
    ) -> bool:
        return bool(
            _prop(self._config).delete_if_value_equals(
                actor_id=self._partition(actor_id, bucket), name=name, value=expected
            )
        )

    def delete_attrs(self, actor_id: str, bucket: str, names: list[str]) -> None:
        from actingweb.db.exceptions import DbError

        partition = self._partition(actor_id, bucket)
        if len(names) == 1:
            # A one-row delete is the property list's set(value=None), so the
            # suites' fault injection on it reaches this run too.
            if not _prop(self._config).set(
                actor_id=partition, name=names[0], value=None
            ):
                raise DbError("attribute delete", actor_id)
            return
        _prop(self._config).batch_delete(actor_id=partition, names=list(names))

    def put_attr(self, actor_id: str, bucket: str, name: str, data: Any) -> None:
        from actingweb.db.exceptions import DbError

        if not data:
            raise ValueError("put_attr does not store falsy data")
        # The attribute storage never answers False: a write that did not
        # land is a fault.
        if not _prop(self._config).set(
            actor_id=self._partition(actor_id, bucket), name=name, value=data
        ):
            raise DbError("attribute put", actor_id)


class _ParityConfig:
    """The suite's config, with an attribute backend over the property
    fake. Every other attribute (the list limits) is the suite's."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        backend = type(
            "ParityDbAttribute",
            (PropertyBackedAttributeDb,),
            {"__init__": lambda self: PropertyBackedAttributeDb.__init__(self, inner)},
        )
        self.DbAttribute = type("ParityModule", (), {"DbAttribute": backend})

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def __bool__(self) -> bool:
        return bool(self._inner)


class AttributeParityList(ListAttribute):
    """A ``ListAttribute`` with the property constructor."""

    def __init__(self, actor_id: str, name: str, config: Any) -> None:
        super().__init__(
            actor_id,
            PARITY_BUCKET,
            name,
            _ParityConfig(config) if config is not None else None,
        )


@pytest.fixture(params=["property", "attribute"], autouse=True)
def list_class(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    """Run the test with ``ListProperty`` and with ``AttributeParityList``."""
    if request.param == "attribute":
        marker = request.node.get_closest_marker("property_only")
        if marker is not None:
            pytest.skip(f"property list only: {marker.args[0] if marker.args else ''}")
        import tests.test_property_list_integrity as integrity

        monkeypatch.setattr(request.module, "ListProperty", AttributeParityList)
        monkeypatch.setattr(integrity, "ListProperty", AttributeParityList)
    return request.param
