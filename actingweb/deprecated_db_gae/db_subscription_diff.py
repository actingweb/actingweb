from google.appengine.ext import ndb
import logging

"""
    DbSubscriptionDiff handles all db operations for a subscription diff

    DbSubscriptionDiffList handles list of subscriptions diffs
    Google datastore for google is used as a backend.
"""

__all__ = [
    'DbSubscriptionDiff',
    'DbSubscriptionDiffList',
]


class SubscriptionDiff(ndb.Model):
    id = ndb.StringProperty(required=True)
    subid = ndb.StringProperty(required=True)
    timestamp = ndb.DateTimeProperty(auto_now_add=True)
    diff = ndb.TextProperty()
    seqnr = ndb.IntegerProperty()


class DbSubscriptionDiff():
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
                self.handle = SubscriptionDiff.query(SubscriptionDiff.id == actor_id,
                                                     SubscriptionDiff.subid == subid
                                                     ).get()
            else:
                self.handle = SubscriptionDiff.query(SubscriptionDiff.id == actor_id,
                                                     SubscriptionDiff.subid == subid,
                                                     SubscriptionDiff.seqnr == seqnr
                                                     ).get()
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
               diff=None,
               seqnr=None):
        """ Create a new subscription diff """
        if not actor_id or not subid:
            logging.debug("Attempt to create subscriptiondiff without actorid or subid")
            return False
        if not seqnr:
            seqnr = 1
        if not diff:
            diff = ''
        self.handle = SubscriptionDiff(id=actor_id,
                                       subid=subid,
                                       diff=diff,
                                       seqnr=seqnr)
        self.handle.put(use_cache=False)
        return True

    def delete(self):
        """ Deletes the subscription diff in the database """
        if not self.handle:
            return False
        self.handle.key.delete()
        self.handle = None
        return True

    def __init__(self):
        self.handle = None


class DbSubscriptionDiffList():
    """
        DbSubscriptionDiffList does all the db operations for list of diff objects

        The actor_id must always be set. 
    """

    def fetch(self, actor_id=None, subid=None):
        """ Retrieves the subscription diffs of an actor_id from the database as an array"""
        if not actor_id:
            return None
        if not subid:
            self.handle = SubscriptionDiff.query(SubscriptionDiff.id == actor_id).order(SubscriptionDiff.seqnr).fetch(use_cache=False)
        else:
            self.handle = SubscriptionDiff.query(SubscriptionDiff.id == actor_id,
                                                 SubscriptionDiff.subid == subid).order(SubscriptionDiff.seqnr).fetch(use_cache=False)
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
        for p in self.handle:
            if seqnr == 0 or p.seqnr <= seqnr:
                p.key.delete()
                self.handle = None
        return True

    def __init__(self):
        self.handle = None
