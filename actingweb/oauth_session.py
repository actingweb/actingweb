"""
OAuth2 session management for postponed actor creation and SPA token management.

This module provides temporary storage for OAuth2 tokens when email cannot be extracted
from the OAuth provider, allowing apps to prompt users for email before creating actors.

It also provides token management for SPAs including:
- Access token storage and validation
- Refresh token storage with rotation support
- Token revocation

Sessions are stored in the database using ActingWeb's attribute bucket system for
persistence across multiple containers in distributed deployments.
"""

import logging
import secrets
import time
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from . import actor as actor_module
    from . import config as config_class

logger = logging.getLogger(__name__)

# Session TTL - 10 minutes
_SESSION_TTL = 600

# Bucket names for token storage
_ACCESS_TOKEN_BUCKET = "spa_access_tokens"
_REFRESH_TOKEN_BUCKET = "spa_refresh_tokens"

# Process-local throttle for the opportunistic expired-token purge. A fresh
# process (e.g. a serverless cold start) starts at 0.0 and purges on its first
# eligible call — the desired self-healing behaviour. See
# OAuth2SessionManager.maybe_purge_expired_tokens().
_last_purge_attempt: float = 0.0


class OAuth2SessionManager:
    """
    Manage temporary OAuth2 sessions when email is not available from provider.

    This allows the application to:
    1. Store OAuth tokens temporarily when email extraction fails
    2. Redirect user to email input form
    3. Complete actor creation once email is provided
    """

    def __init__(self, config: "config_class.Config"):
        self.config = config

    def store_session(
        self,
        token_data: dict[str, Any],
        user_info: dict[str, Any],
        state: str = "",
        provider: str = "google",
        verified_emails: list[str] | None = None,
        pkce_verifier: str | None = None,
    ) -> str:
        """
        Store OAuth2 session data temporarily in database.

        Args:
            token_data: Token response from OAuth provider
            user_info: User information from OAuth provider
            state: OAuth state parameter
            provider: OAuth provider name (google, github, etc)
            verified_emails: List of verified emails from provider (if available)
            pkce_verifier: PKCE code verifier for server-managed PKCE (SPA flows)

        Returns:
            Session ID for retrieving the data later
        """
        from . import attribute
        from .constants import OAUTH2_SYSTEM_ACTOR, OAUTH_SESSION_BUCKET

        session_id = secrets.token_urlsafe(32)

        session_data = {
            "token_data": token_data,
            "user_info": user_info,
            "state": state,
            "provider": provider,
            "created_at": int(time.time()),
        }

        # Store verified emails if provided
        if verified_emails:
            session_data["verified_emails"] = verified_emails
            logger.info(f"Stored {len(verified_emails)} verified emails in session")

        # Store PKCE verifier if provided (for SPA server-managed PKCE)
        if pkce_verifier:
            session_data["pkce_verifier"] = pkce_verifier
            logger.info("Stored PKCE verifier in session")

        # Store in attribute bucket for persistence across containers
        from .constants import OAUTH_SESSION_TTL

        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=OAUTH_SESSION_BUCKET,
            config=self.config,
        )
        bucket.set_attr(
            name=session_id, data=session_data, ttl_seconds=OAUTH_SESSION_TTL
        )

        logger.debug(
            f"Stored OAuth session {session_id[:8]}... for provider {provider}"
        )
        return session_id

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """
        Retrieve OAuth2 session data from database.

        Args:
            session_id: Session ID returned by store_session()

        Returns:
            Session data or None if not found or expired
        """
        from . import attribute
        from .constants import OAUTH2_SYSTEM_ACTOR, OAUTH_SESSION_BUCKET

        if not session_id:
            return None

        # Retrieve from attribute bucket
        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=OAUTH_SESSION_BUCKET,
            config=self.config,
        )
        session_attr = bucket.get_attr(name=session_id)

        if not session_attr or "data" not in session_attr:
            logger.debug(f"OAuth session {session_id[:8]}... not found")
            return None

        session = session_attr["data"]

        # Check if session has expired
        created_at = session.get("created_at", 0)
        if int(time.time()) - created_at > _SESSION_TTL:
            logger.debug(f"OAuth session {session_id[:8]}... expired")
            bucket.delete_attr(name=session_id)
            return None

        from typing import cast

        return cast(dict[str, Any], session)

    def complete_session(
        self, session_id: str, email: str
    ) -> Optional["actor_module.Actor"]:
        """
        Complete OAuth flow with provided email and create actor.

        Args:
            session_id: Session ID from store_session()
            email: User's email address

        Returns:
            Created or existing actor, or None if failed
        """
        session = self.get_session(session_id)
        if not session:
            logger.error(
                f"Cannot complete session {session_id[:8]}... - session not found or expired"
            )
            return None

        try:
            # Extract session data
            token_data = session["token_data"]
            session["user_info"]
            provider = session.get("provider", "google")

            # Validate email format
            if not email or "@" not in email:
                logger.error(f"Invalid email format: {email}")
                return None

            # Normalize email
            email = email.strip().lower()

            # Look up or create actor by email
            from .oauth2 import create_oauth2_authenticator

            authenticator = create_oauth2_authenticator(self.config, provider)
            actor_instance = authenticator.lookup_or_create_actor_by_email(email)

            if not actor_instance:
                logger.error(f"Failed to create actor for email {email}")
                return None

            # Store OAuth tokens in actor properties
            access_token = token_data.get("access_token", "")
            refresh_token = token_data.get("refresh_token")
            expires_in = token_data.get("expires_in", 3600)

            if actor_instance.store:
                actor_instance.store.oauth_token = access_token
                actor_instance.store.oauth_token_expiry = (
                    str(int(time.time()) + expires_in) if expires_in else None
                )
                if refresh_token:
                    actor_instance.store.oauth_refresh_token = refresh_token
                actor_instance.store.oauth_token_timestamp = str(int(time.time()))
                actor_instance.store.oauth_provider = provider

            # Clean up session from database
            from . import attribute
            from .constants import OAUTH2_SYSTEM_ACTOR, OAUTH_SESSION_BUCKET

            bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=OAUTH_SESSION_BUCKET,
                config=self.config,
            )
            bucket.delete_attr(name=session_id)

            logger.info(
                f"Completed OAuth session for {email} -> actor {actor_instance.id}"
            )

            return actor_instance

        except Exception as e:
            logger.error(f"Error completing OAuth session: {e}")
            return None

    def clear_expired_sessions(self) -> int:
        """
        Clear expired sessions from database storage.

        Returns:
            Number of sessions cleared
        """
        from . import attribute
        from .constants import OAUTH2_SYSTEM_ACTOR, OAUTH_SESSION_BUCKET

        current_time = int(time.time())
        expired = []

        # Get all sessions from the bucket
        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=OAUTH_SESSION_BUCKET,
            config=self.config,
        )
        bucket_data = bucket.get_bucket()

        if not bucket_data:
            return 0

        # Find expired sessions
        for session_id, session_attr in bucket_data.items():
            if session_attr and "data" in session_attr:
                session = session_attr["data"]
                created_at = session.get("created_at", 0)
                if current_time - created_at > _SESSION_TTL:
                    expired.append(session_id)

        # Delete expired sessions
        for session_id in expired:
            bucket.delete_attr(name=session_id)

        if expired:
            logger.debug(f"Cleared {len(expired)} expired OAuth sessions")

        return len(expired)

    # ========================================================================
    # SPA Token Management Methods
    # ========================================================================

    def store_access_token(
        self,
        token: str,
        actor_id: str,
        identifier: str,
        ttl: int | None = None,
        chain_id: str | None = None,
    ) -> None:
        """
        Store an access token for SPA use.

        Args:
            token: The access token
            actor_id: Associated actor ID
            identifier: User identifier (email or provider ID)
            ttl: Time to live in seconds (default: 1 hour)
            chain_id: Refresh-token family this access token was minted from (set
                on rotation). When the family is revoked on reuse detection,
                access tokens carrying the same ``chain_id`` are revoked with it,
                so a stolen access token cannot outlive the theft response by up
                to its full TTL. None for tokens not tied to a rotation chain
                (e.g. the initial login token), which simply self-expire.
        """
        from . import attribute
        from .constants import OAUTH2_SYSTEM_ACTOR, SPA_ACCESS_TOKEN_TTL

        effective_ttl = ttl or SPA_ACCESS_TOKEN_TTL

        token_data = {
            "actor_id": actor_id,
            "identifier": identifier,
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + effective_ttl,
            "chain_id": chain_id,
        }

        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=_ACCESS_TOKEN_BUCKET,
            config=self.config,
        )
        bucket.set_attr(name=token, data=token_data, ttl_seconds=effective_ttl)

        logger.info(f"Stored access token for actor {actor_id}")

    def validate_access_token(self, token: str) -> dict[str, Any] | None:
        """
        Validate an access token and return associated data.

        Args:
            token: The access token to validate

        Returns:
            Token data dict or None if invalid/expired
        """
        from . import attribute
        from .constants import OAUTH2_SYSTEM_ACTOR

        if not token:
            return None

        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=_ACCESS_TOKEN_BUCKET,
            config=self.config,
        )
        token_attr = bucket.get_attr(name=token)

        if not token_attr or "data" not in token_attr:
            return None

        token_data = token_attr["data"]
        expires_at = token_data.get("expires_at", 0)

        if int(time.time()) > expires_at:
            # Token expired, clean it up
            bucket.delete_attr(name=token)
            return None

        from typing import cast

        return cast(dict[str, Any], token_data)

    def revoke_access_token(self, token: str) -> bool:
        """
        Revoke an access token.

        Args:
            token: The access token to revoke

        Returns:
            True if token was found and revoked
        """
        from . import attribute
        from .constants import OAUTH2_SYSTEM_ACTOR

        if not token:
            return False

        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=_ACCESS_TOKEN_BUCKET,
            config=self.config,
        )

        try:
            bucket.delete_attr(name=token)
            logger.debug("Revoked access token")
            return True
        except Exception as e:
            logger.warning(f"Error revoking access token: {e}")
            return False

    def create_refresh_token(
        self,
        actor_id: str,
        identifier: str | None = None,
        ttl: int | None = None,
        chain_id: str | None = None,
    ) -> str:
        """
        Create a new refresh token for an actor.

        Args:
            actor_id: The actor ID
            identifier: User identifier (email or provider ID)
            ttl: Time to live in seconds (default: 2 weeks)
            chain_id: Refresh-token lineage/family identifier. When a token is
                created by rotating an existing one, pass the parent token's
                ``chain_id`` so the whole family can be revoked together if reuse
                is later detected (RFC 6819 token-family revocation). When None
                (initial login), a fresh chain is started so each device/session
                gets its own independent lineage and a theft response on one
                device never logs out the others.

        Returns:
            The new refresh token
        """
        from . import attribute
        from .constants import OAUTH2_SYSTEM_ACTOR, SPA_REFRESH_TOKEN_TTL

        effective_ttl = ttl or SPA_REFRESH_TOKEN_TTL
        refresh_token = secrets.token_urlsafe(48)

        token_data = {
            "actor_id": actor_id,
            "identifier": identifier or "",
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + effective_ttl,
            "used": False,
            "chain_id": chain_id or secrets.token_urlsafe(16),
        }

        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=_REFRESH_TOKEN_BUCKET,
            config=self.config,
        )
        bucket.set_attr(name=refresh_token, data=token_data, ttl_seconds=effective_ttl)

        logger.debug(f"Created refresh token for actor {actor_id}")
        return refresh_token

    def validate_refresh_token(self, token: str) -> dict[str, Any] | None:
        """
        Validate a refresh token and return associated data.

        Args:
            token: The refresh token to validate

        Returns:
            Token data dict or None if invalid/expired
        """
        from . import attribute
        from .constants import OAUTH2_SYSTEM_ACTOR

        if not token:
            return None

        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=_REFRESH_TOKEN_BUCKET,
            config=self.config,
        )
        token_attr = bucket.get_attr(name=token)

        if not token_attr or "data" not in token_attr:
            return None

        token_data = token_attr["data"]
        expires_at = token_data.get("expires_at", 0)

        if int(time.time()) > expires_at:
            # Token expired, clean it up
            bucket.delete_attr(name=token)
            return None

        from typing import cast

        return cast(dict[str, Any], token_data)

    def mark_refresh_token_used(self, token: str) -> bool:
        """
        Mark a refresh token as used (for rotation).

        This is part of refresh token rotation - each refresh token
        can only be used once. If a used token is presented again,
        it indicates potential token theft.

        Args:
            token: The refresh token to mark as used

        Returns:
            True if token was found and marked
        """
        from . import attribute
        from .constants import OAUTH2_SYSTEM_ACTOR

        if not token:
            return False

        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=_REFRESH_TOKEN_BUCKET,
            config=self.config,
        )
        token_attr = bucket.get_attr(name=token)

        if not token_attr or "data" not in token_attr:
            return False

        token_data = token_attr["data"]
        token_data["used"] = True
        token_data["used_at"] = int(time.time())

        bucket.set_attr(name=token, data=token_data)
        logger.debug("Marked refresh token as used")
        return True

    def try_mark_refresh_token_used(
        self, token: str
    ) -> tuple[bool, dict[str, Any] | None]:
        """
        Atomically check if refresh token is unused and mark it as used.

        This provides race-free token rotation using atomic compare-and-swap.
        Only the first concurrent request will succeed in marking the token.

        Args:
            token: The refresh token to mark as used

        Returns:
            Tuple of (success, token_data):
            - (True, token_data) if token was unused and successfully marked
            - (False, token_data) if token was already used (includes used_at timestamp)
            - (False, None) if token doesn't exist or is expired
        """
        from . import attribute
        from .constants import OAUTH2_SYSTEM_ACTOR

        if not token:
            return (False, None)

        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=_REFRESH_TOKEN_BUCKET,
            config=self.config,
        )
        token_attr = bucket.get_attr(name=token)

        if not token_attr or "data" not in token_attr:
            return (False, None)

        token_data = token_attr["data"]

        # Check if already used
        if token_data.get("used"):
            return (False, token_data)

        # Check expiration
        expires_at = token_data.get("expires_at", 0)
        if int(time.time()) > expires_at:
            # Token expired, clean it up
            bucket.delete_attr(name=token)
            return (False, None)

        # Atomically update: only succeed if current data has used=False (or no used field)
        old_data = token_data.copy()
        new_data = token_data.copy()
        new_data["used"] = True
        new_data["used_at"] = int(time.time())

        # Try atomic compare-and-swap
        success = bucket.conditional_update_attr(
            name=token, old_data=old_data, new_data=new_data
        )

        if success:
            logger.debug("Atomically marked refresh token as used")
            # Now that the token is consumed it only needs to survive long
            # enough for reuse/theft detection. Shrink its storage TTL from the
            # full refresh TTL to the (much shorter) reuse window so it is purged
            # promptly instead of lingering for two weeks. Best-effort: the
            # conditional update above already secured rotation; if this second
            # write loses a race the token simply keeps its original TTL (prior
            # behaviour). The compare-and-swap is the atomic gate — this rewrite
            # is the winner re-stamping its own row, so it cannot grant rotation
            # to a second caller.
            from .constants import SPA_REFRESH_TOKEN_REUSE_WINDOW

            try:
                bucket.set_attr(
                    name=token,
                    data=new_data,
                    ttl_seconds=SPA_REFRESH_TOKEN_REUSE_WINDOW,
                )
            except Exception as e:  # pragma: no cover - defensive
                logger.debug(f"Could not shorten used refresh token TTL: {e}")
            return (True, new_data)
        else:
            # Another request beat us to it - token is now used
            # Re-read to get current state with used_at timestamp
            # Create fresh bucket instance to bypass cache
            fresh_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=_REFRESH_TOKEN_BUCKET,
                config=self.config,
            )
            token_attr = fresh_bucket.get_attr(name=token)
            if token_attr and "data" in token_attr:
                return (False, token_attr["data"])
            return (False, None)

    def revoke_refresh_token(self, token: str) -> bool:
        """
        Revoke a refresh token.

        Args:
            token: The refresh token to revoke

        Returns:
            True if token was found and revoked
        """
        from . import attribute
        from .constants import OAUTH2_SYSTEM_ACTOR

        if not token:
            return False

        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=_REFRESH_TOKEN_BUCKET,
            config=self.config,
        )

        try:
            bucket.delete_attr(name=token)
            logger.debug("Revoked refresh token")
            return True
        except Exception as e:
            logger.warning(f"Error revoking refresh token: {e}")
            return False

    def revoke_all_tokens(self, actor_id: str) -> int:
        """
        Revoke all tokens for an actor (security measure).

        This should be called when potential token theft is detected
        (e.g., refresh token reuse).

        Args:
            actor_id: The actor ID to revoke tokens for

        Returns:
            Number of tokens revoked
        """
        from . import attribute
        from .constants import OAUTH2_SYSTEM_ACTOR

        revoked = 0

        # Revoke access tokens
        access_bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=_ACCESS_TOKEN_BUCKET,
            config=self.config,
        )
        access_tokens = access_bucket.get_bucket()
        if access_tokens:
            # Snapshot with list() — delete_attr mutates the bucket dict we're
            # iterating (it would raise "dictionary changed size during
            # iteration"). Mirrors cleanup_expired_tokens().
            for token, token_attr in list(access_tokens.items()):
                if token_attr and "data" in token_attr:
                    if token_attr["data"].get("actor_id") == actor_id:
                        access_bucket.delete_attr(name=token)
                        revoked += 1

        # Revoke refresh tokens
        refresh_bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=_REFRESH_TOKEN_BUCKET,
            config=self.config,
        )
        refresh_tokens = refresh_bucket.get_bucket()
        if refresh_tokens:
            # Same snapshot needed as the access-token loop above.
            for token, token_attr in list(refresh_tokens.items()):
                if token_attr and "data" in token_attr:
                    if token_attr["data"].get("actor_id") == actor_id:
                        refresh_bucket.delete_attr(name=token)
                        revoked += 1

        if revoked:
            logger.warning(f"Revoked {revoked} tokens for actor {actor_id}")

        return revoked

    def revoke_token_chain(self, actor_id: str, chain_id: str) -> int:
        """
        Revoke a single refresh-token family/lineage (security measure).

        Called when refresh-token reuse is detected on a rotating chain. Unlike
        :meth:`revoke_all_tokens`, this scopes the theft response to the affected
        lineage only: every refresh token sharing ``chain_id`` is deleted (the
        legitimate holder and the attacker both rotate from the same family, so
        both lose the chain and must re-authenticate), while the actor's *other*
        devices/sessions — which have their own ``chain_id`` — keep working.

        Access tokens minted from this chain (tagged with the same ``chain_id``
        at rotation) are revoked too, so a stolen access token cannot keep
        working for up to its full TTL after the theft response. Access tokens
        with no ``chain_id`` (e.g. the initial login token) are left to
        self-expire — they carry no linkage to scope on, and live at most one
        access-token TTL.

        Args:
            actor_id: The actor ID the chain belongs to
            chain_id: The refresh-token family identifier to revoke

        Returns:
            Number of tokens revoked (refresh + access)
        """
        from . import attribute
        from .constants import OAUTH2_SYSTEM_ACTOR

        if not chain_id:
            return 0

        revoked = 0
        for bucket_name in (_REFRESH_TOKEN_BUCKET, _ACCESS_TOKEN_BUCKET):
            bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=bucket_name,
                config=self.config,
            )
            tokens = bucket.get_bucket()
            if not tokens:
                continue
            # Snapshot with list() — delete_attr mutates the dict we iterate.
            for token, token_attr in list(tokens.items()):
                if token_attr and "data" in token_attr:
                    data = token_attr["data"]
                    if (
                        data.get("actor_id") == actor_id
                        and data.get("chain_id") == chain_id
                    ):
                        bucket.delete_attr(name=token)
                        revoked += 1

        if revoked:
            logger.warning(
                f"Revoked {revoked} token(s) in chain {chain_id[:8]}... "
                f"for actor {actor_id}"
            )

        return revoked

    def cleanup_expired_tokens(self) -> int:
        """
        Clean up expired access and refresh tokens.

        Returns:
            Number of tokens cleaned up
        """
        from . import attribute
        from .constants import OAUTH2_SYSTEM_ACTOR

        current_time = int(time.time())
        cleaned = 0

        # Clean access tokens
        access_bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=_ACCESS_TOKEN_BUCKET,
            config=self.config,
        )
        access_tokens = access_bucket.get_bucket()
        if access_tokens:
            for token, token_attr in list(access_tokens.items()):
                if token_attr and "data" in token_attr:
                    if current_time > token_attr["data"].get("expires_at", 0):
                        access_bucket.delete_attr(name=token)
                        cleaned += 1

        # Clean refresh tokens
        refresh_bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=_REFRESH_TOKEN_BUCKET,
            config=self.config,
        )
        refresh_tokens = refresh_bucket.get_bucket()
        if refresh_tokens:
            for token, token_attr in list(refresh_tokens.items()):
                if token_attr and "data" in token_attr:
                    if current_time > token_attr["data"].get("expires_at", 0):
                        refresh_bucket.delete_attr(name=token)
                        cleaned += 1

        if cleaned:
            logger.debug(f"Cleaned up {cleaned} expired tokens")

        return cleaned

    def purge_expired_tokens(self) -> int:
        """
        Efficiently delete TTL-expired SPA access and refresh tokens.

        Unlike :meth:`cleanup_expired_tokens` — which loads both token buckets in
        full and deletes item by item — this issues a single set-based delete per
        backend, scoped to the two SPA token buckets and driven by the stored
        ``ttl_timestamp``:

        - **PostgreSQL**: one indexed ``DELETE`` using the ``idx_attributes_ttl``
          partial index. O(expired rows), not O(all tokens).
        - **DynamoDB**: relies on the table's native TTL on ``ttl_timestamp``
          (which must be enabled on the attributes table); returns 0 here rather
          than running a full-table Scan.

        Intended to be invoked periodically by the application (e.g. a scheduled
        job / cron / Lambda), the same way the MCP OAuth2 server schedules its
        token cleanup. Combined with the shortened reuse-window TTL applied when
        a refresh token is rotated, this keeps the shared token bucket bounded.

        Returns:
            Number of token rows deleted (0 on DynamoDB, where native TTL applies)
        """
        from .db import get_attribute

        db = get_attribute(self.config)
        try:
            return db.delete_expired(
                buckets=[_ACCESS_TOKEN_BUCKET, _REFRESH_TOKEN_BUCKET]
            )
        except Exception as e:
            logger.warning(f"purge_expired_tokens failed: {e}")
            return 0

    def maybe_purge_expired_tokens(self) -> int:
        """
        Run :meth:`purge_expired_tokens` at most once per
        ``SPA_TOKEN_PURGE_INTERVAL`` per process.

        This is what makes expired-token cleanup self-contained: the token
        endpoint calls it on every request as a heartbeat, and a process-local
        throttle keeps the actual (cheap, indexed) delete to roughly once per
        interval per worker. The library therefore bounds token-table growth on
        its own — applications are not required to schedule a cron/Lambda.

        Concurrency is intentionally lock-free: if two threads in the same
        process race past the throttle, both run the delete, which is idempotent
        and cheap (it only removes already-expired rows). On DynamoDB the
        underlying purge is a no-op (native TTL handles expiry).

        Returns:
            Number of rows deleted (0 when throttled or on DynamoDB).
        """
        global _last_purge_attempt
        from .constants import SPA_TOKEN_PURGE_INTERVAL

        now = time.time()
        if now - _last_purge_attempt < SPA_TOKEN_PURGE_INTERVAL:
            return 0
        # Claim the slot before doing the work so concurrent callers in this
        # process skip rather than pile on.
        _last_purge_attempt = now
        return self.purge_expired_tokens()


def get_oauth2_session_manager(config: "config_class.Config") -> OAuth2SessionManager:
    """
    Factory function to get OAuth2SessionManager instance.

    Args:
        config: ActingWeb configuration

    Returns:
        OAuth2SessionManager instance
    """
    return OAuth2SessionManager(config)
