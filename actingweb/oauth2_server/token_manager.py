"""
ActingWeb Token Management for MCP clients.

This module manages ActingWeb tokens that are separate from Google OAuth2 tokens.
These tokens are issued to MCP clients and validated by MCP endpoints.
"""

import base64
import hashlib
import logging
import secrets
import time
from typing import Any

from .. import config as config_class
from ..constants import (
    ACCESS_TOKEN_INDEX_BUCKET,
    AUTH_CODE_INDEX_BUCKET,
    OAUTH2_SYSTEM_ACTOR,
    REFRESH_TOKEN_INDEX_BUCKET,
)

logger = logging.getLogger(__name__)


class ActingWebTokenManager:
    """
    Manages ActingWeb tokens for MCP authentication.

    These tokens are separate from Google OAuth2 tokens and are used specifically
    for MCP client authentication. They are stored per-actor and linked to
    the user's Google OAuth2 identity.
    """

    def __init__(self, config: config_class.Config):
        self.config = config
        # Use Attributes system for private storage instead of underscore properties
        self.tokens_bucket = "mcp_tokens"  # Private attribute bucket for tokens
        self.refresh_tokens_bucket = (
            "mcp_refresh_tokens"  # Private attribute bucket for refresh tokens
        )
        self.auth_codes_bucket = (
            "mcp_auth_codes"  # Private attribute bucket for auth codes
        )
        self.google_tokens_bucket = (
            "mcp_google_tokens"  # Private attribute bucket for Google tokens
        )
        self.token_prefix = "aw_"  # Prefix to distinguish from Google tokens
        self.default_expires_in = 3600  # 1 hour
        self.refresh_token_expires_in = 2592000  # 30 days

    def create_authorization_code(
        self,
        actor_id: str,
        client_id: str,
        google_token_data: dict[str, Any],
        user_email: str | None = None,
        trust_type: str | None = None,
        code_challenge: str | None = None,
        code_challenge_method: str | None = None,
    ) -> str:
        """
        Create a temporary authorization code for OAuth2 flow.

        Args:
            actor_id: The actor this code is for
            client_id: The MCP client requesting authorization
            google_token_data: Google OAuth2 token data from user auth

        Returns:
            Authorization code to return to MCP client
        """
        # Generate authorization code
        auth_code = f"ac_{secrets.token_urlsafe(32)}"

        # Store Google token data in private attributes
        google_token_key = f"google_token_{auth_code}"
        self._store_google_token_data(actor_id, google_token_key, google_token_data)

        # Store minimal authorization data (expires in 10 minutes)
        auth_data = {
            "code": auth_code,
            "actor_id": actor_id,
            "client_id": client_id,
            "google_token_key": google_token_key,  # Reference to stored Google data
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + 600,  # 10 minutes
            "used": False,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
        }
        if user_email:
            auth_data["user_email"] = user_email
        if trust_type:
            auth_data["trust_type"] = trust_type

        self._store_auth_code(actor_id, auth_code, auth_data)

        logger.debug(
            f"Created authorization code for client {client_id}, actor {actor_id}"
        )
        return auth_code

    def exchange_authorization_code(
        self,
        code: str,
        client_id: str,
        client_secret: str | None = None,
        code_verifier: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Exchange authorization code for ActingWeb access token.

        Args:
            code: Authorization code from authorize endpoint
            client_id: MCP client identifier
            client_secret: MCP client secret (for confidential clients)
            code_verifier: PKCE code verifier (for public clients using PKCE)

        Returns:
            Token response with ActingWeb access token or None if invalid
        """
        # Load and validate authorization code
        auth_data = self._load_auth_code(code)
        if not auth_data:
            logger.warning(f"Invalid authorization code: {code}")
            return None

        # Check if code has expired
        if int(time.time()) > auth_data["expires_at"]:
            logger.warning(f"Expired authorization code: {code}")
            # Clean up both auth code and Google token data
            if "google_token_key" in auth_data:
                self._remove_google_token_data(
                    auth_data["actor_id"], auth_data["google_token_key"]
                )
            self._remove_auth_code(code)
            return None

        # Check if code has been used
        if auth_data.get("used", False):
            logger.warning(f"Authorization code already used: {code}")
            # Clean up both auth code and Google token data
            if "google_token_key" in auth_data:
                self._remove_google_token_data(
                    auth_data["actor_id"], auth_data["google_token_key"]
                )
            self._remove_auth_code(code)
            return None

        # Validate client
        if auth_data["client_id"] != client_id:
            logger.warning(f"Client ID mismatch for code {code}")
            return None

        # PKCE validation
        stored_challenge = auth_data.get("code_challenge")
        stored_method = str(auth_data.get("code_challenge_method"))

        if stored_challenge:  # PKCE was used in authorization
            if not code_verifier:
                logger.warning(
                    f"PKCE code_verifier required but not provided for code {code}"
                )
                return None

            # Validate code_verifier against stored challenge
            if not self._validate_pkce(code_verifier, stored_challenge, stored_method):
                logger.warning(f"PKCE validation failed for code {code}")
                return None

        # Mark code as used
        auth_data["used"] = True
        self._store_auth_code(auth_data["actor_id"], code, auth_data)

        # Load Google token data
        google_token_data = self._load_google_token_data(
            auth_data["actor_id"], auth_data["google_token_key"]
        )
        if not google_token_data:
            logger.error(f"Failed to load Google token data for auth code {code}")
            self._remove_auth_code(code)
            return None

        # Create ActingWeb access token
        access_token = self._create_access_token(
            auth_data["actor_id"], client_id, google_token_data
        )

        # Create refresh token
        refresh_token = self._create_refresh_token(
            auth_data["actor_id"], client_id, access_token["token_id"]
        )

        # Clean up authorization code and Google token data
        self._remove_google_token_data(
            auth_data["actor_id"], auth_data["google_token_key"]
        )
        self._remove_auth_code(code)

        # Return token response
        # Prepare extra context for trust creation at token issuance
        user_email = auth_data.get("user_email")
        trust_type = auth_data.get("trust_type", "mcp_client")

        return {
            "access_token": access_token["token"],
            "token_type": "Bearer",
            "expires_in": access_token["expires_in"],
            "refresh_token": refresh_token["token"],
            "scope": "mcp",  # MCP scope
            "actor_id": auth_data["actor_id"],
            "email": user_email,
            "trust_type": trust_type,
        }

    def validate_access_token(
        self, token: str
    ) -> tuple[str, str, dict[str, Any]] | None:
        """
        Validate ActingWeb access token.

        Args:
            token: ActingWeb access token

        Returns:
            Tuple of (actor_id, client_id, token_data) or None if invalid
        """
        if not token.startswith(self.token_prefix):
            return None

        token_data = self._load_access_token(token)
        if not token_data:
            return None

        # Check if token has expired
        if int(time.time()) > token_data["expires_at"]:
            logger.debug(f"Access token expired: {token}")
            self._remove_access_token(token)
            return None

        return token_data["actor_id"], token_data["client_id"], token_data

    def refresh_access_token(
        self, refresh_token: str, client_id: str, client_secret: str | None = None
    ) -> dict[str, Any] | None:
        """
        Refresh ActingWeb access token using refresh token.

        Args:
            refresh_token: Refresh token
            client_id: MCP client identifier
            client_secret: Client secret (for confidential clients)

        Returns:
            New token response or None if invalid
        """
        refresh_data = self._load_refresh_token(refresh_token)
        if not refresh_data:
            logger.warning("Invalid refresh token")
            return None

        # Check if refresh token has expired
        if int(time.time()) > refresh_data["expires_at"]:
            logger.warning("Refresh token expired")
            self._remove_refresh_token(refresh_token)
            return None

        # Validate client
        if refresh_data["client_id"] != client_id:
            logger.warning("Client ID mismatch for refresh token")
            return None

        # Revoke old access token
        old_token_id = refresh_data.get("access_token_id")
        if old_token_id:
            self._revoke_access_token_by_id(old_token_id)

        # Create new access token without Google token data (refresh flow)
        access_token = self._create_access_token_from_refresh(
            refresh_data["actor_id"], client_id
        )

        # Update refresh token with new access token reference
        refresh_data["access_token_id"] = access_token["token_id"]
        refresh_data["updated_at"] = int(time.time())
        self._store_refresh_token(refresh_data["actor_id"], refresh_token, refresh_data)

        return {
            "access_token": access_token["token"],
            "token_type": "Bearer",
            "expires_in": access_token["expires_in"],
            "refresh_token": refresh_token,  # Same refresh token
            "scope": "mcp",
        }

    def revoke_token(self, token: str, token_type_hint: str | None = None) -> bool:
        """
        Revoke an access or refresh token.

        Args:
            token: Token to revoke
            token_type_hint: "access_token" or "refresh_token"

        Returns:
            True if token was revoked successfully
        """
        if token.startswith(self.token_prefix):
            # Access token
            token_data = self._load_access_token(token)
            if token_data:
                self._remove_access_token(token)
                # Also revoke associated refresh token
                token_id = token_data.get("token_id")
                if token_id:
                    self._revoke_refresh_tokens_for_access_token(token_id)
                return True
        else:
            # Might be refresh token
            refresh_data = self._load_refresh_token(token)
            if refresh_data:
                self._remove_refresh_token(token)
                # Also revoke associated access token
                access_token_id = refresh_data.get("access_token_id")
                if access_token_id:
                    self._revoke_access_token_by_id(access_token_id)
                return True

        return False

    def _create_access_token(
        self, actor_id: str, client_id: str, google_token_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create an ActingWeb access token."""
        token_id = secrets.token_hex(16)
        token = f"{self.token_prefix}{secrets.token_urlsafe(32)}"

        # Store Google token data in private attributes
        google_token_key = f"google_token_access_{token_id}"
        self._store_google_token_data(actor_id, google_token_key, google_token_data)

        token_data = {
            "token_id": token_id,
            "token": token,
            "actor_id": actor_id,
            "client_id": client_id,
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + self.default_expires_in,
            "expires_in": self.default_expires_in,
            "scope": "mcp",
            "google_token_key": google_token_key,  # Reference to stored Google data
        }

        self._store_access_token(actor_id, token, token_data)
        return token_data

    def _create_access_token_from_refresh(
        self, actor_id: str, client_id: str
    ) -> dict[str, Any]:
        """Create an ActingWeb access token from refresh token (no Google token data needed)."""
        token_id = secrets.token_hex(16)
        token = f"{self.token_prefix}{secrets.token_urlsafe(32)}"

        token_data = {
            "token_id": token_id,
            "token": token,
            "actor_id": actor_id,
            "client_id": client_id,
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + self.default_expires_in,
            "expires_in": self.default_expires_in,
            "scope": "mcp",
            # No Google token data needed for refresh flow
        }

        self._store_access_token(actor_id, token, token_data)
        return token_data

    def _create_refresh_token(
        self, actor_id: str, client_id: str, access_token_id: str
    ) -> dict[str, Any]:
        """Create an ActingWeb refresh token."""
        token = f"rt_{secrets.token_urlsafe(32)}"

        refresh_data = {
            "token": token,
            "actor_id": actor_id,
            "client_id": client_id,
            "access_token_id": access_token_id,
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + self.refresh_token_expires_in,
        }

        self._store_refresh_token(actor_id, token, refresh_data)
        return refresh_data

    def _store_auth_code(
        self, actor_id: str, code: str, auth_data: dict[str, Any]
    ) -> None:
        """Store authorization code in private attributes."""
        try:
            from .. import attribute

            # Store auth code in private attributes bucket
            auth_bucket = attribute.Attributes(
                actor_id=actor_id, bucket=self.auth_codes_bucket, config=self.config
            )
            auth_bucket.set_attr(name=code, data=auth_data)

            # Also store in global index for efficient lookup
            index_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=AUTH_CODE_INDEX_BUCKET,
                config=self.config,
            )
            index_bucket.set_attr(name=code, data=actor_id)

            logger.debug(f"Successfully stored auth code for actor {actor_id}")

        except Exception as e:
            logger.error(f"Error storing auth code for actor {actor_id}: {e}")
            import traceback

            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise

    def _load_auth_code(self, code: str) -> dict[str, Any] | None:
        """Load authorization code data."""
        # Search through actors for the code
        # This is a simplified implementation - in production you'd want indexing
        return self._search_auth_code_in_actors(code)

    def _search_auth_code_in_actors(self, code: str) -> dict[str, Any] | None:
        """Search for auth code across actors."""
        try:
            # Use the system actor to store a global index of auth codes
            from .. import attribute

            # Create a global index bucket for auth codes
            index_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=AUTH_CODE_INDEX_BUCKET,
                config=self.config,
            )

            # Look up which actor has this code
            found_actor_data = index_bucket.get_attr(name=code)
            if not found_actor_data or "data" not in found_actor_data:
                logger.debug(f"Auth code {code} not found in global index")
                return None

            found_actor_id = found_actor_data["data"]
            if not found_actor_id:
                logger.debug(f"Auth code {code} has no actor ID in global index")
                return None

            # Load the actual auth code data from private attributes
            auth_bucket = attribute.Attributes(
                actor_id=found_actor_id,
                bucket=self.auth_codes_bucket,
                config=self.config,
            )
            auth_attr = auth_bucket.get_attr(name=code)

            if not auth_attr or "data" not in auth_attr:
                logger.warning(
                    f"Auth code {code} found in index but not in actor {found_actor_id}"
                )
                # Clean up the stale index entry
                index_bucket.delete_attr(name=code)
                return None

            auth_data = auth_attr["data"]
            if isinstance(auth_data, dict):
                logger.debug(f"Found auth code {code} in actor {found_actor_id}")
                return auth_data
            else:
                logger.warning(f"Invalid auth code data format for {code}")
                return None

        except Exception as e:
            logger.error(f"Error searching for auth code {code}: {e}")
            return None

    def _remove_auth_code(self, code: str) -> None:
        """Remove authorization code."""
        try:
            # First find which actor has this code
            from .. import attribute

            index_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=AUTH_CODE_INDEX_BUCKET,
                config=self.config,
            )

            found_actor_data = index_bucket.get_attr(name=code)
            if found_actor_data and "data" in found_actor_data:
                found_actor_id = found_actor_data["data"]
                # Remove from private attributes
                auth_bucket = attribute.Attributes(
                    actor_id=found_actor_id,
                    bucket=self.auth_codes_bucket,
                    config=self.config,
                )
                auth_bucket.delete_attr(name=code)
                logger.debug(f"Removed auth code {code} from actor {found_actor_id}")

            # Remove from global index
            index_bucket.delete_attr(name=code)
            logger.debug(f"Removed auth code {code} from global index")

        except Exception as e:
            logger.error(f"Error removing auth code {code}: {e}")

    def _store_google_token_data(
        self, actor_id: str, token_key: str, google_token_data: dict[str, Any]
    ) -> None:
        """Store Google OAuth2 token data in private attributes."""
        try:
            from .. import attribute

            # Store Google token data in private attributes bucket
            google_bucket = attribute.Attributes(
                actor_id=actor_id, bucket=self.google_tokens_bucket, config=self.config
            )
            google_bucket.set_attr(name=token_key, data=google_token_data)
            logger.debug(
                f"Stored Google token data for actor {actor_id} with key {token_key}"
            )

        except Exception as e:
            logger.error(f"Error storing Google token data for actor {actor_id}: {e}")
            raise

    def _load_google_token_data(
        self, actor_id: str, token_key: str
    ) -> dict[str, Any] | None:
        """Load Google OAuth2 token data from private attributes."""
        try:
            from .. import attribute

            # Load Google token data from private attributes bucket
            google_bucket = attribute.Attributes(
                actor_id=actor_id, bucket=self.google_tokens_bucket, config=self.config
            )
            token_attr = google_bucket.get_attr(name=token_key)

            if not token_attr or "data" not in token_attr:
                logger.warning(f"Google token data not found for key {token_key}")
                return None

            token_data = token_attr["data"]
            return token_data if isinstance(token_data, dict) else None

        except Exception as e:
            logger.error(
                f"Error loading Google token data for actor {actor_id}, key {token_key}: {e}"
            )
            return None

    def _remove_google_token_data(self, actor_id: str, token_key: str) -> None:
        """Remove Google OAuth2 token data from private attributes."""
        try:
            from .. import attribute

            # Remove Google token data from private attributes bucket
            google_bucket = attribute.Attributes(
                actor_id=actor_id, bucket=self.google_tokens_bucket, config=self.config
            )
            google_bucket.delete_attr(name=token_key)
            logger.debug(
                f"Removed Google token data for actor {actor_id} with key {token_key}"
            )
        except Exception as e:
            logger.error(
                f"Error removing Google token data for actor {actor_id}, key {token_key}: {e}"
            )

    def _store_access_token(
        self, actor_id: str, token: str, token_data: dict[str, Any]
    ) -> None:
        """Store access token in private attributes."""
        try:
            from .. import attribute

            # Store access token in private attributes bucket
            tokens_bucket = attribute.Attributes(
                actor_id=actor_id, bucket=self.tokens_bucket, config=self.config
            )
            tokens_bucket.set_attr(name=token, data=token_data)

            # Also store in global index for efficient lookup
            index_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=ACCESS_TOKEN_INDEX_BUCKET,
                config=self.config,
            )
            index_bucket.set_attr(name=token, data=actor_id)

            logger.debug(f"Stored access token for actor {actor_id}")

        except Exception as e:
            logger.error(f"Error storing access token for actor {actor_id}: {e}")
            raise

    def _load_access_token(self, token: str) -> dict[str, Any] | None:
        """Load access token data."""
        # Search through actors for the token
        return self._search_token_in_actors(token)

    def _search_token_in_actors(self, token: str) -> dict[str, Any] | None:
        """Search for token across actors."""
        try:
            # Use the system actor to store a global index of access tokens
            from .. import attribute

            # Create a global index bucket for access tokens
            index_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=ACCESS_TOKEN_INDEX_BUCKET,
                config=self.config,
            )

            # Look up which actor has this token
            found_actor_data = index_bucket.get_attr(name=token)
            if not found_actor_data or "data" not in found_actor_data:
                logger.debug(f"Access token {token} not found in global index")
                return None

            found_actor_id = found_actor_data["data"]
            if not found_actor_id:
                logger.debug(f"Access token {token} has no actor ID in global index")
                return None

            # Load the actual token data from private attributes
            tokens_bucket = attribute.Attributes(
                actor_id=found_actor_id, bucket=self.tokens_bucket, config=self.config
            )
            token_attr = tokens_bucket.get_attr(name=token)

            if not token_attr or "data" not in token_attr:
                logger.warning(
                    f"Access token {token} found in index but not in actor {found_actor_id}"
                )
                # Clean up the stale index entry
                index_bucket.delete_attr(name=token)
                return None

            token_data = token_attr["data"]
            if isinstance(token_data, dict):
                logger.debug(f"Found access token {token} in actor {found_actor_id}")
                return token_data
            else:
                logger.warning(f"Invalid access token data format for {token}")
                return None

        except Exception as e:
            logger.error(f"Error searching for access token {token}: {e}")
            return None

    def _search_refresh_token_in_actors(self, token: str) -> dict[str, Any] | None:
        """Search for refresh token across actors."""
        try:
            # Use the system actor to store a global index of refresh tokens
            from .. import attribute

            # Create a global index bucket for refresh tokens
            index_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=REFRESH_TOKEN_INDEX_BUCKET,
                config=self.config,
            )

            # Look up which actor has this token
            found_actor_data = index_bucket.get_attr(name=token)
            if not found_actor_data or "data" not in found_actor_data:
                logger.debug(f"Refresh token {token} not found in global index")
                return None

            found_actor_id = found_actor_data["data"]
            if not found_actor_id:
                logger.debug(f"Refresh token {token} has no actor ID in global index")
                return None

            # Load the actual token data from private attributes
            refresh_bucket = attribute.Attributes(
                actor_id=found_actor_id,
                bucket=self.refresh_tokens_bucket,
                config=self.config,
            )
            token_attr = refresh_bucket.get_attr(name=token)

            if not token_attr or "data" not in token_attr:
                logger.warning(
                    f"Refresh token {token} found in index but not in actor {found_actor_id}"
                )
                # Clean up the stale index entry
                index_bucket.delete_attr(name=token)
                return None

            token_data = token_attr["data"]
            if isinstance(token_data, dict):
                logger.debug(f"Found refresh token {token} in actor {found_actor_id}")
                return token_data
            else:
                logger.warning(f"Invalid refresh token data format for {token}")
                return None

        except Exception as e:
            logger.error(f"Error searching for refresh token {token}: {e}")
            return None

    def _remove_access_token(self, token: str) -> None:
        """Remove access token."""
        try:
            # First load token data to get Google token key
            token_data = self._load_access_token(token)

            # First find which actor has this token
            from .. import attribute

            index_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=ACCESS_TOKEN_INDEX_BUCKET,
                config=self.config,
            )

            found_actor_data = index_bucket.get_attr(name=token)
            if found_actor_data and "data" in found_actor_data:
                found_actor_id = found_actor_data["data"]
                # Remove from private attributes
                tokens_bucket = attribute.Attributes(
                    actor_id=found_actor_id,
                    bucket=self.tokens_bucket,
                    config=self.config,
                )
                tokens_bucket.delete_attr(name=token)
                logger.debug(
                    f"Removed access token {token} from actor {found_actor_id}"
                )

                # Also remove associated Google token data
                if token_data and "google_token_key" in token_data:
                    self._remove_google_token_data(
                        found_actor_id, token_data["google_token_key"]
                    )

            # Remove from global index
            index_bucket.delete_attr(name=token)
            logger.debug(f"Removed access token {token} from global index")

        except Exception as e:
            logger.error(f"Error removing access token {token}: {e}")

    def _store_refresh_token(
        self, actor_id: str, token: str, refresh_data: dict[str, Any]
    ) -> None:
        """Store refresh token in private attributes."""
        try:
            from .. import attribute

            # Store refresh token in private attributes bucket
            refresh_bucket = attribute.Attributes(
                actor_id=actor_id, bucket=self.refresh_tokens_bucket, config=self.config
            )
            refresh_bucket.set_attr(name=token, data=refresh_data)

            # Also store in global index for efficient lookup
            index_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=REFRESH_TOKEN_INDEX_BUCKET,
                config=self.config,
            )
            index_bucket.set_attr(name=token, data=actor_id)

            logger.debug(f"Stored refresh token for actor {actor_id}")

        except Exception as e:
            logger.error(f"Error storing refresh token for actor {actor_id}: {e}")
            raise

    def _load_refresh_token(self, token: str) -> dict[str, Any] | None:
        """Load refresh token data."""
        # Search through actors for the token
        return self._search_refresh_token_in_actors(token)

    def _remove_refresh_token(self, token: str) -> None:
        """Remove refresh token."""
        try:
            # First find which actor has this token
            from .. import attribute

            index_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=REFRESH_TOKEN_INDEX_BUCKET,
                config=self.config,
            )

            found_actor_data = index_bucket.get_attr(name=token)
            if found_actor_data and "data" in found_actor_data:
                found_actor_id = found_actor_data["data"]
                # Remove from private attributes
                refresh_bucket = attribute.Attributes(
                    actor_id=found_actor_id,
                    bucket=self.refresh_tokens_bucket,
                    config=self.config,
                )
                refresh_bucket.delete_attr(name=token)
                logger.debug(
                    f"Removed refresh token {token} from actor {found_actor_id}"
                )

            # Remove from global index
            index_bucket.delete_attr(name=token)
            logger.debug(f"Removed refresh token {token} from global index")

        except Exception as e:
            logger.error(f"Error removing refresh token {token}: {e}")

    def _revoke_access_token_by_id(self, token_id: str) -> None:
        """Revoke access token by ID."""
        try:
            # Search through the access token index to find tokens with this ID
            from .. import attribute

            # We need to search through all access tokens to find the one with this token_id
            # This is inefficient but necessary given the current storage structure
            attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=ACCESS_TOKEN_INDEX_BUCKET,
                config=self.config,
            )

            # Get all tokens from the index (this could be optimized with a reverse index)
            # For now, we'll search through actors' tokens
            logger.debug(f"Attempting to revoke access token with ID: {token_id}")

            # Since we don't have a reverse index by token_id, we'll need to search
            # This is a limitation of the current design - in production you'd want a proper index
            logger.warning(
                f"Access token revocation by ID {token_id} requires full search - not implemented for efficiency"
            )

        except Exception as e:
            logger.error(f"Error revoking access token by ID {token_id}: {e}")

    def _revoke_refresh_tokens_for_access_token(self, token_id: str) -> None:
        """Revoke refresh tokens associated with access token."""
        try:
            # Search through refresh tokens to find ones referencing this access token ID

            logger.debug(
                f"Attempting to revoke refresh tokens for access token ID: {token_id}"
            )

            # Similar to _revoke_access_token_by_id, this requires searching through all refresh tokens
            # This is a limitation of the current design - in production you'd want proper indexing
            logger.warning(
                f"Refresh token revocation for access token ID {token_id} requires full search - not implemented for efficiency"
            )

        except Exception as e:
            logger.error(
                f"Error revoking refresh tokens for access token ID {token_id}: {e}"
            )

    def _validate_pkce(
        self, code_verifier: str, code_challenge: str, code_challenge_method: str
    ) -> bool:
        """
        Validate PKCE code_verifier against stored code_challenge.

        Args:
            code_verifier: The code verifier provided in token request
            code_challenge: The code challenge stored from authorization request
            code_challenge_method: The method used for the challenge (plain or S256)

        Returns:
            True if valid, False otherwise
        """
        try:
            # Basic format validation
            if not code_verifier or len(code_verifier) < 43 or len(code_verifier) > 128:
                logger.warning(
                    f"Invalid PKCE code_verifier length: {len(code_verifier) if code_verifier else 0}"
                )
                return False

            if not code_challenge or len(code_challenge) < 43:
                logger.warning(
                    f"Invalid PKCE code_challenge length: {len(code_challenge) if code_challenge else 0}"
                )
                return False

            # Validate based on method
            if code_challenge_method == "plain":
                return code_verifier == code_challenge
            elif code_challenge_method == "S256":
                # Create SHA256 hash of code_verifier and base64url encode it
                digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
                expected_challenge = (
                    base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
                )
                return expected_challenge == code_challenge
            else:
                logger.warning(
                    f"Unsupported PKCE challenge method: {code_challenge_method}"
                )
                return False
        except Exception as e:
            logger.error(f"Error validating PKCE: {e}")
            return False

    def create_access_token(
        self,
        actor_id: str,
        client_id: str,
        scope: str = "mcp",
        trust_type: str = "mcp_client",
        grant_type: str = "client_credentials",
    ) -> dict[str, Any] | None:
        """
        Create an access token for client credentials flow.

        Args:
            actor_id: The actor this token is for
            client_id: The client requesting the token
            scope: The requested scope
            trust_type: The trust relationship type
            grant_type: The grant type (client_credentials)

        Returns:
            Token response dictionary or None if failed
        """
        try:
            token_id = secrets.token_hex(16)
            token = f"{self.token_prefix}{secrets.token_urlsafe(32)}"
            current_time = int(time.time())

            token_data = {
                "token_id": token_id,
                "token": token,
                "actor_id": actor_id,
                "client_id": client_id,
                "scope": scope,
                "trust_type": trust_type,
                "grant_type": grant_type,
                "created_at": current_time,
                "expires_at": current_time + self.default_expires_in,
            }

            # Store token in actor's private attributes
            self._store_access_token(actor_id, token, token_data)

            # Return standard OAuth2 token response
            response = {
                "access_token": token,
                "token_type": "Bearer",
                "expires_in": self.default_expires_in,
                "scope": scope,
            }

            logger.info(
                f"Created access token for client credentials flow: {client_id} -> {actor_id}"
            )
            return response

        except Exception as e:
            logger.error(f"Error creating access token for client credentials: {e}")
            return None

    def revoke_client_tokens(self, actor_id: str, client_id: str) -> int:
        """
        Revoke all tokens (access and refresh) associated with a specific client.

        This ensures that when a client is deleted, all its tokens are immediately
        invalidated and cannot be used for further access.

        Args:
            actor_id: The actor the client belongs to
            client_id: The client identifier whose tokens should be revoked

        Returns:
            Number of tokens revoked (access + refresh tokens)
        """
        revoked_count = 0

        try:
            from .. import attribute

            # Revoke all access tokens for this client
            tokens_bucket = attribute.Attributes(
                actor_id=actor_id, bucket=self.tokens_bucket, config=self.config
            )
            access_tokens_data = tokens_bucket.get_bucket()

            if access_tokens_data:
                for token_name, token_attr in access_tokens_data.items():
                    if token_attr and "data" in token_attr:
                        token_data = token_attr["data"]
                        if isinstance(token_data, dict) and token_data.get("client_id") == client_id:
                            # Revoke this access token
                            self._remove_access_token(token_name)
                            revoked_count += 1
                            logger.debug(f"Revoked access token {token_name} for client {client_id}")

            # Revoke all refresh tokens for this client
            refresh_bucket = attribute.Attributes(
                actor_id=actor_id, bucket=self.refresh_tokens_bucket, config=self.config
            )
            refresh_tokens_data = refresh_bucket.get_bucket()

            if refresh_tokens_data:
                for token_name, token_attr in refresh_tokens_data.items():
                    if token_attr and "data" in token_attr:
                        token_data = token_attr["data"]
                        if isinstance(token_data, dict) and token_data.get("client_id") == client_id:
                            # Revoke this refresh token
                            self._remove_refresh_token(token_name)
                            revoked_count += 1
                            logger.debug(f"Revoked refresh token {token_name} for client {client_id}")

            if revoked_count > 0:
                logger.info(
                    f"Revoked {revoked_count} tokens for client {client_id} in actor {actor_id}"
                )
            else:
                logger.debug(f"No tokens found to revoke for client {client_id}")

        except Exception as e:
            logger.error(f"Error revoking tokens for client {client_id}: {e}")

        return revoked_count


# Global token manager
_token_manager: ActingWebTokenManager | None = None


def get_actingweb_token_manager(config: config_class.Config) -> ActingWebTokenManager:
    """Get or create the global ActingWeb token manager."""
    global _token_manager
    if _token_manager is None:
        _token_manager = ActingWebTokenManager(config)
    return _token_manager
