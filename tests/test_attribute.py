"""Tests for attribute module."""

from unittest.mock import Mock

from actingweb.attribute import Attributes, Buckets, InternalStore


class TestAttributesInitialization:
    """Test Attributes class initialization."""

    def test_init_with_all_params(self):
        """Test Attributes initialization with all parameters."""
        mock_config = Mock()
        mock_db_attr = Mock()
        mock_db_attr.get_bucket.return_value = {}
        mock_config.DbAttribute.DbAttribute.return_value = mock_db_attr

        attrs = Attributes(
            actor_id="test_actor", bucket="test_bucket", config=mock_config
        )

        assert attrs.actor_id == "test_actor"
        assert attrs.bucket == "test_bucket"
        assert attrs.config == mock_config

    def test_init_without_config(self):
        """Test Attributes initialization without config."""
        attrs = Attributes(actor_id="test_actor", bucket="test_bucket")

        assert attrs.actor_id == "test_actor"
        assert attrs.bucket == "test_bucket"
        assert attrs.dbprop is None

    def test_init_without_actor_id(self):
        """Test Attributes initialization without actor_id."""
        attrs = Attributes(bucket="test_bucket")

        assert attrs.actor_id is None
        assert attrs.bucket == "test_bucket"

    def test_init_without_bucket(self):
        """Test Attributes initialization without bucket."""
        attrs = Attributes(actor_id="test_actor")

        assert attrs.actor_id == "test_actor"
        assert attrs.bucket is None


class TestAttributesGetBucket:
    """Test Attributes get_bucket method."""

    def test_get_bucket_with_dbprop(self):
        """Test get_bucket retrieves from database."""
        mock_config = Mock()
        mock_db_attr = Mock()
        mock_bucket_data = {"key1": {"data": "value1"}, "key2": {"data": "value2"}}
        mock_db_attr.get_bucket.return_value = mock_bucket_data
        mock_config.DbAttribute.DbAttribute.return_value = mock_db_attr

        attrs = Attributes(
            actor_id="test_actor", bucket="test_bucket", config=mock_config
        )
        result = attrs.get_bucket()

        assert result == mock_bucket_data

    def test_get_bucket_without_dbprop(self):
        """Test get_bucket returns empty dict without dbprop."""
        attrs = Attributes(actor_id="test_actor", bucket="test_bucket")
        attrs.data = {}

        result = attrs.get_bucket()

        assert result == {}


class TestAttributesGetAttr:
    """Test Attributes get_attr method."""

    def test_get_attr_no_name(self):
        """Test get_attr returns None without name."""
        attrs = Attributes(actor_id="test_actor", bucket="test_bucket")

        result = attrs.get_attr(name=None)

        assert result is None

    def test_get_attr_from_cache(self):
        """Test get_attr returns cached value."""
        attrs = Attributes(actor_id="test_actor", bucket="test_bucket")
        attrs.data = {"test_key": {"data": "cached_value"}}

        result = attrs.get_attr(name="test_key")

        assert result == {"data": "cached_value"}

    def test_get_attr_from_db(self):
        """Test get_attr fetches from database if not cached."""
        mock_config = Mock()
        mock_db_attr = Mock()
        mock_db_attr.get_bucket.return_value = {}
        mock_db_attr.get_attr.return_value = {"data": "db_value"}
        mock_config.DbAttribute.DbAttribute.return_value = mock_db_attr

        attrs = Attributes(
            actor_id="test_actor", bucket="test_bucket", config=mock_config
        )
        attrs.data = {}  # Clear cache
        result = attrs.get_attr(name="new_key")

        assert result == {"data": "db_value"}
        mock_db_attr.get_attr.assert_called_once_with(
            actor_id="test_actor", bucket="test_bucket", name="new_key"
        )


class TestAttributesSetAttr:
    """Test Attributes set_attr method."""

    def test_set_attr_no_actor_id(self):
        """Test set_attr returns False without actor_id."""
        attrs = Attributes(bucket="test_bucket")

        result = attrs.set_attr(name="key", data="value")

        assert result is False

    def test_set_attr_no_bucket(self):
        """Test set_attr returns False without bucket."""
        attrs = Attributes(actor_id="test_actor")

        result = attrs.set_attr(name="key", data="value")

        assert result is False

    def test_set_attr_success(self):
        """Test set_attr sets data and calls database."""
        mock_config = Mock()
        mock_db_attr = Mock()
        mock_db_attr.get_bucket.return_value = {}
        mock_db_attr.set_attr.return_value = True
        mock_config.DbAttribute.DbAttribute.return_value = mock_db_attr

        attrs = Attributes(
            actor_id="test_actor", bucket="test_bucket", config=mock_config
        )
        result = attrs.set_attr(name="key", data="value", timestamp="2023-01-01")

        assert result is True
        assert attrs.data is not None  # Type narrowing for pyright
        assert attrs.data["key"] is not None  # Type narrowing for pyright
        assert attrs.data["key"]["data"] == "value"
        assert attrs.data["key"]["timestamp"] == "2023-01-01"
        mock_db_attr.set_attr.assert_called_once_with(
            actor_id="test_actor",
            bucket="test_bucket",
            name="key",
            data="value",
            timestamp="2023-01-01",
            ttl_seconds=None,
        )

    def test_set_attr_with_ttl(self):
        """Test set_attr passes ttl_seconds to database."""
        mock_config = Mock()
        mock_db_attr = Mock()
        mock_db_attr.get_bucket.return_value = {}
        mock_db_attr.set_attr.return_value = True
        mock_config.DbAttribute.DbAttribute.return_value = mock_db_attr

        attrs = Attributes(
            actor_id="test_actor", bucket="test_bucket", config=mock_config
        )
        result = attrs.set_attr(name="key", data="value", ttl_seconds=3600)

        assert result is True
        mock_db_attr.set_attr.assert_called_once_with(
            actor_id="test_actor",
            bucket="test_bucket",
            name="key",
            data="value",
            timestamp=None,
            ttl_seconds=3600,
        )


class TestAttributesDeleteAttr:
    """Test Attributes delete_attr method."""

    def test_delete_attr_no_name(self):
        """Test delete_attr returns False without name."""
        attrs = Attributes(actor_id="test_actor", bucket="test_bucket")

        result = attrs.delete_attr(name=None)

        assert result is False

    def test_delete_attr_success(self):
        """Test delete_attr removes from database."""
        mock_config = Mock()
        mock_db_attr = Mock()
        mock_db_attr.get_bucket.return_value = {}
        mock_db_attr.delete_attr.return_value = True
        mock_config.DbAttribute.DbAttribute.return_value = mock_db_attr

        attrs = Attributes(
            actor_id="test_actor", bucket="test_bucket", config=mock_config
        )
        result = attrs.delete_attr(name="key_to_delete")

        assert result is True
        mock_db_attr.delete_attr.assert_called_once_with(
            actor_id="test_actor", bucket="test_bucket", name="key_to_delete"
        )


class TestAttributesDeleteBucket:
    """Test Attributes delete_bucket method."""

    def test_delete_bucket_no_dbprop(self):
        """Test delete_bucket returns False without dbprop."""
        attrs = Attributes(actor_id="test_actor", bucket="test_bucket")

        result = attrs.delete_bucket()

        assert result is False

    def test_delete_bucket_success(self):
        """Test delete_bucket removes bucket from database."""
        mock_config = Mock()
        mock_db_attr = Mock()
        mock_db_attr.get_bucket.return_value = {}
        mock_db_attr.delete_bucket.return_value = True
        mock_config.DbAttribute.DbAttribute.return_value = mock_db_attr

        attrs = Attributes(
            actor_id="test_actor", bucket="test_bucket", config=mock_config
        )
        result = attrs.delete_bucket()

        assert result is True
        assert attrs.data == {}
        mock_db_attr.delete_bucket.assert_called_once_with(
            actor_id="test_actor", bucket="test_bucket"
        )

    def test_delete_bucket_failure(self):
        """Test delete_bucket returns False on database failure."""
        mock_config = Mock()
        mock_db_attr = Mock()
        mock_db_attr.get_bucket.return_value = {}
        mock_db_attr.delete_bucket.return_value = False
        mock_config.DbAttribute.DbAttribute.return_value = mock_db_attr

        attrs = Attributes(
            actor_id="test_actor", bucket="test_bucket", config=mock_config
        )
        result = attrs.delete_bucket()

        assert result is False


class TestBucketsInitialization:
    """Test Buckets class initialization."""

    def test_init_with_actor_id(self):
        """Test Buckets initialization with actor_id."""
        mock_config = Mock()
        mock_bucket_list = Mock()
        mock_config.DbAttribute.DbAttributeBucketList.return_value = mock_bucket_list

        buckets = Buckets(actor_id="test_actor", config=mock_config)

        assert buckets.actor_id == "test_actor"
        assert buckets.list == mock_bucket_list

    def test_init_without_actor_id(self):
        """Test Buckets initialization without actor_id."""
        mock_config = Mock()

        buckets = Buckets(actor_id=None, config=mock_config)

        assert buckets.list is None


class TestBucketsFetch:
    """Test Buckets fetch methods."""

    def test_fetch_no_list(self):
        """Test fetch returns False without list (which happens when no actor_id)."""
        buckets = Buckets(actor_id=None)
        # When actor_id is None, list is None
        assert buckets.list is None

        # Since list is None, fetch returns False
        # Need to set actor_id to test the fetch path
        buckets.actor_id = "test_actor"  # Set actor_id but list is still None
        result = buckets.fetch()

        assert result is False

    def test_fetch_success(self):
        """Test fetch retrieves all buckets."""
        mock_config = Mock()
        mock_bucket_list = Mock()
        mock_data = {"bucket1": {}, "bucket2": {}}
        mock_bucket_list.fetch.return_value = mock_data
        mock_config.DbAttribute.DbAttributeBucketList.return_value = mock_bucket_list

        buckets = Buckets(actor_id="test_actor", config=mock_config)
        result = buckets.fetch()

        assert result == mock_data
        mock_bucket_list.fetch.assert_called_once_with(actor_id="test_actor")

    def test_fetch_timestamps_no_list(self):
        """Test fetch_timestamps returns False without list."""
        buckets = Buckets(actor_id=None)
        # When actor_id is None, list is None
        assert buckets.list is None

        # Set actor_id but list is still None
        buckets.actor_id = "test_actor"
        result = buckets.fetch_timestamps()

        assert result is False

    def test_fetch_timestamps_success(self):
        """Test fetch_timestamps retrieves timestamps."""
        mock_config = Mock()
        mock_bucket_list = Mock()
        mock_data = {"bucket1": "2023-01-01", "bucket2": "2023-01-02"}
        mock_bucket_list.fetch_timestamps.return_value = mock_data
        mock_config.DbAttribute.DbAttributeBucketList.return_value = mock_bucket_list

        buckets = Buckets(actor_id="test_actor", config=mock_config)
        result = buckets.fetch_timestamps()

        assert result == mock_data
        mock_bucket_list.fetch_timestamps.assert_called_once_with(actor_id="test_actor")


class TestBucketsDelete:
    """Test Buckets delete method."""

    def test_delete_no_list(self):
        """Test delete returns False without list."""
        buckets = Buckets(actor_id=None)

        result = buckets.delete()

        assert result is False

    def test_delete_success(self):
        """Test delete removes all buckets."""
        mock_config = Mock()
        mock_bucket_list = Mock()
        mock_config.DbAttribute.DbAttributeBucketList.return_value = mock_bucket_list

        buckets = Buckets(actor_id="test_actor", config=mock_config)
        result = buckets.delete()

        assert result is True
        mock_bucket_list.delete.assert_called_once_with(actor_id="test_actor")


class TestInternalStoreInitialization:
    """Test InternalStore class initialization."""

    def test_init_default_bucket(self):
        """Test InternalStore uses _internal as default bucket."""
        mock_config = Mock()
        mock_db_attr = Mock()
        mock_db_attr.get_bucket.return_value = {}
        mock_config.DbAttribute.DbAttribute.return_value = mock_db_attr

        store = InternalStore(actor_id="test_actor", config=mock_config)

        assert store._db.bucket == "_internal"

    def test_init_custom_bucket(self):
        """Test InternalStore uses custom bucket."""
        mock_config = Mock()
        mock_db_attr = Mock()
        mock_db_attr.get_bucket.return_value = {}
        mock_config.DbAttribute.DbAttribute.return_value = mock_db_attr

        store = InternalStore(
            actor_id="test_actor", config=mock_config, bucket="custom"
        )

        assert store._db.bucket == "custom"

    def test_init_loads_existing_data(self):
        """Test InternalStore loads existing attributes from database."""
        mock_config = Mock()
        mock_db_attr = Mock()
        mock_db_attr.get_bucket.return_value = {
            "setting1": {"data": "value1"},
            "setting2": {"data": "value2"},
        }
        mock_config.DbAttribute.DbAttribute.return_value = mock_db_attr

        store = InternalStore(actor_id="test_actor", config=mock_config)

        assert store.setting1 == "value1"
        assert store.setting2 == "value2"


class TestInternalStoreAccess:
    """Test InternalStore attribute access."""

    def _create_store(self) -> InternalStore:
        """Helper to create InternalStore with mock."""
        mock_config = Mock()
        mock_db_attr = Mock()
        mock_db_attr.get_bucket.return_value = {}
        mock_db_attr.set_attr.return_value = True
        mock_db_attr.delete_attr.return_value = True
        mock_config.DbAttribute.DbAttribute.return_value = mock_db_attr
        return InternalStore(actor_id="test_actor", config=mock_config)

    def test_getattr_returns_none_for_missing(self):
        """Test __getattr__ returns None for missing attributes."""
        store = self._create_store()

        result = store.nonexistent_attr

        assert result is None

    def test_setattr_sets_value(self):
        """Test __setattr__ sets attribute value."""
        store = self._create_store()

        store.test_attr = "test_value"

        assert store.test_attr == "test_value"

    def test_setattr_none_deletes(self):
        """Test __setattr__ with None deletes the attribute."""
        store = self._create_store()
        store.test_attr = "initial_value"

        store.test_attr = None

        assert store.test_attr is None

    def test_getitem_access(self):
        """Test dictionary-style access with __getitem__."""
        store = self._create_store()
        store.test_key = "test_value"

        result = store["test_key"]

        assert result == "test_value"

    def test_setitem_access(self):
        """Test dictionary-style assignment with __setitem__."""
        store = self._create_store()

        store["test_key"] = "test_value"

        assert store.test_key == "test_value"


class _FakeAttributeRow:
    """Stand-in for a stored ``Attribute`` item.

    ``bucket_name`` is derived the way ``set_attr()`` writes it — the only
    writer — so the fake table cannot drift from the real key layout.
    """

    def __init__(self, bucket: str, name: str, data: object) -> None:
        self.bucket = bucket
        self.name = name
        self.data = data
        self.timestamp = None
        self.deleted = False

    @property
    def bucket_name(self) -> str:
        return self.bucket + ":" + self.name

    def delete(self) -> None:
        self.deleted = True


class _FakeAttributeTable:
    """A ``begins_with`` Query over an in-memory row list.

    Mirrors DynamoDB's semantics exactly: the range-key condition is a byte
    prefix match and nothing else, so anything separating buckets has to come
    from the code under test rather than from the fake.
    """

    def __init__(self, rows: list[_FakeAttributeRow]) -> None:
        self.rows = rows
        self.prefixes: list[str] = []

    def query(self, actor_id, condition, consistent_read=True, **kwargs):  # noqa: ANN001, ARG002
        prefix = condition.values[1].value["S"]
        self.prefixes.append(prefix)
        return [r for r in self.rows if r.bucket_name.startswith(prefix)]


class TestDbAttributeBucketIsolation:
    """A bucket must never see or delete a prefix sibling's rows.

    ``bucket_name`` is ``bucket + ":" + name``, so a bare
    ``begins_with(bucket)`` matched every bucket having this one as a prefix.
    ``delete_bucket()`` then deleted them: ``RemotePeerStore.delete_all()``
    tears down bucket ``remote:{peer_id}`` and most call sites build that id
    with ``validate_peer_id=False``, so ending trust with peer ``abc``
    destroyed peer ``abcd``'s dataset.
    """

    def _install(self, monkeypatch, rows):
        from actingweb.db.dynamodb import attribute as dynamo_attribute

        table = _FakeAttributeTable(rows)
        monkeypatch.setattr(dynamo_attribute.Attribute, "query", table.query)
        return dynamo_attribute.DbAttribute, table

    def test_get_bucket_skips_prefix_sibling_rows(self, monkeypatch):
        rows = [
            _FakeAttributeRow("b", "x", "b-value"),
            _FakeAttributeRow("bb", "y", "bb-value"),
        ]
        db, _table = self._install(monkeypatch, rows)

        result = db.get_bucket(actor_id="actor1", bucket="b")

        assert result is not None
        assert set(result) == {"x"}
        assert result["x"]["data"] == "b-value"

    def test_delete_bucket_spares_prefix_sibling_rows(self, monkeypatch):
        rows = [
            _FakeAttributeRow("b", "x", "b-value"),
            _FakeAttributeRow("bb", "y", "bb-value"),
        ]
        db, _table = self._install(monkeypatch, rows)

        assert db.delete_bucket(actor_id="actor1", bucket="b") is True

        assert rows[0].deleted is True
        assert rows[1].deleted is False

    def test_get_bucket_separates_remote_peer_prefix_siblings(self, monkeypatch):
        rows = [
            _FakeAttributeRow("remote:abc", "x", "abc-value"),
            _FakeAttributeRow("remote:abcd", "x", "abcd-value"),
        ]
        db, _table = self._install(monkeypatch, rows)

        result = db.get_bucket(actor_id="actor1", bucket="remote:abc")

        assert result == {"x": {"data": "abc-value", "timestamp": None}}

    def test_delete_bucket_spares_remote_peer_prefix_sibling(self, monkeypatch):
        rows = [
            _FakeAttributeRow("remote:abc", "x", "abc-value"),
            _FakeAttributeRow("remote:abcd", "x", "abcd-value"),
        ]
        db, _table = self._install(monkeypatch, rows)

        assert db.delete_bucket(actor_id="actor1", bucket="remote:abc") is True

        assert rows[0].deleted is True
        assert rows[1].deleted is False

    def test_exact_compare_rejects_a_colliding_composite_key(self, monkeypatch):
        """The delimiter alone is not enough.

        Bucket names contain ``:`` (``remote:{peer_id}``) and attribute names
        contain ``:`` (``list:{name}:{index}``), so bucket ``remote``/name
        ``abc:x`` produces the byte-identical ``bucket_name``
        ``remote:abc:x`` that bucket ``remote:abc``/name ``x`` would. Both
        backends key on ``(id, bucket_name)``, so those two are the *same row*
        and only one can exist — which is exactly why the delimiter cannot
        settle who owns it. The stored ``bucket`` does, and only an exact
        compare reads it.
        """
        rows = [_FakeAttributeRow("remote", "abc:x", "flat-bucket")]
        db, table = self._install(monkeypatch, rows)

        assert db.get_bucket(actor_id="actor1", bucket="remote:abc") == {}
        assert db.get_bucket(actor_id="actor1", bucket="remote") == {
            "abc:x": {"data": "flat-bucket", "timestamp": None}
        }
        # The narrowed prefix matched the row in both calls; the compare split them.
        assert table.prefixes == ["remote:abc:", "remote:"]

    def test_exact_compare_stops_a_colliding_composite_key_delete(self, monkeypatch):
        rows = [_FakeAttributeRow("remote", "abc:x", "flat-bucket")]
        db, _table = self._install(monkeypatch, rows)

        assert db.delete_bucket(actor_id="actor1", bucket="remote:abc") is True

        assert rows[0].deleted is False

    def test_queries_carry_the_delimiter(self, monkeypatch):
        rows = [_FakeAttributeRow("b", "x", "b-value")]
        db, table = self._install(monkeypatch, rows)

        db.get_bucket(actor_id="actor1", bucket="b")
        db.delete_bucket(actor_id="actor1", bucket="b")

        assert table.prefixes == ["b:", "b:"]
