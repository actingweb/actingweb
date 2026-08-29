from typing import Any

from actingweb.db import get_property, get_property_list

from .property_list import _V1_INDEX_RE, _V2_RANK_MARKER, ListProperty, _v2_is_rank


def rows_for(names: list[str], rows: dict[str, str]) -> dict[str, str]:
    """The subset of ``rows`` attributable to the given list ``names``.

    For narrowing a ``(names, rows)`` pair from ``list_all_with_rows()`` or
    ``list_prefix_with_rows()`` after pruning ``names`` -- the permission
    filter in ``interface/authenticated_views.py`` is the caller. It lives
    here, in the module that owns the row encoding, because ``interface/``
    must never parse a row name: ``list_all_with_rows()``'s own docstring
    declares the rows OPAQUE to callers.

    A bare ``name.startswith(f"list:{name}-")`` is WRONG and is the reason
    this exists. For list ``foo`` it also claims every row of a sibling
    named ``foo-old`` and ``foo-5``. Used to prune, that silently strips a
    PERMITTED sibling's item rows while keeping its ``-meta`` row, and
    ``to_list_from_rows()`` then returns ``[]`` -- a permitted list reported
    as empty, with nothing raised. So attribution uses the same two shape
    checks every reader in ``property_list.py`` uses: ``_V1_INDEX_RE`` for a
    v1 item row's ``-{digits}`` suffix and ``_v2_is_rank()`` for a v2 row's
    ``-#{rank}`` suffix, plus the exact ``-meta`` name.

    Rows that belong to no name in ``names`` are dropped, including rows of
    a list that simply was not asked for. Order is not meaningful.
    """
    if not names:
        return {}

    meta_names = {f"list:{name}-meta": name for name in names}
    # Longest first: for lists "foo" and "foo-5", row "list:foo-5-0" must be
    # tried against "foo-5" (where the suffix "0" passes _V1_INDEX_RE)
    # before "foo" (where the suffix "5-0" fails it). Trying the short one
    # first would reject and move on, which is correct here but only by
    # accident -- ordering makes it correct by construction.
    item_prefixes = sorted(
        ((f"list:{name}-", name) for name in names),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )

    result: dict[str, str] = {}
    for row_name, value in rows.items():
        if row_name in meta_names:
            result[row_name] = value
            continue
        for prefix, _name in item_prefixes:
            if not row_name.startswith(prefix):
                continue
            suffix = row_name[len(prefix) :]
            if suffix.startswith(_V2_RANK_MARKER):
                if _v2_is_rank(suffix[1:]):
                    result[row_name] = value
                    break
            elif _V1_INDEX_RE.match(suffix):
                result[row_name] = value
                break
    return result


class PropertyListStore:
    """
    Explicit interface for managing list properties.

    Used when the application knows it's working with list data.
    """

    def __init__(self, actor_id: str | None = None, config: Any | None = None) -> None:
        self._actor_id = actor_id
        self._config = config
        self.__initialised = True

    def exists(self, name: str) -> bool:
        """Check if a list property exists without creating it."""
        try:
            if self._config:
                db = get_property(self._config)
                meta = db.get(actor_id=self._actor_id, name=f"list:{name}-meta")
                return meta is not None
        except Exception:
            pass
        return False

    def list_all(self) -> list[str]:
        """List all existing list property names."""
        list_names = []
        try:
            if self._config:
                db_list = get_property_list(self._config)
                all_props = (
                    db_list.fetch_all_including_lists(actor_id=self._actor_id) or {}
                )
                for prop_name in all_props.keys():
                    if prop_name.startswith("list:") and prop_name.endswith("-meta"):
                        # Extract list name: "list:name-meta" -> "name"
                        list_name = prop_name[
                            5:-5
                        ]  # Remove 'list:' prefix and '-meta' suffix
                        list_names.append(list_name)
        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error in list_all(): {e}")
        return list_names

    def list_all_with_rows(self) -> tuple[list[str], dict[str, str]]:
        """List all existing list property names, alongside the raw rows
        the names were derived from.

        `list_all()` already pays for `fetch_all_including_lists()` -- the
        actor's WHOLE partition, item rows included -- and discards it.
        This returns that dump too, so a caller who needs both the names
        and each list's contents can prime every list from rows already in
        hand (`ListProperty.prime_from_rows()` /
        `to_list_from_rows()`) instead of paying a second whole-list Query
        per list.

        The rows are a point-in-time snapshot, stale the moment a mutation
        lands, and OPAQUE: feed them to `prime_from_rows()` /
        `to_list_from_rows()` and never inspect or parse a row name -- the
        encoding (`list:{name}-meta`, `list:{name}-{index}` or
        `list:{name}-#{rank}`) is a storage detail the next major
        version's key-prefix scheme will change.

        If you only need ONE namespace of lists, see
        `list_prefix_with_rows()`, which reads just that namespace. Note
        the cost contrast carefully, because it does not go the way the
        names suggest: on a measured account this dump was 1,361.0 RCU
        over 11 queries, and the five scoped reads that together cover the
        same lists were 1,363.5 RCU over 15. Replacing one dump with
        several scoped reads is marginally WORSE. The scoped method pays
        when you want one namespace and were dumping the partition to get
        it -- and the latency win from issuing several of them is the
        CALLER's, from issuing them concurrently.

        On error this returns `([], {})` rather than raising. That is kept
        for compatibility and is the OPPOSITE of
        `list_prefix_with_rows()`; the asymmetry is deliberate and its
        reasoning is on that method.
        """
        list_names: list[str] = []
        rows: dict[str, str] = {}
        try:
            if self._config:
                db_list = get_property_list(self._config)
                rows = db_list.fetch_all_including_lists(actor_id=self._actor_id) or {}
                for prop_name in rows.keys():
                    if prop_name.startswith("list:") and prop_name.endswith("-meta"):
                        list_names.append(prop_name[5:-5])
        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error in list_all_with_rows(): {e}")
            return [], {}
        return list_names, rows

    def list_prefix_with_rows(self, prefix: str) -> tuple[list[str], dict[str, str]]:
        """List properties whose name begins with `prefix`, and their rows.

        The scoped counterpart of `list_all_with_rows()`: ONE namespace of
        the actor's lists instead of the whole partition. Both halves of
        the return are scoped -- `names` holds only the matching lists, and
        `rows` only their rows -- so the pair stays internally consistent.
        That is worth reading twice, because it is where a migration from
        `list_all_with_rows()` goes wrong SILENTLY: code that swaps the
        method and keeps iterating `names` simply stops seeing every list
        outside the prefix, with nothing raised.

        `prefix` is a PREFIX, not a namespace. It matches every list whose
        name begins with it -- including a list named exactly `prefix`, and
        siblings such as `{prefix}-old`. If you mean a namespace, pass the
        delimiter: `"memory_"`, not `"memory"`.

        Cost, honestly: this is not universally cheaper than the dump. Five
        scoped reads covering the same lists measured 1,363.5 RCU / 15
        queries against the dump's 1,361.0 / 11 -- summing all of them is
        marginally worse. It pays when you want ONE namespace, or when you
        can issue several concurrently: the library is synchronous and
        spends one query per call, so any latency win is the caller's to
        take.

        Reads are EVENTUALLY consistent, matching what
        `fetch_all_including_lists()` already does on DynamoDB (PynamoDB's
        `Model.query()` default), and halving the read capacity -- which is
        what decides whether scoping pays at all. Do not call this to read
        back a write you just made.

        There is deliberately no names-only `list_prefix()` sibling. A
        keys-only projection saves no DynamoDB read capacity (a projection
        still pays for the whole item; measured 1,361.0 either way), so it
        would break the `list_all`/`list_all_with_rows` pairing for nothing.

        Rows are OPAQUE and a point-in-time snapshot, exactly as for
        `list_all_with_rows()`. Different lists in one result may reflect
        different instants; there is no snapshot isolation across them.

        Args:
            prefix: The list-name prefix, without the storage `list:`
                prefix. Pass `"memory_"` to reach lists `memory_a`,
                `memory_b`, ...

        Returns:
            `(names, rows)`. Both empty when nothing matches -- which for a
            scoped read is a common, ordinary answer.

            `names` is derived from `-meta` rows, exactly as in
            `list_all_with_rows()`. A damaged list whose meta row was lost
            therefore contributes rows attributed to no name, rather than
            having those rows dropped -- matching the sibling method, and
            leaving recoverable data visible. Use `rows_for()` when you
            need only the rows belonging to a known set of names.

        Raises:
            ValueError: If `prefix` is empty. An empty prefix would be the
                whole-partition dump under a name promising the opposite;
                call `list_all_with_rows()` when that is what you want.
            DbError: On a backend fault. UNLIKE `list_all_with_rows()`,
                which swallows to `([], {})`. The asymmetry is deliberate:
                for a scoped read "nothing here" is the common answer, so
                swallowing would render a throttled query as "you have no
                memories" and the caller could not tell.
        """
        if not prefix:
            raise ValueError(
                "list_prefix_with_rows() needs a non-empty prefix; an empty "
                "one would read the actor's whole partition under a name "
                "promising otherwise. Call list_all_with_rows() for that."
            )
        if not self._config:
            return [], {}

        rows = get_property(self._config).get_prefix(
            actor_id=self._actor_id,
            prefix=f"list:{prefix}",
            consistent_read=False,
        )
        list_names = [
            row_name[5:-5]
            for row_name in rows
            if row_name.startswith("list:") and row_name.endswith("-meta")
        ]
        return list_names, rows

    def __getattr__(self, k: str) -> ListProperty:
        """Return a ListProperty for the requested list name."""
        if k.startswith("_"):
            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{k}'"
            )

        # Validate actor_id is not None before creating ListProperty
        if self._actor_id is None:
            raise RuntimeError("Cannot create ListProperty without a valid actor_id")

        # Return a ListProperty - don't add "list:" prefix here, ListProperty will handle it
        return ListProperty(self._actor_id, k, self._config)


class PropertyStore:
    def __init__(self, actor_id: str | None = None, config: Any | None = None) -> None:
        self._actor_id = actor_id
        self._config = config
        self.__initialised = True

    def __getitem__(self, k: str) -> Any:
        # Block access to list: prefixed keys - use property_lists instead
        if k.startswith("list:"):
            raise ValueError(
                f"Cannot access list properties via [] operator. "
                f"Use property_lists.{k[5:]} instead."
            )
        return self.__getattr__(k)

    def __setitem__(self, k: str, v: Any) -> None:
        # Block access to list: prefixed keys - use property_lists instead
        if k.startswith("list:"):
            raise ValueError(
                f"Cannot access list properties via [] operator. "
                f"Use property_lists.{k[5:]} instead."
            )
        return self.__setattr__(k, v)

    def __setattr__(self, k: str, v: Any) -> None:
        if "_PropertyStore__initialised" not in self.__dict__:
            return object.__setattr__(self, k, v)
        if v is None:
            if k in self.__dict__:
                self.__delattr__(k)
        else:
            # Check for list collision - error if list exists. Only needed
            # when the property is not already known as an existing simple
            # property in this store (collision checks in both directions
            # guarantee a name cannot be both) — skipping it saves one
            # metadata read on every repeat write. A cached None (missed
            # read) must NOT skip the check.
            if self.__dict__.get(k) is None and self.__dict__.get("_config"):
                list_store = PropertyListStore(
                    actor_id=self.__dict__.get("_actor_id"),
                    config=self.__dict__["_config"],
                )
                if list_store.exists(k):
                    raise ValueError(
                        f"Cannot create property '{k}': a list with this name already exists. "
                        f"Delete the list first or use a different name."
                    )

            self.__dict__[k] = v
        # Re-init property to avoid overwrite
        self.__dict__["_db"] = get_property(self.__dict__["_config"])
        # set() will retrieve an attribute and delete it if value = None
        self.__dict__["_db"].set(actor_id=self.__dict__["_actor_id"], name=k, value=v)

    def __getattr__(self, k: str) -> Any:
        try:
            return self.__dict__[k]
        except KeyError:
            self.__dict__["_db"] = get_property(self.__dict__["_config"])
            self.__dict__[k] = self.__dict__["_db"].get(
                actor_id=self.__dict__["_actor_id"], name=k
            )
            return self.__dict__[k]

    def get_all(self) -> dict[str, Any]:
        """Fetch all properties from the database and return as dictionary."""
        if not self._actor_id or not self._config:
            return {}
        db_list = get_property_list(self._config)
        props = db_list.fetch(actor_id=self._actor_id)
        if isinstance(props, dict):
            return props
        return {}


class Property:
    """
    property is the main entity keeping a property.

    It needs to be initalised at object creation time.

    """

    def get(self) -> Any:
        """Retrieves the property from the database"""
        if not self.dbprop:
            # New property after a delete()
            if self.config:
                self.dbprop = get_property(self.config)
            else:
                self.dbprop = None
            self.value = None
        if self.dbprop:
            self.value = self.dbprop.get(actor_id=self.actor_id, name=self.name)
        else:
            self.value = None
        return self.value

    def set(self, value: Any) -> bool:
        """Sets a new value for this property"""
        if not self.dbprop:
            # New property after a delete()
            if self.config:
                self.dbprop = get_property(self.config)
            else:
                self.dbprop = None
        if not self.actor_id or not self.name:
            return False
        # Make sure we have made a dip in db to avoid two properties
        # with same name
        if self.dbprop:
            db_value = self.dbprop.get(actor_id=self.actor_id, name=self.name)
        else:
            db_value = None
        if db_value == value:
            return True
        self.value = value
        if self.dbprop:
            return self.dbprop.set(actor_id=self.actor_id, name=self.name, value=value)
        return False

    def delete(self) -> bool | None:
        """Deletes the property in the database"""
        if not self.dbprop:
            return
        if self.dbprop.delete():
            self.value = None
            self.dbprop = None
            return True
        else:
            return False

    def get_actor_id(self) -> str | None:
        return self.actor_id

    def __init__(
        self,
        actor_id: str | None = None,
        name: str | None = None,
        value: Any | None = None,
        config: Any | None = None,
    ) -> None:
        """A property must be initialised with actor_id and name or
        name and value (to find an actor's property of a certain value)
        """
        self.config = config
        if self.config:
            self.dbprop = get_property(self.config)
        else:
            self.dbprop = None
        self.name = name
        if not actor_id and name and len(name) > 0 and value and len(value) > 0:
            if self.dbprop:
                self.actor_id = self.dbprop.get_actor_id_from_property(
                    name=name, value=value
                )
            else:
                self.actor_id = None
            if not self.actor_id:
                return
            self.value = value
        else:
            self.actor_id = actor_id
            self.value = None
            if name and len(name) > 0:
                self.get()


class Properties:
    """Handles all properties of a specific actor_id

    Access the properties
    in .props as a dictionary
    """

    def fetch(self) -> dict[str, Any] | bool:
        if not self.actor_id:
            return False
        if not self.list:
            return False
        if self.props is not None:
            return self.props
        self.props = self.list.fetch(actor_id=self.actor_id)
        return self.props if self.props is not None else False

    def delete(self) -> bool:
        if not self.list:
            self.fetch()
        if not self.list:
            return False
        self.list.delete()
        return True

    def __init__(self, actor_id: str | None = None, config: Any | None = None) -> None:
        """Properties must always be initialised with an actor_id"""
        self.config = config
        if not actor_id:
            self.list = None
            return
        if self.config:
            self.list = get_property_list(self.config)
        else:
            self.list = None
        self.actor_id = actor_id
        self.props = None
        self.fetch()
