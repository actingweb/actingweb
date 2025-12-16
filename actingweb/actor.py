import base64
import datetime
import json
import logging
from typing import Any

import requests

from actingweb import attribute, peertrustee, property, subscription, trust
from actingweb.constants import (
    DEFAULT_CREATOR,
)
from actingweb.permission_evaluator import PermissionResult, get_permission_evaluator


class ActorError(Exception):
    """Base exception class for Actor-related errors."""

    pass


class ActorNotFoundError(ActorError):
    """Raised when an actor cannot be found."""

    pass


class InvalidActorDataError(ActorError):
    """Raised when actor data is invalid or corrupted."""

    pass


class PeerCommunicationError(ActorError):
    """Raised when communication with peer actors fails."""

    pass


class TrustRelationshipError(ActorError):
    """Raised when trust relationship operations fail."""

    pass


class DummyPropertyClass:
    """Only used to deprecate get_property() in 2.4.4"""

    def __init__(self, v: Any = None) -> None:
        self.value = v


class Actor:
    ###################
    # Basic operations
    ###################

    def __init__(self, actor_id: str | None = None, config: Any | None = None) -> None:
        self.config = config
        self.property_list: Any | None = None
        self.subs_list: list[dict[str, Any]] | None = None
        self.actor: dict[str, Any] | None = None
        self.passphrase: str | None = None
        self.creator: str | None = None
        self.last_response_code: int = 0
        self.last_response_message: str = ""
        self.id: str | None = actor_id
        if self.config:
            self.handle = self.config.DbActor.DbActor()
        else:
            self.handle = None
        if actor_id and config:
            self.store = attribute.InternalStore(actor_id=actor_id, config=config)
            self.property = property.PropertyStore(actor_id=actor_id, config=config)
            self.property_lists = property.PropertyListStore(
                actor_id=actor_id, config=config
            )
        else:
            self.store = None
            self.property = None
            self.property_lists = None
        self.get(actor_id=actor_id)

    def get_peer_info(self, url: str) -> dict[str, Any]:
        """Contacts an another actor over http/s to retrieve meta information
        :param url: Root URI of a remote actor
        :rtype: dict
        :return: The json response from the /meta path in the data element and last_response_code/last_response_message
        set to the results of the https request
        :Example:

        >>>{
        >>>    "last_response_code": 200,
        >>>    "last_response_message": "OK",
        >>>    "data":{}
        >>>}
        """
        try:
            logging.debug(f"Getting peer info at url({url})")
            response = requests.get(url=url + "/meta", timeout=(5, 10))
            res = {
                "last_response_code": response.status_code,
                "last_response_message": response.content,
                "data": json.loads(response.content.decode("utf-8", "ignore")),
            }
            logging.debug(
                f"Got peer info from url({url}) with body({response.content})"
            )
        except (TypeError, ValueError, KeyError):
            res = {
                "last_response_code": 500,
            }
        return res

    async def get_peer_info_async(self, url: str) -> dict[str, Any]:
        """Async version of get_peer_info using AwProxy.

        Contacts another actor over HTTP/S to retrieve meta information without blocking.

        :param url: Root URI of a remote actor
        :return: Dict with last_response_code, last_response_message, and data
        """
        try:
            from .aw_proxy import AwProxy

            logging.debug(f"Getting peer info async at url({url})")
            proxy = AwProxy(
                peer_target={"url": url},
                config=self.config,
            )
            json_data = await proxy.get_resource_async(path="meta")

            if json_data is None:
                res = {
                    "last_response_code": proxy.last_response_code,
                    "last_response_message": proxy.last_response_message,
                    "data": {},
                }
            else:
                res = {
                    "last_response_code": proxy.last_response_code,
                    "last_response_message": proxy.last_response_message,
                    "data": json_data,
                }
            logging.debug(f"Got peer info async from url({url})")
        except Exception as e:
            logging.error(f"Error getting peer info async from {url}: {e}")
            res = {
                "last_response_code": 500,
            }
        return res

    def get(self, actor_id: str | None = None) -> dict[str, Any] | None:
        """Retrieves an actor from storage or initialises if it does not exist"""
        if not actor_id and not self.id:
            return None
        elif not actor_id:
            actor_id = self.id
        if self.handle and self.actor and len(self.actor) > 0:
            return self.actor
        if self.handle:
            self.actor = self.handle.get(actor_id=actor_id)
        else:
            self.actor = None
        if self.actor and len(self.actor) > 0:
            self.id = self.actor["id"]
            self.creator = self.actor["creator"]
            self.passphrase = self.actor["passphrase"]
            self.store = attribute.InternalStore(actor_id=self.id, config=self.config)
            self.property = property.PropertyStore(actor_id=self.id, config=self.config)
            self.property_lists = property.PropertyListStore(
                actor_id=self.id, config=self.config
            )
            if self.config and self.config.force_email_prop_as_creator:
                em = self.store.email
                if em and em.lower() != self.creator:
                    self.modify(creator=em.lower())
        else:
            self.id = None
            self.creator = None
            self.passphrase = None
        return self.actor

    def get_from_property(
        self, name: str = "oauthId", value: str | None = None
    ) -> None:
        """Initialise an actor by matching on a stored property.

        Use with caution as the property's value de-facto becomes
        a security token. If multiple properties are found with the
        same value, no actor will be initialised.
        Also note that this is a costly operation as all properties
        of this type will be retrieved and proceessed.
        """
        actor_id = property.Property(
            name=name, value=value, config=self.config
        ).get_actor_id()
        if not actor_id:
            self.id = None
            self.creator = None
            self.passphrase = None
            return
        self.get(actor_id=actor_id)

    def get_from_creator(self, creator: str | None = None) -> bool:
        """Initialise an actor by matching on creator/email.

        Returns True if an actor could be loaded, otherwise False. When multiple actors
        share the same creator (possible when unique_creator is disabled), the first
        deterministic match will be selected in order to provide stable behaviour for
        login flows that do not specify an explicit actor ID.
        """

        self.id = None
        self.creator = None
        self.passphrase = None

        if not self.config or not creator:
            return False

        lookup_creator = creator.lower() if "@" in creator else creator
        exists = self.config.DbActor.DbActor().get_by_creator(creator=lookup_creator)
        if not exists:
            return False

        # Normalise return to a list of candidate records
        candidates: list[dict[str, Any]]
        if isinstance(exists, list):
            candidates = [c for c in exists if c]
        else:
            candidates = [exists]

        if not candidates:
            return False

        # Ensure deterministic selection order even when DynamoDB returns arbitrary order
        candidates.sort(key=lambda item: item.get("id", ""))

        for candidate in candidates:
            actor_id = candidate.get("id")
            if not actor_id:
                continue
            self.get(actor_id=actor_id)
            if self.id:
                return True

        return False

    def create(
        self,
        url: str,
        creator: str,
        passphrase: str,
        actor_id: str | None = None,
        delete: bool = False,
        trustee_root: str | None = None,
        hooks: Any = None,
    ) -> bool:
        """ "Creates a new actor and persists it.

        If delete is True, any existing actors with same creator value
        will be deleted. If it is False, the one with the correct passphrase
        will be chosen (if any)
        """
        seed = url
        now = datetime.datetime.now(datetime.UTC)
        seed += now.strftime("%Y%m%dT%H%M%S%f")
        if len(creator) > 0:
            self.creator = creator
        else:
            self.creator = DEFAULT_CREATOR
        if self.config and self.config.unique_creator:
            in_db = self.config.DbActor.DbActor()
            exists = in_db.get_by_creator(creator=self.creator)
            if exists:
                # If uniqueness is turned on at a later point, we may have multiple accounts
                # with creator as "creator". Check if we have an internal value "email" and then
                # set creator to the email address.
                if delete:
                    for c in exists:
                        anactor = Actor(actor_id=c["id"], config=self.config)
                        anactor.delete()
                else:
                    if (
                        self.config
                        and self.config.force_email_prop_as_creator
                        and self.creator == DEFAULT_CREATOR
                    ):
                        for c in exists:
                            anactor = Actor(actor_id=c["id"], config=self.config)
                            em = anactor.store.email if anactor.store else None
                            if em:
                                anactor.modify(creator=em.lower())
                    for c in exists:
                        if c["passphrase"] == passphrase:
                            self.handle = in_db
                            self.id = c["id"]
                            self.passphrase = c["passphrase"]
                            self.creator = c["creator"]
                            return True
                    return False
        if passphrase and len(passphrase) > 0:
            self.passphrase = passphrase
        else:
            self.passphrase = self.config.new_token() if self.config else ""
        if actor_id:
            self.id = actor_id
        else:
            self.id = self.config.new_uuid(seed) if self.config else ""
        if not self.handle and self.config:
            self.handle = self.config.DbActor.DbActor()
        if self.handle:
            self.handle.create(
                creator=self.creator, passphrase=self.passphrase, actor_id=self.id
            )
        self.store = attribute.InternalStore(actor_id=self.id, config=self.config)
        self.property = property.PropertyStore(actor_id=self.id, config=self.config)
        self.property_lists = property.PropertyListStore(
            actor_id=self.id, config=self.config
        )

        # Set trustee_root if provided
        if (
            trustee_root
            and isinstance(trustee_root, str)
            and len(trustee_root) > 0
            and self.store
        ):
            self.store.trustee_root = trustee_root

        # Execute actor_created lifecycle hook if hooks are provided
        if hooks:
            try:
                from actingweb.interface.actor_interface import ActorInterface

                registry = getattr(self.config, "service_registry", None)
                actor_interface = ActorInterface(self, service_registry=registry)
                hooks.execute_lifecycle_hooks("actor_created", actor_interface)
            except Exception as e:
                # Log hook execution error but don't fail actor creation
                import logging

                logging.warning(
                    f"Actor created successfully but lifecycle hook failed: {e}"
                )

        return True

    def modify(self, creator: str | None = None) -> bool:
        if not self.handle or not creator:
            logging.debug(
                "Attempted modify of actor with no handle or no param changed"
            )
            return False
        if "@" in creator:
            creator = creator.lower()
        self.creator = creator
        if self.actor:
            self.actor["creator"] = creator
        self.handle.modify(creator=creator)
        return True

    def delete(self) -> None:
        """Deletes an actor and cleans up all relevant stored data"""
        if not self.handle:
            logging.debug("Attempted delete of actor with no handle")
            return
        self.delete_peer_trustee(shorttype="*")
        if not self.property_list:
            self.property_list = property.Properties(
                actor_id=self.id, config=self.config
            )
        self.property_list.delete()
        subs = subscription.Subscriptions(actor_id=self.id, config=self.config)
        subs.fetch()
        subs.delete()
        trusts = trust.Trusts(actor_id=self.id, config=self.config)
        relationships = trusts.fetch()
        if relationships:
            for rel in relationships:
                if isinstance(rel, dict) and "peerid" in rel:
                    self.delete_reciprocal_trust(
                        peerid=rel.get("peerid", ""), delete_peer=True
                    )
        trusts.delete()
        buckets = attribute.Buckets(actor_id=self.id, config=self.config)
        buckets.delete()
        self.handle.delete()

    ######################
    # Advanced operations
    ######################

    def set_property(self, name, value):
        """Sets an actor's property name to value. (DEPRECATED, use actor's property store!)"""
        if self.property:
            self.property[name] = value

    def get_property(self, name):
        """Retrieves a property object named name. (DEPRECATED, use actor's property store!)"""
        return DummyPropertyClass(self.property[name] if self.property else None)

    def delete_property(self, name):
        """Deletes a property name. (DEPRECATED, use actor's property store!)"""
        if self.property:
            self.property[name] = None

    def delete_properties(self):
        """Deletes all properties."""
        if not self.property_list:
            self.property_list = property.Properties(
                actor_id=self.id, config=self.config
            )
        return self.property_list.delete()

    def get_properties(self):
        """Retrieves properties from db and returns a dict."""
        self.property_list = property.Properties(actor_id=self.id, config=self.config)
        return self.property_list.fetch()

    def delete_peer_trustee(self, shorttype=None, peerid=None):
        if not peerid and not shorttype:
            return False
        if shorttype == "*":
            if self.config and self.config.actors:
                for t in self.config.actors:
                    self.delete_peer_trustee(shorttype=t)
            return True
        if (
            shorttype
            and self.config
            and self.config.actors
            and shorttype not in self.config.actors
        ):
            logging.error(f"Got a request to delete an unknown actor type({shorttype})")
            return False
        peer_data = None
        new_peer = None
        if peerid:
            new_peer = peertrustee.PeerTrustee(
                actor_id=self.id, peerid=peerid, config=self.config
            )
            peer_data = new_peer.get()
            if not peer_data or len(peer_data) == 0:
                return False
        elif shorttype:
            new_peer = peertrustee.PeerTrustee(
                actor_id=self.id, short_type=shorttype, config=self.config
            )
            peer_data = new_peer.get()
            if not peer_data or len(peer_data) == 0:
                return False
        if not peer_data:
            return False
        logging.debug(f"Deleting peer actor at baseuri({peer_data['baseuri']})")
        u_p = b"trustee:" + peer_data["passphrase"].encode("utf-8")
        headers = {
            "Authorization": "Basic " + base64.b64encode(u_p).decode("utf-8"),
        }
        try:
            response = requests.delete(
                url=peer_data["baseuri"], headers=headers, timeout=(5, 10)
            )
            self.last_response_code = response.status_code
            self.last_response_message = (
                response.content.decode("utf-8", "ignore")
                if isinstance(response.content, bytes)
                else str(response.content)
            )
        except Exception:
            logging.debug(
                "Not able to delete peer actor remotely due to network issues"
            )
            self.last_response_code = 408
            return False
        if response.status_code < 200 or response.status_code > 299:
            logging.debug("Not able to delete peer actor remotely, peer is unwilling")
            return False
        # Delete trust, peer is already deleted remotely
        if peer_data and not self.delete_reciprocal_trust(
            peerid=peer_data["peerid"], delete_peer=False
        ):
            logging.debug("Not able to delete peer actor trust in db")
        if new_peer and not new_peer.delete():
            logging.debug("Not able to delete peer actor in db")
            return False
        return True

    def get_peer_trustee(self, shorttype=None, peerid=None):
        """Get a peer, either existing or create it as trustee

        Will retrieve an existing peer or create a new and establish trust.
        If no trust exists, a new trust will be established.
        Use either peerid to target a specific known peer, or shorttype to
        allow creation of a new peer if none exists
        """
        if not peerid and not shorttype:
            return None
        if (
            shorttype
            and self.config
            and self.config.actors
            and shorttype not in self.config.actors
        ):
            logging.error(f"Got a request to create an unknown actor type({shorttype})")
            return None
        if peerid:
            new_peer = peertrustee.PeerTrustee(
                actor_id=self.id, peerid=peerid, config=self.config
            )
        else:
            new_peer = peertrustee.PeerTrustee(
                actor_id=self.id, short_type=shorttype, config=self.config
            )
        peer_data = new_peer.get()
        if peer_data and len(peer_data) > 0:
            logging.debug("Found peer in getPeer, now checking existing trust...")
            dbtrust = trust.Trust(
                actor_id=self.id, peerid=peer_data["peerid"], config=self.config
            )
            new_trust = dbtrust.get()
            if new_trust and len(new_trust) > 0:
                return peer_data
            logging.debug("Did not find existing trust, will create a new one")
        factory = ""
        if (
            self.config
            and self.config.actors
            and shorttype
            and shorttype in self.config.actors
        ):
            factory = self.config.actors[shorttype]["factory"]
        # If peer did not exist, create it as trustee
        if not peer_data or len(peer_data) == 0:
            if len(factory) == 0:
                logging.error(
                    f"Peer actor of shorttype({shorttype}) does not have factory set."
                )
            params = {
                "creator": "trustee",
                "trustee_root": (self.config.root + self.id) if self.config else "",
            }
            data = json.dumps(params)
            logging.debug(
                f"Creating peer actor at factory({factory}) with data({data})"
            )
            response = None
            try:
                response = requests.post(
                    url=factory,
                    data=data,
                    timeout=(5, 10),
                    headers={"Content-Type": "application/json"},
                )
                if response:
                    self.last_response_code = response.status_code
                    self.last_response_message = (
                        response.content.decode("utf-8", "ignore")
                        if isinstance(response.content, bytes)
                        else str(response.content)
                    )
            except Exception:
                logging.debug("Not able to create new peer actor")
                self.last_response_code = 408
            logging.debug(f"Create peer actor POST response: {self.last_response_code}")
            if self.last_response_code < 200 or self.last_response_code > 299:
                return None
            try:
                if response and response.content:
                    content_str = (
                        response.content.decode("utf-8", "ignore")
                        if isinstance(response.content, bytes)
                        else str(response.content)
                    )
                    data = json.loads(content_str)
                else:
                    data = {}
            except (TypeError, ValueError, KeyError):
                logging.warning(
                    f"Not able to parse response when creating peer at factory({factory})"
                )
                return None
            if response and "Location" in response.headers:
                baseuri = response.headers["Location"]
            elif response and "location" in response.headers:
                baseuri = response.headers["location"]
            else:
                logging.warning(
                    "No location uri found in response when creating a peer as trustee"
                )
                baseuri = ""
            res = self.get_peer_info(baseuri)
            if (
                not res
                or res["last_response_code"] < 200
                or res["last_response_code"] >= 300
            ):
                return None
            info_peer = res["data"]
            if (
                not info_peer
                or ("id" in info_peer and not info_peer["id"])
                or ("type" in info_peer and not info_peer["type"])
            ):
                logging.info(
                    f"Received invalid peer info when trying to create peer actor at: {factory}"
                )
                return None
            new_peer = peertrustee.PeerTrustee(
                actor_id=self.id,
                peerid=info_peer["id"],
                peer_type=info_peer["type"],
                config=self.config,
            )
            if not new_peer.create(baseuri=baseuri, passphrase=data["passphrase"]):
                logging.error(
                    f"Failed to create in db new peer Actor({self.id}) at {baseuri}"
                )
                return None
        # Now peer exists, create trust
        new_peer_data = new_peer.get()
        if not new_peer_data:
            return None
        secret = self.config.new_token() if self.config else ""
        relationship = ""
        if (
            self.config
            and self.config.actors
            and shorttype
            and shorttype in self.config.actors
        ):
            relationship = self.config.actors[shorttype]["relationship"]
        new_trust = self.create_reciprocal_trust(
            url=new_peer_data["baseuri"],
            secret=secret,
            desc="Trust from trustee to " + (shorttype or ""),
            relationship=relationship,
        )
        if not new_trust or len(new_trust) == 0:
            logging.warning(
                f"Not able to establish trust relationship with peer at factory({factory})"
            )
        else:
            # Approve the relationship
            params = {
                "approved": True,
            }
            u_p = b"trustee:" + new_peer_data["passphrase"].encode("utf-8")
            headers = {
                "Authorization": "Basic " + base64.b64encode(u_p).decode("utf-8"),
                "Content-Type": "application/json",
            }
            data = json.dumps(params)
            try:
                response = requests.put(
                    url=new_peer_data["baseuri"]
                    + "/trust/"
                    + relationship
                    + "/"
                    + (self.id or ""),
                    data=data,
                    headers=headers,
                    timeout=(5, 10),
                )
                if response:
                    self.last_response_code = response.status_code
                    self.last_response_message = (
                        response.content.decode("utf-8", "ignore")
                        if isinstance(response.content, bytes)
                        else str(response.content)
                    )
            except Exception:
                self.last_response_code = 408
                self.last_response_message = (
                    "Not able to approve peer actor trust remotely"
                )
            if self.last_response_code < 200 or self.last_response_code > 299:
                logging.debug("Not able to delete peer actor remotely")
        return new_peer_data

    def get_trust_relationship(self, peerid=None):
        if not peerid:
            return None
        return trust.Trust(actor_id=self.id, peerid=peerid, config=self.config).get()

    def get_trust_relationships(self, relationship="", peerid="", trust_type=""):
        """Retrieves all trust relationships or filtered."""
        trust_list = trust.Trusts(actor_id=self.id, config=self.config)
        relationships = trust_list.fetch()
        rels = []
        if relationships:
            for rel in relationships:
                if isinstance(rel, dict):
                    if len(relationship) > 0 and relationship != rel.get(
                        "relationship", ""
                    ):
                        continue
                    if len(peerid) > 0 and peerid != rel.get("peerid", ""):
                        continue
                    if len(trust_type) > 0 and trust_type != rel.get("type", ""):
                        continue
                rels.append(rel)
        return rels

    def modify_trust_and_notify(
        self,
        relationship=None,
        peerid=None,
        baseuri="",
        secret="",
        desc="",
        approved=None,
        verified=None,
        verification_token=None,
        peer_approved=None,
        # Client metadata for OAuth2 clients
        client_name=None,
        client_version=None,
        client_platform=None,
        oauth_client_id=None,
        # Connection tracking
        last_accessed=None,
        last_connected_via=None,
    ):
        """Changes a trust relationship and noties the peer if approval is changed."""
        if not relationship or not peerid:
            return False
        relationships = self.get_trust_relationships(
            relationship=relationship, peerid=peerid
        )
        if not relationships:
            return False
        this_trust = relationships[0]

        # IMPORTANT: Save approval to database BEFORE notifying peer
        # This prevents race condition where peer tries to subscribe back
        # before our approval is saved
        dbtrust = trust.Trust(actor_id=self.id, peerid=peerid, config=self.config)
        result = dbtrust.modify(
            baseuri=baseuri,
            secret=secret,
            desc=desc,
            approved=approved,
            verified=verified,
            verification_token=verification_token,
            peer_approved=peer_approved,
            client_name=client_name,
            client_version=client_version,
            client_platform=client_platform,
            oauth_client_id=oauth_client_id,
            last_accessed=last_accessed,
            last_connected_via=last_connected_via,
        )

        # Now that approval is saved, notify peer so their auto-subscribe will succeed
        headers = {}
        if approved is True and this_trust["approved"] is False:
            params = {
                "approved": True,
            }
            requrl = this_trust["baseuri"] + "/trust/" + relationship + "/" + self.id
            if this_trust["secret"]:
                headers = {
                    "Authorization": "Bearer " + this_trust["secret"],
                    "Content-Type": "application/json",
                }
            data = json.dumps(params)
            # Note the POST here instead of PUT. POST is used to used to notify about
            # state change in the relationship (i.e. not change the object as PUT
            # would do)
            logging.debug(
                "Trust relationship has been approved, notifying peer at url("
                + requrl
                + ")"
            )
            try:
                response = requests.post(
                    url=requrl, data=data, headers=headers, timeout=(5, 10)
                )
                self.last_response_code = response.status_code
                self.last_response_message = (
                    response.content.decode("utf-8", "ignore")
                    if isinstance(response.content, bytes)
                    else str(response.content)
                )
            except Exception:
                logging.debug("Not able to notify peer at url(" + requrl + ")")
                self.last_response_code = 500
        return result

    async def modify_trust_and_notify_async(
        self,
        relationship=None,
        peerid=None,
        baseuri="",
        secret="",
        desc="",
        approved=None,
        verified=None,
        verification_token=None,
        peer_approved=None,
        # Client metadata for OAuth2 clients
        client_name=None,
        client_version=None,
        client_platform=None,
        oauth_client_id=None,
        # Connection tracking
        last_accessed=None,
        last_connected_via=None,
    ):
        """Async version of modify_trust_and_notify - prevents blocking on peer notification.

        Changes a trust relationship and notifies the peer if approval is changed.
        Database operations remain synchronous, but peer HTTP notification is async.
        """
        if not relationship or not peerid:
            return False
        relationships = self.get_trust_relationships(
            relationship=relationship, peerid=peerid
        )
        if not relationships:
            return False
        this_trust = relationships[0]

        # IMPORTANT: Save approval to database BEFORE notifying peer
        # This prevents race condition where peer tries to subscribe back
        # before our approval is saved
        dbtrust = trust.Trust(actor_id=self.id, peerid=peerid, config=self.config)
        result = dbtrust.modify(
            baseuri=baseuri,
            secret=secret,
            desc=desc,
            approved=approved,
            verified=verified,
            verification_token=verification_token,
            peer_approved=peer_approved,
            client_name=client_name,
            client_version=client_version,
            client_platform=client_platform,
            oauth_client_id=oauth_client_id,
            last_accessed=last_accessed,
            last_connected_via=last_connected_via,
        )

        # Now that approval is saved, notify peer async so their auto-subscribe will succeed
        if approved is True and this_trust["approved"] is False:
            from .aw_proxy import AwProxy

            logging.debug(
                f"Trust relationship approved, notifying peer async at {this_trust['baseuri']}"
            )
            try:
                proxy = AwProxy(
                    peer_target={"baseuri": this_trust["baseuri"], "secret": this_trust.get("secret", "")},
                    config=self.config,
                )
                await proxy.change_resource_async(
                    path=f"trust/{relationship}/{self.id}",
                    params={"approved": True},
                )
                self.last_response_code = proxy.last_response_code
                self.last_response_message = (
                    proxy.last_response_message.decode("utf-8", "ignore")
                    if isinstance(proxy.last_response_message, bytes)
                    else str(proxy.last_response_message)
                )
            except Exception as e:
                logging.debug(f"Not able to notify peer async: {e}")
                self.last_response_code = 500
        return result

    def create_reciprocal_trust(
        self,
        url,
        secret=None,
        desc="",
        relationship="",  # trust type/permission level (e.g., "friend", "admin") - goes in URL
        trust_type="",  # peer's expected ActingWeb mini-app type for validation (optional)
    ):
        """Creates a new reciprocal trust relationship locally and by requesting a relationship from a peer actor.

        Args:
            relationship: The trust type/permission level to request (friend, admin, etc.)
            trust_type: Expected peer mini-app type for validation (optional)
        """
        if len(url) == 0:
            return False
        if not secret or len(secret) == 0:
            return False
        res = self.get_peer_info(url)
        if (
            not res
            or res["last_response_code"] < 200
            or res["last_response_code"] >= 300
        ):
            return False
        peer = res["data"]
        if not peer["id"] or not peer["type"] or len(peer["type"]) == 0:
            logging.info(
                "Received invalid peer info when trying to establish trust: " + url
            )
            return False
        if len(trust_type) > 0:
            if trust_type.lower() != peer["type"].lower():
                logging.info("Peer is of the wrong actingweb type: " + peer["type"])
                return False
        if not relationship or len(relationship) == 0:
            relationship = self.config.default_relationship if self.config else ""
        # Create trust, so that peer can do a verify on the relationship (using
        # verification_token) when we request the relationship
        dbtrust = trust.Trust(actor_id=self.id, peerid=peer["id"], config=self.config)
        if not dbtrust.create(
            baseuri=url,
            secret=secret,
            peer_type=peer["type"],
            relationship=relationship,
            approved=True,
            verified=True,  # Requesting actor has verified=True by default per ActingWeb spec
            desc=desc,
            established_via="trust",
        ):
            logging.warning(
                "Trying to establish a new Reciprocal trust when peer relationship already exists ("
                + peer["id"]
                + ")"
            )
            return False
        # Since we are initiating the relationship, we implicitly approve it
        # It is not verified until the peer has verified us
        new_trust = dbtrust.get()
        params = {
            "baseuri": (self.config.root if self.config else "") + (self.id or ""),
            "id": self.id,
            "type": self.config.aw_type if self.config else "",
            "secret": secret,
            "desc": desc,
            "verify": new_trust["verification_token"] if new_trust else "",
        }
        requrl = url + "/trust/" + relationship
        data = json.dumps(params)
        logging.debug(
            "Creating reciprocal trust at url("
            + requrl
            + ") and body ("
            + str(data)
            + ")"
        )
        try:
            response = requests.post(
                url=requrl,
                data=data,
                timeout=(5, 10),
                headers={
                    "Content-Type": "application/json",
                },
            )
            self.last_response_code = response.status_code
            self.last_response_message = (
                response.content.decode("utf-8", "ignore")
                if isinstance(response.content, bytes)
                else str(response.content)
            )
        except Exception:
            logging.debug("Not able to create trust with peer, deleting my trust.")
            dbtrust.delete()
            return False
        if self.last_response_code == 201 or self.last_response_code == 202:
            # Reload the trust to check if approval was done
            mod_trust = trust.Trust(
                actor_id=self.id, peerid=peer["id"], config=self.config
            )
            mod_trust_data = mod_trust.get()
            if not mod_trust_data or len(mod_trust_data) == 0:
                logging.error(
                    "Couldn't find trust relationship after peer POST and verification"
                )
                return False
            if self.last_response_code == 201:
                # Already approved by peer (probably auto-approved)
                # Do it direct on the trust (and not self.modifyTrustAndNotify) to avoid a callback
                # to the peer
                mod_trust.modify(peer_approved=True)
            return mod_trust.get()
        else:
            logging.debug("Not able to create trust with peer, deleting my trust.")
            dbtrust.delete()
            return False

    async def create_reciprocal_trust_async(
        self,
        url,
        secret=None,
        desc="",
        relationship="",
        trust_type="",
    ):
        """Async version of create_reciprocal_trust - prevents blocking on peer HTTP calls.

        Creates a new reciprocal trust relationship locally and by requesting a relationship from a peer actor.
        """
        if len(url) == 0:
            return False
        if not secret or len(secret) == 0:
            return False

        # Get peer info async
        res = await self.get_peer_info_async(url)
        if (
            not res
            or res["last_response_code"] < 200
            or res["last_response_code"] >= 300
        ):
            return False
        peer = res["data"]
        if not peer.get("id") or not peer.get("type") or len(peer["type"]) == 0:
            logging.info(
                "Received invalid peer info when trying to establish trust: " + url
            )
            return False
        if len(trust_type) > 0:
            if trust_type.lower() != peer["type"].lower():
                logging.info("Peer is of the wrong actingweb type: " + peer["type"])
                return False
        if not relationship or len(relationship) == 0:
            relationship = self.config.default_relationship if self.config else ""

        # Create trust locally (synchronous DB operation)
        dbtrust = trust.Trust(actor_id=self.id, peerid=peer["id"], config=self.config)
        if not dbtrust.create(
            baseuri=url,
            secret=secret,
            peer_type=peer["type"],
            relationship=relationship,
            approved=True,
            verified=True,
            desc=desc,
            established_via="trust",
        ):
            logging.warning(
                f"Trying to establish a new Reciprocal trust when peer relationship already exists ({peer['id']})"
            )
            return False

        # Request relationship from peer async
        new_trust = dbtrust.get()
        params = {
            "baseuri": (self.config.root if self.config else "") + (self.id or ""),
            "id": self.id,
            "type": self.config.aw_type if self.config else "",
            "secret": secret,
            "desc": desc,
            "verify": new_trust["verification_token"] if new_trust else "",
        }

        from .aw_proxy import AwProxy

        logging.debug(f"Creating reciprocal trust async at {url}/trust/{relationship}")
        try:
            proxy = AwProxy(peer_target={"url": url}, config=self.config)
            await proxy.create_resource_async(
                path=f"trust/{relationship}",
                params=params,
            )
            self.last_response_code = proxy.last_response_code
            self.last_response_message = (
                proxy.last_response_message.decode("utf-8", "ignore")
                if isinstance(proxy.last_response_message, bytes)
                else str(proxy.last_response_message)
            )
        except Exception as e:
            logging.debug(f"Not able to create trust with peer async: {e}, deleting my trust.")
            dbtrust.delete()
            return False

        if self.last_response_code == 201 or self.last_response_code == 202:
            # Reload trust to check if approval was done
            mod_trust = trust.Trust(
                actor_id=self.id, peerid=peer["id"], config=self.config
            )
            mod_trust_data = mod_trust.get()
            if not mod_trust_data or len(mod_trust_data) == 0:
                logging.error(
                    "Couldn't find trust relationship after peer POST and verification"
                )
                return False
            if self.last_response_code == 201:
                # Already approved by peer (probably auto-approved)
                mod_trust.modify(peer_approved=True)
            return mod_trust.get()
        else:
            logging.debug("Not able to create trust with peer async, deleting my trust.")
            dbtrust.delete()
            return False

    def create_verified_trust(
        self,
        baseuri="",
        peerid=None,
        approved=False,
        secret=None,
        verification_token=None,
        trust_type=None,  # peer's ActingWeb mini-app type (e.g., "urn:actingweb:example.com:banking")
        peer_approved=None,
        relationship=None,  # trust type/permission level (e.g., "friend", "admin", "partner")
        desc="",
    ):
        """Creates a new trust when requested and call backs to initiating actor to verify relationship.

        Args:
            trust_type: The peer's ActingWeb mini-application type URI
            relationship: The trust type/permission level (friend, admin, etc.)
        """
        if not peerid or len(baseuri) == 0 or not relationship:
            return False
        requrl = baseuri + "/trust/" + relationship + "/" + self.id
        if not secret or len(secret) == 0:
            logging.debug(
                "No secret received from requesting peer("
                + peerid
                + ") at url ("
                + requrl
                + "). Verification is not possible."
            )
            verified = False
        else:
            headers = {
                "Authorization": "Bearer " + secret,
            }
            logging.debug(
                "Verifying trust at requesting peer("
                + peerid
                + ") at url ("
                + requrl
                + ") and secret("
                + secret
                + ")"
            )
            try:
                response = requests.get(url=requrl, headers=headers, timeout=(5, 10))
                self.last_response_code = response.status_code
                self.last_response_message = (
                    response.content.decode("utf-8", "ignore")
                    if isinstance(response.content, bytes)
                    else str(response.content)
                )
                try:
                    logging.debug(
                        "Verifying trust response JSON:" + str(response.content)
                    )
                    content_str = (
                        response.content.decode("utf-8", "ignore")
                        if isinstance(response.content, bytes)
                        else str(response.content)
                    )
                    data = json.loads(content_str)
                    if data["verification_token"] == verification_token:
                        verified = True
                    else:
                        verified = False
                except ValueError:
                    logging.debug(
                        "No json body in response when verifying trust at url("
                        + requrl
                        + ")"
                    )
                    verified = False
            except Exception:
                logging.debug("No response when verifying trust at url" + requrl + ")")
                verified = False
        new_trust = trust.Trust(actor_id=self.id, peerid=peerid, config=self.config)
        if not new_trust.create(
            baseuri=baseuri,
            secret=secret or "",
            peer_type=trust_type or "",
            approved=approved,
            peer_approved=peer_approved if peer_approved is not None else False,
            relationship=relationship,
            verified=verified,
            desc=desc,
            established_via="trust",
        ):
            return False
        else:
            return new_trust.get()

    def delete_reciprocal_trust(self, peerid=None, delete_peer=False):
        """Deletes a trust relationship and requests deletion of peer's relationship as well."""
        failed_once = False  # For multiple relationships, this will be True if at least one deletion at peer failed
        success_once = False  # True if at least one relationship was deleted at peer
        if not peerid:
            rels = self.get_trust_relationships()
        else:
            rels = self.get_trust_relationships(peerid=peerid)
        for rel in rels:
            # For OAuth2-established trusts, there is no remote actor endpoint to call.
            # Skip remote deletion and delete locally only.
            is_oauth2_trust = (
                (rel.get("established_via") == "oauth2")
                or (rel.get("established_via") == "oauth2_client")
                or (rel.get("type") == "oauth2")
                or (rel.get("type") == "oauth2_client")
                or (str(rel.get("peerid", "")).startswith("oauth2:"))
                or (str(rel.get("peerid", "")).startswith("oauth2_client:"))
            )
            # Additional safety check: prevent self-deletion if baseuri points to this actor
            is_self_deletion = (
                rel.get("baseuri", "").endswith(f"/{self.id}")
                or rel.get("baseuri", "") == f"{self.config.root}{self.id}"
                if self.config
                else False
            )

            if delete_peer and not is_oauth2_trust and not is_self_deletion:
                url = rel["baseuri"] + "/trust/" + rel["relationship"] + "/" + self.id
                headers = {}
                if rel["secret"]:
                    headers = {
                        "Authorization": "Bearer " + rel["secret"],
                    }
                logging.debug("Deleting reciprocal relationship at url(" + url + ")")
                try:
                    response = requests.delete(
                        url=url, headers=headers, timeout=(5, 10)
                    )
                except Exception:
                    logging.debug(
                        "Failed to delete reciprocal relationship at url(" + url + ")"
                    )
                    failed_once = True
                    continue
                if (
                    response.status_code < 200 or response.status_code > 299
                ) and response.status_code != 404:
                    logging.debug(
                        "Failed to delete reciprocal relationship at url(" + url + ")"
                    )
                    failed_once = True
                    continue
                else:
                    success_once = True
            elif delete_peer and (is_oauth2_trust or is_self_deletion):
                # Treat as successful remote delete for OAuth2 trusts and self-deletions
                reason = (
                    "OAuth2-established trust"
                    if is_oauth2_trust
                    else "self-deletion detected"
                )
                logging.debug(
                    f"Skipping remote delete for {reason}; deleting locally only"
                )
                success_once = True
            if not self.subs_list:
                self.subs_list = subscription.Subscriptions(
                    actor_id=self.id, config=self.config
                ).fetch()
            # Delete this peer's subscriptions
            if self.subs_list:
                for sub in self.subs_list:
                    if sub["peerid"] == rel["peerid"]:
                        logging.debug(
                            "Deleting subscription("
                            + sub["subscriptionid"]
                            + ") as part of trust deletion."
                        )
                        sub_obj = self.get_subscription_obj(
                            peerid=sub["peerid"],
                            subid=sub["subscriptionid"],
                            callback=sub["callback"],
                        )
                        if sub_obj:
                            sub_obj.delete()
            # Delete associated trust permissions before deleting the trust
            try:
                from .trust_permissions import TrustPermissionStore

                if self.config is not None and self.id is not None:
                    permission_store = TrustPermissionStore(self.config)
                    permission_store.delete_permissions(self.id, rel["peerid"])
            except Exception as e:
                logging.warning(
                    f"Failed to delete trust permissions for {rel['peerid']}: {e}"
                )
            dbtrust = trust.Trust(
                actor_id=self.id, peerid=rel["peerid"], config=self.config
            )
            dbtrust.delete()
        if delete_peer and (not success_once or failed_once):
            return False
        return True

    def create_subscription(
        self,
        peerid=None,
        target=None,
        subtarget=None,
        resource=None,
        granularity=None,
        subid=None,
        callback=False,
    ):
        new_sub = subscription.Subscription(
            actor_id=self.id,
            peerid=peerid,
            subid=subid,
            callback=callback,
            config=self.config,
        )
        new_sub.create(
            target=target,
            subtarget=subtarget,
            resource=resource,
            granularity=granularity,
        )
        return new_sub.get()

    def create_remote_subscription(
        self, peerid=None, target=None, subtarget=None, resource=None, granularity=None
    ):
        """Creates a new subscription at peerid."""
        if not peerid or not target:
            return False
        relationships = self.get_trust_relationships(peerid=peerid)
        if not relationships:
            return False
        peer = relationships[0]
        params = {
            "id": self.id,
            "target": target,
        }
        if subtarget:
            params["subtarget"] = subtarget
        if resource:
            params["resource"] = resource
        if granularity and len(granularity) > 0:
            params["granularity"] = granularity
        requrl = peer["baseuri"] + "/subscriptions/" + self.id
        data = json.dumps(params)
        headers = {
            "Authorization": "Bearer " + peer["secret"],
            "Content-Type": "application/json",
        }
        try:
            logging.debug(
                "Creating remote subscription at url("
                + requrl
                + ") with body ("
                + str(data)
                + ")"
            )
            response = requests.post(
                url=requrl, data=data, headers=headers, timeout=(5, 10)
            )
            self.last_response_code = response.status_code
            self.last_response_message = (
                response.content.decode("utf-8", "ignore")
                if isinstance(response.content, bytes)
                else str(response.content)
            )
        except Exception:
            return None
        try:
            logging.debug(
                "Created remote subscription at url("
                + requrl
                + ") and got JSON response ("
                + str(response.content)
                + ")"
            )
            content_str = (
                response.content.decode("utf-8", "ignore")
                if isinstance(response.content, bytes)
                else str(response.content)
            )
            data = json.loads(content_str)
        except ValueError:
            return None
        if "subscriptionid" in data:
            subid = data["subscriptionid"]
        else:
            return None
        if self.last_response_code == 201:
            self.create_subscription(
                peerid=peerid,
                target=target,
                subtarget=subtarget,
                resource=resource,
                granularity=granularity,
                subid=subid,
                callback=True,
            )
            if "Location" in response.headers:
                return response.headers["Location"]
            elif "location" in response.headers:
                return response.headers["location"]
        else:
            return None

    def get_subscriptions(
        self, peerid=None, target=None, subtarget=None, resource=None, callback=False
    ):
        """Retrieves subscriptions from db."""
        if not self.id:
            return None
        if not self.subs_list:
            self.subs_list = subscription.Subscriptions(
                actor_id=self.id, config=self.config
            ).fetch()
        ret = []
        if self.subs_list:
            for sub in self.subs_list:
                if not peerid or (peerid and sub["peerid"] == peerid):
                    if not target or (target and sub["target"] == target):
                        if not subtarget or (
                            subtarget and sub["subtarget"] == subtarget
                        ):
                            if not resource or (
                                resource and sub["resource"] == resource
                            ):
                                if not callback or (
                                    callback and sub["callback"] == callback
                                ):
                                    ret.append(sub)
        return ret

    def get_subscription(self, peerid=None, subid=None, callback=False):
        """Retrieves a single subscription identified by peerid and subid."""
        if not subid:
            return False
        return subscription.Subscription(
            actor_id=self.id,
            peerid=peerid,
            subid=subid,
            callback=callback,
            config=self.config,
        ).get()

    def get_subscription_obj(self, peerid=None, subid=None, callback=False):
        """Retrieves a single subscription identified by peerid and subid."""
        if not subid:
            return False
        return subscription.Subscription(
            actor_id=self.id,
            peerid=peerid,
            subid=subid,
            callback=callback,
            config=self.config,
        )

    def delete_remote_subscription(self, peerid=None, subid=None):
        if not subid or not peerid:
            return False
        trust_rel = self.get_trust_relationship(peerid=peerid)
        if not trust_rel:
            return False
        sub = self.get_subscription(peerid=peerid, subid=subid)
        if not sub:
            sub = self.get_subscription(peerid=peerid, subid=subid, callback=True)
        if not sub or "callback" not in sub or not sub["callback"]:
            url = trust_rel["baseuri"] + "/subscriptions/" + self.id + "/" + subid
        else:
            url = (
                trust_rel["baseuri"]
                + "/callbacks/subscriptions/"
                + self.id
                + "/"
                + subid
            )
        headers = {
            "Authorization": "Bearer " + trust_rel["secret"],
        }
        try:
            logging.debug("Deleting remote subscription at url(" + url + ")")
            response = requests.delete(url=url, headers=headers, timeout=(5, 10))
            self.last_response_code = response.status_code
            self.last_response_message = (
                response.content.decode("utf-8", "ignore")
                if isinstance(response.content, bytes)
                else str(response.content)
            )
            if response.status_code == 204:
                return True
            else:
                logging.debug(
                    "Failed to delete remote subscription at url(" + url + ")"
                )
                return False
        except Exception:
            return False

    def delete_subscription(self, peerid=None, subid=None, callback=False):
        """Deletes a specified subscription"""
        if not subid:
            return False
        sub = subscription.Subscription(
            actor_id=self.id,
            peerid=peerid,
            subid=subid,
            callback=callback,
            config=self.config,
        )
        return sub.delete()

    def callback_subscription(
        self, peerid=None, sub_obj=None, sub=None, diff=None, blob=None
    ):
        if not peerid or not diff or not sub or not blob:
            logging.warning("Missing parameters in callbackSubscription")
            return
        if "granularity" in sub and sub["granularity"] == "none":
            return
        trust_rel = self.get_trust_relationship(peerid)
        if not trust_rel:
            return

        # Filter blob based on peer permissions for property subscriptions
        if sub.get("target") == "properties":
            filtered_blob = self._filter_subscription_data_by_permissions(
                peerid=peerid,
                blob=blob,
                subtarget=sub.get("subtarget"),
            )
            if filtered_blob is None:
                return  # Nothing to send after filtering
            blob = filtered_blob

        params = {
            "id": self.id,
            "subscriptionid": sub["subscriptionid"],
            "target": sub["target"],
            "sequence": diff["sequence"],
            "timestamp": str(diff["timestamp"]),
            "granularity": sub["granularity"],
        }
        if sub["subtarget"]:
            params["subtarget"] = sub["subtarget"]
        if sub["resource"]:
            params["resource"] = sub["resource"]
        if sub["granularity"] == "high":
            try:
                params["data"] = json.loads(blob)
            except (TypeError, ValueError, KeyError):
                params["data"] = blob
        if sub["granularity"] == "low":
            params["url"] = (
                (self.config.root if self.config else "")
                + (self.id or "")
                + "/subscriptions/"
                + trust_rel["peerid"]
                + "/"
                + sub["subscriptionid"]
                + "/"
                + str(diff["sequence"])
            )
        requrl = (
            trust_rel["baseuri"]
            + "/callbacks/subscriptions/"
            + self.id
            + "/"
            + sub["subscriptionid"]
        )
        data = json.dumps(params)
        headers = {
            "Authorization": "Bearer " + trust_rel["secret"],
            "Content-Type": "application/json",
        }

        # Fire callback asynchronously to avoid blocking the caller
        async def _send_callback_async():
            """Send subscription callback using httpx (non-blocking)."""
            import httpx

            try:
                logging.debug(
                    "Doing async callback on subscription at url("
                    + requrl
                    + ") with body("
                    + str(data)
                    + ")"
                )
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(10.0, connect=5.0)
                ) as client:
                    response = await client.post(
                        requrl, content=data.encode("utf-8"), headers=headers
                    )
                self.last_response_code = response.status_code
                self.last_response_message = (
                    response.content.decode("utf-8", "ignore")
                    if isinstance(response.content, bytes)
                    else str(response.content)
                )
                if response.status_code == 204 and sub["granularity"] == "high":
                    if not sub_obj:
                        logging.warning("About to clear diff without having subobj set")
                    else:
                        sub_obj.clear_diff(diff["sequence"])
            except Exception as e:
                logging.debug(
                    f"Peer did not respond to callback on url({requrl}): {e}"
                )
                self.last_response_code = 0
                self.last_response_message = (
                    "No response from peer for subscription callback"
                )

        # Schedule the async callback without blocking
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            # We're in an async context - create a background task
            loop.create_task(_send_callback_async())
            logging.debug("Scheduled async callback task")
        except RuntimeError:
            # No running event loop - fall back to sync request
            logging.debug("No async loop, falling back to sync callback")
            try:
                response = requests.post(
                    url=requrl,
                    data=data.encode("utf-8"),
                    headers=headers,
                    timeout=(5, 10),
                )
                self.last_response_code = response.status_code
                self.last_response_message = (
                    response.content.decode("utf-8", "ignore")
                    if isinstance(response.content, bytes)
                    else str(response.content)
                )
                if response.status_code == 204 and sub["granularity"] == "high":
                    if not sub_obj:
                        logging.warning("About to clear diff without having subobj set")
                    else:
                        sub_obj.clear_diff(diff["sequence"])
            except Exception:
                logging.debug(
                    "Peer did not respond to callback on url(" + requrl + ")"
                )
                self.last_response_code = 0
                self.last_response_message = (
                    "No response from peer for subscription callback"
                )

    async def create_verified_trust_async(
        self,
        baseuri="",
        peerid=None,
        approved=False,
        secret=None,
        verification_token=None,
        trust_type=None,
        peer_approved=None,
        relationship=None,
        desc="",
    ):
        """Async version - wraps sync method in asyncio.to_thread to prevent blocking."""
        import asyncio

        return await asyncio.to_thread(
            self.create_verified_trust,
            baseuri=baseuri,
            peerid=peerid,
            approved=approved,
            secret=secret,
            verification_token=verification_token,
            trust_type=trust_type,
            peer_approved=peer_approved,
            relationship=relationship,
            desc=desc,
        )

    async def delete_reciprocal_trust_async(self, peerid=None, delete_peer=False):
        """Async version - wraps sync method in asyncio.to_thread to prevent blocking."""
        import asyncio

        return await asyncio.to_thread(
            self.delete_reciprocal_trust, peerid=peerid, delete_peer=delete_peer
        )

    async def create_remote_subscription_async(
        self,
        peerid=None,
        target=None,
        subtarget=None,
        resource=None,
        granularity=None,
    ):
        """Async version - wraps sync method in asyncio.to_thread to prevent blocking."""
        import asyncio

        return await asyncio.to_thread(
            self.create_remote_subscription,
            peerid=peerid,
            target=target,
            subtarget=subtarget,
            resource=resource,
            granularity=granularity,
        )

    async def delete_remote_subscription_async(self, peerid=None, subid=None):
        """Async version - wraps sync method in asyncio.to_thread to prevent blocking."""
        import asyncio

        return await asyncio.to_thread(
            self.delete_remote_subscription, peerid=peerid, subid=subid
        )

    async def callback_subscription_async(
        self, peerid=None, sub_obj=None, sub=None, diff=None, blob=None
    ):
        """Async version - wraps sync method in asyncio.to_thread to prevent blocking."""
        import asyncio

        return await asyncio.to_thread(
            self.callback_subscription,
            peerid=peerid,
            sub_obj=sub_obj,
            sub=sub,
            diff=diff,
            blob=blob,
        )

    def _filter_subscription_data_by_permissions(
        self, peerid: str, blob: str | bytes, subtarget: str | None = None
    ) -> str | None:
        """Filter subscription data based on peer's property permissions.

        Returns filtered blob as JSON string, or None if nothing passes the filter.
        Implements fail-closed: errors result in no data sent.
        """
        try:
            if not self.config or not self.id:
                logging.warning("Missing config or actor ID for subscription filtering")
                return None  # Fail-closed

            evaluator = get_permission_evaluator(self.config)
            if not evaluator:
                logging.warning(
                    f"Permission evaluator not available for subscription filtering to {peerid}"
                )
                return None  # Fail-closed

            # Parse blob with explicit encoding handling for bytes
            if isinstance(blob, bytes):
                data = json.loads(blob.decode('utf-8'))
            elif isinstance(blob, str):
                data = json.loads(blob)
            else:
                data = blob

            if not isinstance(data, dict):
                logging.debug(f"Cannot filter non-dict subscription data: {type(data)}")
                return blob if isinstance(blob, str) else json.dumps(blob)

            filtered_data = {}
            for property_name, value in data.items():
                # Normalize property list keys: strip 'list:' prefix for permission checks
                # Property lists use 'list:name' internally but permissions use 'name'
                normalized_name = (
                    property_name[5:] if property_name.startswith("list:") else property_name
                )

                # Build full property path for permission check
                property_path = f"{subtarget}/{normalized_name}" if subtarget else normalized_name
                result = evaluator.evaluate_property_access(
                    self.id, peerid, property_path, operation="read"
                )
                if result == PermissionResult.ALLOWED:
                    filtered_data[property_name] = value
                else:
                    logging.debug(
                        f"Filtered property {property_path} from subscription callback to {peerid}"
                    )

            if not filtered_data:
                logging.debug(f"No permitted properties in callback to {peerid}, skipping")
                return None

            return json.dumps(filtered_data)
        except Exception as e:
            logging.error(f"Permission filtering failed for subscription callback: {e}")
            return None  # Fail-closed: don't send data on error

    def register_diffs(self, target=None, subtarget=None, resource=None, blob=None):
        """Registers a blob diff against all subscriptions with the correct target, subtarget, and resource.

        If resource is set, the blob is expected to be the FULL resource object, not a diff.
        """
        if blob is None or not target:
            return
        # Get all subscriptions, both with the specific subtarget/resource and those
        # without
        subs = self.get_subscriptions(
            target=target, subtarget=None, resource=None, callback=False
        )
        if not subs:
            subs = []
        if subtarget and resource:
            logging.debug(
                "register_diffs() - blob("
                + blob
                + "), target("
                + target
                + "), subtarget("
                + subtarget
                + "), resource("
                + resource
                + "), # of subs("
                + str(len(subs))
                + ")"
            )
        elif subtarget:
            logging.debug(
                "register_diffs() - blob("
                + blob
                + "), target("
                + target
                + "), subtarget("
                + subtarget
                + "), # of subs("
                + str(len(subs))
                + ")"
            )
        else:
            logging.debug(
                "register_diffs() - blob("
                + blob
                + "), target("
                + target
                + "), # of subs("
                + str(len(subs))
                + ")"
            )
        for sub in subs:
            # Skip the ones without correct subtarget
            if subtarget and sub["subtarget"] and sub["subtarget"] != subtarget:
                logging.debug("     - no match on subtarget, skipping...")
                continue
            # Skip the ones without correct resource
            if resource and sub["resource"] and sub["resource"] != resource:
                logging.debug("     - no match on resource, skipping...")
                continue
            sub_obj = self.get_subscription_obj(
                peerid=sub["peerid"], subid=sub["subscriptionid"]
            )
            if not sub_obj:
                continue
            sub_obj_data = sub_obj.get()
            logging.debug(
                "     - processing subscription("
                + sub["subscriptionid"]
                + ") for peer("
                + sub["peerid"]
                + ") with target("
                + sub_obj_data["target"]
                + ") subtarget("
                + str(sub_obj_data["subtarget"] or "")
                + ") and resource("
                + str(sub_obj_data["resource"] or "")
                + ")"
            )
            # Subscription with a resource, but this diff is on a higher level
            if (
                (not resource or not subtarget)
                and sub_obj_data["subtarget"]
                and sub_obj_data["resource"]
            ):
                # Create a json diff on the subpart that this subscription
                # covers
                try:
                    jsonblob = json.loads(blob)
                    if not subtarget:
                        subblob = json.dumps(
                            jsonblob[sub_obj_data["subtarget"]][
                                sub_obj_data["resource"]
                            ]
                        )
                    else:
                        subblob = json.dumps(jsonblob[sub_obj_data["resource"]])
                except (TypeError, ValueError, KeyError):
                    # The diff does not contain the resource
                    logging.debug(
                        "         - subscription has resource("
                        + sub_obj_data["resource"]
                        + "), no matching blob found in diff"
                    )
                    continue
                logging.debug(
                    "         - subscription has resource("
                    + sub_obj_data["resource"]
                    + "), adding diff("
                    + subblob
                    + ")"
                )
                finblob = subblob
            # The diff is on the resource, but the subscription is on a
            # higher level
            elif resource and not sub_obj_data["resource"]:
                # Since we have a resource, we know the blob is the entire resource, not a diff
                # If the subscription is for a sub-target, send [resource] = blob
                # If the subscription is for a target, send [subtarget][resource] = blob
                upblob = {}
                try:
                    jsonblob = json.loads(blob)
                    if not sub_obj_data["subtarget"]:
                        upblob[subtarget] = {}
                        upblob[subtarget][resource] = jsonblob
                    else:
                        upblob[resource] = jsonblob
                except (TypeError, ValueError, KeyError):
                    if not sub_obj_data["subtarget"]:
                        upblob[subtarget] = {}
                        upblob[subtarget][resource] = blob
                    else:
                        upblob[resource] = blob
                finblob = json.dumps(upblob)
                logging.debug(
                    "         - diff has resource("
                    + resource
                    + "), subscription has not, adding diff("
                    + finblob
                    + ")"
                )
            # Subscriptions with subtarget, but this diff is on a higher level
            elif not subtarget and sub_obj_data["subtarget"]:
                # Create a json diff on the subpart that this subscription
                # covers
                subblob = None
                try:
                    jsonblob = json.loads(blob)
                    subblob = json.dumps(jsonblob[sub_obj_data["subtarget"]])
                except (TypeError, ValueError, KeyError):
                    # The diff blob does not contain the subtarget
                    pass
                logging.debug(
                    "         - subscription has subtarget("
                    + sub_obj_data["subtarget"]
                    + "), adding diff("
                    + subblob
                    + ")"
                )
                finblob = subblob
            # The diff is on the subtarget, but the subscription is on the
            # higher level
            elif subtarget and not sub_obj_data["subtarget"]:
                # Create a data["subtarget"] = blob diff to give correct level
                # of diff to subscriber
                upblob = {}
                try:
                    jsonblob = json.loads(blob)
                    upblob[subtarget] = jsonblob
                except (TypeError, ValueError, KeyError):
                    upblob[subtarget] = blob
                finblob = json.dumps(upblob)
                logging.debug(
                    "         - diff has subtarget("
                    + subtarget
                    + "), subscription has not, adding diff("
                    + finblob
                    + ")"
                )
            else:
                # The diff is correct for the subscription
                logging.debug(
                    "         - exact target/subtarget match, adding diff(" + blob + ")"
                )
                finblob = blob
            if sub_obj:
                diff = sub_obj.add_diff(blob=finblob)
            else:
                diff = None
            if not diff:
                logging.warning(
                    "Failed when registering a diff to subscription ("
                    + sub["subscriptionid"]
                    + "). Will not send callback."
                )
            else:
                if (
                    self.config
                    and self.config.module
                    and self.config.module["deferred"]
                ):
                    self.config.module["deferred"].defer(
                        self.callback_subscription,
                        peerid=sub["peerid"],
                        sub_obj=sub_obj,
                        sub=sub_obj_data,
                        diff=diff,
                        blob=finblob,
                    )
                else:
                    self.callback_subscription(
                        peerid=sub["peerid"],
                        sub_obj=sub_obj,
                        sub=sub_obj_data,
                        diff=diff,
                        blob=finblob,
                    )


class Actors:
    """Handles all actors"""

    def fetch(self):
        if not self.list:
            return False
        if self.actors is not None:
            return self.actors
        self.actors = self.list.fetch()
        return self.actors

    def __init__(self, config=None):
        self.config = config
        if self.config:
            self.list = self.config.DbActor.DbActorList()
        else:
            self.list = None
        self.actors = None
        self.fetch()
