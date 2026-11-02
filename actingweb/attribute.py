import logging
from typing import Any, cast

from actingweb.db import get_attribute, get_attribute_bucket_list
from actingweb.db.exceptions import DbError

logger = logging.getLogger(__name__)


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
        # The one folding read: ``actor.store.x`` never raises on a fault.
        # ``loaded`` stays False after one, and is the caller's signal.
        d = self.__dict__["_db"].get_bucket(strict=False)
        if d:
            for k, v in d.items():
                # Populate directly — no write-through back to the database
                self.__dict__[k] = (v or {}).get("data")

    @property
    def loaded(self) -> bool:
        """Whether the bucket was read and the backend answered.

        The store reads its bucket with ``strict=False``, so a backend fault
        leaves every attribute reading ``None`` for the life of this
        instance; a caller that acts on an absent value must check this
        first.
        """
        self._ensure_loaded()
        return self.__dict__["_db"].loaded

    def mark_empty(self) -> None:
        """Treat the bucket as read and empty, without a database read.

        For an actor that was just created: its bucket has nothing in it yet.
        """
        self.__dict__["_loaded"] = True
        self.__dict__["_db"].mark_loaded_empty()

    def set_confirmed(self, k: str, v: Any, *, raise_on_fault: bool = False) -> bool:
        """Write ``k`` and confirm it landed with a strict read-back.

        A plain assignment raises ``DbError`` on a fault but cannot catch a
        lost acknowledgement. Use this where a value that silently fails to
        land changes a security decision, such as the ``auth_method``
        marker. ``v=None`` deletes ``k`` and confirms it is gone. Returns
        ``False`` on a fault or a mismatch and never raises, unless
        ``raise_on_fault`` is set: then a fault raises ``DbError`` (a
        mismatch still answers False).
        """
        db = self.__dict__["_db"]
        try:
            self._ensure_loaded()
            if v is None:
                # The read decides, whatever the delete answered.
                db.delete_attr(name=k)
            elif not db.set_attr(name=k, data=v):
                return False
            backend = db.dbprop
            if not backend:
                return False
            row = backend.get_attr_strict(
                actor_id=db.actor_id, bucket=db.bucket, name=k
            )
        except DbError:  # folds DbError: False unless raise_on_fault
            if raise_on_fault:
                raise
            logger.error(f"Could not confirm the write of {k}: a store fault")
            return False
        except Exception as e:  # folds DbError: returns False (not confirmed); every caller fails closed or rolls back
            logger.error(f"Could not confirm the write of {k}: {e}")
            return False
        if v is None:
            if row is not None:
                return False
            self.__dict__.pop(k, None)
            return True
        if not row or row.get("data") != v:
            return False
        self.__dict__[k] = v
        return True

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
            # Write first: the write raises DbError on a fault, and the store
            # must not then answer the value storage never got.
            self.__dict__["_db"].set_attr(name=k, data=v)
            self.__dict__[k] = v

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

    def get_bucket(self, strict: bool = True) -> dict[str, Any] | None:
        """Retrieves the attribute bucket from the database.

        A read fault raises ``DbError``. With ``strict=False`` it answers
        ``{}`` instead and leaves :attr:`loaded` False, so a caller can tell
        an empty bucket from one that could not be read. Display reads pass
        it; a read whose "absent" branch is a decision must not.

        Tracks full-bucket loads with a flag rather than data emptiness:
        a set_attr()/get_attr() may have cached individual entries, and
        treating a partially-cached dict as "loaded" would silently return
        an incomplete bucket.

        ``_bucket_loaded`` is set only when the backend answered, and it
        means "loaded, and the backend answered". ``get_attr()`` treats the
        flag as authoritative about ABSENCE: a bucket that could not be read
        must never become "the bucket has no such attribute" for the life of
        this instance. Expired rows are returned, as the backend returns
        them.
        """
        if not self._bucket_loaded:
            if self.dbprop:
                try:
                    fetched_data = self.dbprop.get_bucket(
                        actor_id=self.actor_id, bucket=self.bucket
                    )
                except DbError:  # folds DbError: strict=False read, the caller asked
                    if strict:
                        raise
                    logger.error(
                        f"Bucket {self.bucket} of {self.actor_id} could not be "
                        "read; answering {} (strict=False)"
                    )
                    self.data = {}
                    return self.data
                # None only for missing arguments (or a backend double that
                # folds a fault): the bucket stays unloaded.
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

    @property
    def loaded(self) -> bool:
        """True once :meth:`get_bucket` got an answer from the backend.

        ``get_bucket(strict=False)`` returns ``{}`` both for an empty bucket
        and after a backend fault. Check this after calling it to tell them
        apart: an empty bucket leaves ``loaded`` True, a faulted read leaves
        it False (as it is before any read). After a strict read that
        returned, it is always True.
        """
        return self._bucket_loaded

    def mark_loaded_empty(self) -> None:
        """Record the bucket as read and empty without asking the backend."""
        self.data = {}
        self._bucket_loaded = True

    def get_attr(
        self, name: str | None = None, strict: bool = True
    ) -> dict[str, Any] | None:
        """Retrieves a single attribute.

        A read fault raises ``DbError``; ``strict=False`` answers it with
        ``None`` (and caches nothing). An expired row is returned, as
        ``get_bucket()[name]`` would return it: only the backend's
        ``get_attr_strict`` hides expired rows.

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
                try:
                    row = self.dbprop.get_attr(
                        actor_id=self.actor_id, bucket=self.bucket, name=name
                    )
                except DbError:  # folds DbError: strict=False read, the caller asked
                    if strict:
                        raise
                    logger.error(
                        f"Attribute {self.bucket}/{name} of {self.actor_id} could "
                        "not be read; answering None (strict=False)"
                    )
                    return None
                self.data[name] = row
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
            try:
                ok = self.dbprop.set_attr(
                    actor_id=self.actor_id,
                    bucket=self.bucket,
                    name=name,
                    data=data,
                    timestamp=timestamp,
                    ttl_seconds=ttl_seconds,
                )
            except Exception:
                # The cache was updated before the call; storage may hold
                # either value now.
                self._unload_after_failed_delete(name)
                raise
            if not ok and not data:
                self._unload_after_failed_delete(name)
            return ok
        return False

    def _unload_after_failed_delete(self, name: str) -> None:
        """A delete the backend did not confirm must not leave the loaded
        bucket asserting absence.

        The cache entry is changed BEFORE the backend call, so if the
        backend then raises or reports failure the dict disagrees with
        storage -- and ``get_attr()`` would answer from the authoritative
        dict for the life of this instance. Clearing the flag is the
        fail-safe repair: the next ``get_attr()`` or ``get_bucket()`` reads
        through again.
        """
        self.data.pop(name, None)
        self._bucket_loaded = False

    def conditional_update_attr(
        self,
        name: str | None = None,
        old_data: Any | None = None,
        new_data: Any | None = None,
        timestamp: Any | None = None,
        ttl_seconds: int | None = None,
    ) -> bool:
        """Conditionally update an attribute only if current data matches old_data.

        This provides atomic compare-and-swap functionality for race-free updates.

        Args:
            name: Attribute name
            old_data: Expected current data value (for comparison)
            new_data: New data to set if current matches old_data
            timestamp: Optional timestamp
            ttl_seconds: When given, the same write sets the row's storage TTL.
                Unlike ``set_attr`` it never re-creates a row that is gone.

        Returns:
            True if update succeeded (current matched old_data), False otherwise.
            Both backends also answer False on a fault; a caller that must tell
            the two apart re-reads with the backend's ``get_attr_strict``.
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
            # Only when asked for, so a backend (or test double) written
            # before the keyword existed keeps working for every other caller.
            **({"ttl_seconds": ttl_seconds} if ttl_seconds is not None else {}),
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

    def create_attr_if_absent(
        self,
        name: str | None = None,
        data: Any | None = None,
        timestamp: Any | None = None,
        ttl_seconds: int | None = None,
    ) -> bool:
        """Create an attribute only if no live row holds ``name`` (atomic).

        True means this call won: it created the row or replaced an expired
        one (or the stored row already holds JSON-equal data, an SDK-retried
        create that landed). False means a live row holds the name, or
        another bucket owns the key; a later ``get_attr(name)`` on this
        instance then reads the winner's row. Two callers writing identical
        data both win, so a caller that needs exactly one winner puts a
        per-call nonce in ``data``. Read the row back with the backend's
        ``get_attr_strict`` to see the same expiry rule (``get_attr`` returns
        expired rows). See ``DbAttributeProtocol.create_attr_if_absent``.

        Raises:
            ValueError: ``name`` is missing, or the store is not loaded.
            DbError: on a backend fault (not False).
        """
        if not name:
            raise ValueError("create_attr_if_absent needs a name")
        if not self.actor_id or not self.bucket or not self.dbprop:
            raise ValueError("create_attr_if_absent needs a loaded attribute store")

        won = self.dbprop.create_attr_if_absent(
            actor_id=self.actor_id,
            bucket=self.bucket,
            name=name,
            data=data,
            timestamp=timestamp,
            ttl_seconds=ttl_seconds,
        )
        if self.data is None:
            self.data = {}
        if won:
            self.data[name] = {"data": data, "timestamp": timestamp}
        else:
            # The cache must not keep a miss: the next get_attr(name) reads
            # the winner's row through.
            self.data.pop(name, None)
            self._bucket_loaded = False
        return won

    def delete_attr(self, name: str | None = None) -> bool:
        if not name:
            return False
        if self.data and name in self.data:
            del self.data[name]
        if self.dbprop:
            try:
                ok = self.dbprop.delete_attr(
                    actor_id=self.actor_id, bucket=self.bucket, name=name
                )
            except Exception:
                self._unload_after_failed_delete(name)
                raise
            if not ok:
                self._unload_after_failed_delete(name)
            return ok
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
