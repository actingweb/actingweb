import logging
import os
import random
import time
import uuid
from collections.abc import Callable
from typing import Any

from pynamodb.attributes import UnicodeAttribute
from pynamodb.connection import Connection
from pynamodb.constants import PAY_PER_REQUEST_BILLING_MODE
from pynamodb.exceptions import (
    DeleteError,
    DoesNotExist,
    PutError,
    TransactWriteError,
    UpdateError,
)
from pynamodb.indexes import AllProjection, GlobalSecondaryIndex
from pynamodb.models import Model
from pynamodb.transactions import TransactWrite

from actingweb.db.creator_rules import is_exempt, normalise_creator
from actingweb.db.dynamodb._ensure import ensure_table
from actingweb.db.dynamodb.creator import Creator
from actingweb.db.exceptions import CreatorTaken, DbError

"""
    DbActor handles all db operations for an actor
    Google datastore for google is used as a backend.
"""

logger = logging.getLogger(__name__)


class CreatorIndex(GlobalSecondaryIndex[Any]):
    """
    Secondary index on actor
    """

    class Meta:
        index_name = "creator-index"
        projection = AllProjection()

    creator = UnicodeAttribute(hash_key=True)


class Actor(Model):
    """
    DynamoDB data model for an actor
    """

    class Meta:  # type: ignore[misc]
        table_name = os.getenv("AWS_DB_PREFIX", "demo_actingweb") + "_actors"
        billing_mode = PAY_PER_REQUEST_BILLING_MODE
        region = os.getenv("AWS_DEFAULT_REGION", "us-west-1")
        host = os.getenv("AWS_DB_HOST", None)

    id = UnicodeAttribute(hash_key=True)
    creator = UnicodeAttribute()
    passphrase = UnicodeAttribute()
    creator_index = CreatorIndex()


class DbActor:
    """
    DbActor does all the db operations for actor objects

    """

    def get(
        self, actor_id: str | None = None, *, strict: bool = True
    ) -> dict[str, Any] | None:
        """Retrieves the actor from the database.

        None when no such actor exists. A read fault raises ``DbError``;
        ``strict=False`` answers it with None instead (logged at ERROR).
        """
        if not actor_id:
            return None
        try:
            self.handle = Actor.get(actor_id, consistent_read=True)
        except DoesNotExist:
            return None
        except Exception as e:
            if strict:
                raise DbError("actor get") from e
            logger.error(
                f"Failed to read actor {actor_id} from DynamoDB: "
                f"{type(e).__name__}: {e}. Returning None (strict=False)."
            )
            return None
        if self.handle:
            t = self.handle
            return {
                "id": t.id,
                "creator": t.creator,
                "passphrase": t.passphrase,
            }
        else:
            return None

    def get_by_creator(
        self,
        creator: str | None = None,
        *,
        strict: bool = True,
        consistent: bool = False,
        ids_only: bool = False,
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """The actors with this creator, as a list (``[]`` when none).

        ``ids_only`` answers ``[{"id": ...}]`` from the index alone, with no
        per-row read (``consistent`` is then ignored): a caller that reads
        only some of the rows lists them cheaply.

        The creator index is eventually consistent: it can list an actor
        whose row was just deleted, or miss one just created. With
        ``consistent`` each listed row is re-read with a consistent get and a
        row deleted since the index listed it is left out; without it the
        index's projection is returned as is.

        A read fault raises ``DbError``; ``strict=False`` answers it with
        None instead.
        """
        if not creator:
            return None
        if "@" in creator:
            creator = creator.lower()
        ret: list[dict[str, Any]] = []
        try:
            query = (
                Actor.creator_index.query(creator, attributes_to_get=["id"])
                if ids_only
                else Actor.creator_index.query(creator)
            )
            for c in query:
                logger.debug("get_by_creator matched actor id=" + c.id)
                if ids_only:
                    ret.append({"id": c.id})
                    continue
                if consistent:
                    try:
                        row = Actor.get(c.id, consistent_read=True)
                    except DoesNotExist:
                        continue  # deleted since the index listed it
                else:
                    row = c
                ret.append(
                    {"id": row.id, "creator": row.creator, "passphrase": row.passphrase}
                )
        except Exception as e:
            if strict:
                raise DbError("actor get_by_creator") from e
            logger.error(f"Error retrieving actors by creator {creator}: {e}")
            return None
        return ret

    def modify(
        self, creator: str | None = None, passphrase: bytes | None = None
    ) -> bool:
        """Modify an actor.

        With ``unique_creator`` a new non-exempt creator is claimed in the
        same transaction as the rename (``CreatorTaken`` when another actor
        holds it), and the old one is released afterwards. False when the
        stored creator no longer matches the handle.
        """
        if not self.handle:
            logger.debug("Attempted modification of DbActor without db handle")
            return False
        old_creator = self.handle.creator  # type: ignore[attr-defined]
        new_creator = normalise_creator(creator) if creator else old_creator
        if self.unique_creator and new_creator != old_creator:
            return self._modify_unique(old_creator, new_creator, passphrase)
        previous = (self.handle.creator, self.handle.passphrase)  # type: ignore[attr-defined]
        if creator and len(creator) > 0:
            self.handle.creator = new_creator  # type: ignore[attr-defined]
        if passphrase and len(passphrase) > 0:
            self.handle.passphrase = passphrase.decode("utf-8")  # type: ignore[attr-defined]
        # Conditioned on the creator this handle was loaded with: the save
        # writes the whole row, and unconditioned it would write the
        # handle's copy back over a concurrent rename (under the flag,
        # leaving a creator with no record) or re-create a deleted actor.
        # A conditional PutItem needs no permission beyond the plain one.
        condition = Actor.id.exists() & creator_is(old_creator)
        if not (passphrase and len(passphrase) > 0):
            # Not changing it, but the whole row is written: a rotation since
            # the load (a sign-in's clean-in-place) would be undone.
            old_passphrase = previous[1]
            condition = condition & (
                Actor.passphrase.does_not_exist()
                if old_passphrase is None
                else Actor.passphrase == old_passphrase
            )
        try:
            self.handle.save(condition=condition)  # type: ignore[attr-defined]
        except PutError as e:
            # A failed save leaves the handle as stored.
            self.handle.creator, self.handle.passphrase = previous  # type: ignore[attr-defined]
            if e.cause_response_code == "ConditionalCheckFailedException":
                logger.warning(
                    f"Modify of actor {self.handle.id}: the stored creator no "  # type: ignore[attr-defined]
                    "longer matches; nothing changed"
                )
                return False
            raise DbError("actor modify") from e
        except Exception as e:
            self.handle.creator, self.handle.passphrase = previous  # type: ignore[attr-defined]
            raise DbError("actor modify") from e
        return True

    def _modify_unique(
        self, old_creator: str, new_creator: str, passphrase: bytes | None
    ) -> bool:
        """The rename under ``unique_creator``: the actor update (conditioned
        on the old creator) and the new record in one transaction, then the
        old record released only if it names this actor.

        The release is separate on purpose: a pre-enable duplicate's old
        creator is held by the kept actor, and a condition on it inside the
        transaction would cancel the rename.
        """
        actor = self.handle
        assert actor is not None
        actor_id = actor.id
        actions: list[Any] = [Actor.creator.set(new_creator)]
        new_passphrase = (
            passphrase.decode("utf-8") if passphrase and len(passphrase) > 0 else None
        )
        if new_passphrase is not None:
            actions.append(Actor.passphrase.set(new_passphrase))
        condition = creator_is(old_creator)
        if is_exempt(new_creator):
            try:
                actor.update(actions=actions, condition=condition)
            except UpdateError as e:
                if e.cause_response_code == "ConditionalCheckFailedException":
                    logger.warning(
                        f"Modify of actor {actor_id}: the stored creator no "
                        "longer matches; nothing changed"
                    )
                    return False
                raise DbError("actor modify") from e
            except Exception as e:
                raise DbError("actor modify") from e
        else:
            record = Creator(creator=new_creator, actor_id=actor_id)

            def build(t: TransactWrite) -> None:
                t.update(actor, actions=actions, condition=condition)
                t.save(
                    record,
                    condition=(
                        Creator.creator.does_not_exist()
                        | (Creator.actor_id == actor_id)
                    ),
                )

            codes = self._run_transaction(build, op="actor modify")
            if codes is not None:
                if self._record_names_other(new_creator, actor_id):
                    raise CreatorTaken(new_creator)
                logger.warning(
                    f"Modify of actor {actor_id}: the stored creator no longer "
                    "matches; nothing changed"
                )
                return False
            actor.creator = new_creator
            if new_passphrase is not None:
                actor.passphrase = new_passphrase
        # A case-only change of a legacy address keeps the same key: the
        # record just claimed is this actor's, and must stay.
        if not is_exempt(old_creator) and normalise_creator(old_creator) != new_creator:
            self._release_record(old_creator, actor_id)
        return True

    def create(
        self,
        actor_id: str | None = None,
        creator: str | None = None,
        passphrase: str | None = None,
        *,
        replace_holder: str | None = None,
    ) -> bool:
        """Create a new actor.

        With ``unique_creator`` a non-exempt creator is claimed in the same
        transaction (``CreatorTaken`` when another actor holds it);
        ``replace_holder`` moves it from that actor instead
        (:meth:`replace_creator_holder`).
        """
        if not actor_id:
            return False
        # Email in creator needs to be lower case
        creator = normalise_creator(creator)
        if not passphrase:
            passphrase = ""
        if replace_holder is not None:
            return self.replace_creator_holder(
                replace_holder,
                actor_id=actor_id,
                creator=creator,
                passphrase=passphrase,
            )
        if self.get(actor_id=actor_id):
            logger.warning("Trying to create actor that exists(" + actor_id + ")")
            return False
        actor = Actor(id=actor_id, creator=creator, passphrase=passphrase)
        if self.unique_creator and not is_exempt(creator):
            record = Creator(creator=creator, actor_id=actor_id)

            def build(t: TransactWrite) -> None:
                t.save(actor, condition=Actor.id.does_not_exist())
                t.save(record, condition=Creator.creator.does_not_exist())

            codes = self._run_transaction(build, op="actor create")
            if codes is not None:
                if self._actor_exists(actor_id):
                    logger.warning(
                        "Trying to create actor that exists(" + actor_id + ")"
                    )
                    return False
                raise CreatorTaken(creator)
            self.handle = actor
            return True
        self.handle = actor
        try:
            # The condition, not the check above, is what keeps a live actor
            # from being overwritten by a concurrent create.
            self.handle.save(condition=Actor.id.does_not_exist())
        except PutError as e:
            self.handle = None
            if e.cause_response_code == "ConditionalCheckFailedException":
                logger.warning("Trying to create actor that exists(" + actor_id + ")")
                return False
            raise DbError("actor create") from e
        except Exception as e:
            self.handle = None
            raise DbError("actor create") from e
        return True

    def replace_creator_holder(
        self,
        old_id: str,
        *,
        actor_id: str,
        creator: str,
        passphrase: str,
    ) -> bool:
        """Create ``actor_id`` and move ``creator``'s record to it from
        ``old_id``, in one transaction.

        False when ``actor_id`` is taken; ``CreatorTaken`` when the record no
        longer names ``old_id`` (nothing is written either way). ``old_id``
        keeps its row, which the caller removes; its delete then leaves the
        record alone, since the record no longer names it.
        """
        if not self.unique_creator:
            raise ValueError("replace_creator_holder needs unique_creator")
        creator = normalise_creator(creator)
        if is_exempt(creator):
            raise ValueError("an exempt creator has no holder to replace")
        actor = Actor(id=actor_id, creator=creator, passphrase=passphrase or "")
        record = Creator(creator=creator)

        def build(t: TransactWrite) -> None:
            t.save(actor, condition=Actor.id.does_not_exist())
            t.update(
                record,
                actions=[Creator.actor_id.set(actor_id)],
                condition=Creator.actor_id == old_id,
            )

        codes = self._run_transaction(build, op="actor replace holder")
        if codes is not None:
            if self._actor_exists(actor_id):
                logger.warning("Trying to create actor that exists(" + actor_id + ")")
                return False
            raise CreatorTaken(creator)
        self.handle = actor
        return True

    def get_creator_holder(
        self, creator: str | None = None, *, strict: bool = True
    ) -> str | None:
        """The actor id the ``creators`` record names, read consistently;
        None when there is no record (or for an exempt creator)."""
        if not self.unique_creator:
            raise ValueError("get_creator_holder needs unique_creator")
        value = normalise_creator(creator)
        if is_exempt(value):
            return None
        try:
            record = Creator.get(value, consistent_read=True)
        except DoesNotExist:
            return None
        except Exception as e:
            if strict:
                raise DbError("creator holder get") from e
            logger.error(f"Error reading the creator record of {value!r}: {e}")
            return None
        return record.actor_id or None

    def release_stale_creator(self, creator: str, actor_id: str) -> bool:
        """Remove ``creator``'s record naming ``actor_id`` if a consistent read
        shows that actor gone or holding another creator. True when removed.

        The one way a record that is not the caller's own is deleted (the
        sign-in lookup, ``actingweb-unique-creators resolve``): the delete is
        conditioned on ``actor_id``, so a record moved meanwhile is kept.
        """
        if not self.unique_creator:
            raise ValueError("release_stale_creator needs unique_creator")
        return release_stale_record(normalise_creator(creator), actor_id)

    def delete(self) -> bool:
        """Deletes the actor in the database.

        True when the row is gone after the call (an already-absent row
        counts); a fault raises ``DbError``. False only without a handle.
        With ``unique_creator`` the creator's record is then removed only if
        it names this actor; a fault there is logged, not raised, since the
        actor is gone (``actingweb-unique-creators report`` lists the record).
        """
        if not self.handle:
            logger.debug("Attempted delete of DbActor without db handle")
            return False
        actor_id = self.handle.id  # type: ignore[attr-defined]
        creator = self.handle.creator  # type: ignore[attr-defined]
        if not self.unique_creator:
            try:
                self.handle.delete()  # type: ignore[attr-defined]
            except Exception as e:
                raise DbError("actor delete") from e
            self.handle = None
            return True
        creator = self._delete_as_stored(self.handle, creator)
        self.handle = None
        if not is_exempt(creator):
            self._release_record(creator, actor_id)
        return True

    @staticmethod
    def _delete_as_stored(handle: Any, creator: str) -> str:
        """Delete the actor row and return the creator it had when deleted.

        The delete is conditioned on the handle's creator; when another
        process renamed the actor since it was loaded, the row is read again
        and deleted under its current creator, so the record released is the
        one that names it (a stale handle would leave that record orphaned).
        """
        for _ in range(2):
            try:
                handle.delete(condition=creator_is(creator))
                return creator
            except DeleteError as e:
                if e.cause_response_code != "ConditionalCheckFailedException":
                    raise DbError("actor delete") from e
            except Exception as e:
                raise DbError("actor delete") from e
            try:
                current = Actor.get(handle.id, consistent_read=True)
            except DoesNotExist:
                return creator  # already gone
            except Exception as e:
                raise DbError("actor delete") from e
            creator = current.creator
        raise DbError("actor delete")

    def _release_record(self, creator: str, actor_id: str) -> None:
        """Delete ``creator``'s record if it names ``actor_id``.

        A record naming another actor (a pre-enable duplicate's kept actor,
        a successor after the sign-in swap) is left alone. A fault is logged:
        the actor change it follows has committed.
        """
        # Keyed as stored: a legacy mixed-case address has a lowercase key.
        creator = normalise_creator(creator)
        try:
            Creator(creator=creator).delete(condition=Creator.actor_id == actor_id)
        except DeleteError as e:
            if e.cause_response_code == "ConditionalCheckFailedException":
                return

            logger.error(
                f"The creator record of {creator!r} could not be released by "
                f"actor {actor_id}: {e}; actingweb-unique-creators report lists it"
            )
        except Exception as e:
            logger.error(
                f"The creator record of {creator!r} could not be released by "
                f"actor {actor_id}: {e}; actingweb-unique-creators report lists it"
            )

    # Which condition failed is confirmed with one consistent read rather
    # than taken from the cancellation reasons' index: DynamoDB Local reports
    # the failure on the first item whatever failed. Only the refused path
    # pays the read.
    @staticmethod
    def _actor_exists(actor_id: str) -> bool:
        try:
            Actor.get(actor_id, consistent_read=True)
        except DoesNotExist:
            return False
        except Exception as e:
            raise DbError("actor get") from e
        return True

    @staticmethod
    def _record_names_other(creator: str, actor_id: str) -> bool:
        try:
            record = Creator.get(creator, consistent_read=True)
        except DoesNotExist:
            return False
        except Exception as e:
            raise DbError("creator record get") from e
        return record.actor_id != actor_id

    # One try and at most two retries on a TransactionConflict.
    TRANSACT_ATTEMPTS = 3
    _connection: Connection | None = None

    @classmethod
    def _get_connection(cls) -> Connection:
        """The connection transactions run on, built lazily from the actor
        table's endpoint and region (the ``creators`` table shares them)."""
        if cls._connection is None:
            cls._connection = Connection(host=Actor.Meta.host, region=Actor.Meta.region)
        return cls._connection

    @classmethod
    def _run_transaction(
        cls, build: Callable[[TransactWrite], None], *, op: str
    ) -> list[str | None] | None:
        """Commit one ``TransactWriteItems``: None when it committed, else the
        cancellation code of each item when a condition failed (callers
        confirm which one with a read, see ``_actor_exists``).

        A ``TransactionConflict`` is retried at most twice, with jitter and
        the same client request token, so a retry of a commit whose answer
        was lost is not applied twice. Anything else raises ``DbError``.
        """
        token = uuid.uuid4().hex
        for attempt in range(cls.TRANSACT_ATTEMPTS):
            try:
                with TransactWrite(
                    connection=cls._get_connection(), client_request_token=token
                ) as transaction:
                    build(transaction)
                return None
            except TransactWriteError as e:
                codes = [r.code if r else None for r in (e.cancellation_reasons or [])]
                conflict = "TransactionConflict" in codes or e.cause_response_code in (
                    "TransactionConflictException",
                    "TransactionInProgressException",
                )
                last = attempt == cls.TRANSACT_ATTEMPTS - 1
                if conflict and not last:
                    time.sleep(random.uniform(0.05, 0.2) * (attempt + 1))
                    continue
                # On the last attempt a failed condition wins over a conflict:
                # the caller's answer (taken, changed) is not an outage.
                if "ConditionalCheckFailed" in codes:
                    return codes
                raise DbError(op) from e
            except Exception as e:
                raise DbError(op) from e
        raise DbError(op)

    def __init__(self, *, unique_creator: bool = False) -> None:
        self.handle = None
        self.unique_creator = unique_creator
        ensure_table(Actor)
        if unique_creator:
            ensure_table(Creator)


class DbActorList:
    """
    DbActorList does all the db operations for list of actor objects
    """

    def fetch(self, *, strict: bool = True) -> list[dict[str, Any]] | bool:
        """Retrieves ALL actors in the database (``[]`` when there are none).

        Admin/maintenance use only: this is a deliberate full-table Scan,
        O(table size) and unpaginated — do not call it on a serving path.
        A read fault raises ``DbError``; ``strict=False`` answers it with
        False instead.
        """
        ret = []
        try:
            for t in Actor.scan():
                ret.append(
                    {
                        "id": t.id,
                        "creator": t.creator,
                    }
                )
        except Exception as e:
            if strict:
                raise DbError("actor list fetch") from e
            logger.error(f"Error fetching actor list: {e}")
            return False
        return ret

    def __init__(self):
        self.handle = None


def release_stale_record(creator: str, actor_id: str) -> bool:
    """Delete the record ``creator → actor_id`` if the actor is gone or no
    longer holds ``creator`` on a consistent read, and is still as read
    when the delete commits (rule 9 of the invariant audit); True when
    deleted.

    Raises ``DbError`` on a fault. Shared by the backend
    (:meth:`DbActor.release_stale_creator`) and the maintenance command.
    """
    try:
        current = Actor.get(actor_id, consistent_read=True)
    except DoesNotExist:
        current = None
    except Exception as e:
        raise DbError("actor get") from e
    if current is not None and normalise_creator(current.creator) == creator:
        return False  # it holds the creator: the record is true

    def build(t: TransactWrite) -> None:
        t.delete(Creator(creator=creator), condition=Creator.actor_id == actor_id)
        # The actor still as read: a rename back to ``creator`` in between
        # would otherwise lose the record it just claimed.
        t.condition_check(Actor, actor_id, condition=actor_as_read(current))

    # A failed condition: the record moved or went, or the actor changed.
    return DbActor._run_transaction(build, op="creator record delete") is None


def record_for_actor_as_read(
    creator: str, actor: "Actor", *, moving_from: str | None = None
) -> bool:
    """Write the record ``creator → actor.id``, committed only while the
    actor row is as read (rule 9 of the invariant audit); True when it
    committed. With ``moving_from`` the record is moved from that actor,
    otherwise written only if absent. Raises ``DbError`` on a fault."""

    def build(t: TransactWrite) -> None:
        if moving_from is None:
            t.save(
                Creator(creator=creator, actor_id=actor.id),
                condition=Creator.creator.does_not_exist(),
            )
        else:
            t.update(
                Creator(creator=creator),
                actions=[Creator.actor_id.set(actor.id)],
                condition=Creator.actor_id == moving_from,
            )
        t.condition_check(Actor, actor.id, condition=actor_as_read(actor))

    return DbActor._run_transaction(build, op="creator record write") is None


def move_stale_record(creator: str, stale_id: str, actor: "Actor") -> bool:
    """Move the record ``creator → stale_id`` to ``actor.id`` in one
    transaction, committed only while ``stale_id`` is still gone or holds
    another creator and ``actor`` is as read (rules 1 and 9). With a release
    and a write as two steps a sign-in in between would find no record and
    create another actor. False when ``stale_id`` holds ``creator`` (the
    record is true) or anything changed. Raises ``DbError`` on a fault."""
    try:
        stale: Actor | None = Actor.get(stale_id, consistent_read=True)
    except DoesNotExist:
        stale = None
    except Exception as e:
        raise DbError("actor get") from e
    if stale is not None and normalise_creator(stale.creator) == creator:
        return False

    def build(t: TransactWrite) -> None:
        t.update(
            Creator(creator=creator),
            actions=[Creator.actor_id.set(actor.id)],
            condition=Creator.actor_id == stale_id,
        )
        t.condition_check(Actor, stale_id, condition=actor_as_read(stale))
        t.condition_check(Actor, actor.id, condition=actor_as_read(actor))

    return DbActor._run_transaction(build, op="creator record move") is None


def actor_as_read(row: "Actor | None") -> Any:
    """The condition that an actor row is still as a consistent read found
    it: the same stored creator, or still absent. For a ``condition_check``
    beside a record write that depends on the row."""
    if row is None:
        return Actor.id.does_not_exist()
    return Actor.id.exists() & creator_is(row.creator)


def creator_is(value: str | None) -> Any:
    """The condition that the stored creator is ``value``: absent for None
    (an equality with None never matches a missing attribute), and an
    exact match otherwise, ``""`` included."""
    if value is None:
        return Actor.creator.does_not_exist()
    return Actor.creator == value
