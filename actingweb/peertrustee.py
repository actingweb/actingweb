import logging

class peertrustee():

    def get(self):
        if self.peertrustee and len(self.peertrustee) > 0:
            return self.peertrustee
        self.peertrustee = self.handle.get(actorId=self.actorId,
                                           peerid=self.peerid,
                                           type=self.type)
        return self.peertrustee

    def create(self, baseuri=None, passphrase=None):
        if not self.handle:
            self.handle = self.config.db_peertrustee.db_peertrustee()
        if not self.actorId or not self.peerid:
            logging.debug("Attempt to create new peer trustee without actorId or peerid set")
            return False
        if not self.type or len(self.type) == 0:
            logging.debug("Attempt to create peer trustee without type set.")
            return False
        return self.handle.create(actorId=self.actorId,
                                  peerid=self.peerid,
                                  type=self.type,
                                  baseuri=baseuri,
                                  passphrase=passphrase)

    def delete(self):
        if not self.handle:
            logging.debug("Attempt to delete peertrustee without db handle")
            return False
        return self.handle.delete()

    def __init__(self, actorId=None, peerid=None, shorttype=None, type=None, config=None):
        self.config = config
        self.handle = self.config.db_peertrustee.db_peertrustee()
        self.peertrustee = {}
        self.type = None
        if not actorId or len(actorId) == 0:
            logging.debug("No actorid set in initialisation of peertrust")
            return
        if type:
            self.type = type
        elif not type and shorttype:
            if not self.config.actors[shorttype]:
                logging.error('Got request to initialise peer trustee with unknown shorttype(' + shorttype + ')')
                return
            self.type = self.config.actors[shorttype]["type"]
        elif not peerid:
            logging.debug("Peerid and shorttype are not set in initialisation of peertrustee. One is required")
            return
        self.actorId = actorId
        self.peerid = peerid
        self.get()
