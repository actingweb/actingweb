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

# Token TTLs
_ACCESS_TOKEN_TTL = 3600  # 1 hour
_REFRESH_TOKEN_TTL = 86400 * 14  # 2 weeks

# Bucket names for token storage
_ACCESS_TOKEN_BUCKET = "spa_access_tokens"
_REFRESH_TOKEN_BUCKET = "spa_refresh_tokens"


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
            logger.debug(f"Stored {len(verified_emails)} verified emails in session")

        # Store PKCE verifier if provided (for SPA server-managed PKCE)
        if pkce_verifier:
            session_data["pkce_verifier"] = pkce_verifier
            logger.debug("Stored PKCE verifier in session")

        # Store in attribute bucket for persistence across containers
        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=OAUTH_SESSION_BUCKET,
            config=self.config,
        )
        bucket.set_attr(name=session_id, data=session_data)

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
        self, token: str, actor_id: str, identifier: str, ttl: int | None = None
    ) -> None:
        """
        Store an access token for SPA use.

        Args:
            token: The access token
            actor_id: Associated actor ID
            identifier: User identifier (email or provider ID)
            ttl: Time to live in seconds (default: 1 hour)
        """
        from . import attribute
        from .constants import OAUTH2_SYSTEM_ACTOR

        token_data = {
            "actor_id": actor_id,
            "identifier": identifier,
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + (ttl or _ACCESS_TOKEN_TTL),
        }

        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=_ACCESS_TOKEN_BUCKET,
            config=self.config,
        )
        bucket.set_attr(name=token, data=token_data)

        logger.debug(f"Stored access token for actor {actor_id}")

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
        self, actor_id: str, identifier: str | None = None, ttl: int | None = None
    ) -> str:
        """
        Create a new refresh token for an actor.

        Args:
            actor_id: The actor ID
            identifier: User identifier (email or provider ID)
            ttl: Time to live in seconds (default: 2 weeks)

        Returns:
            The new refresh token
        """
        from . import attribute
        from .constants import OAUTH2_SYSTEM_ACTOR

        refresh_token = secrets.token_urlsafe(48)

        token_data = {
            "actor_id": actor_id,
            "identifier": identifier or "",
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + (ttl or _REFRESH_TOKEN_TTL),
            "used": False,
        }

        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=_REFRESH_TOKEN_BUCKET,
            config=self.config,
        )
        bucket.set_attr(name=refresh_token, data=token_data)

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
            for token, token_attr in access_tokens.items():
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
            for token, token_attr in refresh_tokens.items():
                if token_attr and "data" in token_attr:
                    if token_attr["data"].get("actor_id") == actor_id:
                        refresh_bucket.delete_attr(name=token)
                        revoked += 1

        if revoked:
            logger.warning(f"Revoked {revoked} tokens for actor {actor_id}")

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


def get_oauth2_session_manager(config: "config_class.Config") -> OAuth2SessionManager:
    """
    Factory function to get OAuth2SessionManager instance.

    Args:
        config: ActingWeb configuration

    Returns:
        OAuth2SessionManager instance
    """
    return OAuth2SessionManager(config)
