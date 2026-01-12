"""PostgreSQL implementation of trust database operations."""

import logging
from datetime import datetime
from typing import Any

from actingweb.db.postgresql.connection import get_connection
from actingweb.db.utils import ensure_timezone_aware_iso
from actingweb.trust import canonical_connection_method

logger = logging.getLogger(__name__)


def _parse_timestamp(value: str | datetime | None) -> datetime:
    """
    Parse timestamp value consistently, handling both string and datetime inputs.

    Args:
        value: String timestamp (ISO format) or datetime object

    Returns:
        datetime object

    Raises:
        ValueError: If string cannot be parsed as valid ISO timestamp
    """
    if value is None:
        raise ValueError("Timestamp value cannot be None")
    if isinstance(value, str):
        try:
            # Handle both 'Z' UTC suffix and timezone offset formats
            normalized = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized)
        except ValueError as e:
            raise ValueError(f"Invalid ISO timestamp format: {value}") from e
    elif isinstance(value, datetime):
        return value
    else:
        raise ValueError(f"Timestamp must be string or datetime, got {type(value)}")


class DbTrust:
    """
    DbTrust does all the db operations for trust objects.

    The actor_id must always be set.
    """

    handle: dict[str, Any] | None

    def __init__(self) -> None:
        """Initialize DbTrust (no auto-table creation, use migrations)."""
        self.handle = None

    def get(
        self,
        actor_id: str | None = None,
        peerid: str | None = None,
        token: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Retrieve trust from the database.

        Either peerid or token must be set.
        If peerid is set, token will be ignored.

        Args:
            actor_id: The actor ID
            peerid: The peer ID (takes precedence over token)
            token: The secret token (used if peerid not provided)

        Returns:
            Dict with trust data, or None if not found
        """
        if not actor_id:
            return None

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    if peerid:
                        # Query by actor_id and peerid (primary key)
                        cur.execute(
                            """
                            SELECT id, peerid, baseuri, type, relationship, secret, "desc",
                                   approved, peer_approved, verified, verification_token,
                                   peer_identifier, established_via, created_at, last_accessed,
                                   last_connected_via, client_name, client_version, client_platform,
                                   oauth_client_id
                            FROM trusts
                            WHERE id = %s AND peerid = %s
                            """,
                            (actor_id, peerid),
                        )
                    elif token:
                        # Query by actor_id and secret (using secret index)
                        cur.execute(
                            """
                            SELECT id, peerid, baseuri, type, relationship, secret, "desc",
                                   approved, peer_approved, verified, verification_token,
                                   peer_identifier, established_via, created_at, last_accessed,
                                   last_connected_via, client_name, client_version, client_platform,
                                   oauth_client_id
                            FROM trusts
                            WHERE id = %s AND secret = %s
                            LIMIT 1
                            """,
                            (actor_id, token),
                        )
                    else:
                        return None

                    row = cur.fetchone()

                    if not row:
                        return None

                    # Build result dict
                    result: dict[str, Any] = {
                        "id": row[0],
                        "peerid": row[1],
                        "baseuri": row[2],
                        "type": row[3],
                        "relationship": row[4],
                        "secret": row[5],
                        "desc": row[6],
                        "approved": row[7],
                        "peer_approved": row[8],
                        "verified": row[9],
                        "verification_token": row[10],
                    }

                    # Add unified trust attributes if they exist
                    if row[11]:  # peer_identifier
                        result["peer_identifier"] = row[11]
                    if row[12]:  # established_via
                        result["established_via"] = row[12]

                    created_at_iso = None
                    if row[13]:  # created_at
                        created_at_iso = ensure_timezone_aware_iso(row[13])
                        result["created_at"] = created_at_iso

                    if row[14]:  # last_accessed
                        last_accessed_iso = ensure_timezone_aware_iso(row[14])
                        result["last_accessed"] = last_accessed_iso
                        result["last_connected_at"] = last_accessed_iso
                    elif created_at_iso:
                        result["last_connected_at"] = created_at_iso

                    if row[15]:  # last_connected_via
                        result["last_connected_via"] = canonical_connection_method(
                            row[15]
                        )

                    # Add client metadata for OAuth2 clients if they exist
                    if row[16]:  # client_name
                        result["client_name"] = row[16]
                    if row[17]:  # client_version
                        result["client_version"] = row[17]
                    if row[18]:  # client_platform
                        result["client_platform"] = row[18]
                    if row[19]:  # oauth_client_id
                        result["oauth_client_id"] = row[19]

                    # Store handle for future operations
                    self.handle = result
                    return result

        except Exception as e:
            logger.error(f"Error retrieving trust {actor_id}/{peerid or token}: {e}")
            return None

    def create(
        self,
        actor_id: str | None = None,
        peerid: str | None = None,
        baseuri: str = "",
        peer_type: str = "",
        relationship: str = "",
        secret: str = "",
        approved: str = "",
        verified: bool = False,
        peer_approved: bool = False,
        verification_token: str = "",
        desc: str = "",
        # New unified trust attributes
        peer_identifier: str | None = None,
        established_via: str | None = None,
        created_at: str | datetime | None = None,
        last_accessed: str | datetime | None = None,
        last_connected_via: str | None = None,
        # Client metadata for OAuth2 clients
        client_name: str | None = None,
        client_version: str | None = None,
        client_platform: str | None = None,
        oauth_client_id: str | None = None,
    ) -> bool:
        """
        Create a new trust.

        Args:
            actor_id: The actor ID
            peerid: The peer ID
            baseuri: Base URI of the peer
            peer_type: Peer's ActingWeb type
            relationship: Trust type (e.g., "friend", "admin")
            secret: Secret token
            approved: Approval status
            verified: Verification status
            peer_approved: Peer approval status
            verification_token: Verification token
            desc: Description
            peer_identifier: Email, username, UUID
            established_via: How trust was established
            created_at: Creation timestamp
            last_accessed: Last access timestamp
            last_connected_via: Last connection method
            client_name: Client name for OAuth2
            client_version: Client version for OAuth2
            client_platform: Client platform for OAuth2
            oauth_client_id: OAuth2 client ID

        Returns:
            True on success, False on failure
        """
        if not actor_id or not peerid:
            return False

        # Always set created_at/last_accessed for new trusts
        now = datetime.utcnow()
        created_timestamp = created_at or now
        if isinstance(created_timestamp, str):
            created_timestamp = _parse_timestamp(created_timestamp)

        last_timestamp = last_accessed or created_timestamp
        if isinstance(last_timestamp, str):
            last_timestamp = _parse_timestamp(last_timestamp)

        # Normalize connection method
        normalized_last_connected_via = None
        if last_connected_via:
            normalized_last_connected_via = canonical_connection_method(
                last_connected_via
            )
        elif established_via:
            normalized_last_connected_via = canonical_connection_method(established_via)

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO trusts (
                            id, peerid, baseuri, type, relationship, secret, "desc",
                            approved, peer_approved, verified, verification_token,
                            peer_identifier, established_via, created_at, last_accessed,
                            last_connected_via, client_name, client_version, client_platform,
                            oauth_client_id
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        """,
                        (
                            actor_id,
                            peerid,
                            baseuri,
                            peer_type,
                            relationship,
                            secret,
                            desc,
                            approved,
                            peer_approved,
                            verified,
                            verification_token,
                            peer_identifier,
                            established_via,
                            created_timestamp,
                            last_timestamp,
                            normalized_last_connected_via,
                            client_name,
                            client_version,
                            client_platform,
                            oauth_client_id,
                        ),
                    )
                conn.commit()

            # Build handle
            self.handle = {
                "id": actor_id,
                "peerid": peerid,
                "baseuri": baseuri,
                "type": peer_type,
                "relationship": relationship,
                "secret": secret,
                "desc": desc,
                "approved": approved,
                "peer_approved": peer_approved,
                "verified": verified,
                "verification_token": verification_token,
            }

            # Add optional fields to handle
            if peer_identifier:
                self.handle["peer_identifier"] = peer_identifier
            if established_via:
                self.handle["established_via"] = established_via
            if created_timestamp:
                self.handle["created_at"] = created_timestamp.isoformat()
            if last_timestamp:
                self.handle["last_accessed"] = last_timestamp.isoformat()
                self.handle["last_connected_at"] = last_timestamp.isoformat()
            if normalized_last_connected_via:
                self.handle["last_connected_via"] = normalized_last_connected_via
            if client_name:
                self.handle["client_name"] = client_name
            if client_version:
                self.handle["client_version"] = client_version
            if client_platform:
                self.handle["client_platform"] = client_platform
            if oauth_client_id:
                self.handle["oauth_client_id"] = oauth_client_id

            return True

        except Exception as e:
            logger.error(f"Error creating trust {actor_id}/{peerid}: {e}")
            return False

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
        created_at: str | datetime | None = None,
        last_accessed: str | datetime | None = None,
        last_connected_via: str | None = None,
        # Client metadata for OAuth2 clients
        client_name: str | None = None,
        client_version: str | None = None,
        client_platform: str | None = None,
        oauth_client_id: str | None = None,
    ) -> bool:
        """
        Modify a trust.

        If bools are None, they will not be changed.

        Args:
            baseuri: New base URI
            secret: New secret
            desc: New description
            approved: New approval status
            verified: New verification status
            verification_token: New verification token
            peer_approved: New peer approval status
            peer_identifier: New peer identifier
            established_via: How trust was established
            created_at: Creation timestamp
            last_accessed: Last access timestamp
            last_connected_via: Last connection method
            client_name: Client name
            client_version: Client version
            client_platform: Client platform
            oauth_client_id: OAuth2 client ID

        Returns:
            True on success, False on failure
        """
        if not self.handle:
            logger.debug("Attempted modification of DbTrust without db handle")
            return False

        actor_id = self.handle.get("id")
        peerid = self.handle.get("peerid")

        if not actor_id or not peerid:
            logger.error("DbTrust handle missing id or peerid field")
            return False

        # Build update query dynamically
        updates = []
        params = []

        if baseuri and len(baseuri) > 0:
            updates.append("baseuri = %s")
            params.append(baseuri)
            self.handle["baseuri"] = baseuri

        if secret and len(secret) > 0:
            updates.append("secret = %s")
            params.append(secret)
            self.handle["secret"] = secret

        if desc and len(desc) > 0:
            updates.append('"desc" = %s')
            params.append(desc)
            self.handle["desc"] = desc

        if approved is not None:
            updates.append("approved = %s")
            params.append(approved)
            self.handle["approved"] = approved

        if verified is not None:
            updates.append("verified = %s")
            params.append(verified)
            self.handle["verified"] = verified

        if verification_token and len(verification_token) > 0:
            updates.append("verification_token = %s")
            params.append(verification_token)
            self.handle["verification_token"] = verification_token

        if peer_approved is not None:
            updates.append("peer_approved = %s")
            params.append(peer_approved)
            self.handle["peer_approved"] = peer_approved

        # Handle unified trust attributes
        if peer_identifier is not None:
            updates.append("peer_identifier = %s")
            params.append(peer_identifier)
            self.handle["peer_identifier"] = peer_identifier

        if established_via is not None:
            updates.append("established_via = %s")
            params.append(established_via)
            self.handle["established_via"] = established_via

        if created_at is not None:
            try:
                created_timestamp = _parse_timestamp(created_at)
                updates.append("created_at = %s")
                params.append(created_timestamp)
                self.handle["created_at"] = created_timestamp.isoformat()
            except ValueError as e:
                logger.warning(f"Invalid created_at timestamp: {e}")

        if last_accessed is not None:
            try:
                last_timestamp = _parse_timestamp(last_accessed)
                updates.append("last_accessed = %s")
                params.append(last_timestamp)
                self.handle["last_accessed"] = last_timestamp.isoformat()
                self.handle["last_connected_at"] = last_timestamp.isoformat()
            except ValueError as e:
                logger.warning(f"Invalid last_accessed timestamp: {e}")

        if last_connected_via is not None:
            normalized = canonical_connection_method(last_connected_via)
            updates.append("last_connected_via = %s")
            params.append(normalized)
            self.handle["last_connected_via"] = normalized

        # Handle client metadata
        if client_name is not None:
            updates.append("client_name = %s")
            params.append(client_name)
            self.handle["client_name"] = client_name

        if client_version is not None:
            updates.append("client_version = %s")
            params.append(client_version)
            self.handle["client_version"] = client_version

        if client_platform is not None:
            updates.append("client_platform = %s")
            params.append(client_platform)
            self.handle["client_platform"] = client_platform

        if oauth_client_id is not None:
            updates.append("oauth_client_id = %s")
            params.append(oauth_client_id)
            self.handle["oauth_client_id"] = oauth_client_id

        if not updates:
            return True  # Nothing to update

        # Add WHERE clause parameters
        params.extend([actor_id, peerid])

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        UPDATE trusts
                        SET {", ".join(updates)}
                        WHERE id = %s AND peerid = %s
                        """,
                        tuple(params),
                    )
                conn.commit()
            return True

        except Exception as e:
            logger.error(f"Error modifying trust {actor_id}/{peerid}: {e}")
            return False

    def delete(self) -> bool:
        """
        Delete trust using self.handle.

        Returns:
            True on success, False on failure
        """
        if not self.handle:
            return False

        actor_id = self.handle.get("id")
        peerid = self.handle.get("peerid")

        if not actor_id or not peerid:
            logger.error("DbTrust handle missing id or peerid field")
            return False

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM trusts
                        WHERE id = %s AND peerid = %s
                        """,
                        (actor_id, peerid),
                    )
                conn.commit()

            self.handle = None
            return True

        except Exception as e:
            logger.error(f"Error deleting trust {actor_id}/{peerid}: {e}")
            return False

    @staticmethod
    def is_token_in_db(actor_id: str | None = None, token: str | None = None) -> bool:
        """
        Check if token exists in database for actor.

        Args:
            actor_id: The actor ID
            token: The secret token to check

        Returns:
            True if token found, False otherwise
        """
        if not actor_id or not token:
            return False

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id
                        FROM trusts
                        WHERE id = %s AND secret = %s
                        LIMIT 1
                        """,
                        (actor_id, token),
                    )
                    row = cur.fetchone()
                    return row is not None

        except Exception as e:
            logger.error(f"Error checking token {actor_id}/{token}: {e}")
            return False


class DbTrustList:
    """
    DbTrustList does all the db operations for list of trust objects.

    The actor_id must always be set.
    """

    handle: Any | None
    actor_id: str | None
    trusts: list[dict[str, Any]] | None

    def __init__(self) -> None:
        """Initialize DbTrustList."""
        self.handle = None
        self.actor_id = None
        self.trusts = []

    def fetch(self, actor_id: str | None = None) -> list[dict[str, Any]] | list[Any]:
        """
        Retrieve all trusts for an actor.

        Args:
            actor_id: The actor ID

        Returns:
            List of trust dicts, or empty list if none found
        """
        if not actor_id:
            return []

        self.actor_id = actor_id
        self.trusts = []

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, peerid, baseuri, type, relationship, secret, "desc",
                               approved, peer_approved, verified, verification_token,
                               peer_identifier, established_via, created_at, last_accessed,
                               last_connected_via, client_name, client_version, client_platform,
                               oauth_client_id
                        FROM trusts
                        WHERE id = %s
                        ORDER BY peerid
                        """,
                        (actor_id,),
                    )
                    rows = cur.fetchall()

                    for row in rows:
                        result: dict[str, Any] = {
                            "id": row[0],
                            "peerid": row[1],
                            "baseuri": row[2],
                            "type": row[3],
                            "relationship": row[4],
                            "secret": row[5],
                            "desc": row[6],
                            "approved": row[7],
                            "peer_approved": row[8],
                            "verified": row[9],
                            "verification_token": row[10],
                        }

                        # Add unified trust attributes if they exist
                        if row[11]:  # peer_identifier
                            result["peer_identifier"] = row[11]
                        if row[12]:  # established_via
                            result["established_via"] = row[12]

                        created_at_iso = None
                        if row[13]:  # created_at
                            created_at_iso = ensure_timezone_aware_iso(row[13])
                            result["created_at"] = created_at_iso

                        if row[14]:  # last_accessed
                            last_accessed_iso = ensure_timezone_aware_iso(row[14])
                            result["last_accessed"] = last_accessed_iso
                            result["last_connected_at"] = last_accessed_iso
                        elif created_at_iso:
                            result["last_connected_at"] = created_at_iso

                        if row[15]:  # last_connected_via
                            result["last_connected_via"] = canonical_connection_method(
                                row[15]
                            )

                        # Add client metadata for OAuth2 clients if they exist
                        if row[16]:  # client_name
                            result["client_name"] = row[16]
                        if row[17]:  # client_version
                            result["client_version"] = row[17]
                        if row[18]:  # client_platform
                            result["client_platform"] = row[18]
                        if row[19]:  # oauth_client_id
                            result["oauth_client_id"] = row[19]

                        self.trusts.append(result)

                    return self.trusts

        except Exception as e:
            logger.error(f"Error fetching trusts for actor {actor_id}: {e}")
            return []

    def delete(self) -> bool:
        """
        Delete all trusts for the actor.

        Returns:
            True on success, False on failure
        """
        if not self.actor_id:
            return False

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM trusts
                        WHERE id = %s
                        """,
                        (self.actor_id,),
                    )
                conn.commit()

            self.handle = None
            return True

        except Exception as e:
            logger.error(f"Error deleting trusts for actor {self.actor_id}: {e}")
            return False
