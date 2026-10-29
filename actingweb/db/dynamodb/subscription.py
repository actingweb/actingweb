import logging
import os
from typing import Any

from pynamodb.attributes import BooleanAttribute, NumberAttribute, UnicodeAttribute
from pynamodb.constants import PAY_PER_REQUEST_BILLING_MODE
from pynamodb.exceptions import UpdateError
from pynamodb.models import Model

from actingweb.db.dynamodb._ensure import ensure_table
from actingweb.db.exceptions import DbError

"""
    DbSubscription handles all db operations for a subscription

    DbSubscriptionList handles list of subscriptions
    AWS Dynamodb is used as a backend.
"""

logger = logging.getLogger(__name__)


class Subscription(Model):
    class Meta:  # type: ignore[misc]
        table_name = os.getenv("AWS_DB_PREFIX", "demo_actingweb") + "_subscriptions"
        billing_mode = PAY_PER_REQUEST_BILLING_MODE
        region = os.getenv("AWS_DEFAULT_REGION", "us-west-1")
        host = os.getenv("AWS_DB_HOST", None)

    id = UnicodeAttribute(hash_key=True)
    peer_sub_id = UnicodeAttribute(range_key=True)
    peerid = UnicodeAttribute()
    subid = UnicodeAttribute()
    granularity = UnicodeAttribute(null=True)
    target = UnicodeAttribute(null=True)
    subtarget = UnicodeAttribute(null=True)
    resource = UnicodeAttribute(null=True)
    seqnr = NumberAttribute(default=0)
    callback = BooleanAttribute()


class DbSubscription:
    """
    DbSubscription does all the db operations for subscription objects

    The  actor_id must always be set.
    """

    def get(self, actor_id=None, peerid=None, subid=None, *, strict=True):
        """Retrieves the subscription from the database.

        None when absent. A read fault raises ``DbError``; ``strict=False``
        answers it with None.
        """
        if not actor_id:
            return None
        if not peerid or not subid:
            logger.debug("Attempt to get subscription without peerid or subid")
            return None
        try:
            # We only expect one
            for t in Subscription.query(
                actor_id,
                Subscription.peer_sub_id == peerid + ":" + subid,
                consistent_read=True,
            ):
                self.handle = t
                return {
                    "id": t.id,
                    "peerid": t.peerid,
                    "subscriptionid": t.subid,
                    "granularity": (t.granularity or ""),
                    "target": (t.target or ""),
                    "subtarget": (t.subtarget or ""),
                    "resource": (t.resource or ""),
                    "sequence": t.seqnr,
                    "callback": t.callback,
                }
        except Exception as e:
            if strict:
                raise DbError("subscription get") from e
            logger.error(f"Error reading subscription of {actor_id}: {e}")
        return None

    def modify(
        self,
        peerid=None,
        subid=None,
        granularity=None,
        target=None,
        subtarget=None,
        resource=None,
        seqnr=None,
        callback=None,
    ):
        """Modify a subscription
        If bools are none, they will not be changed.
        """
        if not self.handle:
            logger.debug("Attempted modification of DbSubscription without db handle")
            return False
        if peerid and len(peerid) > 0:
            self.handle.peerid = peerid
        if subid and len(subid) > 0:
            self.handle.subid = subid
        if granularity and len(granularity) > 0:
            self.handle.granularity = granularity
        if callback is not None:
            self.handle.callback = callback
        if target and len(target) > 0:
            self.handle.target = target
        if subtarget and len(subtarget) > 0:
            self.handle.subtarget = subtarget
        if resource and len(resource) > 0:
            self.handle.resource = resource
        if seqnr is not None:
            self.handle.seqnr = seqnr
        try:
            self.handle.save()
        except Exception as e:
            raise DbError("subscription modify") from e
        return True

    def increment_seq(
        self,
        actor_id: str | None = None,
        peerid: str | None = None,
        subid: str | None = None,
    ) -> int | None:
        """Atomically add 1 to the stored sequence and return the new value.

        Two concurrent writers get two numbers: the increment is one
        ``UpdateItem`` with ``ADD``, not a read followed by a write. Works on
        the loaded handle, or on the row the three keys name without reading
        it first. None when the subscription row does not exist. A fault
        raises ``DbError``; the increment may then have landed, so the caller
        must not reuse the number it expected.
        """
        if actor_id and peerid and subid:
            item = Subscription(id=actor_id, peer_sub_id=peerid + ":" + subid)
        elif self.handle:
            item = self.handle
        else:
            logger.debug("Attempted increment_seq of DbSubscription without db handle")
            return None
        try:
            item.update(
                actions=[Subscription.seqnr.add(1)],
                condition=Subscription.id.exists(),
            )
        except UpdateError as e:
            if e.cause_response_code == "ConditionalCheckFailedException":
                return None
            raise DbError("subscription increment_seq") from e
        except Exception as e:
            raise DbError("subscription increment_seq") from e
        return int(item.seqnr)

    def create(
        self,
        actor_id=None,
        peerid=None,
        subid=None,
        granularity=None,
        target=None,
        subtarget=None,
        resource=None,
        seqnr=0,
        callback=False,
    ):
        """Create a new subscription"""
        if not actor_id or not peerid or not subid:
            return False
        if self.get(actor_id=actor_id, peerid=peerid, subid=subid):
            return False
        self.handle = Subscription(
            id=actor_id,
            peer_sub_id=peerid + ":" + subid,
            peerid=peerid,
            subid=subid,
            seqnr=seqnr,
            callback=callback,
        )
        if granularity and len(granularity) > 0:
            self.handle.granularity = granularity
        if target and len(target) > 0:
            self.handle.target = target
        if subtarget and len(subtarget) > 0:
            self.handle.subtarget = subtarget
        if resource and len(resource) > 0:
            self.handle.resource = resource
        try:
            self.handle.save()
        except Exception as e:
            raise DbError("subscription create") from e
        return True

    def delete(self):
        """Deletes the subscription in the database.

        True when the row is gone after the call (an already-absent row
        counts); a fault raises ``DbError``. False only without a handle.
        """
        if not self.handle:
            logger.debug("Attempted delete of DbSubscription with no handle set.")
            return False
        try:
            self.handle.delete()
        except Exception as e:
            raise DbError("subscription delete") from e
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        ensure_table(Subscription)


class DbSubscriptionList:
    """
    DbTrustList does all the db operations for list of trust objects

    The  actor_id must always be set.
    """

    def fetch(self, actor_id, *, strict=True):
        """Retrieves the subscriptions of an actor_id from the database as an array

        ``[]`` when there are none. A read fault raises ``DbError``;
        ``strict=False`` answers it with ``[]``.
        """
        if not actor_id:
            return None
        self.actor_id = actor_id
        try:
            return self._fetch(actor_id)
        except Exception as e:
            if strict:
                raise DbError("subscription list fetch") from e
            logger.error(f"Error fetching the subscriptions of {actor_id}: {e}")
            self.subscriptions = []
            return []

    def _fetch(self, actor_id: str) -> list[dict[str, Any]]:
        self.handle = Subscription.query(actor_id, consistent_read=True)
        self.subscriptions = []
        if self.handle:
            for t in self.handle:
                self.subscriptions.append(
                    {
                        "id": t.id,
                        "peerid": t.peerid,
                        "subscriptionid": t.subid,
                        "granularity": (t.granularity or ""),
                        "target": (t.target or ""),
                        "subtarget": (t.subtarget or ""),
                        "resource": (t.resource or ""),
                        "sequence": t.seqnr,
                        "callback": t.callback,
                    }
                )
            return self.subscriptions
        else:
            return []

    def delete(self):
        """Deletes all the subscriptions for an actor in the database"""
        if not self.actor_id:
            return False
        try:
            for p in Subscription.query(self.actor_id, consistent_read=True):
                p.delete()
        except Exception as e:
            raise DbError("subscription list delete") from e
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        self.actor_id = None
        self.subscriptions = []
        ensure_table(Subscription)
