import logging
import os
from typing import Any

from pynamodb.attributes import UnicodeAttribute
from pynamodb.constants import PAY_PER_REQUEST_BILLING_MODE
from pynamodb.exceptions import DoesNotExist
from pynamodb.models import Model

from actingweb.db.dynamodb._ensure import ensure_table
from actingweb.db.exceptions import DbError

"""
    DbPeerTrustee handles all db operations for a peer we are a trustee for.
    Google datastore for google is used as a backend.
"""

logger = logging.getLogger(__name__)


class PeerTrustee(Model):
    class Meta:  # type: ignore[misc]
        table_name = os.getenv("AWS_DB_PREFIX", "demo_actingweb") + "_peertrustees"
        billing_mode = PAY_PER_REQUEST_BILLING_MODE
        region = os.getenv("AWS_DEFAULT_REGION", "us-west-1")
        host = os.getenv("AWS_DB_HOST", None)

    id = UnicodeAttribute(hash_key=True)
    peerid = UnicodeAttribute(range_key=True)
    baseuri = UnicodeAttribute()
    type = UnicodeAttribute()
    passphrase = UnicodeAttribute()


class DbPeerTrustee:
    """
    DbPeerTrustee does all the db operations for property objects

    The actor_id must always be set.
    """

    def get(self, actor_id=None, peer_type=None, peerid=None, *, strict=True):
        """Retrieves the peertrustee from the database.

        None when absent, False when several match ``peer_type``. A read
        fault raises ``DbError``; ``strict=False`` answers it with None.
        """
        if not actor_id:
            return None
        if not peerid and not peer_type:
            logger.debug("Attempt to get DbPeerTrustee without peerid or type")
            return None
        try:
            if not self.handle and peerid:
                self.handle = PeerTrustee.get(actor_id, peerid, consistent_read=True)
            elif not self.handle and peer_type:
                count = 0
                peer_trustees = PeerTrustee.query(
                    actor_id, filter_condition=PeerTrustee.type == peer_type
                )
                for h in peer_trustees:
                    self.handle = h
                    count += 1
                if count > 1:
                    logger.error(
                        "Found more than one peer of this peer trustee type("
                        + peer_type
                        + "). Unable to determine which, need peerid lookup."
                    )
                    return False
                if count == 0:
                    self.handle = None
        except DoesNotExist:
            self.handle = None
        except Exception as e:
            self.handle = None
            if strict:
                raise DbError("peertrustee get") from e
            logger.error(f"Error reading peertrustee of {actor_id}: {e}")
        if self.handle:
            t = self.handle
            return {
                "id": t.id,
                "peerid": t.peerid,
                "baseuri": t.baseuri,
                "type": t.type,
                "passphrase": t.passphrase,
            }
        else:
            return None

    def create(
        self, actor_id=None, peerid=None, peer_type=None, baseuri=None, passphrase=None
    ):
        """Create a new peertrustee"""
        if not actor_id or not peerid or not peer_type:
            logger.debug(
                "actor_id, peerid, and type are mandatory when creating peertrustee in db"
            )
            return False
        if not baseuri:
            baseuri = ""
        if not passphrase:
            passphrase = ""
        self.handle = PeerTrustee(
            id=actor_id,
            peerid=peerid,
            type=peer_type,
            baseuri=baseuri,
            passphrase=passphrase,
        )
        try:
            self.handle.save()
        except Exception as e:
            raise DbError("peertrustee create") from e
        return True

    def modify(self, peer_type=None, baseuri=None, passphrase=None):
        """Modify a peertrustee

        If bools are none, they will not be changed.
        """
        if not self.handle:
            logger.debug("Attempted modification of DbPeerTrustee without db handle")
            return False
        if baseuri and len(baseuri) > 0:
            self.handle.baseuri = baseuri
        if passphrase and len(passphrase) > 0:
            self.handle.passphrase = passphrase  # type: ignore[arg-type]
        if peer_type and len(peer_type) > 0:
            self.handle.type = peer_type
        try:
            self.handle.save()
        except Exception as e:
            raise DbError("peertrustee modify") from e
        return True

    def delete(self):
        """Deletes the peertrustee in the database after a get().

        True when the row is gone after the call (an already-absent row
        counts); a fault raises ``DbError``. False only without a handle.
        """
        if not self.handle:
            return False
        try:
            self.handle.delete()
        except Exception as e:
            raise DbError("peertrustee delete") from e
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        ensure_table(PeerTrustee)


class DbPeerTrusteeList:
    """
    DbPeerTrusteeList does all the db operations for list of peertrustee objects

    The  actor_id must always be set.
    """

    def fetch(
        self, actor_id: str | None = None, *, strict: bool = True
    ) -> list[dict[str, Any]] | None:
        """Retrieves the peer trustees of an actor_id from the database.

        A consistent read, like the trust and subscription lists: a caller
        that deletes and re-reads must not see the rows it just removed. A
        read fault raises ``DbError``; ``strict=False`` answers it with
        ``[]``."""
        if not actor_id:
            return None
        self.actor_id = actor_id
        rows: list[dict[str, Any]] = []
        try:
            for t in PeerTrustee.query(self.actor_id, consistent_read=True):
                rows.append(
                    {
                        "id": t.id,
                        "peerid": t.peerid,
                        "baseuri": t.baseuri,
                        "type": t.type,
                        "passphrase": t.passphrase,
                    }
                )
        except Exception as e:
            if strict:
                raise DbError("peertrustee list fetch") from e
            logger.error(f"Error fetching the peertrustees of {actor_id}: {e}")
            rows = []
        self.peertrustees = rows
        return rows

    def delete(self):
        """Deletes all the peertrustees in the database"""
        if not self.actor_id:
            return False
        try:
            for p in PeerTrustee.query(self.actor_id, consistent_read=True):
                p.delete()
        except Exception as e:
            raise DbError("peertrustee list delete") from e
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        self.actor_id = None
        self.peertrustees = None
        ensure_table(PeerTrustee)
