import logging


class PeerTrustee:
    def get(self):
        if self.peertrustee and len(self.peertrustee) > 0:
            return self.peertrustee
        if self.handle:
            self.peertrustee = self.handle.get(
                actor_id=self.actor_id, peerid=self.peerid, peer_type=self.peer_type
            )
        else:
            self.peertrustee = {}
        return self.peertrustee

    def create(self, baseuri=None, passphrase=None):
        if not self.handle:
            if self.config:
                self.handle = self.config.DbPeerTrustee.DbPeerTrustee()
            else:
                return False
        if not self.actor_id or not self.peerid:
            logging.debug(
                "Attempt to create new peer trustee without actor_id or peerid set"
            )
            return False
        if not self.peer_type or len(self.peer_type) == 0:
            logging.debug("Attempt to create peer trustee without peer_type set.")
            return False
        return self.handle.create(
            actor_id=self.actor_id,
            peerid=self.peerid,
            peer_type=self.peer_type,
            baseuri=baseuri,
            passphrase=passphrase,
        )

    def delete(self):
        if not self.handle:
            logging.debug("Attempt to delete peertrustee without db handle")
            return False
        return self.handle.delete()

    def __init__(
        self, actor_id=None, peerid=None, short_type=None, peer_type=None, config=None
    ):
        self.config = config
        if self.config:
            self.handle = self.config.DbPeerTrustee.DbPeerTrustee()
        else:
            self.handle = None
        self.peertrustee = {}
        self.peer_type = None
        if not actor_id or len(actor_id) == 0:
            logging.debug("No actorid set in initialisation of peertrust")
            return
        if peer_type:
            self.peer_type = peer_type
        elif not peer_type and short_type:
            if (
                not self.config
                or not self.config.actors
                or short_type not in self.config.actors
            ):
                logging.error(
                    "Got request to initialise peer trustee with unknown shortpeer_type("
                    + (peer_type or "None")
                    + ")"
                )
                return
            self.peer_type = self.config.actors[short_type]["type"]
        elif not peerid:
            logging.debug(
                "Peerid and short_type are not set in initialisation of peertrustee. One is required"
            )
            return
        self.actor_id = actor_id
        self.peerid = peerid
        if self.handle:
            self.get()
