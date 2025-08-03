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
from typing import Dict, Any, Optional

try:
    from cryptography.fernet import Fernet  # type: ignore[import-not-found]
except ImportError:
    Fernet = None
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
            raise ImportError("cryptography package is required for OAuth2 state management")

        # Generate or retrieve encryption key
        self.encryption_key = self._get_or_create_encryption_key()
        self.cipher = Fernet(self.encryption_key)

    def create_state(self, mcp_context: Dict[str, Any]) -> str:
        """
        Create encrypted state parameter with MCP context.

        Args:
            mcp_context: MCP client context to preserve through OAuth2 flow

        Returns:
            Encrypted state parameter string
        """
        # Create state data
        state_data = {"timestamp": int(time.time()), "csrf_token": secrets.token_hex(16), "mcp_context": mcp_context}

        # Serialize and encrypt
        state_json = json.dumps(state_data)
        encrypted_state = self.cipher.encrypt(state_json.encode("utf-8"))

        # Base64 encode for URL safety
        state_param = base64.urlsafe_b64encode(encrypted_state).decode("utf-8")

        logger.debug(f"Created state parameter for MCP client {mcp_context.get('client_id', 'unknown')}")
        return state_param

    def validate_and_extract_state(self, state_param: str) -> Optional[Dict[str, Any]]:
        """
        Validate and extract MCP context from state parameter.

        Args:
            state_param: Encrypted state parameter from OAuth2 callback

        Returns:
            MCP context dict or None if invalid/expired
        """
        try:
            # Base64 decode
            encrypted_state = base64.urlsafe_b64decode(state_param.encode("utf-8"))

            # Decrypt
            state_json = self.cipher.decrypt(encrypted_state).decode("utf-8")
            state_data = json.loads(state_json)

            # Validate timestamp
            timestamp = state_data.get("timestamp", 0)
            if int(time.time()) - timestamp > self.state_lifetime:
                logger.warning("State parameter expired")
                return None

            # Extract MCP context
            mcp_context: Dict[str, Any] = state_data.get("mcp_context", {})

            logger.debug(f"Validated state parameter for MCP client {mcp_context.get('client_id', 'unknown')}")
            return mcp_context

        except Exception as e:
            logger.warning(f"Invalid state parameter: {e}")
            return None

    def create_mcp_state(
        self, client_id: str, original_state: Optional[str], redirect_uri: str, email_hint: Optional[str] = None
    ) -> str:
        """
        Create state parameter for MCP OAuth2 flow.

        Args:
            client_id: MCP client identifier
            original_state: Original state from MCP client
            redirect_uri: MCP client redirect URI
            email_hint: Email hint for Google OAuth2

        Returns:
            Encrypted state parameter
        """
        mcp_context = {
            "client_id": client_id,
            "original_state": original_state,
            "redirect_uri": redirect_uri,
            "email_hint": email_hint,
            "flow_type": "mcp_oauth2",
        }

        return self.create_state(mcp_context)

    def extract_mcp_context(self, state_param: str) -> Optional[Dict[str, Any]]:
        """
        Extract MCP context from OAuth2 callback state.

        Args:
            state_param: State parameter from OAuth2 callback

        Returns:
            MCP context or None if invalid
        """
        logger.info(f"Extracting MCP context from state: {state_param[:50]}... (truncated)")
        state_data = self.validate_and_extract_state(state_param)
        logger.info(f"Validated state data: {state_data}")
        if not state_data:
            logger.warning("State validation failed")
            return None

        # Validate this is an MCP flow
        flow_type = state_data.get("flow_type")
        logger.info(f"Flow type from state: {flow_type}")
        if flow_type != "mcp_oauth2":
            logger.warning(f"State parameter is not for MCP OAuth2 flow, got: {flow_type}")
            return None

        logger.info("Successfully extracted MCP context")
        return state_data

    def _get_or_create_encryption_key(self) -> bytes:
        """
        Get or create encryption key for state parameters.

        In production, this should be stored securely and consistently
        across application instances.
        """
        # For now, we'll use a simple approach
        # In production, you would want to:
        # 1. Store the key securely (e.g., in environment variables, key management service)
        # 2. Rotate keys periodically
        # 3. Support multiple keys for graceful rotation

        # Try to get key from config or environment
        if hasattr(self.config, "oauth2_state_encryption_key"):
            key_str = getattr(self.config, "oauth2_state_encryption_key")
            if key_str:
                try:
                    return base64.urlsafe_b64decode(key_str.encode("utf-8"))
                except Exception:
                    pass

        # Generate new key (this should be persistent in production)
        if Fernet is None:
            raise ImportError("cryptography package is required")
        key: bytes = Fernet.generate_key()

        # Log warning about key generation
        logger.warning(
            "Generated new OAuth2 state encryption key. " "In production, store this key persistently: %s",
            base64.urlsafe_b64encode(key).decode("utf-8"),
        )

        return key


# Global state manager
_state_manager: Optional[OAuth2StateManager] = None


def get_oauth2_state_manager(config: config_class.Config) -> OAuth2StateManager:
    """Get or create the global OAuth2 state manager."""
    global _state_manager
    if _state_manager is None:
        _state_manager = OAuth2StateManager(config)
    return _state_manager
