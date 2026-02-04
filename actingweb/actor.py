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
from actingweb.db import get_actor, get_actor_list, get_subscription_suspension
from actingweb.permission_evaluator import PermissionResult, get_permission_evaluator

logger = logging.getLogger(__name__)


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
            self.handle = get_actor(self.config)
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

    def get_peer_info(
        self, url: str, max_retries: int = 3, retry_delay: float = 0.5
    ) -> dict[str, Any]:
        """Contacts another actor over http/s to retrieve meta information.

        Includes retry logic for transient network failures with exponential backoff.

        Note: This sync method blocks the event loop. In FastAPI/uvicorn contexts,
        use AsyncTrustHandler which calls create_reciprocal_trust_async() instead.

        :param url: Root URI of a remote actor
        :param max_retries: Maximum number of retry attempts (default: 3)
        :param retry_delay: Initial delay between retries in seconds (default: 0.5)
        :rtype: dict
        :return: The json response from the /meta path in the data element and
            last_response_code/last_response_message set to the results of the https request

        Example::

            {
                "last_response_code": 200,
                "last_response_message": "OK",
                "data": {}
            }
        """
        import time

        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    logger.info(
                        f"Retry attempt {attempt + 1}/{max_retries} for peer info from {url}"
                    )
                else:
                    logger.debug(f"Fetching peer info from {url}")

                response = requests.get(url=url + "/meta", timeout=(5, 10))
                res = {
                    "last_response_code": response.status_code,
                    "last_response_message": response.content,
                    "data": json.loads(response.content.decode("utf-8", "ignore")),
                }
                logger.debug(
                    f"Got peer info from url({url}) with body({response.content})"
                )
                return res
            except (TypeError, ValueError, KeyError) as e:
                # JSON parsing errors - don't retry
                logger.warning(f"Invalid response from peer {url}: {e}")
                return {
                    "last_response_code": 500,
                    "last_response_message": str(e),
                }
            except requests.exceptions.RequestException as e:
                # Network errors - retry with exponential backoff
                last_error = e
                if attempt < max_retries - 1:
                    delay = retry_delay * (2**attempt)  # Exponential backoff
                    logger.warning(
                        f"Network error fetching peer info from {url}: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                else:
                    logger.warning(
                        f"Network error fetching peer info from {url} after "
                        f"{max_retries} attempts: {e}"
                    )

        # All retries exhausted
        return {
            "last_response_code": 500,
            "last_response_message": str(last_error) if last_error else "Unknown error",
        }

    async def get_peer_info_async(self, url: str) -> dict[str, Any]:
        """Async version of get_peer_info using httpx.

        Contacts another actor over HTTP/S to retrieve meta information without blocking.

        :param url: Root URI of a remote actor
        :return: Dict with last_response_code, last_response_message, and data
        """
        import httpx

        try:
            logger.debug(f"Fetching peer info async from {url}")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url + "/meta")
                res = {
                    "last_response_code": response.status_code,
                    "last_response_message": response.content,
                    "data": response.json(),
                }
                logger.debug(
                    f"Got peer info async from url({url}) with body({response.content})"
                )
                return res
        except (TypeError, ValueError, KeyError) as e:
            # JSON parsing errors
            logger.warning(f"Invalid response from peer {url}: {e}")
            return {
                "last_response_code": 500,
                "last_response_message": str(e),
                "data": {},
            }
        except httpx.TimeoutException as e:
            logger.warning(f"Timeout fetching peer info async from {url}: {e}")
            return {
                "last_response_code": 408,
                "last_response_message": "Timeout",
                "data": {},
            }
        except httpx.RequestError as e:
            logger.warning(f"Network error fetching peer info async from {url}: {e}")
            return {
                "last_response_code": 500,
                "last_response_message": str(e),
                "data": {},
            }

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
        exists = get_actor(self.config).get_by_creator(creator=lookup_creator)
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
            in_db = get_actor(self.config)
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
            self.handle = get_actor(self.config)
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
                logger.warning(
                    f"Actor created successfully but lifecycle hook failed: {e}"
                )

        return True

    def modify(self, creator: str | None = None) -> bool:
        if not self.handle or not creator:
            logger.debug("Attempted modify of actor with no handle or no param changed")
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
            logger.debug("Attempted delete of actor with no handle")
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
            logger.error(f"Got a request to delete an unknown actor type({shorttype})")
            return False
        peer_data = None
        new_peer = None
        if peerid:
            new_peer = peertrustee.PeerTrustee(
                actor_id=self.id, peerid=peerid, config=self.config
            )
            peer_data = new_peer.get()
            if (
                isinstance(peer_data, bool)
                or not peer_data
                or (isinstance(peer_data, dict) and len(peer_data) == 0)
            ):
                return False
        elif shorttype:
            new_peer = peertrustee.PeerTrustee(
                actor_id=self.id, short_type=shorttype, config=self.config
            )
            peer_data = new_peer.get()
            if (
                isinstance(peer_data, bool)
                or not peer_data
                or (isinstance(peer_data, dict) and len(peer_data) == 0)
            ):
                return False
        if not peer_data or isinstance(peer_data, bool):
            return False
        logger.info(f"Deleting peer actor at {peer_data['baseuri']}")
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
            logger.debug("Not able to delete peer actor remotely due to network issues")
            self.last_response_code = 408
            return False
        if response.status_code < 200 or response.status_code > 299:
            logger.debug("Not able to delete peer actor remotely, peer is unwilling")
            return False
        # Delete trust, peer is already deleted remotely
        if peer_data and not self.delete_reciprocal_trust(
            peerid=peer_data["peerid"], delete_peer=False
        ):
            logger.debug("Not able to delete peer actor trust in db")
        if new_peer and not new_peer.delete():
            logger.debug("Not able to delete peer actor in db")
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
            logger.error(f"Got a request to create an unknown actor type({shorttype})")
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
        if peer_data and not isinstance(peer_data, bool) and len(peer_data) > 0:
            logger.debug("Found peer in getPeer, now checking existing trust...")
            dbtrust = trust.Trust(
                actor_id=self.id, peerid=peer_data["peerid"], config=self.config
            )
            new_trust = dbtrust.get()
            if new_trust and len(new_trust) > 0:
                return peer_data
            logger.debug("Did not find existing trust, will create a new one")
        factory = ""
        if (
            self.config
            and self.config.actors
            and shorttype
            and shorttype in self.config.actors
        ):
            factory = self.config.actors[shorttype]["factory"]
        # If peer did not exist, create it as trustee
        if not peer_data or isinstance(peer_data, bool) or len(peer_data) == 0:
            if len(factory) == 0:
                logger.error(
                    f"Peer actor of shorttype({shorttype}) does not have factory set."
                )
            params = {
                "creator": "trustee",
                "trustee_root": (self.config.root + self.id) if self.config else "",
            }
            data = json.dumps(params)
            logger.debug(f"Creating peer actor at factory({factory})")
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
                logger.debug("Not able to create new peer actor")
                self.last_response_code = 408
            logger.info(f"Created peer actor, response code: {self.last_response_code}")
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
                logger.warning(
                    f"Not able to parse response when creating peer at factory({factory})"
                )
                return None
            if response and "Location" in response.headers:
                baseuri = response.headers["Location"]
            elif response and "location" in response.headers:
                baseuri = response.headers["location"]
            else:
                logger.warning(
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
                logger.info(
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
                logger.error(
                    f"Failed to create in db new peer Actor({self.id}) at {baseuri}"
                )
                return None
        # Now peer exists, create trust
        new_peer_data = new_peer.get()
        if not new_peer_data or isinstance(new_peer_data, bool):
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
            logger.warning(
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
                logger.debug("Not able to delete peer actor remotely")
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
        try:
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
        except Exception as e:
            logger.error(f"Exception in dbtrust.modify: {e}", exc_info=True)
            return False

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
            logger.debug(
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
                logger.debug("Not able to notify peer at url(" + requrl + ")")
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

            logger.debug(
                f"Trust relationship approved, notifying peer async at {this_trust['baseuri']}"
            )
            try:
                proxy = AwProxy(
                    peer_target={
                        "baseuri": this_trust["baseuri"],
                        "secret": this_trust.get("secret", ""),
                    },
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
                logger.debug(f"Not able to notify peer async: {e}")
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
            logger.info(
                "Received invalid peer info when trying to establish trust: " + url
            )
            return False
        if len(trust_type) > 0:
            if trust_type.lower() != peer["type"].lower():
                logger.info("Peer is of the wrong actingweb type: " + peer["type"])
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
            logger.warning(
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
        logger.debug(
            f"Creating reciprocal trust at url({requrl}) for peer {params.get('id', 'unknown')}"
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
            logger.debug("Not able to create trust with peer, deleting my trust.")
            dbtrust.delete()
            return False
        if self.last_response_code == 201 or self.last_response_code == 202:
            # Reload the trust to check if approval was done
            mod_trust = trust.Trust(
                actor_id=self.id, peerid=peer["id"], config=self.config
            )
            mod_trust_data = mod_trust.get()
            if not mod_trust_data or len(mod_trust_data) == 0:
                logger.error(
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
            logger.debug("Not able to create trust with peer, deleting my trust.")
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
            logger.info(
                "Received invalid peer info when trying to establish trust: " + url
            )
            return False
        if len(trust_type) > 0:
            if trust_type.lower() != peer["type"].lower():
                logger.info("Peer is of the wrong actingweb type: " + peer["type"])
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
            logger.warning(
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

        import httpx

        requrl = url + "/trust/" + relationship
        data = json.dumps(params)
        logger.info(
            f"Requesting trust relationship async from peer at ({requrl}) with data({data})"
        )
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    requrl,
                    content=data,
                    headers={"Content-Type": "application/json"},
                )
                self.last_response_code = response.status_code
                self.last_response_message = (
                    response.content.decode("utf-8", "ignore")
                    if isinstance(response.content, bytes)
                    else str(response.content)
                )
        except httpx.TimeoutException:
            logger.debug("Timeout creating trust with peer async, deleting my trust.")
            dbtrust.delete()
            return False
        except httpx.RequestError as e:
            logger.debug(
                f"Not able to create trust with peer async: {e}, deleting my trust."
            )
            dbtrust.delete()
            return False

        if self.last_response_code == 201 or self.last_response_code == 202:
            # Reload trust to check if approval was done
            mod_trust = trust.Trust(
                actor_id=self.id, peerid=peer["id"], config=self.config
            )
            mod_trust_data = mod_trust.get()
            if not mod_trust_data or len(mod_trust_data) == 0:
                logger.error(
                    "Couldn't find trust relationship after peer POST and verification"
                )
                return False
            if self.last_response_code == 201:
                # Already approved by peer (probably auto-approved)
                mod_trust.modify(peer_approved=True)
            return mod_trust.get()
        else:
            logger.debug("Not able to create trust with peer async, deleting my trust.")
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
            logger.debug(
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
            logger.debug(
                f"Verifying trust at requesting peer({peerid}) at url ({requrl})"
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
                    content_str = (
                        response.content.decode("utf-8", "ignore")
                        if isinstance(response.content, bytes)
                        else str(response.content)
                    )
                    data = json.loads(content_str)
                    logger.debug(
                        f"Verifying trust response: verified={data.get('verified', False)}, "
                        f"approved={data.get('approved', False)}, peer_approved={data.get('peer_approved', False)}"
                    )
                    if data["verification_token"] == verification_token:
                        verified = True
                    else:
                        verified = False
                except ValueError:
                    logger.debug(
                        "No json body in response when verifying trust at url("
                        + requrl
                        + ")"
                    )
                    verified = False
            except Exception:
                logger.debug("No response when verifying trust at url" + requrl + ")")
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
                logger.info(f"Deleting reciprocal relationship at {url}")
                try:
                    response = requests.delete(
                        url=url, headers=headers, timeout=(5, 10)
                    )
                except Exception:
                    logger.debug(
                        "Failed to delete reciprocal relationship at url(" + url + ")"
                    )
                    failed_once = True
                    continue
                if (
                    response.status_code < 200 or response.status_code > 299
                ) and response.status_code != 404:
                    logger.debug(
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
                logger.debug(
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
                        logger.debug(
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
                logger.warning(
                    f"Failed to delete trust permissions for {rel['peerid']}: {e}"
                )

            # Clean up remote peer data (RemotePeerStore)
            # No config check needed - delete_all() is a no-op if no data exists
            try:
                from .interface.actor_interface import ActorInterface
                from .remote_storage import RemotePeerStore

                actor_interface = ActorInterface(self)
                store = RemotePeerStore(
                    actor_interface,
                    rel["peerid"],
                    validate_peer_id=False,
                )
                store.delete_all()
                logger.info(f"Cleaned up RemotePeerStore for peer {rel['peerid']}")
            except ImportError:
                pass  # RemotePeerStore not available
            except Exception as e:
                logger.warning(
                    f"Failed to cleanup RemotePeerStore for {rel['peerid']}: {e}"
                )

            # Clean up callback processor state
            # No config check needed - clear operation is a no-op if no state exists
            try:
                from .callback_processor import CallbackProcessor

                processor = CallbackProcessor(self)  # type: ignore[arg-type]
                processor.clear_all_state_for_peer(rel["peerid"])
                logger.info(
                    f"Cleaned up CallbackProcessor state for peer {rel['peerid']}"
                )
            except ImportError:
                pass  # CallbackProcessor not available
            except Exception as e:
                logger.warning(
                    f"Failed to cleanup callback state for {rel['peerid']}: {e}"
                )

            # Clean up cached peer profile
            # No config check needed - delete is a no-op if no profile exists
            if self.config is not None and self.id is not None:
                try:
                    from .peer_profile import get_peer_profile_store

                    profile_store = get_peer_profile_store(self.config)
                    profile_store.delete_profile(self.id, rel["peerid"])
                    logger.info(f"Cleaned up peer profile for peer {rel['peerid']}")
                except ImportError:
                    pass  # Peer profile system not available
                except Exception as e:
                    logger.warning(
                        f"Failed to cleanup peer profile for {rel['peerid']}: {e}"
                    )

            # Clean up cached peer capabilities (methods/actions)
            # No config check needed - delete is a no-op if nothing cached
            if self.config is not None and self.id is not None:
                try:
                    from .peer_capabilities import get_cached_capabilities_store

                    capabilities_store = get_cached_capabilities_store(self.config)
                    capabilities_store.delete_capabilities(self.id, rel["peerid"])
                    logger.info(
                        f"Cleaned up peer capabilities for peer {rel['peerid']}"
                    )
                except ImportError:
                    pass  # Peer capabilities system not available
                except Exception as e:
                    logger.warning(
                        f"Failed to cleanup peer capabilities for {rel['peerid']}: {e}"
                    )

            # Clean up cached peer permissions
            # No config check needed - delete is a no-op if nothing cached
            if self.config is not None and self.id is not None:
                try:
                    from .peer_permissions import get_peer_permission_store

                    peer_permissions_store = get_peer_permission_store(self.config)
                    peer_permissions_store.delete_permissions(self.id, rel["peerid"])
                    logger.info(
                        f"Cleaned up peer permissions cache for peer {rel['peerid']}"
                    )
                except ImportError:
                    pass  # Peer permissions caching not available
                except Exception as e:
                    logger.warning(
                        f"Failed to cleanup peer permissions cache for {rel['peerid']}: {e}"
                    )

            # Finally, delete the trust record itself
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
            logger.debug(
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
            logger.debug(
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
        self,
        peerid: str | None = None,
        target: str | None = None,
        subtarget: str | None = None,
        resource: str | None = None,
        callback: bool | None = None,
    ) -> list[dict[str, Any]] | None:
        """Retrieves subscriptions from db.

        Args:
            peerid: Filter by peer ID (None = all peers)
            target: Filter by target (None = all targets)
            subtarget: Filter by subtarget (None = all subtargets)
            resource: Filter by resource (None = all resources)
            callback: Filter by callback flag (None = all, False = inbound, True = outbound)

        Returns:
            List of subscription dictionaries, or None if actor has no ID
        """
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
                                if callback is None or sub["callback"] == callback:
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
            logger.info(f"Deleting remote subscription at {url}")
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
                logger.debug("Failed to delete remote subscription at url(" + url + ")")
                return False
        except Exception:
            return False

    def delete_subscription(self, peerid=None, subid=None, callback=False):
        """Deletes a specified subscription"""
        if not subid:
            return False

        # For outbound subscriptions (callback=True), check if we need to clean up RemotePeerStore
        # We need to check this BEFORE deletion to know how many subscriptions exist
        should_cleanup_remote_peer_store = False
        if callback and peerid:
            try:
                # CRITICAL: Clear the subscription cache to get fresh data from database
                # Otherwise we might see stale subscriptions or the one we're about to delete
                self.subs_list = None

                # Check if we have any other outbound subscriptions to this peer
                other_subs = self.get_subscriptions(peerid=peerid, callback=True)

                # Filter out the current subscription being deleted
                # IMPORTANT: Field name is "subscriptionid" not "subid"
                remaining_subs = [
                    s for s in (other_subs or []) if s.get("subscriptionid") != subid
                ]

                if remaining_subs:
                    logger.debug(
                        f"Not cleaning up RemotePeerStore for {peerid} - "
                        f"{len(remaining_subs)} other outbound subscription(s) still active"
                    )
                else:
                    # Mark for cleanup after successful deletion
                    should_cleanup_remote_peer_store = True
            except Exception as e:
                logger.warning(f"Failed to check RemotePeerStore cleanup for {peerid}: {e}")

        sub = subscription.Subscription(
            actor_id=self.id,
            peerid=peerid,
            subid=subid,
            callback=callback,
            config=self.config,
        )
        result = sub.delete()

        # Clear subscription cache after deletion to ensure fresh data on next access
        self.subs_list = None

        # Clean up RemotePeerStore AFTER successful deletion to avoid data loss
        # Note: should_cleanup_remote_peer_store is only True when peerid is not None
        if result and should_cleanup_remote_peer_store and peerid:
            try:
                from .interface.actor_interface import ActorInterface
                from .remote_storage import RemotePeerStore

                # No other outbound subscriptions to this peer, safe to clean up
                actor_interface = ActorInterface(self)  # type: ignore[arg-type]
                store = RemotePeerStore(
                    actor_interface,
                    peerid,
                    validate_peer_id=False,
                )
                store.delete_all()
                logger.info(f"Cleaned up RemotePeerStore for peer {peerid}")
            except ImportError:
                pass  # RemotePeerStore not available
            except Exception as e:
                logger.warning(f"Failed to clean up RemotePeerStore for {peerid}: {e}")

        return result

    def callback_subscription(
        self, peerid=None, sub_obj=None, sub=None, diff=None, blob=None
    ):
        if not peerid or not diff or not sub or not blob:
            logger.warning("Missing parameters in callbackSubscription")
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

        # Helper function for sync callback
        def _send_callback_sync():
            """Send subscription callback using requests (blocking)."""
            try:
                logger.debug(
                    "Doing sync callback on subscription at url("
                    + requrl
                    + ") with body("
                    + str(data)
                    + ")"
                )
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
                # Log the response for debugging callback delivery issues
                if response.status_code == 204:
                    logger.info(
                        f"Callback seq={diff.get('sequence')} delivered successfully (204)"
                    )
                else:
                    logger.warning(
                        f"Callback seq={diff.get('sequence')} returned {response.status_code}: "
                        f"{self.last_response_message[:200] if self.last_response_message else 'no message'}"
                    )
                # NOTE: Don't clear diffs immediately after 204 response. The subscriber
                # might have added the callback to a pending queue (due to sequence gaps),
                # and the diff would be lost. Diffs are cleared when the subscriber
                # explicitly confirms processing via PUT /subscriptions/{id} with sequence.
            except (requests.RequestException, requests.Timeout, ConnectionError) as e:
                logger.warning(
                    f"Callback seq={diff.get('sequence')} failed - peer did not respond: {e}"
                )
                self.last_response_code = 0
                self.last_response_message = (
                    "No response from peer for subscription callback"
                )

        # Check if sync callbacks are forced (recommended for Lambda/serverless)
        use_sync = getattr(self.config, "sync_subscription_callbacks", False)
        if use_sync:
            logger.info(
                f"Sync callback seq={diff.get('sequence')} to {sub.get('peerid', 'unknown')}"
            )
            _send_callback_sync()
            return

        # Fire callback asynchronously to avoid blocking the caller
        async def _send_callback_async():
            """Send subscription callback using httpx (non-blocking)."""
            import httpx

            try:
                logger.debug(
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
                # NOTE: Don't clear diffs immediately after 204 response. The subscriber
                # might have added the callback to a pending queue (due to sequence gaps),
                # and the diff would be lost. Diffs are cleared when the subscriber
                # explicitly confirms processing via PUT /subscriptions/{id} with sequence.
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                logger.debug(f"Peer did not respond to callback on url({requrl}): {e}")
                self.last_response_code = 0
                self.last_response_message = (
                    "No response from peer for subscription callback"
                )

        # Schedule the async callback without blocking (may be lost on Lambda freeze!)
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            # We're in an async context - create a background task
            loop.create_task(_send_callback_async())
            logger.debug(
                f"Async callback seq={diff.get('sequence')} to {sub.get('peerid', 'unknown')} (fire-and-forget)"
            )
        except RuntimeError:
            # No running event loop - fall back to sync request
            logger.debug("No async loop, falling back to sync callback")
            _send_callback_sync()

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
                logger.warning("Missing config or actor ID for subscription filtering")
                return None  # Fail-closed

            evaluator = get_permission_evaluator(self.config)
            if not evaluator:
                logger.warning(
                    f"Permission evaluator not available for subscription filtering to {peerid}"
                )
                return None  # Fail-closed

            # Parse blob with explicit encoding handling for bytes
            if isinstance(blob, bytes):
                data = json.loads(blob.decode("utf-8"))
            elif isinstance(blob, str):
                data = json.loads(blob)
            else:
                data = blob

            if not isinstance(data, dict):
                logger.debug(f"Cannot filter non-dict subscription data: {type(data)}")
                return blob if isinstance(blob, str) else json.dumps(blob)

            filtered_data = {}
            for property_name, value in data.items():
                # Normalize property list keys: strip 'list:' prefix for permission checks
                # Property lists use 'list:name' internally but permissions use 'name'
                normalized_name = (
                    property_name[5:]
                    if property_name.startswith("list:")
                    else property_name
                )

                # Build full property path for permission check
                property_path = (
                    f"{subtarget}/{normalized_name}" if subtarget else normalized_name
                )
                result = evaluator.evaluate_property_access(
                    self.id, peerid, property_path, operation="read"
                )
                if result == PermissionResult.ALLOWED:
                    filtered_data[property_name] = value
                else:
                    logger.debug(
                        f"Filtered property {property_path} from subscription callback to {peerid}"
                    )

            if not filtered_data:
                logger.debug(
                    f"No permitted properties in callback to {peerid}, skipping"
                )
                return None

            return json.dumps(filtered_data)
        except Exception as e:
            logger.error(f"Permission filtering failed for subscription callback: {e}")
            return None  # Fail-closed: don't send data on error

    # =========================================================================
    # Subscription Suspension Management
    # =========================================================================

    def is_subscription_suspended(
        self, target: str, subtarget: str | None = None
    ) -> bool:
        """Check if diff registration is suspended for a target/subtarget.

        Args:
            target: Target resource (e.g., "properties")
            subtarget: Optional subtarget (e.g., property name)

        Returns:
            True if suspended, False otherwise
        """
        if not self.config or not self.id:
            return False
        try:
            db = get_subscription_suspension(self.config, self.id)
            return db.is_suspended(target, subtarget)
        except Exception as e:
            logger.error(f"Error checking suspension: {e}")
            return False

    def suspend_subscriptions(self, target: str, subtarget: str | None = None) -> bool:
        """Suspend diff registration for a target/subtarget.

        While suspended, property changes will NOT register diffs or trigger callbacks.
        Call resume_subscriptions() to lift suspension and send resync callbacks.

        Args:
            target: Target resource (e.g., "properties")
            subtarget: Optional subtarget (e.g., property name)

        Returns:
            True if newly suspended, False if already suspended
        """
        if not self.config or not self.id:
            return False
        try:
            db = get_subscription_suspension(self.config, self.id)
            return db.suspend(target, subtarget)
        except Exception as e:
            logger.error(f"Error suspending subscriptions: {e}")
            return False

    def resume_subscriptions(self, target: str, subtarget: str | None = None) -> int:
        """Resume diff registration and send resync callbacks.

        Sends a resync callback to ALL subscriptions on this target/subtarget,
        telling them to do a full GET to re-sync their state.

        Args:
            target: Target resource (e.g., "properties")
            subtarget: Optional subtarget (e.g., property name)

        Returns:
            The number of resync callbacks sent
        """
        if not self.config or not self.id:
            return 0
        try:
            db = get_subscription_suspension(self.config, self.id)
            if not db.resume(target, subtarget):
                return 0  # Wasn't suspended

            # Find all affected subscriptions and send resync callbacks
            return self._send_resync_callbacks(target, subtarget)
        except Exception as e:
            logger.error(f"Error resuming subscriptions: {e}")
            return 0

    def _send_resync_callbacks(self, target: str, subtarget: str | None) -> int:
        """Send resync callbacks to all subscriptions on target/subtarget.

        Args:
            target: Target resource
            subtarget: Optional subtarget

        Returns:
            Number of callbacks sent successfully
        """
        subs = self.get_subscriptions(target=target, subtarget=None, callback=False)
        if not subs:
            return 0

        count = 0
        for sub in subs:
            sub_target = sub.get("target", "")
            sub_subtarget = sub.get("subtarget")

            # Match target
            if sub_target != target:
                continue

            # Match subtarget if specified
            # Empty subtarget in subscription means "all subtargets", so it matches any filter
            if subtarget is not None and sub_subtarget and sub_subtarget != subtarget:
                continue

            # Send resync callback
            # If we resumed a specific subtarget, use that for the resync
            # (even if the subscription itself has no subtarget or a different one)
            resync_subtarget = subtarget if subtarget else sub_subtarget
            if self._callback_subscription_resync(sub, resync_subtarget):
                count += 1

        logger.info(f"Sent {count} resync callbacks for {target}/{subtarget}")
        return count

    def _send_resync_callback_sync(
        self, callback_url: str, payload: dict, secret: str, peer_id: str
    ) -> bool:
        """Send resync callback synchronously (blocking).

        Args:
            callback_url: URL to send the callback to
            payload: Callback payload
            secret: Trust secret for authentication
            peer_id: Peer ID (for logging)

        Returns:
            True if callback was sent successfully
        """
        import httpx

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    callback_url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {secret}",
                    },
                )

            if response.status_code in (200, 204):
                logger.info(
                    f"Sent resync callback to {peer_id} for subscription "
                    f"{payload.get('subscriptionid')}"
                )
                return True
            else:
                logger.warning(
                    f"Resync callback to {peer_id} failed: {response.status_code}"
                )
                return False

        except Exception as e:
            logger.error(f"Error sending resync callback to {peer_id}: {e}")
            return False

    def _send_resync_callback_async(
        self, callback_url: str, payload: dict, secret: str, peer_id: str
    ) -> None:
        """Send resync callback asynchronously (fire-and-forget).

        Args:
            callback_url: URL to send the callback to
            payload: Callback payload
            secret: Trust secret for authentication
            peer_id: Peer ID (for logging)
        """

        async def _send():
            import httpx

            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        callback_url,
                        json=payload,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {secret}",
                        },
                    )

                if response.status_code in (200, 204):
                    logger.info(
                        f"Sent resync callback to {peer_id} for subscription "
                        f"{payload.get('subscriptionid')}"
                    )
                else:
                    logger.warning(
                        f"Resync callback to {peer_id} failed: {response.status_code}"
                    )

            except Exception as e:
                logger.error(f"Error sending resync callback to {peer_id}: {e}")

        try:
            import asyncio

            loop = asyncio.get_running_loop()
            loop.create_task(_send())
            logger.debug(
                f"Async resync callback to {peer_id} for subscription "
                f"{payload.get('subscriptionid')} (fire-and-forget)"
            )
        except RuntimeError:
            # No event loop - fallback to sync
            logger.debug("No async loop, falling back to sync resync callback")
            self._send_resync_callback_sync(callback_url, payload, secret, peer_id)

    def _callback_subscription_resync(
        self, subscription: dict, override_subtarget: str | None = None
    ) -> bool:
        """Send a resync callback to a single subscription.

        Checks peer capability before sending resync. If peer doesn't support
        the subscriptionresync option, falls back to low-granularity callback.

        Respects the sync_subscription_callbacks configuration to determine
        whether to send callbacks synchronously (blocking) or asynchronously
        (fire-and-forget).

        Args:
            subscription: Subscription dict with peerid, subscriptionid, callback, etc.
            override_subtarget: Optional subtarget to use instead of subscription's subtarget
                              (used when resuming a specific subtarget on a broader subscription)

        Returns:
            True if callback was sent/scheduled successfully
        """
        from datetime import UTC, datetime

        peer_id = subscription.get("peerid", "")
        sub_id = subscription.get("subscriptionid", "")
        target = subscription.get("target", "")
        # Use override_subtarget if provided, otherwise use subscription's subtarget
        sub_subtarget = (
            override_subtarget
            if override_subtarget is not None
            else subscription.get("subtarget")
        )

        # Get trust relationship to construct callback URL
        from .trust import Trust

        trust = Trust(actor_id=self.id, peerid=peer_id, config=self.config)
        trust_data = trust.get()

        if not trust_data:
            logger.warning(f"No trust found for peer {peer_id}")
            return False

        # Construct callback URL from trust relationship (same as callback_subscription)
        callback_url = (
            trust_data.get("baseuri", "")
            + "/callbacks/subscriptions/"
            + (self.id or "")
            + "/"
            + sub_id
        )

        if not callback_url or not trust_data.get("baseuri"):
            logger.warning(
                f"No callback URL for subscription {sub_id} - missing baseuri in trust"
            )
            return False

        # Check if peer supports resync callbacks (use cached data only)
        from .interface.actor_interface import ActorInterface
        from .peer_capabilities import PeerCapabilities

        actor_interface = ActorInterface(self)
        caps = PeerCapabilities(actor_interface, peer_id)

        # Use cached capabilities without blocking on network fetch
        # If cache is expired or not available, assume support (optimistic)
        supports_resync_cached = caps.supports_resync_callbacks_cached()
        if supports_resync_cached is None:
            # Cache expired or not available - assume support to avoid blocking
            # This is optimistic but safe: if peer doesn't support resync,
            # the receiver will process it as a regular low-granularity callback
            supports_resync = True
            logger.debug(
                f"Capabilities not cached for peer {peer_id}, "
                f"assuming resync support (optimistic)"
            )

            # Schedule background refresh to update cache for next time
            # This doesn't block the current operation
            try:
                import asyncio

                async def _refresh_capabilities():
                    try:
                        await caps.refresh_async()
                        logger.debug(
                            f"Background refresh of capabilities for {peer_id}"
                        )
                    except Exception as e:
                        logger.debug(
                            f"Background capability refresh failed for {peer_id}: {e}"
                        )

                loop = asyncio.get_running_loop()
                loop.create_task(_refresh_capabilities())
            except RuntimeError:
                # No event loop - skip background refresh
                # Next operation will still use optimistic approach
                pass
        else:
            supports_resync = supports_resync_cached
            logger.debug(
                f"Using cached capability for peer {peer_id}: "
                f"resync_supported={supports_resync}"
            )

        # Increment sequence number
        new_seq = self._increment_subscription_sequence(peer_id, sub_id)

        # Build resource URL for resync
        if not self.config:
            logger.warning("No config available for building resource URL")
            return False
        resource_url = f"{self.config.proto}{self.config.fqdn}/{self.id}/{target}"
        if sub_subtarget:
            resource_url += f"/{sub_subtarget}"

        # Build callback payload - use resync type only if peer supports it
        if supports_resync:
            # Resync callback per protocol spec v1.4
            payload = {
                "id": self.id,
                "subscriptionid": sub_id,
                "target": target,
                "subtarget": sub_subtarget,
                "sequence": new_seq,
                "timestamp": datetime.now(UTC).isoformat(),
                "granularity": subscription.get("granularity", "high"),
                "type": "resync",
                "url": resource_url,
            }
            logger.debug(f"Sending resync callback to peer {peer_id} (supports resync)")
        else:
            # Fallback: create a full-state diff and send low-granularity callback
            # Get the full current state
            full_state = self._get_full_state_for_subscription(target, sub_subtarget)

            # Store as a subscription diff
            diff_url = self._store_subscription_diff(
                peer_id, sub_id, new_seq, full_state
            )

            # Send low-granularity callback with URL to subscription diff
            payload = {
                "id": self.id,
                "subscriptionid": sub_id,
                "target": target,
                "subtarget": sub_subtarget,
                "sequence": new_seq,
                "timestamp": datetime.now(UTC).isoformat(),
                "granularity": "low",
                "url": diff_url,
            }
            logger.info(
                f"Peer {peer_id} does not support resync callbacks, "
                f"creating full-state diff for low-granularity callback"
            )

        # Get trust secret for authentication (already fetched above)
        secret = trust_data.get("secret", "")

        # Check sync configuration (like diff callbacks do)
        use_sync = getattr(self.config, "sync_subscription_callbacks", False)

        if use_sync:
            # Lambda mode: blocking call
            logger.info(f"Sync resync callback to {peer_id}")
            return self._send_resync_callback_sync(
                callback_url, payload, secret, peer_id
            )
        else:
            # Local mode: async fire-and-forget
            self._send_resync_callback_async(callback_url, payload, secret, peer_id)
            return True  # Scheduled (not confirmed)

    def _get_full_state_for_subscription(
        self, target: str, subtarget: str | None
    ) -> dict[str, Any]:
        """Get the full current state for a subscription target.

        Args:
            target: Subscription target (e.g., "properties")
            subtarget: Optional subtarget (e.g., list name for property lists)

        Returns:
            Dict containing the full state
        """
        if target == "properties":
            if subtarget:
                # Specific property list or property
                if hasattr(self, "property_lists") and self.property_lists:
                    if self.property_lists.exists(subtarget):
                        # It's a list - return all items
                        list_attr = getattr(self.property_lists, subtarget)
                        items = list(list_attr)
                        logger.debug(
                            f"Getting full state for list '{subtarget}': {len(items)} items"
                        )
                        # Return as list operation format for diff
                        return {
                            subtarget: {
                                "list": subtarget,
                                "operation": "extend",
                                "items": items,
                            }
                        }

                # Try as scalar property
                prop_data = self.get_property(subtarget)
                if prop_data is not None:
                    logger.debug(f"Getting full state for property '{subtarget}'")
                    return {subtarget: prop_data}
                logger.warning(f"Subtarget '{subtarget}' not found as list or property")
                return {}
            else:
                # All properties - get both scalars and lists
                result = {}
                # Get scalar properties
                all_props = self.get_properties()
                if all_props:
                    result.update(all_props)
                # Get property lists
                if hasattr(self, "property_lists") and self.property_lists:
                    for list_name in self.property_lists.list_all():
                        list_attr = getattr(self.property_lists, list_name)
                        items = list(list_attr)
                        result[list_name] = {
                            "list": list_name,
                            "operation": "extend",
                            "items": items,
                        }
                logger.debug(
                    f"Getting full state for all properties: {len(result)} keys"
                )
                return result
        return {}

    def _store_subscription_diff(
        self, peer_id: str, subscription_id: str, sequence: int, data: dict[str, Any]
    ) -> str:
        """Store a subscription diff and return its URL.

        Args:
            peer_id: Peer actor ID
            subscription_id: Subscription ID
            sequence: Sequence number (already incremented)
            data: Diff data to store

        Returns:
            URL to fetch this diff
        """
        import json

        from .db import get_subscription_diff

        if not self.config:
            logger.error("No config available for storing subscription diff")
            return ""

        # Store diff using low-level diff protocol (sequence already incremented)
        logger.debug(
            f"Storing subscription diff for {subscription_id} seq={sequence}, "
            f"data keys: {list(data.keys())}"
        )

        diff_handle = get_subscription_diff(self.config)
        blob = json.dumps(data)

        logger.debug(f"Diff blob size: {len(blob)} bytes")

        success = diff_handle.create(
            actor_id=self.id,
            subid=subscription_id,
            diff=blob,
            seqnr=sequence,
        )

        if success:
            logger.info(
                f"Successfully stored subscription diff for {subscription_id} seq={sequence}"
            )
        else:
            logger.error(
                f"Failed to store subscription diff for {subscription_id} seq={sequence}, "
                f"actor_id={self.id}"
            )

        # Build URL to this diff
        # Format: /{actor_id}/subscriptions/{peer_id}/{subscription_id}/{sequence}
        diff_url = (
            f"{self.config.proto}{self.config.fqdn}/{self.id}"
            f"/subscriptions/{peer_id}/{subscription_id}/{sequence}"
        )
        logger.debug(f"Diff URL: {diff_url}")
        return diff_url

    def _increment_subscription_sequence(
        self, peer_id: str, subscription_id: str
    ) -> int:
        """Increment and return the new sequence number for a subscription.

        Args:
            peer_id: Peer actor ID
            subscription_id: Subscription ID

        Returns:
            New sequence number
        """
        sub_obj = self.get_subscription_obj(peerid=peer_id, subid=subscription_id)
        if not sub_obj:
            return 1

        # Use the increase_seq() method which increments and returns new sequence
        new_seq = sub_obj.increase_seq()
        return new_seq if new_seq else 1

    # =========================================================================
    # Diff Registration
    # =========================================================================

    def register_diffs(self, target=None, subtarget=None, resource=None, blob=None):
        """Registers a blob diff against all subscriptions with the correct target, subtarget, and resource.

        If resource is set, the blob is expected to be the FULL resource object, not a diff.

        Note: Skips registration if the target/subtarget is currently suspended.
        Use suspend_subscriptions() and resume_subscriptions() to manage suspension.
        """
        if blob is None or not target:
            return

        # Check suspension BEFORE registering diffs
        if self.is_subscription_suspended(target, subtarget):
            logger.debug(
                f"Skipping diff registration for {target}/{subtarget}: suspended"
            )
            return
        # Get all subscriptions, both with the specific subtarget/resource and those
        # without
        subs = self.get_subscriptions(
            target=target, subtarget=None, resource=None, callback=False
        )
        if not subs:
            subs = []
        if subtarget and resource:
            logger.debug(
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
            logger.debug(
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
            logger.debug(
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
                logger.debug("     - no match on subtarget, skipping...")
                continue
            # Skip the ones without correct resource
            if resource and sub["resource"] and sub["resource"] != resource:
                logger.debug("     - no match on resource, skipping...")
                continue
            sub_obj = self.get_subscription_obj(
                peerid=sub["peerid"], subid=sub["subscriptionid"]
            )
            if not sub_obj:
                continue
            sub_obj_data = sub_obj.get()
            logger.debug(
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
                    logger.debug(
                        "         - subscription has resource("
                        + sub_obj_data["resource"]
                        + "), no matching blob found in diff"
                    )
                    continue
                logger.debug(
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
                logger.debug(
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
                logger.debug(
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
                logger.debug(
                    "         - diff has subtarget("
                    + subtarget
                    + "), subscription has not, adding diff("
                    + finblob
                    + ")"
                )
            else:
                # The diff is correct for the subscription
                logger.debug(
                    "         - exact target/subtarget match, adding diff(" + blob + ")"
                )
                finblob = blob
            if sub_obj:
                diff = sub_obj.add_diff(blob=finblob)
            else:
                diff = None
            if not diff:
                logger.warning(
                    "Failed when registering a diff to subscription ("
                    + sub["subscriptionid"]
                    + "). Will not send callback."
                )
            else:
                # Direct call - callback_subscription handles sync/async internally
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
            self.list = get_actor_list(self.config)
        else:
            self.list = None
        self.actors = None
        self.fetch()
