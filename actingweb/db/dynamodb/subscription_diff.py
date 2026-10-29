import datetime
import logging
import os

from pynamodb.attributes import NumberAttribute, UnicodeAttribute, UTCDateTimeAttribute
from pynamodb.constants import PAY_PER_REQUEST_BILLING_MODE
from pynamodb.exceptions import DoesNotExist, PutError
from pynamodb.models import Model

from actingweb.db.dynamodb._ensure import ensure_table
from actingweb.db.exceptions import DbError

"""
    DbSubscriptionDiff handles all db operations for a subscription diff

    DbSubscriptionDiffList handles list of subscriptions diffs
    Google datastore for google is used as a backend.
"""

logger = logging.getLogger(__name__)


class SubscriptionDiff(Model):
    class Meta:  # type: ignore[misc]
        table_name = os.getenv("AWS_DB_PREFIX", "demo_actingweb") + "_subscriptiondiffs"
        billing_mode = PAY_PER_REQUEST_BILLING_MODE
        region = os.getenv("AWS_DEFAULT_REGION", "us-west-1")
        host = os.getenv("AWS_DB_HOST", None)

    id = UnicodeAttribute(hash_key=True)
    subid_seqnr = UnicodeAttribute(range_key=True)
    subid = UnicodeAttribute()
    timestamp = UTCDateTimeAttribute(default=datetime.datetime.utcnow())
    diff = UnicodeAttribute()
    seqnr = NumberAttribute(default=1)


class DbSubscriptionDiff:
    """
    DbSubscriptionDiff does all the db operations for subscription diff objects

    The  actor_id must always be set.
    """

    def get(self, actor_id=None, subid=None, seqnr=None, *, strict=True):
        """Retrieves the subscriptiondiff from the database.

        None when absent. A read fault raises ``DbError``; ``strict=False``
        answers it with None.
        """
        if not actor_id and not self.handle:
            return None
        if not subid and not self.handle:
            logger.debug("Attempt to get subscriptiondiff without subid")
            return None
        if not self.handle:
            try:
                if not seqnr:
                    query = SubscriptionDiff.query(
                        actor_id,
                        SubscriptionDiff.subid_seqnr.startswith(subid or ""),
                        consistent_read=True,
                    )
                    # Find the record with lowest seqnr
                    for t in query:
                        if not self.handle:
                            self.handle = t
                            continue
                        if t.seqnr < self.handle.seqnr:
                            self.handle = t
                else:
                    self.handle = SubscriptionDiff.get(
                        actor_id, (subid or "") + ":" + str(seqnr), consistent_read=True
                    )
            except DoesNotExist:
                self.handle = None
                return None
            except Exception as e:
                self.handle = None
                if strict:
                    raise DbError("subscription diff get") from e
                logger.error(f"Error reading subscription diff of {actor_id}: {e}")
                return None
        if self.handle:
            t = self.handle
            return {
                "id": t.id,
                "subscriptionid": t.subid,
                "timestamp": t.timestamp,
                "data": t.diff,
                "sequence": t.seqnr,
            }
        else:
            return None

    def create(self, actor_id=None, subid=None, diff="", seqnr=1):
        """Create a new subscription diff.

        False for missing arguments or a sequence number that already has a
        diff (the write is conditional, as PostgreSQL's primary key makes
        it); a fault raises ``DbError``.
        """
        if not actor_id or not subid:
            logger.debug("Attempt to create subscriptiondiff without actorid or subid")
            return False
        self.handle = SubscriptionDiff(
            id=actor_id,
            subid_seqnr=subid + ":" + str(seqnr),
            subid=subid,
            diff=diff,
            seqnr=seqnr,
        )
        try:
            self.handle.save(condition=SubscriptionDiff.subid_seqnr.does_not_exist())
        except PutError as e:
            if e.cause_response_code == "ConditionalCheckFailedException":
                logger.warning(
                    f"Diff {subid}:{seqnr} of {actor_id} already exists; not "
                    "overwritten"
                )
                self.handle = None
                return False
            raise DbError("subscription diff create") from e
        except Exception as e:
            raise DbError("subscription diff create") from e
        return True

    def delete(self):
        """Deletes the subscription diff in the database.

        True when the row is gone after the call (an already-absent row
        counts); a fault raises ``DbError``. False only without a handle.
        """
        if not self.handle:
            return False
        try:
            self.handle.delete()
        except Exception as e:
            raise DbError("subscription diff delete") from e
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        ensure_table(SubscriptionDiff)


class DbSubscriptionDiffList:
    """
    DbSubscriptionDiffList does all the db operations for list of diff objects

    The actor_id must always be set.
    """

    def fetch(self, actor_id=None, subid=None, *, strict=True):
        """Retrieves the subscription diffs of an actor_id from the database as an array

        ``[]`` when there are none. A read fault raises ``DbError``;
        ``strict=False`` answers it with ``[]``.
        """
        if not actor_id:
            return None
        self.actor_id = actor_id
        self.subid = subid
        self.diffs = []
        try:
            self.handle = SubscriptionDiff.query(actor_id, consistent_read=True)
            for t in self.handle:
                if subid and subid != t.subid:
                    continue
                self.diffs.append(
                    {
                        "id": t.id,
                        "subscriptionid": t.subid,
                        "timestamp": t.timestamp,
                        "diff": t.diff,
                        "sequence": t.seqnr,
                    }
                )
        except Exception as e:
            if strict:
                raise DbError("subscription diff list fetch") from e
            logger.error(f"Error fetching the subscription diffs of {actor_id}: {e}")
            self.diffs = []
            return []
        # The range key is "subid:seqnr", so the query returns 1, 10, 2:
        # order by the number, as PostgreSQL's ORDER BY seqnr does.
        self.diffs.sort(key=lambda d: d["sequence"])
        return self.diffs

    def delete(self, seqnr=None):
        """Deletes all the fetched subscription diffs in the database

        Optional seqnr deletes up to (excluding) a specific seqnr
        """
        if not self.handle:
            return False
        if not seqnr or not isinstance(seqnr, int):
            seqnr = 0
        try:
            for p in SubscriptionDiff.query(self.actor_id, consistent_read=True):
                if self.subid and self.subid != p.subid:
                    continue
                if seqnr == 0 or p.seqnr <= seqnr:
                    p.delete()
        except Exception as e:
            raise DbError("subscription diff list delete") from e
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        self.diffs = []
        self.actor_id = None
        self.subid = None
        ensure_table(SubscriptionDiff)
