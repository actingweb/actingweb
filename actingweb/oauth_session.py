"""
OAuth2 session management for postponed actor creation.

This module provides temporary storage for OAuth2 tokens when email cannot be extracted
from the OAuth provider, allowing apps to prompt users for email before creating actors.
"""

import logging
import time
import secrets
from typing import Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from . import config as config_class
    from . import actor as actor_module

logger = logging.getLogger(__name__)

# Session storage (in-memory for now, apps can override with database-backed storage)
_oauth_sessions: Dict[str, Dict[str, Any]] = {}
_SESSION_TTL = 600  # 10 minutes


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
        token_data: Dict[str, Any],
        user_info: Dict[str, Any],
        state: str = "",
        provider: str = "google"
    ) -> str:
        """
        Store OAuth2 session data temporarily.

        Args:
            token_data: Token response from OAuth provider
            user_info: User information from OAuth provider
            state: OAuth state parameter
            provider: OAuth provider name (google, github, etc)

        Returns:
            Session ID for retrieving the data later
        """
        session_id = secrets.token_urlsafe(32)

        _oauth_sessions[session_id] = {
            "token_data": token_data,
            "user_info": user_info,
            "state": state,
            "provider": provider,
            "created_at": int(time.time()),
        }

        logger.debug(f"Stored OAuth session {session_id[:8]}... for provider {provider}")
        return session_id

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve OAuth2 session data.

        Args:
            session_id: Session ID returned by store_session()

        Returns:
            Session data or None if not found or expired
        """
        if not session_id:
            return None

        session = _oauth_sessions.get(session_id)
        if not session:
            logger.debug(f"OAuth session {session_id[:8]}... not found")
            return None

        # Check if session has expired
        created_at = session.get("created_at", 0)
        if int(time.time()) - created_at > _SESSION_TTL:
            logger.debug(f"OAuth session {session_id[:8]}... expired")
            del _oauth_sessions[session_id]
            return None

        return session

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
            user_info = session["user_info"]
            provider = session.get("provider", "google")

            # Validate email format
            if not email or "@" not in email:
                logger.error(f"Invalid email format: {email}")
                return None

            # Normalize email
            email = email.strip().lower()

            # Look up or create actor by email
            from . import actor as actor_module
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

            # Clean up session
            del _oauth_sessions[session_id]
            logger.info(f"Completed OAuth session for {email} -> actor {actor_instance.id}")

            return actor_instance

        except Exception as e:
            logger.error(f"Error completing OAuth session: {e}")
            return None

    def clear_expired_sessions(self) -> int:
        """
        Clear expired sessions from storage.

        Returns:
            Number of sessions cleared
        """
        current_time = int(time.time())
        expired = []

        for session_id, session in _oauth_sessions.items():
            created_at = session.get("created_at", 0)
            if current_time - created_at > _SESSION_TTL:
                expired.append(session_id)

        for session_id in expired:
            del _oauth_sessions[session_id]

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
