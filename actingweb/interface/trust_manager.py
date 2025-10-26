"""
Simplified trust relationship management for ActingWeb actors.
"""

import logging
from datetime import datetime
from typing import Any

from ..actor import Actor as CoreActor
from ..trust import canonical_connection_method


class TrustRelationship:
    """Represents a trust relationship with another actor."""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    @property
    def peer_id(self) -> str:
        """ID of the peer actor."""
        return str(self._data.get("peerid", ""))

    @property
    def base_uri(self) -> str:
        """Base URI of the peer actor."""
        return str(self._data.get("baseuri", ""))

    @property
    def peerid(self) -> str:
        """Peer actor ID."""
        return str(self._data.get("peerid", ""))

    @property
    def relationship(self) -> str:
        """Type of relationship (friend, partner, etc.)."""
        return str(self._data.get("relationship", ""))

    @property
    def approved(self) -> bool:
        """Whether this side has approved the relationship."""
        return bool(self._data.get("approved", False))

    @property
    def peer_approved(self) -> bool:
        """Whether the peer has approved the relationship."""
        return bool(self._data.get("peer_approved", False))

    @property
    def verified(self) -> bool:
        """Whether the relationship has been verified."""
        return bool(self._data.get("verified", False))

    @property
    def is_active(self) -> bool:
        """Whether the relationship is fully active (approved by both sides)."""
        return self.approved and self.peer_approved and self.verified

    @property
    def description(self) -> str:
        """Description of the relationship."""
        return str(self._data.get("desc", ""))

    @property
    def peer_type(self) -> str:
        """Type of the peer actor."""
        return str(self._data.get("type", ""))

    @property
    def established_via(self) -> str | None:
        """How this trust relationship was established (actingweb, oauth2, mcp)."""
        return self._data.get("established_via")

    @property
    def peer_identifier(self) -> str | None:
        """Generic peer identifier (email, username, UUID, etc.)."""
        return self._data.get("peer_identifier")

    @property
    def created_at(self) -> str | None:
        """When this trust relationship was created."""
        return self._data.get("created_at")

    @property
    def last_accessed(self) -> str | None:
        """When this trust relationship was last accessed."""
        return self._data.get("last_connected_at") or self._data.get("last_accessed")

    @property
    def last_connected_at(self) -> str | None:
        """Most recent time the relationship authenticated successfully."""
        return self._data.get("last_connected_at") or self._data.get("last_accessed")

    @property
    def last_connected_via(self) -> str | None:
        """How the trust last connected (trust, subscription, oauth, mcp)."""
        return self._data.get("last_connected_via")

    @property
    def client_name(self) -> str | None:
        """Friendly name of the OAuth2 client (e.g., ChatGPT, Claude, MCP Inspector)."""
        return self._data.get("client_name")

    @property
    def client_version(self) -> str | None:
        """Version of the OAuth2 client software."""
        return self._data.get("client_version")

    @property
    def client_platform(self) -> str | None:
        """Platform info from User-Agent for OAuth2 clients."""
        return self._data.get("client_platform")

    @property
    def oauth_client_id(self) -> str | None:
        """OAuth2 client ID reference for credentials-based clients."""
        return self._data.get("oauth_client_id")

    @property
    def user_agent(self) -> str | None:
        """Alias for client_platform for backward compatibility."""
        return self.client_platform

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return self._data.copy()


class TrustManager:
    """
    Simplified interface for managing trust relationships.

    Example usage:
        # Create trust with another actor
        relationship = actor.trust.create_relationship(
            peer_url="https://peer.example.com/actor123",
            relationship="friend"
        )

        # List all relationships
        for rel in actor.trust.relationships:
            print(f"Trust with {rel.peer_id}: {rel.relationship}")

        # Find specific relationship
        friend = actor.trust.find_relationship(relationship="friend")

        # Approve a relationship
        actor.trust.approve_relationship(peer_id="peer123")
    """

    def __init__(self, core_actor: CoreActor):
        self._core_actor = core_actor

    @property
    def relationships(self) -> list[TrustRelationship]:
        """Get all trust relationships."""
        relationships = self._core_actor.get_trust_relationships()
        return [TrustRelationship(rel) for rel in relationships if isinstance(rel, dict)]

    def find_relationship(
        self, peer_id: str = "", relationship: str = "", trust_type: str = ""
    ) -> TrustRelationship | None:
        """Find a specific trust relationship."""
        relationships = self._core_actor.get_trust_relationships(
            peerid=peer_id, relationship=relationship, trust_type=trust_type
        )
        if relationships and isinstance(relationships[0], dict):
            return TrustRelationship(relationships[0])
        return None

    def get_relationship(self, peer_id: str) -> TrustRelationship | None:
        """Get relationship with specific peer."""
        rel_data = self._core_actor.get_trust_relationship(peerid=peer_id)
        if rel_data and isinstance(rel_data, dict):
            return TrustRelationship(rel_data)
        return None

    def create_relationship(
        self, peer_url: str, relationship: str = "friend", secret: str = "", description: str = ""
    ) -> TrustRelationship | None:
        """Create a new trust relationship with another actor."""
        if not secret:
            secret = self._core_actor.config.new_token() if self._core_actor.config else ""

        rel_data = self._core_actor.create_reciprocal_trust(
            url=peer_url, secret=secret, desc=description, relationship=relationship
        )

        if rel_data and isinstance(rel_data, dict):
            return TrustRelationship(rel_data)
        return None

    def approve_relationship(self, peer_id: str) -> bool:
        """Approve a trust relationship."""
        relationship = self.get_relationship(peer_id)
        if not relationship:
            return False

        result = self._core_actor.modify_trust_and_notify(
            peerid=peer_id, relationship=relationship.relationship, approved=True
        )
        return bool(result)

    def delete_relationship(self, peer_id: str) -> bool:
        """Delete a trust relationship."""
        result = self._core_actor.delete_reciprocal_trust(peerid=peer_id, delete_peer=True)
        return bool(result)

    def delete_all_relationships(self) -> bool:
        """Delete all trust relationships."""
        result = self._core_actor.delete_reciprocal_trust(delete_peer=True)
        return bool(result)

    @property
    def active_relationships(self) -> list[TrustRelationship]:
        """Get all active (approved and verified) relationships."""
        return [rel for rel in self.relationships if rel.is_active]

    @property
    def pending_relationships(self) -> list[TrustRelationship]:
        """Get all pending (not yet approved by both sides) relationships."""
        return [rel for rel in self.relationships if not rel.is_active]

    def get_peers_by_relationship(self, relationship: str) -> list[TrustRelationship]:
        """Get all peers with a specific relationship type."""
        return [rel for rel in self.relationships if rel.relationship == relationship]

    def has_relationship_with(self, peer_id: str) -> bool:
        """Check if there's a relationship with the given peer."""
        return self.get_relationship(peer_id) is not None

    def is_trusted_peer(self, peer_id: str) -> bool:
        """Check if peer is trusted (has active relationship)."""
        relationship = self.get_relationship(peer_id)
        return relationship is not None and relationship.is_active

    # --- OAuth2/MCP unified helpers ---
    def _standardize_peer_id(self, source: str, identifier: str) -> str:
        """Create a standardized peer_id for non-actor peers (e.g., oauth2/mcp)."""
        normalized = identifier.replace("@", "_at_").replace(".", "_dot_")
        return f"{source}:{normalized}"

    def create_or_update_oauth_trust(
        self,
        email: str,
        trust_type: str,
        oauth_tokens: dict[str, Any] | None = None,
        established_via: str | None = None,
        client_id: str | None = None,
        client_name: str | None = None,
        client_version: str | None = None,
        client_platform: str | None = None,
    ) -> bool:
        """
        Create or update a trust established via OAuth2 or MCP using an email identity.

        When client_id is provided, creates unique trust relationships per client,
        allowing the same user to authenticate multiple MCP clients independently.

        Args:
            email: Authenticated user's email address
            trust_type: Type of trust relationship to create
            oauth_tokens: OAuth2 tokens from authentication
            established_via: How the trust was established ("oauth2_interactive", "oauth2_client")
            client_id: Optional MCP client ID for unique per-client relationships
            client_name: Friendly name of the client (e.g., "ChatGPT", "Claude")
            client_version: Version of the client software
            client_platform: Platform/User-Agent info

        Returns:
            True if trust relationship was created/updated successfully

        Note:
            - Does not run remote reciprocal flows
            - Idempotent on peer identifier
            - With client_id: creates "oauth2:email_at_domain:client_id" peer IDs
            - Without client_id: uses legacy "oauth2:email_at_domain" format
        """
        if not email:
            return False

        # Resolve trust_type via registry if available; fall back to provided name
        try:
            from ..trust_type_registry import get_registry

            cfg = getattr(self._core_actor, "config", None)
            if cfg is not None:
                registry = get_registry(cfg)
                tt = registry.get_type(trust_type)
                if not tt:
                    # Fallback to a conservative default if available
                    fallback = "web_user"
                    tt_fb = registry.get_type(fallback)
                    if tt_fb:
                        trust_type = fallback
        except RuntimeError:
            logging.debug("Trust type registry not initialized - using provided trust_type as-is")
            pass
        except Exception as e:
            logging.debug(f"Error accessing trust type registry: {e}")
            pass

        # Standardize peer id and check existing
        source = established_via or "oauth2"

        # Determine appropriate peer type based on context
        if client_id and established_via == "oauth2_client":
            # For MCP clients, use "mcp" as the peer type instead of the establishment method
            peer_type = "mcp"
        else:
            # For other OAuth2 trusts, use the establishment method
            peer_type = source

        # Create unique identifier per client when client_id is provided
        if client_id:
            # For MCP clients, include client_id to ensure each client gets its own trust relationship
            # Format: "oauth2:email_at_example_dot_com:client_123abc"
            normalized_email = email.replace("@", "_at_").replace(".", "_dot_")
            normalized_client = client_id.replace("@", "_at_").replace(".", "_dot_").replace(":", "_colon_")
            peer_id = f"{source}:{normalized_email}:{normalized_client}"
        else:
            # Legacy format for backward compatibility
            peer_id = self._standardize_peer_id(source, email)

        logging.debug(
            f"Creating/updating OAuth trust: email={email}, trust_type={trust_type}, established_via={established_via}, source={source}, client_id={client_id}, peer_id={peer_id}"
        )
        existing = self.get_relationship(peer_id)

        try:
            import time

            int(time.time())
        except Exception:
            pass

        if existing:
            # Update last accessed and established_via via DB layer without notifying peers
            try:
                from ..db_dynamodb.db_trust import DbTrust

                db = DbTrust()
                if db.get(actor_id=self._core_actor.id, peerid=peer_id):
                    now_iso = datetime.utcnow().isoformat()

                    # Always update last_accessed and established_via for OAuth2 trusts
                    modify_kwargs = {
                        "last_accessed": now_iso,
                        "established_via": source,  # Ensure established_via is set correctly
                        "last_connected_via": canonical_connection_method(source),
                    }

                    if not getattr(db.handle, "created_at", None):
                        modify_kwargs["created_at"] = now_iso

                    # Keep peer identifier in sync for OAuth2/MCP clients
                    if email:
                        modify_kwargs["peer_identifier"] = email

                    if client_name:
                        modify_kwargs["client_name"] = client_name
                    if client_version:
                        modify_kwargs["client_version"] = client_version
                    if client_platform:
                        modify_kwargs["client_platform"] = client_platform
                    if client_id and source == "oauth2_client":
                        modify_kwargs["oauth_client_id"] = client_id

                        # If description still references client identifier, replace with friendly name
                        current_desc = getattr(db.handle, "desc", "") or ""
                        normalized_desc = current_desc.strip().lower()
                        default_desc = f"OAuth2 client: {email}".strip().lower()
                        if client_name and normalized_desc == default_desc:
                            modify_kwargs["desc"] = f"OAuth2 client: {client_name}"

                    db.modify(**modify_kwargs)
                    logging.debug(f"Updated existing OAuth trust: peer_id={peer_id}, established_via={source}")
            except Exception:
                pass
        else:
            # Create a local trust record directly via DbTrust (no remote handshake)
            try:
                from ..db_dynamodb.db_trust import DbTrust

                db = DbTrust()
                secret = self._core_actor.config.new_token() if self._core_actor.config else ""
                baseuri = ""
                # For OAuth2 clients, don't set baseuri as they don't have ActingWeb endpoints
                # Only set baseuri for regular actor-to-actor trust relationships
                if source != "oauth2_client":
                    try:
                        if self._core_actor.config and self._core_actor.id:
                            baseuri = f"{self._core_actor.config.root}{self._core_actor.id}"
                    except Exception:
                        baseuri = ""

                # For OAuth2 clients, determine approval based on established_via
                if source == "oauth2_client":
                    # OAuth2 client trust: actor approves client creation, but client must authenticate to be peer_approved
                    local_approved = str(True)  # Actor approves the client
                    remote_approved = False     # Client not approved until successful authentication
                    desc_name = client_name or email
                    desc = f"OAuth2 client: {desc_name}"
                else:
                    # Regular OAuth2 user trust: both sides approved after successful OAuth flow
                    local_approved = str(True)  # Actor approves the user
                    remote_approved = True      # User already authenticated via OAuth
                    desc = f"OAuth trust for {email}"

                # Build client metadata dict (only include non-None values)
                client_metadata = {}
                if client_name:
                    client_metadata["client_name"] = client_name
                if client_version:
                    client_metadata["client_version"] = client_version
                if client_platform:
                    client_metadata["client_platform"] = client_platform
                if client_id and source == "oauth2_client":
                    client_metadata["oauth_client_id"] = client_id

                now_iso = datetime.utcnow().isoformat()

                created = db.create(
                    actor_id=self._core_actor.id,
                    peerid=peer_id,
                    baseuri=baseuri,
                    peer_type=peer_type,
                    relationship=trust_type,
                    secret=secret,
                    approved=local_approved,
                    verified=True,
                    peer_approved=remote_approved,
                    verification_token="",
                    desc=desc,
                    peer_identifier=email,
                    established_via=source,
                    created_at=now_iso,
                    last_accessed=now_iso,
                    last_connected_via=canonical_connection_method(source),
                    **client_metadata,  # Include client metadata in the trust relationship
                )
                if created:
                    logging.info(
                        f"Successfully created OAuth trust relationship: peer_id={peer_id}, trust_type={trust_type}, source={source}"
                    )
                else:
                    logging.error(f"Failed to create OAuth trust relationship in database: peer_id={peer_id}")
                    return False
            except Exception as e:
                logging.error(f"Exception creating OAuth trust relationship: {e}")
                return False

        # Store tokens in a consistent internal attribute namespace
        if oauth_tokens and hasattr(self._core_actor, "store"):
            try:
                from ..constants import OAUTH_TOKENS_PREFIX

                token_key = f"{OAUTH_TOKENS_PREFIX}{peer_id}"
                # Ensure store exists and is a mapping
                store = getattr(self._core_actor, "store", None)
                if store is not None:
                    store[token_key] = {
                        "access_token": oauth_tokens.get("access_token", ""),
                        "refresh_token": oauth_tokens.get("refresh_token", ""),
                        "expires_at": oauth_tokens.get("expires_at", 0),
                        "token_type": oauth_tokens.get("token_type", "Bearer"),
                    }
            except Exception:
                pass

        return True
