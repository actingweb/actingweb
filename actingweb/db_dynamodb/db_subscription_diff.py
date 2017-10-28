import logging
import datetime
import os

from pynamodb.models import Model
from pynamodb.attributes import UnicodeAttribute, NumberAttribute, UTCDateTimeAttribute

"""
    db_subscription_diff handles all db operations for a subscription diff

    db_subscription_diff_list handles list of subscriptions diffs
    Google datastore for google is used as a backend.
"""

__all__ = [
    'db_subscription_diff',
    'db_subscription_diff_list',
]


class SubscriptionDiff(Model):
    class Meta:
        table_name = "subscriptiondiffs"
        region = 'us-west-1'
        host = os.getenv('AWS_DB_HOST', None)

    id = UnicodeAttribute(hash_key=True)
    subid = UnicodeAttribute(hash_key=True)
    timestamp = UTCDateTimeAttribute(default=datetime.datetime.now())
    diff = UnicodeAttribute()
    seqnr = NumberAttribute(default=1)


class db_subscription_diff():
    """
        db_subscription_diff does all the db operations for subscription diff objects

        The  actorId must always be set.
    """

    def get(self,  actorId=None, subid=None, seqnr=None):
        """ Retrieves the subscriptiondiff from the database """
        if not actorId and not self.handle:
            return None
        if not subid and not self.handle:
            logging.debug("Attempt to get subscriptiondiff without subid")
            return None
        if not self.handle:
            if not seqnr:
                self.handle = SubscriptionDiff.query(
                    actorId,
                    SubscriptionDiff.subid == subid,
                    consistent_read=True)
            else:
                self.handle = SubscriptionDiff.query(
                    actorId,
                    SubscriptionDiff.subid == subid,
                    SubscriptionDiff.seqnr == seqnr,
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

    def create(self, actorId=None,
               subid=None,
               diff=None,
               seqnr=None):
        """ Create a new subscription diff """
        if not actorId or not subid:
            logging.debug("Attempt to create subscriptiondiff without actorid or subid")
            return False
        if not seqnr:
            seqnr = 1
        if not diff:
            diff = ''
        self.handle = SubscriptionDiff(id=actorId,
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
            SubscriptionDiff.create_table(read_capacity_units=1, write_capacity_units=1, wait=True)


class db_subscription_diff_list():
    """
        db_subscription_diff_list does all the db operations for list of diff objects

        The actorId must always be set. 
    """

    def fetch(self, actorId=None, subid=None):
        """ Retrieves the subscription diffs of an actorId from the database as an array"""
        if not actorId:
            return None
        self.actorId = actorId
        self.subid = subid
        if not subid:
            self.handle = SubscriptionDiff.scan(
                SubscriptionDiff.id == self.actorId,
                scan_index_forward=True,
                consistent_read=True)
        else:
            self.handle = SubscriptionDiff.scan(
                SubscriptionDiff.id == self.actorId,
                SubscriptionDiff.subid == self.subid,
                scan_index_forward=True,
                consistent_read=True)
        self.diffs = []
        if self.handle:
            for t in self.handle:
                self.diffs.append(
                {
                    "id": t.id,
                    "subscriptionid": t.subid,
                    "timestamp": t.timestamp,
                    "diff": t.diff,
                    "sequence": t.seqnr,
                })
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
            self.handle = SubscriptionDiff.scan(
                SubscriptionDiff.id == self.actorId,
                scan_index_forward=True,
                consistent_read=True)
        else:
            self.handle = SubscriptionDiff.scan(
                SubscriptionDiff.id == self.actorId,
                SubscriptionDiff.subid == self.subid,
                scan_index_forward=True,
                consistent_read=True)
        for p in self.handle:
            if seqnr == 0 or p.seqnr <= seqnr:
                p.delete()
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        self.diffs = []
        self.actorId = None
        self.subid = None
