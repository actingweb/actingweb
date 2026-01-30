import datetime
import logging
from typing import Any

from actingweb.db import (
    get_subscription,
    get_subscription_diff,
    get_subscription_diff_list,
    get_subscription_list,
)

logger = logging.getLogger(__name__)


class Subscription:
    """Base class with core subscription methods (storage-related)"""

    def get(self) -> dict[str, Any]:
        """Retrieve subscription from db given pre-initialized variables"""
        if not self.actor_id or not self.peerid or not self.subid:
            return {}
        if self.subscription and len(self.subscription) > 0:
            return self.subscription
        if self.handle:
            self.subscription = self.handle.get(
                actor_id=self.actor_id, peerid=self.peerid, subid=self.subid
            )
        else:
            self.subscription = {}
        if not self.subscription:
            self.subscription = {}
        return self.subscription

    def create(
        self,
        target: str | None = None,
        subtarget: str | None = None,
        resource: str | None = None,
        granularity: str | None = None,
        seqnr: int = 0,
    ) -> bool:
        """Create new subscription and push it to db"""
        if self.subscription and len(self.subscription) > 0:
            logger.debug(
                "Attempted creation of subscription when already loaded from storage"
            )
            return False
        if not self.actor_id or not self.peerid:
            logger.debug(
                "Attempted creation of subscription without actor_id or peerid set"
            )
            return False
        if not self.subid:
            now = datetime.datetime.utcnow()
            if self.config:
                seed = self.config.root + now.strftime("%Y%m%dT%H%M%S%f")
                self.subid = self.config.new_uuid(seed)
            else:
                self.subid = None
        if not self.handle or not self.handle.create(
            actor_id=self.actor_id,
            peerid=self.peerid,
            subid=self.subid,
            granularity=granularity,
            target=target,
            subtarget=subtarget,
            resource=resource,
            seqnr=seqnr,
            callback=self.callback,
        ):
            return False
        assert self.subscription is not None  # Always initialized in __init__
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
            logger.debug("Attempted delete of subscription without storage handle")
            return False

        # Clear diffs
        self.clear_diffs()

        # Clear callback processor state if this is a callback subscription
        if self.callback and self.actor_id and self.peerid and self.subid:
            try:
                from .callback_processor import CallbackProcessor

                # Create a minimal actor-like object for CallbackProcessor
                # We need to avoid circular imports and full Actor initialization
                class _ActorStub:
                    def __init__(self, actor_id, config):
                        self.id = actor_id
                        self.config = config

                actor_stub = _ActorStub(self.actor_id, self.config)
                processor = CallbackProcessor(actor_stub)  # type: ignore[arg-type]
                processor.clear_state(self.peerid, self.subid)
                logger.debug(
                    f"Cleared callback state for subscription {self.subid} from peer {self.peerid}"
                )
            except ImportError:
                pass  # CallbackProcessor not available
            except Exception as e:
                logger.warning(f"Failed to clear callback state for {self.subid}: {e}")

        # Delete subscription record
        self.handle.delete()
        return True

    def increase_seq(self):
        if not self.handle:
            logger.debug(
                "Attempted increase_seq without subscription retrieved from storage"
            )
            return False
        assert self.subscription is not None  # Always initialized in __init__
        self.subscription["sequence"] += 1
        if not self.handle.modify(seqnr=self.subscription["sequence"]):
            # Failed to update database
            return False
        return self.subscription["sequence"]

    def decrease_seq(self):
        """Rollback sequence number by 1 (used when diff creation fails after seq increment)"""
        if not self.handle:
            logger.debug(
                "Attempted decrease_seq without subscription retrieved from storage"
            )
            return False
        assert self.subscription is not None  # Always initialized in __init__
        if self.subscription["sequence"] <= 0:
            logger.warning(
                f"Attempted decrease_seq when sequence is already {self.subscription['sequence']}"
            )
            return False
        self.subscription["sequence"] -= 1
        if not self.handle.modify(seqnr=self.subscription["sequence"]):
            # Failed to update database
            return False
        return self.subscription["sequence"]

    def add_diff(self, blob=None):
        """Add a new diff for this subscription"""
        if not self.actor_id or not self.subid or not blob:
            logger.debug("Attempted add_diff without actorid, subid, or blob")
            return False
        if not self.config:
            return False
        assert self.subscription is not None  # Always initialized in __init__

        # Increment sequence BEFORE creating diff so first diff gets sequence=1 per spec
        new_sequence = self.increase_seq()
        if not new_sequence:
            logger.error(
                f"Failed increasing sequence number for subscription {self.subid} for peer {self.peerid}"
            )
            return False

        # Now create diff with the incremented sequence number
        diff = get_subscription_diff(self.config)
        success = diff.create(
            actor_id=self.actor_id,
            subid=self.subid,
            diff=blob,
            seqnr=self.subscription["sequence"],
        )

        # If diff creation failed, rollback the sequence increment
        if not success:
            logger.error(
                f"Failed creating diff for subscription {self.subid}, rolling back sequence from {new_sequence}"
            )
            self.decrease_seq()
            return False

        return diff.get()

    def get_diff(self, seqnr=0):
        """Get one specific diff"""
        if seqnr == 0:
            return None
        if not isinstance(seqnr, int):
            return None
        if not self.config:
            return None
        diff = get_subscription_diff(self.config)
        return diff.get(actor_id=self.actor_id, subid=self.subid, seqnr=seqnr)

    def get_diffs(self):
        """Get all the diffs available for this subscription ordered by the timestamp, oldest first"""
        if not self.config:
            return []
        diff_list = get_subscription_diff_list(self.config)
        return diff_list.fetch(actor_id=self.actor_id, subid=self.subid)

    def clear_diff(self, seqnr):
        """Clears one specific diff"""
        if not self.config:
            return False
        diff = get_subscription_diff(self.config)
        diff.get(actor_id=self.actor_id, subid=self.subid, seqnr=seqnr)
        return diff.delete()

    def clear_diffs(self, seqnr=0):
        """Clear all diffs up to and including a seqnr"""
        if not self.config:
            return False
        diff_list = get_subscription_diff_list(self.config)
        diff_list.fetch(actor_id=self.actor_id, subid=self.subid)
        diff_list.delete(seqnr=seqnr)

    def __init__(
        self, actor_id=None, peerid=None, subid=None, callback=False, config=None
    ):
        self.config = config
        if self.config:
            self.handle = get_subscription(self.config)
        else:
            self.handle = None
        self.subscription = {}
        if not actor_id:
            return
        self.actor_id = actor_id
        self.peerid = peerid
        self.subid = subid
        self.callback = callback
        if self.actor_id and self.peerid and self.subid:
            self.get()


class Subscriptions:
    """Handles all subscriptions of a specific actor_id

    Access the indvidual subscriptions in .dbsubscriptions and the subscription data
    in .subscriptions as a dictionary
    """

    def fetch(self):
        if self.subscriptions is not None:
            return self.subscriptions
        if not self.list and self.config:
            self.list = get_subscription_list(self.config)
        if not self.subscriptions and self.list:
            self.subscriptions = self.list.fetch(actor_id=self.actor_id)
        return self.subscriptions

    def delete(self):
        if not self.list:
            logger.debug("Already deleted list in subscriptions")
            return False
        if self.subscriptions:
            for sub in self.subscriptions:
                if not self.config:
                    continue
                diff_list = get_subscription_diff_list(self.config)
                diff_list.fetch(actor_id=self.actor_id, subid=sub["subscriptionid"])
                diff_list.delete()
        self.list.delete()
        self.list = None
        self.subscriptions = None
        return True

    def __init__(self, actor_id=None, config=None):
        """Properties must always be initialised with an actor_id"""
        self.config = config
        if not actor_id:
            self.list = None
            logger.debug("No actor_id in initialisation of subscriptions")
            return
        if self.config:
            self.list = get_subscription_list(self.config)
        else:
            self.list = None
        self.actor_id = actor_id
        self.subscriptions = None
        self.fetch()
