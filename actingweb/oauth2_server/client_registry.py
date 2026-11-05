"""
MCP Client Registry for dynamic client registration and management.

This module handles registration of MCP clients (like ChatGPT) that need OAuth2
credentials to authenticate with ActingWeb. Client credentials are stored
per-actor but clients are not treated as actors themselves.
"""

import logging
import secrets
import time
from typing import Any

from .. import attribute
from .. import config as config_class
from ..client_text import sanitize_client_name
from ..constants import CLIENT_INDEX_BUCKET, OAUTH2_SYSTEM_ACTOR
from ..db.exceptions import DbError
from ..secret_compare import secret_equals

logger = logging.getLogger(__name__)

# token_endpoint_auth_method values accepted at registration. "none" is a
# public client; the two secret transports are both accepted for any
# confidential client at the token endpoint.
SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS = (
    "none",
    "client_secret_post",
    "client_secret_basic",
)


class MCPClientRegistry:
    """
    Registry for MCP clients with per-actor storage.

    This class manages dynamic client registration (RFC 7591) for MCP clients,
    storing credentials in actor properties rather than treating clients as actors.
    """

    def __init__(self, config: config_class.Config):
        self.config = config
        # Use Attributes system for private storage instead of underscore properties
        self.clients_bucket = "mcp_clients"  # Private attribute bucket for client data

    def register_client(
        self, actor_id: str, registration_data: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Register an MCP client for a specific actor and create corresponding trust relationship.

        This integrates OAuth2 client registration with ActingWeb's trust system,
        ensuring that clients are properly authenticated and authorized.

        Args:
            actor_id: The actor this client will be associated with
            registration_data: Client registration request data

        ``token_endpoint_auth_method`` may be ``none`` (a public client: no
        secret is issued, PKCE is required at authorize, and it may refresh
        without a secret), ``client_secret_post`` (the default) or
        ``client_secret_basic``; anything else raises ``ValueError``, which
        the registration endpoint answers as ``invalid_client_metadata``.
        ``client_name`` is sanitised (``actingweb.client_text``).

        Returns:
            Client registration response per RFC 7591. ``client_secret`` and
            ``client_secret_expires_at`` (0) are present only for a
            confidential client.
        """
        # Validate required fields. The name is client-supplied and
        # unauthenticated; it names the client's trust row and is rendered by
        # applications, so it is sanitised before it is stored or returned.
        client_name = sanitize_client_name(registration_data.get("client_name"))
        if not client_name:
            raise ValueError("client_name is required")

        # RFC 7591 §2: absent means client_secret_basic in the RFC, but this
        # registry has always defaulted to client_secret_post and both are
        # accepted as the transport for any confidential client. "none" makes
        # a public client: no secret is issued and PKCE is its proof.
        auth_method = (
            registration_data.get("token_endpoint_auth_method") or "client_secret_post"
        )
        if auth_method not in SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS:
            raise ValueError(
                "token_endpoint_auth_method must be one of "
                + ", ".join(SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS)
            )
        is_public = auth_method == "none"

        # Generate client credentials
        client_id = f"mcp_{secrets.token_hex(16)}"
        client_secret: str | None = None if is_public else secrets.token_urlsafe(32)

        # Prepare client data
        client_data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "client_name": client_name,
            "redirect_uris": registration_data.get("redirect_uris", []),
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": auth_method,
            "trust_type": registration_data.get("trust_type", "mcp_client"),
            "created_at": int(time.time()),
            "actor_id": actor_id,
        }
        # R3: the client-credentials grant mints from this registration; one
        # made before the actor was adopted in place mints nothing.
        from .. import session_generation

        client_data[session_generation.STAMP_FIELD] = session_generation.current(
            actor_id, self.config
        )

        # Store client in actor properties
        logger.debug(
            f"register_client: storing client_id={client_id} for actor_id={actor_id}"
        )
        self._store_client(actor_id, client_id, client_data)

        # Update global index
        logger.debug(
            f"register_client: updating global index client_id={client_id} -> actor_id={actor_id}"
        )
        self._update_global_index(client_id, actor_id)

        # Create corresponding trust relationship for this OAuth2 client
        self._create_client_trust_relationship(actor_id, client_id, client_data)

        # Return registration response
        base_url = f"{self.config.proto}{self.config.fqdn}"
        response: dict[str, Any] = {
            "client_id": client_id,
            "client_name": client_name,
            "redirect_uris": client_data["redirect_uris"],
            "grant_types": client_data["grant_types"],
            "response_types": client_data["response_types"],
            "token_endpoint_auth_method": client_data["token_endpoint_auth_method"],
            "trust_type": client_data["trust_type"],
            "created_at": client_data["created_at"],
            "client_id_issued_at": client_data["created_at"],
            "actor_id": client_data["actor_id"],
            # OAuth2 endpoints
            "authorization_endpoint": f"{base_url}/oauth/authorize",
            "token_endpoint": f"{base_url}/oauth/token",
            "issuer": base_url,
        }
        if client_secret is not None:
            # RFC 7591 §3.2.1: REQUIRED when a secret is issued; 0 = never.
            response["client_secret"] = client_secret
            response["client_secret_expires_at"] = 0

        logger.debug(f"Registered MCP client {client_id} for actor {actor_id}")
        return response

    def validate_client(
        self, client_id: str, client_secret: str | None = None
    ) -> dict[str, Any] | None:
        """
        Validate client credentials.

        Args:
            client_id: Client identifier
            client_secret: Client secret (optional for public clients)

        Returns:
            Client data if valid, None otherwise
        """
        client_data = self._load_client(client_id)
        if not client_data:
            return None

        # For confidential clients, validate secret
        if client_secret is not None:
            stored_secret = client_data.get("client_secret")
            if not secret_equals(stored_secret, client_secret):
                logger.warning(f"Invalid client secret for client {client_id}")
                logger.debug(
                    f"Client secret validation failed - Expected length: {len(stored_secret) if stored_secret else 0}, Provided length: {len(client_secret)}"
                )
                logger.debug(
                    f"Client last regenerated: {client_data.get('secret_regenerated_at', 'Never')}"
                )
                return None
            else:
                logger.debug(f"Client secret validation successful for {client_id}")
                if client_data.get("secret_regenerated_at"):
                    logger.debug(
                        f"Using regenerated secret from {client_data.get('secret_regenerated_at')}"
                    )

        return client_data

    def load_client_strict(self, client_id: str) -> dict[str, Any] | None:
        """Load a client record, telling absence from a store fault.

        For the token endpoint, where "no such client" is answered with 401
        ``invalid_client`` and a client may drop its registration on it. The
        other lookups (authorize, the callback filter, the SDK) keep
        :meth:`validate_client`'s fail-as-absent read.

        Returns:
            The client record, or None when the client does not exist.

        Raises:
            TokenStoreUnavailable: the client index or the client row could
                not be read.
        """
        from ..db import get_attribute
        from .token_manager import TokenStoreUnavailable

        db = get_attribute(self.config)
        try:
            index_row = db.get_attr_strict(
                actor_id=OAUTH2_SYSTEM_ACTOR, bucket=CLIENT_INDEX_BUCKET, name=client_id
            )
            actor_id = index_row.get("data") if index_row else None
            if not actor_id:
                return None
            client_row = db.get_attr_strict(
                actor_id=actor_id, bucket=self.clients_bucket, name=client_id
            )
        except Exception as e:
            raise TokenStoreUnavailable(
                f"Could not read client {client_id} from the store"
            ) from e
        client_data = client_row.get("data") if client_row else None
        return client_data if isinstance(client_data, dict) else None

    def validate_redirect_uri(self, client_id: str, redirect_uri: str) -> bool:
        """
        Validate redirect URI for a client.

        Args:
            client_id: Client identifier
            redirect_uri: Redirect URI to validate

        Returns:
            True if URI is valid for this client
        """
        client_data = self._load_client(client_id)
        if not client_data:
            return False

        registered_uris = client_data.get("redirect_uris", [])
        return redirect_uri in registered_uris

    def get_client_actor_id(self, client_id: str) -> str | None:
        """
        Get the actor ID associated with a client.

        Args:
            client_id: Client identifier

        Returns:
            Actor ID or None if client not found
        """
        client_data = self._load_client(client_id)
        return client_data.get("actor_id") if client_data else None

    def list_clients_for_actor(self, actor_id: str) -> list[dict[str, Any]]:
        """
        List all clients registered for an actor.

        Args:
            actor_id: Actor identifier

        Returns:
            List of client data dictionaries
        """
        try:
            # Use the proper ActingWeb pattern with attribute buckets
            bucket = attribute.Attributes(
                actor_id=actor_id, bucket="mcp_clients", config=self.config
            )

            # Get all client attributes from the bucket (a listing for display)
            bucket_data = bucket.get_bucket(strict=False)
            if not bucket_data:
                return []

            # Extract the actual client data from each attribute
            clients = []
            for attr_data in bucket_data.values():
                if attr_data and "data" in attr_data:
                    clients.append(attr_data["data"])
            return clients

        except Exception as e:  # folds DbError: display listing (strict=False)
            logger.error(f"Error listing clients for actor {actor_id}: {e}")
            return []

    def delete_client(
        self,
        client_id: str,
        actor_id: str | None = None,
        *,
        actor_deleted: bool = False,
    ) -> bool:
        """
        Delete an OAuth2 client and revoke all its tokens.

        ``actor_deleted=True``: the owning actor is being wiped, and its
        bucket (the client row), its tokens and its trusts go with the wipe,
        so only the client's global index row is removed (confirmed).

        This method performs a complete cleanup:
        1. Revokes all access and refresh tokens for the client
        2. Deletes the client from actor's bucket
        3. Deletes the client from global index
        4. Deletes the corresponding trust relationship

        Args:
            client_id: Client identifier to delete
            actor_id: Optional actor ID where tokens are stored. If provided, this
                      takes precedence over the actor_id in client_data. This is
                      important when called from Trust.delete() which has the
                      authoritative actor_id for the trust relationship.

        Returns:
            True if deletion was successful, False otherwise
        """
        if actor_deleted:
            from ..single_use import delete_confirmed

            # Only an index row that names this actor: a client row copied
            # into the deleted actor's bucket must not disable a client
            # registered elsewhere.
            index_row = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=CLIENT_INDEX_BUCKET,
                config=self.config,
            ).get_attr(name=client_id)
            indexed_owner = index_row.get("data") if index_row else None
            if indexed_owner and actor_id and indexed_owner != actor_id:
                logger.error(
                    f"Not deleting the index row of OAuth2 client {client_id}: "
                    f"it names actor {indexed_owner}, not the deleted {actor_id}"
                )
                return True
            return delete_confirmed(
                self.config, OAUTH2_SYSTEM_ACTOR, CLIENT_INDEX_BUCKET, client_id
            )
        owner_id = self._disable_client(client_id, actor_id)
        if owner_id is None:
            return False
        # Delete corresponding trust relationship
        self._delete_client_trust_relationship(owner_id, client_id)
        logger.info(
            f"Successfully deleted OAuth2 client {client_id} for actor {owner_id}"
        )
        return True

    def disable_client(self, client_id: str, *, actor_id: str) -> bool:
        """Steps 1-3 of :meth:`delete_client` for its owner ``actor_id``:
        revoke the client's tokens and delete its row and index row, leaving
        the trust rows. ``Trust.delete`` calls it before it deletes the row,
        so a fault leaves the row for the retry. False when ``actor_id`` does
        not own the client or neither row is confirmed gone; a fault raises
        ``DbError``."""
        return self._disable_client(client_id, actor_id) is not None

    def _disable_client(self, client_id: str, actor_id: str | None) -> str | None:
        """Revoke, then delete the client row and its index row. The owner's
        actor id when the client is disabled, None when it is refused or not
        confirmed."""
        try:
            # First find the client to get metadata (and actor_id if not provided).
            client_data = self._load_client(client_id)

            # Resolve the actor whose bucket holds the client. The caller-provided
            # actor_id takes precedence — it comes from the trust relationship,
            # which is the authoritative source for token/client storage.
            if not actor_id and client_data:
                actor_id = client_data.get("actor_id")
            # Only the owner deletes a client: its index row is global, so a
            # caller that merely holds a connection (a user who authorized
            # another actor's or the system actor's client) would disable it
            # for everyone. Such a caller removes its own connection with
            # delete_client_connection().
            owner = client_data.get("actor_id") if client_data else None
            if owner and actor_id and owner != actor_id:
                logger.error(
                    f"Refusing to delete OAuth2 client {client_id} for actor "
                    f"{actor_id}: it is registered under actor {owner}"
                )
                return None
            if (
                not client_data
                and actor_id
                and not self.client_owned_by(actor_id, client_id)
            ):
                # No index row to say who owns it: only the caller's own
                # client bucket can, and it does not hold this client.
                logger.error(
                    f"Refusing to delete OAuth2 client {client_id} for actor "
                    f"{actor_id}: it is not registered under that actor"
                )
                return None

            # The global client index is only a best-effort lookup optimization
            # (see _search_client_in_actors). Under heavy concurrent access to the
            # shared system-actor index bucket the entry may be transiently
            # unreadable. As long as we know the authoritative actor_id we can —
            # and must — still delete the client from that actor's bucket; bailing
            # out here is what previously orphaned the client (it stayed listable).
            if not actor_id:
                logger.warning(f"Client {client_id} not found for deletion")
                return None
            if not client_data:
                logger.warning(
                    f"Client {client_id} missing from global index; deleting from "
                    f"actor {actor_id}'s bucket using the caller-provided actor_id"
                )

            # Revoke all tokens for this client to terminate access immediately
            from .token_manager import (
                TokenStoreUnavailable,
                get_actingweb_token_manager,
            )

            token_manager = get_actingweb_token_manager(self.config)
            try:
                revoked_count = token_manager.revoke_client_tokens(actor_id, client_id)
                logger.info(f"Revoked {revoked_count} tokens for client {client_id}")
            except TokenStoreUnavailable as e:
                # Deleting the client below is what stops its refresh tokens
                # (the grants cannot authenticate it any more), so go on; an
                # access token that was not revoked lives out its TTL (1 h).
                logger.error(
                    f"Deleting client {client_id}: could not list all of its "
                    f"tokens ({e}); deleting the client anyway, which disables "
                    f"its refresh tokens; unrevoked access tokens expire within "
                    f"an hour"
                )

            # Delete the client row and its index row, confirming each: the
            # token endpoint needs both to authenticate the client, so either
            # one gone disables it. A plain delete cannot be trusted to report
            # a fault (DynamoDB swallows it), and the outage that stopped the
            # token listing above usually fails these too.
            from ..single_use import delete_confirmed

            row_gone = delete_confirmed(
                self.config, actor_id, self.clients_bucket, client_id
            )
            index_gone = delete_confirmed(
                self.config, OAUTH2_SYSTEM_ACTOR, CLIENT_INDEX_BUCKET, client_id
            )
            if not row_gone and not index_gone:
                logger.error(
                    f"Could not delete OAuth2 client {client_id} for actor "
                    f"{actor_id}: neither its row nor its index row is confirmed "
                    f"gone, so it can still authenticate"
                )
                return None
            if not (row_gone and index_gone):
                logger.warning(
                    f"OAuth2 client {client_id}: only its "
                    f"{'row' if row_gone else 'index row'} is confirmed deleted; "
                    f"that is enough to disable it"
                )

            return actor_id

        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error deleting client {client_id}: {e}")
            return None

    def client_owned_by(self, actor_id: str, client_id: str) -> bool:
        """Whether ``client_id`` is registered under ``actor_id``: its row is
        in that actor's own client bucket. Needs no global index read, so a
        missing index row never turns an owner into a mere connection.
        Raises ``DbError`` on a fault."""
        bucket = attribute.Attributes(
            actor_id=actor_id, bucket=self.clients_bucket, config=self.config
        )
        row = bucket.get_attr(name=client_id)
        data = row.get("data") if row else None
        # The row names its owner; a row in this bucket naming another
        # actor (copied, restored, malformed) is not ownership.
        return isinstance(data, dict) and data.get("actor_id") == actor_id

    def revoke_connection_tokens(self, actor_id: str, client_id: str) -> int:
        """Revoke ``actor_id``'s tokens for ``client_id``, and only those.

        Raises ``DbError`` when a token could not be confirmed revoked, so
        the caller can stop before it removes what a retry would need.
        """
        from .token_manager import TokenStoreUnavailable, get_actingweb_token_manager

        try:
            return get_actingweb_token_manager(self.config).revoke_client_tokens(
                actor_id, client_id
            )
        except TokenStoreUnavailable as e:
            raise DbError("OAuth2 client token revocation", actor_id) from e

    def delete_client_connection(self, actor_id: str, client_id: str) -> None:
        """End one actor's connection to a client: revoke that actor's
        tokens for it, then delete that actor's trust rows of it. The client,
        its index row and every other actor's connection stay. Raises
        ``DbError`` on a fault; a retry finishes what is left."""
        self.revoke_connection_tokens(actor_id, client_id)
        self._delete_client_trust_relationship(actor_id, client_id)

    def _store_client(
        self, actor_id: str, client_id: str, client_data: dict[str, Any]
    ) -> None:
        """Store client data using ActingWeb attributes bucket."""
        try:
            # Use the proper ActingWeb pattern with attribute buckets
            bucket = attribute.Attributes(
                actor_id=actor_id, bucket="mcp_clients", config=self.config
            )

            # Store client data in the bucket
            logger.debug(
                f"Storing client {client_id} in mcp_clients bucket for actor {actor_id}"
            )
            bucket.set_attr(name=client_id, data=client_data)
            logger.info(f"Stored OAuth2 client {client_id}")

        except Exception as e:
            logger.error(f"Error storing client {client_id} for actor {actor_id}: {e}")
            raise

    def _load_client(self, client_id: str) -> dict[str, Any] | None:
        """Load client data by searching all actors."""
        try:
            # Extract actor ID from client data if we can find it
            # This is a simplified search - in production you might want to index this

            # For now, we'll need to search through actors
            # This is not efficient but works for the implementation
            # In production, you might want to maintain a separate client index

            # Try to find the client by searching through actor properties
            # Since we don't have a direct way to search all actors efficiently,
            # we'll implement a basic search pattern

            # The client_id contains the actor context in our implementation
            # We can optimize this later with proper indexing

            client_data: dict[str, Any] | None = self._search_client_in_actors(
                client_id
            )
            return client_data

        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error loading client {client_id}: {e}")
            return None

    def _search_client_in_actors(self, client_id: str) -> dict[str, Any] | None:
        """
        Search for client across actors.

        This is a basic implementation. In production, you would want to:
        1. Maintain a client ID -> actor ID index
        2. Use database queries for efficient lookup
        3. Cache frequently accessed clients
        """
        # For now, we'll implement a basic search
        # This method would need to be optimized for production use

        # Since we don't have an efficient way to search all actors,
        # we'll implement a property-based approach where we store
        # a global client index as well

        return self._load_from_global_index(client_id)

    def _load_from_global_index(self, client_id: str) -> dict[str, Any] | None:
        """Load client from a global index using attribute buckets."""
        try:
            # Use global attribute bucket for client index
            # This stores client_id -> actor_id mapping
            global_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=CLIENT_INDEX_BUCKET,
                config=self.config,
            )

            # Get the actor ID for this client
            actor_id_attr = global_bucket.get_attr(name=client_id)
            if not actor_id_attr or "data" not in actor_id_attr:
                logger.debug(
                    f"_load_from_global_index: client_id={client_id} not found in global index"
                )
                return None

            actor_id = actor_id_attr["data"]
            logger.debug(
                f"_load_from_global_index: client_id={client_id} -> actor_id={actor_id} from global index"
            )
            if not actor_id:
                return None

            # Load the actual client data from the actor's bucket
            client_bucket = attribute.Attributes(
                actor_id=actor_id, bucket="mcp_clients", config=self.config
            )
            client_attr = client_bucket.get_attr(name=client_id)
            if not client_attr or "data" not in client_attr:
                return None

            client_data: dict[str, Any] = client_attr["data"]
            logger.debug(
                f"_load_from_global_index: loaded client_data for {client_id}, client_data.actor_id={client_data.get('actor_id')}"
            )

            return client_data

        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error loading client from global index: {e}")
            return None

    def _create_client_trust_relationship(
        self, actor_id: str, client_id: str, client_data: dict[str, Any]
    ) -> None:
        """
        Create a trust relationship for the OAuth2 client.

        This ensures that OAuth2 clients are integrated into ActingWeb's trust system
        and subject to permission evaluation.

        Args:
            actor_id: Actor this client belongs to
            client_id: OAuth2 client ID
            client_data: Client registration data
        """
        try:
            from .. import actor as actor_module
            from ..interface.trust_manager import TrustManager

            # Load the actor
            core_actor = actor_module.Actor(actor_id, config=self.config)
            if not core_actor.actor:
                logger.error(
                    f"Cannot create trust relationship - actor {actor_id} not found"
                )
                return

            trust_manager = TrustManager(core_actor)

            # Create trust relationship using OAuth2 client credentials flow
            # Use client_id as the "email" identifier for this trust type
            trust_created = trust_manager.create_or_update_oauth_trust(
                email=client_id,  # Use client_id as identifier
                trust_type=client_data.get("trust_type", "mcp_client"),
                oauth_tokens={
                    "client_id": client_id,
                    "client_secret": client_data["client_secret"],
                    "grant_type": "client_credentials",
                    "created_at": client_data["created_at"],
                },
                established_via="oauth2_client",  # OAuth2 client credentials flow (not interactive)
                client_id=client_id,  # Ensure unique peer ID per client
                client_name=client_data.get("client_name"),
            )

            if trust_created:
                logger.info(f"Created trust relationship for OAuth2 client {client_id}")
            else:
                logger.error(
                    f"Failed to create trust relationship for OAuth2 client {client_id}"
                )

        except DbError:
            raise
        except Exception as e:
            logger.error(
                f"Error creating trust relationship for client {client_id}: {e}"
            )
            # Don't raise - client registration can continue without trust relationship

    def _delete_client_trust_relationship(self, actor_id: str, client_id: str) -> None:
        """
        Delete the trust relationship for an OAuth2 client.

        Args:
            actor_id: Actor this client belongs to
            client_id: OAuth2 client ID
        """
        try:
            from .. import actor as actor_module
            from ..interface.actor_interface import ActorInterface

            # Load the actor
            core_actor = actor_module.Actor(actor_id, config=self.config)
            if not core_actor.actor:
                logger.error(
                    f"Cannot delete trust relationship - actor {actor_id} not found"
                )
                return

            # Create ActorInterface wrapper
            registry = getattr(self.config, "service_registry", None)
            actor_interface = ActorInterface(
                core_actor=core_actor, service_registry=registry
            )

            # Every row of this client: the row the authentication resolver
            # finds, any legacy row beside it (an upgraded actor can hold a
            # tagged and a legacy row under different peer ids), and the
            # real-email legacy rows whose last peer-id segment is the
            # client id. Never a substring match: an unrelated row whose
            # peer id contains this id must survive.
            from .trust_lookup import client_trusts_for_deletion

            trusts = client_trusts_for_deletion(
                actor_interface.trust.relationships, client_id
            )
            if not trusts:
                logger.warning(
                    f"No trust relationship found to delete for OAuth2 client {client_id}"
                )
                return
            # Every row is tried before a fault is raised: the client row and
            # its index are already gone, so a retry finds no client to start
            # from (``OAuth2ClientManager.delete_client`` sweeps the actor's
            # leftover rows on that "not found" path).
            first_fault: DbError | None = None
            for trust in trusts:
                peer_id = trust.peerid
                try:
                    if actor_interface.trust.delete_relationship(peer_id):
                        logger.info(
                            f"Deleted trust relationship for OAuth2 client {client_id}: {peer_id}"
                        )
                    elif not any(
                        t.peerid == peer_id for t in actor_interface.trust.relationships
                    ):
                        # Deleting an earlier row of this client cascaded
                        # (``Trust.delete`` deletes the client again), and
                        # this row went with it.
                        logger.info(
                            f"Trust relationship {peer_id} for OAuth2 client {client_id} was already deleted"
                        )
                    else:
                        logger.warning(
                            f"Failed to delete trust relationship {peer_id} for client {client_id}"
                        )
                except DbError as e:  # folds DbError: raised after the other rows
                    if first_fault is None:
                        first_fault = e
                    logger.error(
                        f"Database error deleting trust relationship {peer_id} for client {client_id}: {e}"
                    )
                except Exception as e:
                    logger.error(
                        f"Error deleting trust relationship {peer_id} for client {client_id}: {e}"
                    )
            if first_fault is not None:
                raise first_fault

        except DbError:
            raise
        except Exception as e:
            logger.error(
                f"Error deleting trust relationship for client {client_id}: {e}"
            )
            # Don't raise - client deletion can continue

    def _update_global_index(self, client_id: str, actor_id: str) -> None:
        """Update the global client index using attribute buckets."""
        try:
            # Use global attribute bucket for client index
            # This stores client_id -> actor_id mapping
            global_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=CLIENT_INDEX_BUCKET,
                config=self.config,
            )

            # Store the client_id -> actor_id mapping
            global_bucket.set_attr(name=client_id, data=actor_id)
            logger.debug(f"Updated global index: {client_id} -> {actor_id}")

        except Exception as e:
            logger.error(f"Error updating global client index: {e}")
            raise


# Global registry instance
_client_registry: MCPClientRegistry | None = None
# The config the registry was built from; a different one must rebuild it.
_client_registry_config: config_class.Config | None = None


def get_mcp_client_registry(config: config_class.Config) -> MCPClientRegistry:
    """Get or create the global MCP client registry.

    Rebuilds when handed a different ``Config``. Serving one application's
    registry to another crosses database backends: registration writes the
    trust row to the first application's store while resolution reads the
    second's, and the read comes back empty rather than erroring.
    """
    global _client_registry, _client_registry_config
    if _client_registry is None or _client_registry_config is not config:
        _client_registry = MCPClientRegistry(config)
        _client_registry_config = config
    return _client_registry
