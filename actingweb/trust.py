import logging
from typing import Any


class Trust:
    def get(self) -> dict[str, Any] | None:
        """Retrieve a trust relationship with either peerid or token"""
        if self.trust and len(self.trust) > 0:
            return self.trust
        if not self.handle:
            return None
        if not self.peerid and self.token:
            self.trust = self.handle.get(actor_id=self.actor_id, token=self.token)
        elif self.peerid and not self.token:
            self.trust = self.handle.get(actor_id=self.actor_id, peerid=self.peerid)
        else:
            self.trust = self.handle.get(actor_id=self.actor_id, peerid=self.peerid, token=self.token)
        return self.trust

    def delete(self) -> bool:
        """Delete the trust relationship"""
        if not self.handle:
            return False
        self.trust = {}
        return self.handle.delete()

    def modify(
        self,
        baseuri: str | None = None,
        secret: str | None = None,
        desc: str | None = None,
        approved: bool | None = None,
        verified: bool | None = None,
        verification_token: str | None = None,
        peer_approved: bool | None = None,
    ) -> bool:
        if not self.handle:
            logging.debug("Attempted modifcation of trust without handle")
            return False
        if baseuri:
            self.trust["baseuri"] = baseuri
        if secret:
            self.trust["secret"] = secret
        if desc:
            self.trust["desc"] = desc
        if approved is not None:
            self.trust["approved"] = str(approved).lower()
        if verified is not None:
            self.trust["verified"] = str(verified).lower()
        if verification_token:
            self.trust["verification_token"] = verification_token
        if peer_approved is not None:
            self.trust["peer_approved"] = str(peer_approved).lower()
        return self.handle.modify(
            baseuri=baseuri,
            secret=secret,
            desc=desc,
            approved=approved,
            verified=verified,
            verification_token=verification_token,
            peer_approved=peer_approved,
        )

    def create(
        self,
        baseuri: str = "",
        peer_type: str = "",
        relationship: str = "",
        secret: str = "",
        approved: bool = False,
        verified: bool = False,
        verification_token: str = "",
        desc: str = "",
        peer_approved: bool = False,
    ) -> bool:
        """Create a new trust relationship"""
        self.trust = {"baseuri": baseuri, "type": peer_type}
        if not relationship or len(relationship) == 0:
            self.trust["relationship"] = self.config.default_relationship if self.config else ""
        else:
            self.trust["relationship"] = relationship
        if not secret or len(secret) == 0:
            self.trust["secret"] = self.config.new_token() if self.config else ""
        else:
            self.trust["secret"] = secret
        # Be absolutely sure that the secret is not already used
        if self.config:
            testhandle = self.config.DbTrust.DbTrust()
            if testhandle.is_token_in_db(actor_id=self.actor_id, token=self.trust["secret"]):
                logging.warning("Found a non-unique token where it should be unique")
                return False
        self.trust["approved"] = str(approved).lower()
        self.trust["peer_approved"] = str(peer_approved).lower()
        self.trust["verified"] = str(verified).lower()
        if verification_token:
            self.trust["verification_token"] = verification_token
        else:
            self.trust["verification_token"] = self.config.new_token() if self.config else ""
        self.trust["desc"] = desc or ""
        self.trust["id"] = self.actor_id or ""
        self.trust["peerid"] = self.peerid or ""
        if not self.trust.get("verification_token"):
            self.trust["verification_token"] = self.config.new_token() if self.config else ""
        if not self.handle:
            return False
        return self.handle.create(
            actor_id=self.actor_id,
            peerid=self.peerid,
            baseuri=self.trust["baseuri"],
            peer_type=self.trust["type"],
            relationship=self.trust["relationship"],
            secret=self.trust["secret"],
            approved=approved,
            verified=verified,
            peer_approved=peer_approved,
            verification_token=self.trust["verification_token"],
            desc=self.trust["desc"],
        )

    def __init__(
        self,
        actor_id: str | None = None,
        peerid: str | None = None,
        token: str | None = None,
        config: Any | None = None,
    ) -> None:
        self.config = config
        if self.config:
            self.handle = self.config.DbTrust.DbTrust()
        else:
            self.handle = None
        self.trust = {}
        if not actor_id or len(actor_id) == 0:
            logging.debug("No actorid set in initialisation of trust")
            return
        if not peerid and not token:
            logging.debug("Both peerid and token are not set in initialisation of trust. One must be set.")
            return
        if not token and (not peerid or len(peerid) == 0):
            logging.debug("No peerid set in initialisation of trust")
            return
        self.actor_id = actor_id
        self.peerid = peerid
        self.token = token
        self.get()


class Trusts:
    """Handles all trusts of a specific actor_id

    Access the indvidual trusts in .dbtrusts and the trust data
    in .trusts as a dictionary
    """

    def fetch(self) -> dict[str, Any] | None:
        if self.trusts is not None:
            return self.trusts
        if not self.list and self.config:
            self.list = self.config.DbTrust.DbTrustList()
        if not self.trusts and self.list:
            self.trusts = self.list.fetch(actor_id=self.actor_id)
        return self.trusts

    def delete(self) -> bool:
        if not self.list:
            logging.debug("Already deleted list in trusts")
            return False
        self.list.delete()
        return True

    def __init__(self, actor_id: str | None = None, config: Any | None = None) -> None:
        """Properties must always be initialised with an actor_id"""
        self.config = config
        if not actor_id:
            self.list = None
            logging.debug("No actor_id in initialisation of trusts")
            return
        if self.config:
            self.list = self.config.DbTrust.DbTrustList()
        else:
            self.list = None
        self.actor_id = actor_id
        self.trusts = None
        self.fetch()
