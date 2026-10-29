import logging
import os
from typing import Any

from pynamodb.attributes import UnicodeAttribute
from pynamodb.constants import PAY_PER_REQUEST_BILLING_MODE
from pynamodb.exceptions import DoesNotExist, PutError
from pynamodb.indexes import AllProjection, GlobalSecondaryIndex
from pynamodb.models import Model

from actingweb.db.dynamodb._ensure import ensure_table
from actingweb.db.exceptions import DbError

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
        """Modify an actor"""
        if not self.handle:
            logger.debug("Attempted modification of DbActor without db handle")
            return False
        previous = (self.handle.creator, self.handle.passphrase)  # type: ignore[attr-defined]
        if creator and len(creator) > 0:
            # Email in creator needs to be lower case
            if "@" in creator:
                creator = creator.lower()
            self.handle.creator = creator  # type: ignore[attr-defined]
        if passphrase and len(passphrase) > 0:
            self.handle.passphrase = passphrase.decode("utf-8")  # type: ignore[attr-defined]
        try:
            self.handle.save()  # type: ignore[attr-defined]
        except Exception as e:
            # A failed save leaves the handle as stored.
            self.handle.creator, self.handle.passphrase = previous  # type: ignore[attr-defined]
            raise DbError("actor modify") from e
        return True

    def create(
        self,
        actor_id: str | None = None,
        creator: str | None = None,
        passphrase: str | None = None,
    ) -> bool:
        """Create a new actor"""
        if not actor_id:
            return False
        if not creator:
            creator = ""
        # Email in creator needs to be lower case
        if "@" in creator:
            creator = creator.lower()
        if not passphrase:
            passphrase = ""
        if self.get(actor_id=actor_id):
            logger.warning("Trying to create actor that exists(" + actor_id + ")")
            return False
        self.handle = Actor(id=actor_id, creator=creator, passphrase=passphrase)
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

    def delete(self) -> bool:
        """Deletes the actor in the database.

        True when the row is gone after the call (an already-absent row
        counts); a fault raises ``DbError``. False only without a handle.
        """
        if not self.handle:
            logger.debug("Attempted delete of DbActor without db handle")
            return False
        try:
            self.handle.delete()  # type: ignore[attr-defined]
        except Exception as e:
            raise DbError("actor delete") from e
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        ensure_table(Actor)


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
