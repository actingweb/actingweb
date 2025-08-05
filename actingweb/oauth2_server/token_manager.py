"""
ActingWeb Token Management for MCP clients.

This module manages ActingWeb tokens that are separate from Google OAuth2 tokens.
These tokens are issued to MCP clients and validated by MCP endpoints.
"""

import json
import logging
import secrets
import time
from typing import Dict, Any, Optional, Tuple
from .. import actor as actor_module
from .. import config as config_class

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
        self.tokens_property = "_mcp_tokens"  # Actor property to store tokens
        self.auth_codes_property = "_mcp_auth_codes"  # Temporary auth codes
        self.token_prefix = "aw_"  # Prefix to distinguish from Google tokens
        self.default_expires_in = 3600  # 1 hour
        self.refresh_token_expires_in = 2592000  # 30 days

    def create_authorization_code(self, actor_id: str, client_id: str, google_token_data: Dict[str, Any]) -> str:
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

        # Store Google token data separately to avoid DynamoDB size limits
        google_token_key = f"_google_token_{auth_code}"
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
        }

        self._store_auth_code(actor_id, auth_code, auth_data)

        logger.info(f"Created authorization code for client {client_id}, actor {actor_id}")
        return auth_code

    def exchange_authorization_code(
        self, code: str, client_id: str, client_secret: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Exchange authorization code for ActingWeb access token.

        Args:
            code: Authorization code from authorize endpoint
            client_id: MCP client identifier
            client_secret: MCP client secret (for confidential clients)

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
                self._remove_google_token_data(auth_data["actor_id"], auth_data["google_token_key"])
            self._remove_auth_code(code)
            return None

        # Check if code has been used
        if auth_data.get("used", False):
            logger.warning(f"Authorization code already used: {code}")
            # Clean up both auth code and Google token data
            if "google_token_key" in auth_data:
                self._remove_google_token_data(auth_data["actor_id"], auth_data["google_token_key"])
            self._remove_auth_code(code)
            return None

        # Validate client
        if auth_data["client_id"] != client_id:
            logger.warning(f"Client ID mismatch for code {code}")
            return None

        # Mark code as used
        auth_data["used"] = True
        self._store_auth_code(auth_data["actor_id"], code, auth_data)

        # Load Google token data
        google_token_data = self._load_google_token_data(auth_data["actor_id"], auth_data["google_token_key"])
        if not google_token_data:
            logger.error(f"Failed to load Google token data for auth code {code}")
            self._remove_auth_code(code)
            return None

        # Create ActingWeb access token
        access_token = self._create_access_token(auth_data["actor_id"], client_id, google_token_data)

        # Create refresh token
        refresh_token = self._create_refresh_token(auth_data["actor_id"], client_id, access_token["token_id"])

        # Clean up authorization code and Google token data
        self._remove_google_token_data(auth_data["actor_id"], auth_data["google_token_key"])
        self._remove_auth_code(code)

        # Return token response
        return {
            "access_token": access_token["token"],
            "token_type": "Bearer",
            "expires_in": access_token["expires_in"],
            "refresh_token": refresh_token["token"],
            "scope": "mcp",  # MCP scope
        }

    def validate_access_token(self, token: str) -> Optional[Tuple[str, str, Dict[str, Any]]]:
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
        self, refresh_token: str, client_id: str, client_secret: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
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
            logger.warning(f"Invalid refresh token")
            return None

        # Check if refresh token has expired
        if int(time.time()) > refresh_data["expires_at"]:
            logger.warning(f"Refresh token expired")
            self._remove_refresh_token(refresh_token)
            return None

        # Validate client
        if refresh_data["client_id"] != client_id:
            logger.warning(f"Client ID mismatch for refresh token")
            return None

        # Revoke old access token
        old_token_id = refresh_data.get("access_token_id")
        if old_token_id:
            self._revoke_access_token_by_id(old_token_id)

        # Get Google token data for new access token
        google_token_data = refresh_data.get("google_token_data", {})

        # Create new access token
        access_token = self._create_access_token(refresh_data["actor_id"], client_id, google_token_data)

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

    def revoke_token(self, token: str, token_type_hint: Optional[str] = None) -> bool:
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

    def _create_access_token(self, actor_id: str, client_id: str, google_token_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create an ActingWeb access token."""
        token_id = secrets.token_hex(16)
        token = f"{self.token_prefix}{secrets.token_urlsafe(32)}"

        # Store Google token data separately to avoid size limits
        google_token_key = f"_google_token_access_{token_id}"
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

    def _create_refresh_token(self, actor_id: str, client_id: str, access_token_id: str) -> Dict[str, Any]:
        """Create a refresh token."""
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

    def _store_auth_code(self, actor_id: str, code: str, auth_data: Dict[str, Any]) -> None:
        """Store authorization code as individual property."""
        try:
            actor_obj = actor_module.Actor(actor_id, self.config)

            # Load the actor data and ensure it exists
            actor_data = actor_obj.get(actor_id)
            if not actor_data or len(actor_data) == 0:
                logger.error(f"Actor {actor_id} does not exist or has no data")
                raise RuntimeError(f"Actor {actor_id} not found")

            if not actor_obj.property:
                logger.error(f"Actor {actor_id} does not have property object initialized")
                raise RuntimeError(f"Actor {actor_id} has no property object")

            # Store each auth code as its own property to avoid size limits
            auth_code_property = f"{self.auth_codes_property}_{code}"
            actor_obj.property[auth_code_property] = json.dumps(auth_data)

            # Also store in global index for efficient lookup
            from .. import attribute

            index_bucket = attribute.Attributes(actor_id="_mcp_system", bucket="auth_code_index", config=self.config)
            index_bucket.set_attr(name=code, data=actor_id)

            logger.info(f"Successfully stored auth code for actor {actor_id}")

        except Exception as e:
            logger.error(f"Error storing auth code for actor {actor_id}: {e}")
            import traceback

            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise

    def _load_auth_code(self, code: str) -> Optional[Dict[str, Any]]:
        """Load authorization code data."""
        # Search through actors for the code
        # This is a simplified implementation - in production you'd want indexing
        return self._search_auth_code_in_actors(code)

    def _search_auth_code_in_actors(self, code: str) -> Optional[Dict[str, Any]]:
        """Search for auth code across actors."""
        try:
            # Use the system actor to store a global index of auth codes
            from .. import attribute

            # Create a global index bucket for auth codes
            index_bucket = attribute.Attributes(actor_id="_mcp_system", bucket="auth_code_index", config=self.config)

            # Look up which actor has this code
            found_actor_data = index_bucket.get_attr(name=code)
            if not found_actor_data or "data" not in found_actor_data:
                logger.debug(f"Auth code {code} not found in global index")
                return None
                
            found_actor_id = found_actor_data["data"]
            if not found_actor_id:
                logger.debug(f"Auth code {code} has no actor ID in global index")
                return None

            # Load the actual auth code data from the actor
            actor_obj = actor_module.Actor(found_actor_id, self.config)
            actor_data = actor_obj.get(found_actor_id)
            if not actor_data or not actor_obj.property:
                logger.error(f"Actor {found_actor_id} not found or has no properties")
                return None

            # Get the specific auth code property
            auth_code_property = f"{self.auth_codes_property}_{code}"
            auth_code_json = actor_obj.property[auth_code_property] if actor_obj.property else None
            
            if auth_code_json is None:
                logger.warning(f"Auth code {code} found in index but not in actor {found_actor_id}")
                # Clean up the stale index entry
                index_bucket.delete_attr(name=code)
                return None

            auth_data = json.loads(auth_code_json)
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

            index_bucket = attribute.Attributes(actor_id="_mcp_system", bucket="auth_code_index", config=self.config)

            found_actor_data = index_bucket.get_attr(name=code)
            if found_actor_data and "data" in found_actor_data:
                found_actor_id = found_actor_data["data"]
                # Remove from actor properties
                actor_obj = actor_module.Actor(found_actor_id, self.config)
                actor_data = actor_obj.get(found_actor_id)
                if actor_data and actor_obj.property:
                    # Remove the specific auth code property
                    auth_code_property = f"{self.auth_codes_property}_{code}"
                    actor_obj.property[auth_code_property] = None  # Delete the property
                    logger.debug(f"Removed auth code {code} from actor {found_actor_id}")

            # Remove from global index
            index_bucket.delete_attr(name=code)
            logger.debug(f"Removed auth code {code} from global index")

        except Exception as e:
            logger.error(f"Error removing auth code {code}: {e}")

    def _store_google_token_data(self, actor_id: str, token_key: str, google_token_data: Dict[str, Any]) -> None:
        """Store Google OAuth2 token data separately to avoid size limits."""
        try:
            actor_obj = actor_module.Actor(actor_id, self.config)
            actor_data = actor_obj.get(actor_id)
            if not actor_data or not actor_obj.property:
                logger.error(f"Actor {actor_id} not found or has no properties")
                raise RuntimeError(f"Actor {actor_id} not found")
            
            # Store Google token data directly as a property
            actor_obj.property[token_key] = json.dumps(google_token_data)
            logger.debug(f"Stored Google token data for actor {actor_id} with key {token_key}")
            
        except Exception as e:
            logger.error(f"Error storing Google token data for actor {actor_id}: {e}")
            raise
    
    def _load_google_token_data(self, actor_id: str, token_key: str) -> Optional[Dict[str, Any]]:
        """Load Google OAuth2 token data."""
        try:
            actor_obj = actor_module.Actor(actor_id, self.config)
            actor_data = actor_obj.get(actor_id)
            if not actor_data or not actor_obj.property:
                logger.error(f"Actor {actor_id} not found or has no properties")
                return None
            
            # Load Google token data from property
            token_json = actor_obj.property[token_key] if actor_obj.property else None
            if token_json is None:
                logger.warning(f"Google token data not found for key {token_key}")
                return None
            
            parsed_data = json.loads(token_json)
            return parsed_data if isinstance(parsed_data, dict) else None
            
        except Exception as e:
            logger.error(f"Error loading Google token data for actor {actor_id}, key {token_key}: {e}")
            return None
    
    def _remove_google_token_data(self, actor_id: str, token_key: str) -> None:
        """Remove Google OAuth2 token data."""
        try:
            actor_obj = actor_module.Actor(actor_id, self.config)
            actor_data = actor_obj.get(actor_id)
            if actor_data and actor_obj.property:
                actor_obj.property[token_key] = None  # Delete the property
                logger.debug(f"Removed Google token data for actor {actor_id} with key {token_key}")
        except Exception as e:
            logger.error(f"Error removing Google token data for actor {actor_id}, key {token_key}: {e}")

    def _store_access_token(self, actor_id: str, token: str, token_data: Dict[str, Any]) -> None:
        """Store access token as individual property."""
        try:
            actor_obj = actor_module.Actor(actor_id, self.config)
            actor_data = actor_obj.get(actor_id)
            if not actor_data or not actor_obj.property:
                logger.error(f"Actor {actor_id} not found or has no properties")
                raise RuntimeError(f"Actor {actor_id} not found")

            # Store each access token as its own property to avoid size limits
            token_property = f"{self.tokens_property}_{token}"
            actor_obj.property[token_property] = json.dumps(token_data)
            
            # Also store in global index for efficient lookup
            from .. import attribute
            index_bucket = attribute.Attributes(
                actor_id="_mcp_system", 
                bucket="access_token_index", 
                config=self.config
            )
            index_bucket.set_attr(name=token, data=actor_id)
            
            logger.debug(f"Stored access token for actor {actor_id}")

        except Exception as e:
            logger.error(f"Error storing access token for actor {actor_id}: {e}")
            raise

    def _load_access_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Load access token data."""
        # Search through actors for the token
        return self._search_token_in_actors(token)

    def _search_token_in_actors(self, token: str) -> Optional[Dict[str, Any]]:
        """Search for token across actors."""
        try:
            # Use the system actor to store a global index of access tokens
            from .. import attribute
            
            # Create a global index bucket for access tokens
            index_bucket = attribute.Attributes(
                actor_id="_mcp_system", 
                bucket="access_token_index", 
                config=self.config
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

            # Load the actual token data from the actor
            actor_obj = actor_module.Actor(found_actor_id, self.config)
            actor_data = actor_obj.get(found_actor_id)
            if not actor_data or not actor_obj.property:
                logger.error(f"Actor {found_actor_id} not found or has no properties")
                return None

            # Get the specific token property
            token_property = f"{self.tokens_property}_{token}"
            token_json = actor_obj.property[token_property] if actor_obj.property else None
            
            if token_json is None:
                logger.warning(f"Access token {token} found in index but not in actor {found_actor_id}")
                # Clean up the stale index entry
                index_bucket.delete_attr(name=token)
                return None

            token_data = json.loads(token_json)
            if isinstance(token_data, dict):
                logger.debug(f"Found access token {token} in actor {found_actor_id}")
                return token_data
            else:
                logger.warning(f"Invalid access token data format for {token}")
                return None

        except Exception as e:
            logger.error(f"Error searching for access token {token}: {e}")
            return None

    def _remove_access_token(self, token: str) -> None:
        """Remove access token."""
        try:
            # First load token data to get Google token key
            token_data = self._load_access_token(token)
            
            # First find which actor has this token
            from .. import attribute
            
            index_bucket = attribute.Attributes(
                actor_id="_mcp_system", 
                bucket="access_token_index", 
                config=self.config
            )
            
            found_actor_data = index_bucket.get_attr(name=token)
            if found_actor_data and "data" in found_actor_data:
                found_actor_id = found_actor_data["data"]
                # Remove from actor properties
                actor_obj = actor_module.Actor(found_actor_id, self.config)
                actor_data = actor_obj.get(found_actor_id)
                if actor_data and actor_obj.property:
                    # Remove the specific token property
                    token_property = f"{self.tokens_property}_{token}"
                    actor_obj.property[token_property] = None  # Delete the property
                    logger.debug(f"Removed access token {token} from actor {found_actor_id}")
                    
                    # Also remove associated Google token data
                    if token_data and "google_token_key" in token_data:
                        self._remove_google_token_data(found_actor_id, token_data["google_token_key"])
            
            # Remove from global index
            index_bucket.delete_attr(name=token)
            logger.debug(f"Removed access token {token} from global index")
            
        except Exception as e:
            logger.error(f"Error removing access token {token}: {e}")

    def _store_refresh_token(self, actor_id: str, token: str, refresh_data: Dict[str, Any]) -> None:
        """Store refresh token."""
        # Similar to access token storage
        pass  # Placeholder

    def _load_refresh_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Load refresh token data."""
        return None  # Placeholder

    def _remove_refresh_token(self, token: str) -> None:
        """Remove refresh token."""
        pass  # Placeholder

    def _revoke_access_token_by_id(self, token_id: str) -> None:
        """Revoke access token by ID."""
        pass  # Placeholder

    def _revoke_refresh_tokens_for_access_token(self, token_id: str) -> None:
        """Revoke refresh tokens associated with access token."""
        pass  # Placeholder


# Global token manager
_token_manager: Optional[ActingWebTokenManager] = None


def get_actingweb_token_manager(config: config_class.Config) -> ActingWebTokenManager:
    """Get or create the global ActingWeb token manager."""
    global _token_manager
    if _token_manager is None:
        _token_manager = ActingWebTokenManager(config)
    return _token_manager
