"""
OAuth2 State Parameter Management for ActingWeb.

This module handles encryption and decryption of OAuth2 state parameters
to preserve MCP client context through the Google OAuth2 flow while
providing CSRF protection.
"""

import base64
import json
import logging
import secrets
import time
from typing import Any

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None  # type: ignore[misc,assignment]
from .. import config as config_class

logger = logging.getLogger(__name__)


class OAuth2StateManager:
    """
    Manages OAuth2 state parameters with encryption and CSRF protection.

    The state parameter is used to:
    1. Prevent CSRF attacks
    2. Preserve MCP client context through Google OAuth2 flow
    3. Store temporary data needed to complete the MCP authorization
    """

    def __init__(self, config: config_class.Config):
        self.config = config
        self.state_lifetime = 600  # 10 minutes

        if Fernet is None:
            raise ImportError(
                "cryptography package is required for OAuth2 state management"
            )

        # Generate or retrieve encryption key
        self.encryption_key = self._get_or_create_encryption_key()
        self.cipher = Fernet(self.encryption_key)

    def create_state(self, mcp_context: dict[str, Any]) -> str:
        """
        Create encrypted state parameter with MCP context.

        Args:
            mcp_context: MCP client context to preserve through OAuth2 flow

        Returns:
            Encrypted state parameter string
        """
        # Create state data
        state_data = {
            "timestamp": int(time.time()),
            "csrf_token": secrets.token_hex(16),
            "mcp_context": mcp_context,
        }

        # Serialize and encrypt
        state_json = json.dumps(state_data)
        encrypted_state = self.cipher.encrypt(state_json.encode("utf-8"))

        # Base64 encode for URL safety
        state_param = base64.urlsafe_b64encode(encrypted_state).decode("utf-8")

        logger.debug(
            f"Created state parameter for MCP client {mcp_context.get('client_id', 'unknown')}"
        )
        return state_param

    def validate_and_extract_state(self, state_param: str) -> dict[str, Any] | None:
        """
        Validate and extract MCP context from state parameter.

        Args:
            state_param: Encrypted state parameter from OAuth2 callback

        Returns:
            MCP context dict or None if invalid/expired
        """
        try:
            # Base64 decode with padding fix
            # Add missing padding if needed
            state_bytes = state_param.encode("utf-8")
            missing_padding = len(state_bytes) % 4
            if missing_padding:
                state_bytes += b"=" * (4 - missing_padding)
            encrypted_state = base64.urlsafe_b64decode(state_bytes)

            # Decrypt
            state_json = self.cipher.decrypt(encrypted_state).decode("utf-8")
            state_data = json.loads(state_json)

            # Validate timestamp
            timestamp = state_data.get("timestamp", 0)
            if int(time.time()) - timestamp > self.state_lifetime:
                logger.warning("State parameter expired")
                return None

            # Extract MCP context
            mcp_context: dict[str, Any] = state_data.get("mcp_context", {})

            logger.debug(
                f"Validated state parameter for MCP client {mcp_context.get('client_id', 'unknown')}"
            )
            return mcp_context

        except Exception as e:
            logger.warning(f"Invalid state parameter: {e}")
            return None

    def create_mcp_state(
        self,
        client_id: str,
        original_state: str | None,
        redirect_uri: str,
        email_hint: str | None = None,
        trust_type: str | None = None,
        code_challenge: str | None = None,
        code_challenge_method: str | None = None,
    ) -> str:
        """
        Create state parameter for MCP OAuth2 flow with trust type selection.

        Args:
            client_id: MCP client identifier
            original_state: Original state from MCP client
            redirect_uri: MCP client redirect URI
            email_hint: Email hint for Google OAuth2
            trust_type: Trust relationship type to establish
            code_challenge: PKCE code challenge
            code_challenge_method: PKCE code challenge method

        Returns:
            Encrypted state parameter
        """
        mcp_context = {
            "client_id": client_id,
            "original_state": original_state,
            "redirect_uri": redirect_uri,
            "email_hint": email_hint,
            "trust_type": trust_type,  # Add trust type to context
            "flow_type": "mcp_oauth2",
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
        }

        return self.create_state(mcp_context)

    def extract_mcp_context(self, state_param: str) -> dict[str, Any] | None:
        """
        Extract MCP context from OAuth2 callback state.

        Args:
            state_param: State parameter from OAuth2 callback

        Returns:
            MCP context or None if invalid
        """
        logger.debug(
            f"Extracting MCP context from state: {state_param[:50]}... (truncated)"
        )
        state_data = self.validate_and_extract_state(state_param)
        logger.debug(f"Validated state data: {state_data}")
        if not state_data:
            logger.warning("State validation failed")
            return None

        # Validate this is an MCP flow
        flow_type = state_data.get("flow_type")
        logger.debug(f"Flow type from state: {flow_type}")
        if flow_type != "mcp_oauth2":
            logger.warning(
                f"State parameter is not for MCP OAuth2 flow, got: {flow_type}"
            )
            return None

        logger.debug("Successfully extracted MCP context")
        return state_data

    def _get_or_create_encryption_key(self) -> bytes:
        """
        Get or create encryption key for state parameters.

        Uses the OAuth2 system actor to store the key persistently
        in an attribute bucket.
        """
        # Try to get key from config or environment first (for backwards compatibility)
        if hasattr(self.config, "oauth2_state_encryption_key"):
            key_str = self.config.oauth2_state_encryption_key  # type: ignore[attr-defined]
            if key_str:
                try:
                    return base64.urlsafe_b64decode(key_str.encode("utf-8"))
                except Exception:
                    pass

        # Try to get key from OAuth2 system actor
        try:
            from .. import actor as actor_module
            from ..constants import OAUTH2_SYSTEM_ACTOR
            from .system_actor import ensure_oauth2_system_actor

            # Ensure the system actor exists
            ensure_oauth2_system_actor(self.config)

            # Load the system actor
            sys_actor = actor_module.Actor(OAUTH2_SYSTEM_ACTOR, config=self.config)

            # Try to get existing key from system actor properties
            try:
                key_str = getattr(
                    sys_actor.property, "oauth2_state_encryption_key", None
                )
                if key_str:
                    logger.debug(
                        "Retrieved OAuth2 state encryption key from system actor"
                    )
                    return base64.urlsafe_b64decode(key_str.encode("utf-8"))
            except Exception as e:
                logger.debug(f"Failed to retrieve existing encryption key: {e}")

            # Generate new key and store it
            if Fernet is None:
                raise ImportError("cryptography package is required")
            key: bytes = Fernet.generate_key()
            key_str = base64.urlsafe_b64encode(key).decode("utf-8")

            # Store key in system actor properties
            try:
                sys_actor.property.oauth2_state_encryption_key = key_str  # type: ignore[union-attr]
                logger.info(
                    "Generated and stored new OAuth2 state encryption key in system actor"
                )
                return key
            except Exception as e:
                logger.error(f"Failed to store encryption key in system actor: {e}")
                # Fall back to in-memory key with warning
                logger.warning(
                    "Using in-memory encryption key (not persistent across restarts)"
                )
                return key

        except Exception as e:
            logger.error(f"Error accessing OAuth2 system actor: {e}")
            # Fall back to generating a new key (not persistent)
            if Fernet is None:
                raise ImportError("cryptography package is required") from e
            key: bytes = Fernet.generate_key()
            logger.warning(
                "Generated new OAuth2 state encryption key (not persistent). "
                "Store this key persistently: %s",
                base64.urlsafe_b64encode(key).decode("utf-8"),
            )
            return key


# Global state manager
_state_manager: OAuth2StateManager | None = None


def get_oauth2_state_manager(config: config_class.Config) -> OAuth2StateManager:
    """Get or create the global OAuth2 state manager."""
    global _state_manager
    if _state_manager is None:
        _state_manager = OAuth2StateManager(config)
    return _state_manager
