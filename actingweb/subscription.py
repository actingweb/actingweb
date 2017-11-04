import datetime
import logging

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
        if self.subscription and len(self.subscription) > 0:
            logging.debug("Attempted creation of subscription when already loaded from storage")
            return False
        if not self.actorId or not self.peerid:
            logging.debug("Attempted creation of subscription without actorId or peerid set")
            return False
        if not self.subid:
            now = datetime.datetime.now()
            seed = self.config.root + now.strftime("%Y%m%dT%H%M%S%f")
            self.subid = self.config.newUUID(seed)
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
            return False
        self.clearDiffs()
        self.handle.delete()
        return True

    def increaseSeq(self):
        if not self.handle:
            logging.debug("Attempted increaseSeq without subscription retrieved from storage")
            return False
        self.subscription["sequence"] += 1
        return self.handle.modify(seqnr=self.subscription["sequence"])

    def addDiff(self, blob=None):
        """Add a new diff for this subscription"""
        if not self.actorId or not self.subid or not blob:
            logging.debug("Attempted addDiff without actorid, subid, or blob")
            return False
        diff = self.config.db_subscription_diff.db_subscription_diff()
        diff.create(actorId=self.actorId,
                    subid=self.subid,
                    diff=blob,
                    seqnr=self.subscription["sequence"]
                    )
        if not self.increaseSeq():
            logging.error("Failed increasing sequence number for subscription " +
                          self.subid + " for peer " + self.peerid)
        return diff.get()

    def getDiff(self, seqnr=0):
        """Get one specific diff"""
        if seqnr == 0:
            return None
        if not isinstance(seqnr, int):
            return None
        diff = self.config.db_subscription_diff.db_subscription_diff()
        return diff.get(actorId=self.actorId, subid=self.subid, seqnr=seqnr)

    def getDiffs(self):
        """Get all the diffs available for this subscription ordered by the timestamp, oldest first"""
        diff_list = self.config.db_subscription_diff.db_subscription_diff_list()
        return diff_list.fetch(actorId=self.actorId, subid=self.subid)

    def clearDiff(self, seqnr):
        """Clears one specific diff"""
        diff = self.config.db_subscription_diff.db_subscription_diff()
        diff.get(actorId=self.actorId, subid=self.subid, seqnr=seqnr)
        return diff.delete()

    def clearDiffs(self, seqnr=0):
        """Clear all diffs up to and including a seqnr"""
        diff_list = self.config.db_subscription_diff.db_subscription_diff_list()
        diff_list.fetch(actorId=self.actorId, subid=self.subid)
        diff_list.delete(seqnr=seqnr)

    def __init__(self, actorId=None, peerid=None, subid=None, callback=False, config=None):
        self.config = config
        self.handle = self.config.db_subscription.db_subscription()
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
            self.list = self.config.db_subscription.db_subscription_list()
        if not self.subscriptions:
            self.subscriptions = self.list.fetch(actorId=self.actorId)
        return self.subscriptions

    def delete(self):
        if not self.list:
            logging.debug("Already deleted list in subscriptions")
            return False
        for sub in self.subscriptions:
            diff_list = self.config.db_subscription_diff.db_subscription_diff_list()
            diff_list.fetch(actorId=self.actorId, subid=sub["subscriptionid"])
            diff_list.delete()
        self.list.delete()
        self.list = None
        self.subscriptions = None
        return True

    def __init__(self,  actorId=None, config=None):
        """ Properties must always be initialised with an actorId """
        self.config = config
        if not actorId:
            self.list = None
            logging.debug("No actorId in initialisation of subscriptions")
            return
        self.list = self.config.db_subscription.db_subscription_list()
        self.actorId = actorId
        self.subscriptions = None
        self.fetch()

