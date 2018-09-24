from builtins import object
import datetime
import logging


class Subscription(object):
    """Base class with core subscription methods (storage-related)"""

    def get(self):
        """Retrieve subscription from db given pre-initialized variables """
        if not self.actor_id or not self.peerid or not self.subid:
            return None
        if self.subscription and len(self.subscription) > 0:
            return self.subscription
        self.subscription = self.handle.get(actor_id=self.actor_id,
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
        if not self.actor_id or not self.peerid:
            logging.debug("Attempted creation of subscription without actor_id or peerid set")
            return False
        if not self.subid:
            now = datetime.datetime.utcnow()
            seed = self.config.root + now.strftime("%Y%m%dT%H%M%S%f")
            self.subid = self.config.new_uuid(seed)
        if not self.handle.create(actor_id=self.actor_id,
                                  peerid=self.peerid,
                                  subid=self.subid,
                                  granularity=granularity,
                                  target=target,
                                  subtarget=subtarget,
                                  resource=resource,
                                  seqnr=seqnr,
                                  callback=self.callback):
            return False
        self.subscription["id"] = self.actor_id
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
        self.clear_diffs()
        self.handle.delete()
        return True

    def increase_seq(self):
        if not self.handle:
            logging.debug("Attempted increase_seq without subscription retrieved from storage")
            return False
        self.subscription["sequence"] += 1
        return self.handle.modify(seqnr=self.subscription["sequence"])

    def add_diff(self, blob=None):
        """Add a new diff for this subscription"""
        if not self.actor_id or not self.subid or not blob:
            logging.debug("Attempted add_diff without actorid, subid, or blob")
            return False
        diff = self.config.DbSubscriptionDiff.DbSubscriptionDiff()
        diff.create(actor_id=self.actor_id,
                    subid=self.subid,
                    diff=blob,
                    seqnr=self.subscription["sequence"]
                    )
        if not self.increase_seq():
            logging.error("Failed increasing sequence number for subscription " +
                          self.subid + " for peer " + self.peerid)
        return diff.get()

    def get_diff(self, seqnr=0):
        """Get one specific diff"""
        if seqnr == 0:
            return None
        if not isinstance(seqnr, int):
            return None
        diff = self.config.DbSubscriptionDiff.DbSubscriptionDiff()
        return diff.get(actor_id=self.actor_id, subid=self.subid, seqnr=seqnr)

    def get_diffs(self):
        """Get all the diffs available for this subscription ordered by the timestamp, oldest first"""
        diff_list = self.config.DbSubscriptionDiff.DbSubscriptionDiffList()
        return diff_list.fetch(actor_id=self.actor_id, subid=self.subid)

    def clear_diff(self, seqnr):
        """Clears one specific diff"""
        diff = self.config.DbSubscriptionDiff.DbSubscriptionDiff()
        diff.get(actor_id=self.actor_id, subid=self.subid, seqnr=seqnr)
        return diff.delete()

    def clear_diffs(self, seqnr=0):
        """Clear all diffs up to and including a seqnr"""
        diff_list = self.config.DbSubscriptionDiff.DbSubscriptionDiffList()
        diff_list.fetch(actor_id=self.actor_id, subid=self.subid)
        diff_list.delete(seqnr=seqnr)

    def __init__(self, actor_id=None, peerid=None, subid=None, callback=False, config=None):
        self.config = config
        self.handle = self.config.DbSubscription.DbSubscription()
        self.subscription = {}
        if not actor_id:
            return
        self.actor_id = actor_id
        self.peerid = peerid
        self.subid = subid
        self.callback = callback
        if self.actor_id and self.peerid and self.subid:
            self.get()


class Subscriptions(object):
    """ Handles all subscriptions of a specific actor_id

        Access the indvidual subscriptions in .dbsubscriptions and the subscription data
        in .subscriptions as a dictionary
    """

    def fetch(self):
        if self.subscriptions is not None:
            return self.subscriptions
        if not self.list:
            self.list = self.config.DbSubscription.DbSubscriptionList()
        if not self.subscriptions:
            self.subscriptions = self.list.fetch(actor_id=self.actor_id)
        return self.subscriptions

    def delete(self):
        if not self.list:
            logging.debug("Already deleted list in subscriptions")
            return False
        for sub in self.subscriptions:
            diff_list = self.config.DbSubscriptionDiff.DbSubscriptionDiffList()
            diff_list.fetch(actor_id=self.actor_id, subid=sub["subscriptionid"])
            diff_list.delete()
        self.list.delete()
        self.list = None
        self.subscriptions = None
        return True

    def __init__(self,  actor_id=None, config=None):
        """ Properties must always be initialised with an actor_id """
        self.config = config
        if not actor_id:
            self.list = None
            logging.debug("No actor_id in initialisation of subscriptions")
            return
        self.list = self.config.DbSubscription.DbSubscriptionList()
        self.actor_id = actor_id
        self.subscriptions = None
        self.fetch()
