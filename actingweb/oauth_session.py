"""
OAuth2 session management for postponed actor creation.

This module provides temporary storage for OAuth2 tokens when email cannot be extracted
from the OAuth provider, allowing apps to prompt users for email before creating actors.

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


class OAuth2SessionManager:
    """
    Manage temporary OAuth2 sessions when email is not available from provider.

    This allows the application to:
    1. Store OAuth tokens temporarily when email extraction fails
    2. Redirect user to email input form
    3. Complete actor creation once email is provided
    """

    def __init__(self, config: 'config_class.Config'):
        self.config = config

    def store_session(
        self,
        token_data: dict[str, Any],
        user_info: dict[str, Any],
        state: str = "",
        provider: str = "google",
        verified_emails: list[str] | None = None
    ) -> str:
        """
        Store OAuth2 session data temporarily in database.

        Args:
            token_data: Token response from OAuth provider
            user_info: User information from OAuth provider
            state: OAuth state parameter
            provider: OAuth provider name (google, github, etc)
            verified_emails: List of verified emails from provider (if available)

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

        # Store in attribute bucket for persistence across containers
        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=OAUTH_SESSION_BUCKET,
            config=self.config
        )
        bucket.set_attr(name=session_id, data=session_data)

        logger.debug(f"Stored OAuth session {session_id[:8]}... for provider {provider}")
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
            config=self.config
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

    def complete_session(self, session_id: str, email: str) -> Optional['actor_module.Actor']:
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
            logger.error(f"Cannot complete session {session_id[:8]}... - session not found or expired")
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
                actor_instance.store.oauth_token_expiry = str(int(time.time()) + expires_in) if expires_in else None
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
                config=self.config
            )
            bucket.delete_attr(name=session_id)

            logger.info(f"Completed OAuth session for {email} -> actor {actor_instance.id}")

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
            config=self.config
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


def get_oauth2_session_manager(config: 'config_class.Config') -> OAuth2SessionManager:
    """
    Factory function to get OAuth2SessionManager instance.

    Args:
        config: ActingWeb configuration

    Returns:
        OAuth2SessionManager instance
    """
    return OAuth2SessionManager(config)
