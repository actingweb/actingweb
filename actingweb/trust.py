import logging
from typing import Any


def canonical_connection_method(method: str | None) -> str | None:
    """
    Normalize connection hints to canonical channels.

    Args:
        method: Connection method hint (e.g., "oauth2:interactive", "trust", "mcp")

    Returns:
        Canonical connection method or original value if not recognized

    Examples:
        - "oauth2:interactive" -> "oauth"
        - "OAUTH" -> "oauth"
        - "trust" -> "trust"
        - "subscription" -> "subscription"
        - "mcp" -> "mcp"
        - "unknown_method" -> "unknown_method"
    """
    if not method:
        return None

    # Validate input is a string
    if not isinstance(method, str):
        logging.warning(
            f"Connection method must be string, got {type(method)}: {method}"
        )
        return None

    lowered = method.lower().strip()

    # Handle empty or whitespace-only strings
    if not lowered:
        return None

    # Known canonical methods
    VALID_CONNECTION_METHODS = {"oauth", "trust", "subscription", "mcp"}

    # Handle oauth variants (oauth, oauth2, oauth2:interactive, etc.)
    if lowered.startswith("oauth"):
        return "oauth"

    # Handle known exact matches
    if lowered in VALID_CONNECTION_METHODS:
        return lowered

    # Log unknown methods for monitoring but still return them
    logging.debug(f"Unknown connection method: {method}")
    return method


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
            self.trust = self.handle.get(
                actor_id=self.actor_id, peerid=self.peerid, token=self.token
            )
        return self.trust

    def delete(self) -> bool:
        """Delete the trust relationship"""
        if not self.handle:
            return False

        # If this is an OAuth2 client trust, delete the client (which also revokes tokens)
        if self.config and self._is_oauth2_client_trust():
            client_id = self._extract_client_id_from_peerid()
            if client_id:
                try:
                    # Delete the client registration and revoke tokens
                    # Pass the trust's actor_id to ensure tokens are revoked in the correct actor
                    # (the client registry lookup might return a different actor_id)
                    from .oauth2_server.client_registry import get_mcp_client_registry
                    registry = get_mcp_client_registry(self.config)
                    registry.delete_client(client_id, actor_id=self.actor_id)
                    logging.info(f"Deleted OAuth2 client {client_id} as part of trust deletion")
                except Exception as e:
                    logging.error(f"Error deleting OAuth2 client during trust deletion: {e}")
                    # Continue with trust deletion even if client deletion fails

        self.trust = {}
        return self.handle.delete()

    def _is_oauth2_client_trust(self) -> bool:
        """Check if this trust relationship is for an OAuth2 client."""
        if not self.trust or not isinstance(self.trust, dict):
            return False

        peerid = self.trust.get("peerid", "")
        established_via = self.trust.get("established_via", "")
        trust_type = self.trust.get("type", "")

        # Check if this is an OAuth2 client trust based on peer_id format or metadata
        return (
            str(peerid).startswith("oauth2_client:") or
            established_via == "oauth2_client" or
            trust_type in ("oauth2_client", "mcp_client")
        )

    def _extract_client_id_from_peerid(self) -> str | None:
        """Extract client_id from peer_id format: oauth2_client:email:client_id"""
        if not self.trust or not isinstance(self.trust, dict):
            return None

        peerid = self.trust.get("peerid", "")
        if not peerid or not isinstance(peerid, str):
            return None

        # Format: oauth2_client:email:client_id
        # Client ID is the last component
        if peerid.startswith("oauth2_client:"):
            parts = peerid.split(":")
            if len(parts) >= 3:
                client_id = parts[-1]  # Last part is the client_id
                if client_id.startswith("mcp_"):
                    return client_id

        return None

    def modify(
        self,
        baseuri: str | None = None,
        secret: str | None = None,
        desc: str | None = None,
        approved: bool | None = None,
        verified: bool | None = None,
        verification_token: str | None = None,
        peer_approved: bool | None = None,
        # New unified trust attributes
        peer_identifier: str | None = None,
        established_via: str | None = None,
        created_at: str | None = None,
        last_accessed: str | None = None,
        last_connected_via: str | None = None,
        # Client metadata for OAuth2 clients
        client_name: str | None = None,
        client_version: str | None = None,
        client_platform: str | None = None,
        oauth_client_id: str | None = None,
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
            # Pass through new unified trust attributes
            peer_identifier=peer_identifier,
            established_via=established_via,
            created_at=created_at,
            last_accessed=last_accessed,
            last_connected_via=last_connected_via,
            # Pass through client metadata
            client_name=client_name,
            client_version=client_version,
            client_platform=client_platform,
            oauth_client_id=oauth_client_id,
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
        peer_identifier: str | None = None,
        established_via: str | None = None,
        created_at: str | None = None,
        last_accessed: str | None = None,
        last_connected_via: str | None = None,
    ) -> bool:
        """Create a new trust relationship"""
        self.trust = {"baseuri": baseuri, "type": peer_type}
        if not relationship or len(relationship) == 0:
            self.trust["relationship"] = (
                self.config.default_relationship if self.config else ""
            )
        else:
            self.trust["relationship"] = relationship
        if not secret or len(secret) == 0:
            self.trust["secret"] = self.config.new_token() if self.config else ""
        else:
            self.trust["secret"] = secret
        # Be absolutely sure that the secret is not already used
        if self.config:
            testhandle = self.config.DbTrust.DbTrust()
            if testhandle.is_token_in_db(
                actor_id=self.actor_id, token=self.trust["secret"]
            ):
                logging.warning("Found a non-unique token where it should be unique")
                return False
        self.trust["approved"] = str(approved).lower()
        self.trust["peer_approved"] = str(peer_approved).lower()
        self.trust["verified"] = str(verified).lower()
        if verification_token:
            self.trust["verification_token"] = verification_token
        else:
            self.trust["verification_token"] = (
                self.config.new_token() if self.config else ""
            )
        self.trust["desc"] = desc or ""
        self.trust["id"] = self.actor_id or ""
        self.trust["peerid"] = self.peerid or ""
        if not self.trust.get("verification_token"):
            self.trust["verification_token"] = (
                self.config.new_token() if self.config else ""
            )
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
            peer_identifier=peer_identifier,
            established_via=established_via,
            created_at=created_at,
            last_accessed=last_accessed,
            last_connected_via=last_connected_via,
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
        # Initialize attributes before any early returns to avoid AttributeError
        self.actor_id = actor_id
        self.peerid = peerid
        self.token = token
        if not actor_id or len(actor_id) == 0:
            logging.debug("No actorid set in initialisation of trust")
            return
        if not peerid and not token:
            logging.debug(
                "Both peerid and token are not set in initialisation of trust. One must be set."
            )
            return
        if not token and (not peerid or len(peerid) == 0):
            logging.debug("No peerid set in initialisation of trust")
            return
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
        # Initialize attributes before any early returns to avoid AttributeError
        self.actor_id = actor_id
        self.trusts = None
        self.list = None
        if not actor_id:
            logging.debug("No actor_id in initialisation of trusts")
            return
        if self.config:
            self.list = self.config.DbTrust.DbTrustList()
        self.fetch()
