import logging
import os
from datetime import datetime

from pynamodb.attributes import BooleanAttribute, UnicodeAttribute, UTCDateTimeAttribute
from pynamodb.indexes import AllProjection, GlobalSecondaryIndex
from pynamodb.models import Model

from actingweb.trust import canonical_connection_method

"""
    DbTrust handles all db operations for a trust
    Google datastore for google is used as a backend.
"""


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


class SecretIndex(GlobalSecondaryIndex):
    """
    Secondary index on trust
    """

    class Meta:
        index_name = "secret-index"
        read_capacity_units = 2
        write_capacity_units = 1
        projection = AllProjection()

    secret = UnicodeAttribute(hash_key=True)


class Trust(Model):
    """Data model for a trust relationship"""

    class Meta:  # type: ignore[misc]
        table_name = os.getenv("AWS_DB_PREFIX", "demo_actingweb") + "_trusts"
        read_capacity_units = 5
        write_capacity_units = 2
        region = os.getenv("AWS_DEFAULT_REGION", "us-west-1")
        host = os.getenv("AWS_DB_HOST", None)

    # Existing attributes
    id = UnicodeAttribute(hash_key=True)  # actor_id
    peerid = UnicodeAttribute(range_key=True)
    baseuri = UnicodeAttribute()
    type = UnicodeAttribute()  # peer's ActingWeb mini-application type (e.g., "urn:actingweb:example.com:banking")
    relationship = (
        UnicodeAttribute()
    )  # trust type (e.g., "friend", "admin", "partner") - defines permission level
    secret = UnicodeAttribute()
    desc = UnicodeAttribute()
    approved = BooleanAttribute()
    peer_approved = BooleanAttribute()
    verified = BooleanAttribute()
    verification_token = UnicodeAttribute()

    # New attributes for unified trust system
    peer_identifier = UnicodeAttribute(
        null=True
    )  # Email, username, UUID - service-specific identifier
    established_via = UnicodeAttribute(
        null=True
    )  # 'actingweb', 'oauth2_interactive', 'oauth2_client'
    created_at = UTCDateTimeAttribute(null=True)  # When trust was created
    last_accessed = UTCDateTimeAttribute(null=True)  # Last time trust was used
    last_connected_via = UnicodeAttribute(null=True)  # How the trust was last accessed

    # Client metadata for OAuth2 clients (MCP, etc.)
    client_name = UnicodeAttribute(
        null=True
    )  # Friendly name of the client (e.g., "ChatGPT", "Claude", "MCP Inspector")
    client_version = UnicodeAttribute(null=True)  # Version of the client software
    client_platform = UnicodeAttribute(null=True)  # Platform info from User-Agent
    oauth_client_id = UnicodeAttribute(
        null=True
    )  # Reference to OAuth2 client ID for credentials-based clients

    # Indexes
    secret_index = SecretIndex()


class DbTrust:
    """
    DbTrust does all the db operations for trust objects

    The  actor_id must always be set.
    """

    def get(self, actor_id=None, peerid=None, token=None):
        """Retrieves the trust from the database

        Either peerid or token must be set.
        If peerid is set, token will be ignored.
        """
        if not actor_id:
            return None
        try:
            if not self.handle and peerid:
                self.handle = Trust.get(actor_id, peerid, consistent_read=True)
            elif not self.handle and token:
                res = Trust.secret_index.query(token)
                for h in res:
                    if actor_id == h.id:
                        self.handle = h
                        break
        except Exception:  # PynamoDB DoesNotExist exception
            return None
        if not self.handle:
            return None
        t = self.handle
        result = {
            "id": t.id,
            "peerid": t.peerid,
            "baseuri": t.baseuri,
            "type": t.type,
            "relationship": t.relationship,
            "secret": t.secret,
            "desc": t.desc,
            "approved": t.approved,
            "peer_approved": t.peer_approved,
            "verified": t.verified,
            "verification_token": t.verification_token,
        }

        # Add new unified trust attributes if they exist
        if hasattr(t, "peer_identifier") and t.peer_identifier:
            result["peer_identifier"] = t.peer_identifier
        if hasattr(t, "established_via") and t.established_via:
            result["established_via"] = t.established_via
        created_at_iso = None
        if hasattr(t, "created_at") and t.created_at:
            created_at_iso = t.created_at.isoformat()
            result["created_at"] = created_at_iso
        if hasattr(t, "last_accessed") and t.last_accessed:
            last_accessed_iso = t.last_accessed.isoformat()
            result["last_accessed"] = last_accessed_iso
            result["last_connected_at"] = last_accessed_iso
        elif created_at_iso:
            result["last_connected_at"] = created_at_iso

        if hasattr(t, "last_connected_via") and t.last_connected_via:
            result["last_connected_via"] = canonical_connection_method(
                t.last_connected_via
            )

        # Add client metadata for OAuth2 clients if they exist
        if hasattr(t, "client_name") and t.client_name:
            result["client_name"] = t.client_name
        if hasattr(t, "client_version") and t.client_version:
            result["client_version"] = t.client_version
        if hasattr(t, "client_platform") and t.client_platform:
            result["client_platform"] = t.client_platform
        if hasattr(t, "oauth_client_id") and t.oauth_client_id:
            result["oauth_client_id"] = t.oauth_client_id

        return result

    def modify(
        self,
        baseuri=None,
        secret=None,
        desc=None,
        approved=None,
        verified=None,
        verification_token=None,
        peer_approved=None,
        # New unified trust attributes
        peer_identifier=None,
        established_via=None,
        created_at=None,
        last_accessed=None,
        last_connected_via=None,
        # Client metadata for OAuth2 clients
        client_name=None,
        client_version=None,
        client_platform=None,
        oauth_client_id=None,
    ):
        """Modify a trust

        If bools are none, they will not be changed.
        """
        if not self.handle:
            logging.debug("Attempted modification of DbTrust without db handle")
            return False
        if baseuri and len(baseuri) > 0:
            self.handle.baseuri = baseuri
        if secret and len(secret) > 0:
            self.handle.secret = secret
        if desc and len(desc) > 0:
            self.handle.desc = desc
        if approved is not None:
            self.handle.approved = approved
        if verified is not None:
            self.handle.verified = verified
        if verification_token and len(verification_token) > 0:
            self.handle.verification_token = verification_token
        if peer_approved is not None:
            self.handle.peer_approved = peer_approved

        # Handle new unified trust attributes
        if peer_identifier is not None:
            self.handle.peer_identifier = peer_identifier
        if established_via is not None:
            self.handle.established_via = established_via
        if created_at is not None:
            try:
                self.handle.created_at = _parse_timestamp(created_at)
            except ValueError as e:
                logging.warning(f"Invalid created_at timestamp: {e}")
                # Keep existing value if parsing fails
        if last_accessed is not None:
            try:
                self.handle.last_accessed = _parse_timestamp(last_accessed)
            except ValueError as e:
                logging.warning(f"Invalid last_accessed timestamp: {e}")
                # Keep existing value if parsing fails

        if last_connected_via is not None:
            self.handle.last_connected_via = canonical_connection_method(
                last_connected_via
            )

        # Handle client metadata for OAuth2 clients
        if client_name is not None:
            self.handle.client_name = client_name
        if client_version is not None:
            self.handle.client_version = client_version
        if client_platform is not None:
            self.handle.client_platform = client_platform
        if oauth_client_id is not None:
            self.handle.oauth_client_id = oauth_client_id

        self.handle.save()
        return True

    def create(
        self,
        actor_id=None,
        peerid=None,
        baseuri="",
        peer_type="",
        relationship="",
        secret="",
        approved="",
        verified=False,
        peer_approved=False,
        verification_token="",
        desc="",
        # New unified trust attributes
        peer_identifier=None,
        established_via=None,
        created_at=None,
        last_accessed=None,
        last_connected_via=None,
        # Client metadata for OAuth2 clients
        client_name=None,
        client_version=None,
        client_platform=None,
        oauth_client_id=None,
    ):
        """Create a new trust"""
        if not actor_id or not peerid:
            return False
        # Create trust with existing attributes
        trust_kwargs = {
            "id": actor_id,
            "peerid": peerid,
            "baseuri": baseuri,
            "type": peer_type,
            "relationship": relationship,
            "secret": secret,
            "approved": approved,
            "verified": verified,
            "peer_approved": peer_approved,
            "verification_token": verification_token,
            "desc": desc,
        }

        # Add new unified trust attributes if provided
        if peer_identifier is not None:
            trust_kwargs["peer_identifier"] = peer_identifier
        if established_via is not None:
            trust_kwargs["established_via"] = established_via

        if last_connected_via is not None:
            trust_kwargs["last_connected_via"] = canonical_connection_method(
                last_connected_via
            )

        # Add client metadata if provided
        if client_name is not None:
            trust_kwargs["client_name"] = client_name
        if client_version is not None:
            trust_kwargs["client_version"] = client_version
        if client_platform is not None:
            trust_kwargs["client_platform"] = client_platform
        if oauth_client_id is not None:
            trust_kwargs["oauth_client_id"] = oauth_client_id

        # Always set created_at/last_accessed for new trusts
        now = datetime.utcnow()
        created_timestamp = created_at or now
        if isinstance(created_timestamp, str):
            created_timestamp = datetime.fromisoformat(
                created_timestamp.replace("Z", "+00:00")
            )
        trust_kwargs["created_at"] = created_timestamp

        last_timestamp = last_accessed or created_timestamp
        if isinstance(last_timestamp, str):
            last_timestamp = datetime.fromisoformat(
                last_timestamp.replace("Z", "+00:00")
            )
        trust_kwargs["last_accessed"] = last_timestamp

        if "last_connected_via" not in trust_kwargs and established_via is not None:
            trust_kwargs["last_connected_via"] = canonical_connection_method(
                established_via
            )

        self.handle = Trust(**trust_kwargs)
        self.handle.save()
        return True

    def delete(self):
        """Deletes the property in the database"""
        if not self.handle:
            return False
        self.handle.delete()
        self.handle = None
        return True

    @staticmethod
    def is_token_in_db(actor_id=None, token=None):
        """Returns True if token is found in db"""
        if not actor_id or len(actor_id) == 0:
            return False
        if not token or len(token) == 0:
            return False
        for r in Trust.secret_index.query(token):
            if r.id != actor_id:
                continue
            else:
                return True
        return False

    def __init__(self):
        self.handle = None
        if not Trust.exists():
            Trust.create_table(wait=True)


class DbTrustList:
    """
    DbTrustList does all the db operations for list of trust objects

    The  actor_id must always be set.
    """

    def fetch(self, actor_id):
        """Retrieves the trusts of an actor_id from the database as an array"""
        if not actor_id:
            return None
        self.actor_id = actor_id
        self.handle = Trust.scan(Trust.id == self.actor_id, consistent_read=True)
        self.trusts = []
        if self.handle:
            for t in self.handle:
                result = {
                    "id": t.id,
                    "peerid": t.peerid,
                    "baseuri": t.baseuri,
                    "type": t.type,
                    "relationship": t.relationship,
                    "secret": t.secret,
                    "desc": t.desc,
                    "approved": t.approved,
                    "peer_approved": t.peer_approved,
                    "verified": t.verified,
                    "verification_token": t.verification_token,
                }

                # Add new unified trust attributes if they exist (same logic as get() method)
                if hasattr(t, "peer_identifier") and t.peer_identifier:
                    result["peer_identifier"] = t.peer_identifier
                if hasattr(t, "established_via"):
                    result["established_via"] = t.established_via
                created_at_iso = None
                if hasattr(t, "created_at") and t.created_at:
                    created_at_iso = t.created_at.isoformat()
                    result["created_at"] = created_at_iso
                if hasattr(t, "last_accessed") and t.last_accessed:
                    last_accessed_iso = t.last_accessed.isoformat()
                    result["last_accessed"] = last_accessed_iso
                    result["last_connected_at"] = last_accessed_iso
                elif created_at_iso:
                    result["last_connected_at"] = created_at_iso

                if hasattr(t, "last_connected_via") and t.last_connected_via:
                    result["last_connected_via"] = canonical_connection_method(
                        t.last_connected_via
                    )

                # Add client metadata for OAuth2 clients if they exist (same logic as get() method)
                if hasattr(t, "client_name") and t.client_name:
                    result["client_name"] = t.client_name
                if hasattr(t, "client_version") and t.client_version:
                    result["client_version"] = t.client_version
                if hasattr(t, "client_platform") and t.client_platform:
                    result["client_platform"] = t.client_platform
                if hasattr(t, "oauth_client_id") and t.oauth_client_id:
                    result["oauth_client_id"] = t.oauth_client_id

                self.trusts.append(result)
            return self.trusts
        else:
            return []

    def delete(self):
        """Deletes all the properties in the database"""
        self.handle = Trust.scan(Trust.id == self.actor_id, consistent_read=True)
        if not self.handle:
            return False
        for p in self.handle:
            p.delete()
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        self.actor_id = None
        self.trusts = []
        if not Trust.exists():
            Trust.create_table(wait=True)
