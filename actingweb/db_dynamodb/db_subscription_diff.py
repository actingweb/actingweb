from builtins import str
from builtins import object
import logging
import datetime
import os

from pynamodb.models import Model
from pynamodb.attributes import UnicodeAttribute, NumberAttribute, UTCDateTimeAttribute

"""
    DbSubscriptionDiff handles all db operations for a subscription diff

    DbSubscriptionDiffList handles list of subscriptions diffs
    Google datastore for google is used as a backend.
"""


class SubscriptionDiff(Model):
    class Meta(object):
        table_name = os.getenv('AWS_DB_PREFIX', 'demo_actingweb') + "_subscriptiondiffs"
        read_capacity_units = 2
        write_capacity_units = 3
        region = os.getenv('AWS_DEFAULT_REGION', 'us-west-1')
        host = os.getenv('AWS_DB_HOST', None)

    id = UnicodeAttribute(hash_key=True)
    subid_seqnr = UnicodeAttribute(range_key=True)
    subid = UnicodeAttribute()
    timestamp = UTCDateTimeAttribute(default=datetime.datetime.utcnow())
    diff = UnicodeAttribute()
    seqnr = NumberAttribute(default=1)


class DbSubscriptionDiff(object):
    """
        DbSubscriptionDiff does all the db operations for subscription diff objects

        The  actor_id must always be set.
    """

    def get(self,  actor_id=None, subid=None, seqnr=None):
        """ Retrieves the subscriptiondiff from the database """
        if not actor_id and not self.handle:
            return None
        if not subid and not self.handle:
            logging.debug("Attempt to get subscriptiondiff without subid")
            return None
        if not self.handle:
            if not seqnr:
                query = SubscriptionDiff.query(
                    actor_id,
                    SubscriptionDiff.subid_seqnr.startswith(subid),
                    consistent_read=True)
                # Find the record with lowest seqnr
                for t in query:
                    if not self.handle:
                        self.handle = t
                        continue
                    if t.seqnr < self.handle.seqnr:
                        self.handle = t
            else:
                self.handle = SubscriptionDiff.get(
                    actor_id,
                    subid + ":" + str(seqnr),
                    consistent_read=True)
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

    def create(self, actor_id=None,
               subid=None,
               diff='',
               seqnr=1):
        """ Create a new subscription diff """
        if not actor_id or not subid:
            logging.debug("Attempt to create subscriptiondiff without actorid or subid")
            return False
        self.handle = SubscriptionDiff(id=actor_id,
                                       subid_seqnr=subid + ":" + str(seqnr),
                                       subid=subid,
                                       diff=diff,
                                       seqnr=seqnr)
        self.handle.save()
        return True

    def delete(self):
        """ Deletes the subscription diff in the database """
        if not self.handle:
            return False
        self.handle.delete()
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        if not SubscriptionDiff.exists():
            SubscriptionDiff.create_table(wait=True)


class DbSubscriptionDiffList(object):
    """
        DbSubscriptionDiffList does all the db operations for list of diff objects

        The actor_id must always be set. 
    """

    def fetch(self, actor_id=None, subid=None):
        """ Retrieves the subscription diffs of an actor_id from the database as an array"""
        if not actor_id:
            return None
        self.actor_id = actor_id
        self.subid = subid
        if not subid:
            self.handle = SubscriptionDiff.query(
                actor_id,
                consistent_read=True)
        else:
            self.handle = SubscriptionDiff.query(
                actor_id,
                SubscriptionDiff.subid.startswith(subid),
                consistent_read=True)
        self.diffs = []
        if self.handle:
            for t in self.handle:
                self.diffs.append({
                    "id": t.id,
                    "subscriptionid": t.subid,
                    "timestamp": t.timestamp,
                    "diff": t.diff,
                    "sequence": t.seqnr,
                })
                sorted(self.diffs, key=lambda diff: diff["sequence"])
            return self.diffs
        else:
            return []

    def delete(self, seqnr=None):
        """ Deletes all the fetched subscription diffs in the database 

            Optional seqnr deletes up to (excluding) a specific seqnr
        """
        if not self.handle:
            return False
        if not seqnr or not isinstance(seqnr, int):
            seqnr = 0
        if not self.subid:
            self.handle = SubscriptionDiff.query(
                self.actor_id,
                consistent_read=True)
        else:
            self.handle = SubscriptionDiff.query(
                self.actor_id,
                SubscriptionDiff.subid.startswith(self.subid),
                consistent_read=True)
        for p in self.handle:
            if seqnr == 0 or p.seqnr <= seqnr:
                p.delete()
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        self.diffs = []
        self.actor_id = None
        self.subid = None
        if not SubscriptionDiff.exists():
            SubscriptionDiff.create_table(wait=True)
