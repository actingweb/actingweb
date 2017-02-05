from db_gae import db_models as db
from db_gae import db_subscription
import config
import datetime
import logging

__all__ = [
    'subscription',
    'subscriptions',
]


class subscription():
    """Base class with core subscription methods (storage-related)"""

    def get(self):
        """Retrieve subscription from db given pre-initialized variables """
        if not self.actorId or not self.peerid or not self.subid:
            return None
        if self.subscription and len(self.subscription) > 0:
            return self.subscription
        self.subscription = self.handle.get(actorId=self.actorId,
                                            peerid=self.peerid,
                                            subid=self.subid)
        if not self.subscription:
            self.subscription = {}
        return self.subscription

    def create(self, target=None, subtarget=None, resource=None, granularity=None, seqnr=1):
        """Create new subscription and push it to db"""
        Config = config.config()
        if self.subscription and len(self.subscription) > 0:
            logging.debug("Attempted creation of subscription when already loaded from storage")
            return False
        if not self.actorId or not self.peerid:
            logging.debug("Attempted creation of subscription without actorId or peerid set")
            return False
        if not self.subid:
            now = datetime.datetime.now()
            seed = Config.root + now.strftime("%Y%m%dT%H%M%S%f")
            self.subid = Config.newUUID(seed)
        if not self.handle.create(actorId=self.actorId,
                                  peerid=self.peerid,
                                  subid=self.subid,
                                  granularity=granularity,
                                  target=target,
                                  subtarget=subtarget,
                                  resource=resource,
                                  seqnr=seqnr,
                                  callback=self.callback):
            return False
        self.subscription["id"] = self.actorId
        self.subscription["subscriptionid"] = self.subid
        self.subscription["peerid"] = self.peerid
        self.subscription["target"] = target
        self.subscription["subtarget"] = subtarget
        self.subscription["resource"] = resource
        self.subscription["granularity"] = granularity
        self.subscription["sequence"] = seqnr
        self.subscription["callback"] = self.callback
        return True

    def delete(self):
        """Delete a subscription in storage"""
        if not self.handle:
            logging.debug("Attempted delete of subscription without storage handle")
        diffs = self.getDiffs()
        for diff in diffs:
            diff.key.delete()
        self.handle.delete()
        return True

    def increaseSeq(self):
        if not self.handle:
            logging.debug("Attempted increaseSeq without subscription retrieved from storage")
            return False
        self.subscription["sequence"] += 1
        return self.handle.modify(seqnr=self.subscription["sequence"])

    def addDiff(self, blob=None):
        """Add a new diff for this subscription timestamped with now"""
        if not self.actorId or not self.subid or not blob:
            return False
        diff = db.SubscriptionDiff(id=self.actorId,
                                   subid=self.subid,
                                   diff=blob,
                                   seqnr=self.subscription["sequence"]
                                   )
        diff.put(use_cache=False)
        if not self.increaseSeq():
            logging.error("Failed increasing sequence number for subscription " +
                          self.subid + " for peer " + self.peerid)
        return diff

    def getDiff(self, seqid=0):
        """Get one specific diff"""
        if seqid == 0:
            return None
        if not isinstance(seqid, int):
            return None
        return db.SubscriptionDiff.query(db.SubscriptionDiff.id == self.actorId,
                                         db.SubscriptionDiff.subid == self.subid,
                                         db.SubscriptionDiff.seqnr == seqid).get(use_cache=False)

    def getDiffs(self):
        """Get all the diffs available for this subscription ordered by the timestamp, oldest first"""
        return db.SubscriptionDiff.query(db.SubscriptionDiff.id == self.actorId,
                                         db.SubscriptionDiff.subid == self.subid).order(db.SubscriptionDiff.seqnr).fetch(use_cache=False)

    def clearDiff(self, seqid):
        """Clears one specific diff"""
        diff = self.getDiff(seqid)
        if diff:
            diff.key.delete(use_cache=False)
            return True
        return False

    def clearDiffs(self, seqnr=0):
        """Clear all diffs up to and including a seqnr"""
        diffs = self.getDiffs()
        for diff in diffs:
            if seqnr != 0 and diff.seqnr > seqnr:
                break
            diff.key.delete(use_cache=False)

    def __init__(self, actorId=None, peerid=None, subid=None, callback=False):
        self.handle = db_subscription.db_subscription()
        self.subscription = {}
        if not actorId:
            return False
        self.actorId = actorId
        self.peerid = peerid
        self.subid = subid
        self.callback = callback
        if self.actorId and self.peerid and self.subid:
            self.get()


class subscriptions():
    """ Handles all subscriptions of a specific actor_id

        Access the indvidual subscriptions in .dbsubscriptions and the subscription data
        in .subscriptions as a dictionary
    """

    def fetch(self):
        if self.subscriptions is not None:
            return self.subscriptions
        if not self.list:
            db_trust.db_trust_list()
        if not self.subscriptions:
            self.subscriptions = self.list.fetch(actorId=self.actorId)
        return self.subscriptions

    def delete(self):
        if not self.list:
            logging.debug("Already deleted list in subscriptions")
            return False
        self.list.delete()
        return True

    def __init__(self,  actorId=None):
        """ Properties must always be initialised with an actorId """
        if not actorId:
            self.list = None
            logging.debug("No actorId in initialisation of subscriptions")
            return
        self.list = db_subscription.db_subscription_list()
        self.actorId = actorId
        self.subscriptions = None
        self.fetch()

