from typing import Any, cast

from actingweb.db import get_attribute, get_attribute_bucket_list


class InternalStore:
    """Access to internal attributes using .prop notation"""

    def __init__(
        self,
        actor_id: str | None = None,
        config: Any | None = None,
        bucket: str | None = None,
    ) -> None:
        if not bucket:
            bucket = "_internal"
        self._db = Attributes(actor_id=actor_id, bucket=bucket, config=config)
        # The bucket is loaded lazily on first access: constructing the
        # store (which happens on every Actor construction) must not cost a
        # database query when the attributes are never touched.
        self._loaded = False
        self.__initialised = True

    def _ensure_loaded(self) -> None:
        """Load the whole bucket into the instance on first access.

        Must run before the first write as well as the first read: a write
        populates the underlying Attributes cache with a single key, after
        which get_bucket() would return a partial bucket.
        """
        if self.__dict__.get("_loaded"):
            return
        self.__dict__["_loaded"] = True
        d = self.__dict__["_db"].get_bucket()
        if d:
            for k, v in d.items():
                # Populate directly — no write-through back to the database
                self.__dict__[k] = (v or {}).get("data")

    def __getitem__(self, k: str) -> Any:
        return self.__getattr__(k)

    def __setitem__(self, k: str, v: Any) -> None:
        return self.__setattr__(k, v)

    def __setattr__(self, k: str, v: Any) -> None:
        if "_InternalStore__initialised" not in self.__dict__:
            return object.__setattr__(self, k, v)
        if k is None:
            raise ValueError
        self._ensure_loaded()
        if v is None:
            self.__dict__["_db"].delete_attr(name=k)
            if k in self.__dict__:
                self.__delattr__(k)
        else:
            self.__dict__[k] = v
            self.__dict__["_db"].set_attr(name=k, data=v)

    def __getattr__(self, k: str) -> Any:
        # Only reached when k is not in __dict__. Avoid triggering a load
        # for private/dunder lookups (pickling, introspection).
        if k.startswith("_"):
            return None
        self._ensure_loaded()
        return self.__dict__.get(k)


class Attributes:
    """
    Attributes is the main entity keeping an attribute.

    It needs to be initalized at object creation time.

    """

    def get_bucket(self) -> dict[str, Any] | None:
        """Retrieves the attribute bucket from the database.

        Tracks full-bucket loads with a flag rather than data emptiness:
        a set_attr()/get_attr() may have cached individual entries, and
        treating a partially-cached dict as "loaded" would silently return
        an incomplete bucket.

        ``_bucket_loaded`` is set only when the backend actually RETURNED A
        DICT, and it means "loaded, and the backend answered". That
        distinction is load-bearing now that ``get_attr()`` treats the flag
        as authoritative about ABSENCE: a bucket that could not be read
        must not become "the bucket has no such attribute", permanently,
        for the life of this instance.

        Both backends return ``None`` for a caught exception, and
        PostgreSQL additionally returns it for a genuinely EMPTY bucket
        (see the comment below and ``db/postgresql/attribute.py``). Not
        distinguishing those is deliberate and conservative: on PostgreSQL
        an empty bucket is simply never trusted, so ``get_attr()`` still
        point-reads there, which costs nothing real — an empty bucket has
        no absent-name savings to give up. Aligning the two backends'
        empty-vs-fault contract is filed separately rather than smuggled in
        here; the conservative version cannot break a caller that a grep
        did not find.

        Note that on DynamoDB most real faults do not arrive as ``None`` at
        all: ``DbAttribute.get_bucket()`` wraps only the Query
        CONSTRUCTION, and PynamoDB fires the request lazily during
        iteration, so a throttle mid-page raises straight through this
        method with the flag still unset — already the safe outcome.
        """
        if not self._bucket_loaded:
            if self.dbprop:
                fetched_data = self.dbprop.get_bucket(
                    actor_id=self.actor_id, bucket=self.bucket
                )
                # PostgreSQL backend returns None for non-existent buckets
                if fetched_data is None:
                    self.data = {}
                else:
                    # Cast needed due to dict invariance in value types
                    self.data = cast(dict[str, dict[str, Any] | None], fetched_data)
                    self._bucket_loaded = True
            else:
                self.data = {}
                self._bucket_loaded = True
        return self.data

    def get_attr(self, name: str | None = None) -> dict[str, Any] | None:
        """Retrieves a single attribute.

        A fully-loaded bucket is AUTHORITATIVE: once ``get_bucket()`` has
        returned a dict, a name absent from it is absent from storage, and
        answering ``None`` here costs no query. Before, every absent name
        cost one point read per instance.

        The early return also stops this method polluting a loaded bucket.
        The miss path below caches ``self.data[name] = None``, and
        ``get_bucket()`` returns ``self.data`` BY IDENTITY — so a loaded
        bucket used to grow keys that have no stored row, and a caller
        iterating the "bucket" saw names that do not exist.

        "Absent" stays distinguishable from "present with a null value": a
        stored row holding ``null`` reads back as the truthy dict
        ``{"data": None, "timestamp": ...}``, while absence is ``None``.
        """
        if not name:
            return None
        # Ensure self.data is initialized (defensive check)
        if self.data is None:
            self.data = {}
        if name not in self.data:
            if self._bucket_loaded:
                return None
            if self.dbprop:
                self.data[name] = self.dbprop.get_attr(
                    actor_id=self.actor_id, bucket=self.bucket, name=name
                )
            else:
                self.data[name] = None
        return self.data[name]

    def set_attr(
        self,
        name: str | None = None,
        data: Any | None = None,
        timestamp: Any | None = None,
        ttl_seconds: int | None = None,
    ) -> bool:
        """Sets new data for this attribute.

        Args:
            name: Attribute name
            data: Data to store (JSON-serializable)
            timestamp: Optional timestamp
            ttl_seconds: Optional TTL in seconds. If provided, DynamoDB will
                         automatically delete this item after expiry.
        """
        if not self.actor_id or not self.bucket or not name:
            return False
        # Ensure self.data is initialized (defensive check)
        if self.data is None:
            self.data = {}
        assert self.data is not None  # Type narrowing for pyright
        if not data:
            # Both backends treat a FALSY data as a delete and return True
            # (delete_attr() is literally set_attr(data=None)), so caching
            # an entry here would make the dict disagree with storage about
            # presence -- and get_attr() now treats a loaded dict as
            # authoritative about absence. `not data`, not `data is None`:
            # {} / [] / "" / 0 / False all delete on the backend too.
            self.data.pop(name, None)
        else:
            if self.data.get(name) is None:
                self.data[name] = {}
            attr_data = self.data[name]
            assert attr_data is not None  # Type narrowing for pyright
            attr_data["data"] = data
            attr_data["timestamp"] = timestamp
        if self.dbprop:
            return self.dbprop.set_attr(
                actor_id=self.actor_id,
                bucket=self.bucket,
                name=name,
                data=data,
                timestamp=timestamp,
                ttl_seconds=ttl_seconds,
            )
        return False

    def conditional_update_attr(
        self,
        name: str | None = None,
        old_data: Any | None = None,
        new_data: Any | None = None,
        timestamp: Any | None = None,
    ) -> bool:
        """Conditionally update an attribute only if current data matches old_data.

        This provides atomic compare-and-swap functionality for race-free updates.

        Args:
            name: Attribute name
            old_data: Expected current data value (for comparison)
            new_data: New data to set if current matches old_data
            timestamp: Optional timestamp

        Returns:
            True if update succeeded (current matched old_data), False otherwise
        """
        if not self.actor_id or not self.bucket or not name:
            return False
        if not self.dbprop:
            return False

        # Use the database backend's atomic conditional update
        success = self.dbprop.conditional_update_attr(
            actor_id=self.actor_id,
            bucket=self.bucket,
            name=name,
            old_data=old_data,
            new_data=new_data,
            timestamp=timestamp,
        )

        # Update local cache only if successful
        if success:
            if self.data is None:
                self.data = {}
            assert self.data is not None  # Type narrowing for pyright
            if name not in self.data or self.data[name] is None:
                self.data[name] = {}
            attr_data = self.data[name]
            assert attr_data is not None  # Type narrowing for pyright
            attr_data["data"] = new_data
            attr_data["timestamp"] = timestamp

        return success

    def delete_attr(self, name: str | None = None) -> bool:
        if not name:
            return False
        if self.data and name in self.data:
            del self.data[name]
        if self.dbprop:
            return self.dbprop.delete_attr(
                actor_id=self.actor_id, bucket=self.bucket, name=name
            )
        return False

    def delete_attr_conditional(self, name: str | None = None) -> bool:
        """Atomically delete a single attribute, returning True only if this
        call removed an existing value.

        This is the race-free counterpart to :meth:`delete_attr`: concurrent
        callers racing on the same attribute see exactly one True. Use it to
        enforce single-use consume semantics (e.g. mobile-ticket redemption),
        where the caller that wins the delete is the only one allowed to act on
        the value.
        """
        if not name or not self.dbprop:
            return False
        success = self.dbprop.delete_attr_conditional(
            actor_id=self.actor_id, bucket=self.bucket, name=name
        )
        if success and self.data and name in self.data:
            del self.data[name]
        return success

    def delete_bucket(self) -> bool:
        """Deletes the attribute bucket in the database"""
        if not self.dbprop:
            return False
        if self.dbprop.delete_bucket(actor_id=self.actor_id, bucket=self.bucket):
            if self.config:
                self.dbprop = get_attribute(self.config)
            else:
                self.dbprop = None
            self.data = {}
            self._bucket_loaded = False
            return True
        else:
            return False

    def __init__(
        self,
        actor_id: str | None = None,
        bucket: str | None = None,
        config: Any | None = None,
    ) -> None:
        """A attribute must be initialised with actor_id and bucket"""
        self.config = config
        if self.config:
            self.dbprop = get_attribute(self.config)
        else:
            self.dbprop = None
        self.bucket = bucket
        self.actor_id = actor_id
        self.data: dict[str, dict[str, Any] | None] = {}
        # The bucket is loaded lazily by get_bucket(): most consumers only
        # ever read/write single attributes (get_attr/set_attr), and eagerly
        # loading the whole bucket here cost a database query per
        # construction — including twice per Actor construction.
        self._bucket_loaded = False


class Buckets:
    """Handles all attribute buckets of a specific actor_id

    Access the attributes
    in .props as a dictionary
    """

    def fetch(self) -> dict[str, dict[str, dict[str, Any]]] | bool:
        if not self.actor_id:
            return False
        if self.list:
            result = self.list.fetch(actor_id=self.actor_id)
            return result if result is not None else False
        return False

    def fetch_timestamps(self) -> dict[str, Any] | bool:
        if not self.actor_id:
            return False
        if self.list:
            result = self.list.fetch_timestamps(actor_id=self.actor_id)
            return result if result is not None else False
        return False

    def delete(self) -> bool:
        if not self.list:
            return False
        self.list.delete(actor_id=self.actor_id)
        if self.config:
            self.list = get_attribute_bucket_list(self.config)
        else:
            self.list = None
        return True

    def __init__(self, actor_id: str | None = None, config: Any | None = None) -> None:
        """attributes must always be initialised with an actor_id"""
        self.config = config
        if not actor_id:
            self.list = None
            return
        if self.config:
            self.list = get_attribute_bucket_list(self.config)
        else:
            self.list = None
        self.actor_id = actor_id
