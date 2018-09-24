from builtins import object
import logging
import os
from pynamodb.models import Model
from pynamodb.attributes import UnicodeAttribute, NumberAttribute, BooleanAttribute

"""
    DbSubscription handles all db operations for a subscription

    DbSubscriptionList handles list of subscriptions
    AWS Dynamodb is used as a backend.
"""


class Subscription(Model):
    class Meta(object):
        table_name = os.getenv('AWS_DB_PREFIX', 'demo_actingweb') + "_subscriptions"
        read_capacity_units = 2
        write_capacity_units = 1
        region = os.getenv('AWS_DEFAULT_REGION', 'us-west-1')
        host = os.getenv('AWS_DB_HOST', None)

    id = UnicodeAttribute(hash_key=True)
    peer_sub_id = UnicodeAttribute(range_key=True)
    peerid = UnicodeAttribute()
    subid = UnicodeAttribute()
    granularity = UnicodeAttribute(null=True)
    target = UnicodeAttribute(null=True)
    subtarget = UnicodeAttribute(null=True)
    resource = UnicodeAttribute(null=True)
    seqnr = NumberAttribute(default=1)
    callback = BooleanAttribute()


class DbSubscription(object):
    """
        DbSubscription does all the db operations for subscription objects

        The  actor_id must always be set.
    """

    def get(self,  actor_id=None, peerid=None, subid=None):
        """ Retrieves the subscription from the database """
        if not actor_id:
            return None
        if not peerid or not subid:
            logging.debug("Attempt to get subscription without peerid or subid")
            return None
        try:
            # We only expect one
            for t in Subscription.query(actor_id,
                                        Subscription.peer_sub_id == peerid + ":" + subid,
                                        consistent_read=True):
                self.handle = t
                return {
                    "id": t.id,
                    "peerid": t.peerid,
                    "subscriptionid": t.subid,
                    "granularity": (t.granularity or ''),
                    "target": (t.target or ''),
                    "subtarget": (t.subtarget or ''),
                    "resource": (t.resource or ''),
                    "sequence": t.seqnr,
                    "callback": t.callback,
                }
        except Subscription.DoesNotExist:
            pass
        return None

    def modify(self,
               peerid=None,
               subid=None,
               granularity=None,
               target=None,
               subtarget=None,
               resource=None,
               seqnr=None,
               callback=None):
        """ Modify a subscription
            If bools are none, they will not be changed.
        """
        if not self.handle:
            logging.debug("Attempted modification of DbSubscription without db handle")
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
        if seqnr:
            self.handle.seqnr = seqnr
        self.handle.save()
        return True

    def create(self, actor_id=None,
               peerid=None,
               subid=None,
               granularity=None,
               target=None,
               subtarget=None,
               resource=None,
               seqnr=1,
               callback=False):
        """ Create a new subscription """
        if not actor_id or not peerid or not subid:
            return False
        if self.get(actor_id=actor_id, peerid=peerid, subid=subid):
            return False
        self.handle = Subscription(id=actor_id,
                                   peer_sub_id=peerid + ":" + subid,
                                   peerid=peerid,
                                   subid=subid,
                                   seqnr=seqnr,
                                   callback=callback)
        if granularity and len(granularity) > 0:
            self.handle.granularity = granularity
        if target and len(target) > 0:
            self.handle.target = target
        if subtarget and len(subtarget) > 0:
            self.handle.subtarget = subtarget
        if resource and len(resource) > 0:
            self.handle.resource = resource
        self.handle.save()
        return True

    def delete(self):
        """ Deletes the subscription in the database """
        if not self.handle:
            logging.debug("Attempted delete of DbSubscription with no handle set.")
            return False
        self.handle.delete()
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        if not Subscription.exists():
            Subscription.create_table(wait=True)


class DbSubscriptionList(object):
    """
        DbTrustList does all the db operations for list of trust objects

        The  actor_id must always be set.
    """

    def fetch(self, actor_id):
        """ Retrieves the subscriptions of an actor_id from the database as an array"""
        if not actor_id:
            return None
        self.actor_id = actor_id
        self.handle = Subscription.query(self.actor_id, consistent_read=True)
        self.subscriptions = []
        if self.handle:
            for t in self.handle:
                self.subscriptions.append({
                    "id": t.id,
                    "peerid": t.peerid,
                    "subscriptionid": t.subid,
                    "granularity": (t.granularity or ''),
                    "target": (t.target or ''),
                    "subtarget": (t.subtarget or ''),
                    "resource": (t.resource or ''),
                    "sequence": t.seqnr,
                    "callback": t.callback,
                })
            return self.subscriptions
        else:
            return []

    def delete(self):
        """ Deletes all the subscriptions for an actor in the database """
        if not self.actor_id:
            return False
        self.handle = Subscription.query(self.actor_id, consistent_read=True)
        if not self.handle:
            return False
        for p in self.handle:
            p.delete()
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        self.actor_id = None
        self.subscriptions = []
        if not Subscription.exists():
            Subscription.create_table(wait=True)
