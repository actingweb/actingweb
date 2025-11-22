"""
Service configuration for third-party OAuth2 service integration.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class ServiceConfig:
    """
    Configuration for a third-party OAuth2 service.

    This replaces the manual OAuth configuration from the legacy system
    with a clean, type-safe configuration object.
    """

    name: str
    client_id: str
    client_secret: str
    scopes: list[str]
    auth_uri: str
    token_uri: str
    userinfo_uri: str | None = None
    revocation_uri: str | None = None
    base_api_url: str | None = None
    extra_params: dict[str, Any] | None = None

    def __post_init__(self):
        """Validate configuration after initialization."""
        if not self.name:
            raise ValueError("Service name is required")
        if not self.client_id:
            raise ValueError(f"client_id is required for service '{self.name}'")
        if not self.client_secret:
            raise ValueError(f"client_secret is required for service '{self.name}'")
        if not self.scopes:
            raise ValueError(f"scopes are required for service '{self.name}'")
        if not self.auth_uri:
            raise ValueError(f"auth_uri is required for service '{self.name}'")
        if not self.token_uri:
            raise ValueError(f"token_uri is required for service '{self.name}'")

    def is_enabled(self) -> bool:
        """Check if service is properly configured."""
        return bool(
            self.name
            and self.client_id
            and self.client_secret
            and self.scopes
            and self.auth_uri
            and self.token_uri
        )

    def to_oauth2_config(self) -> dict[str, Any]:
        """Convert to OAuth2 configuration format."""
        config = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": " ".join(self.scopes),
            "auth_uri": self.auth_uri,
            "token_uri": self.token_uri,
        }

        if self.userinfo_uri:
            config["userinfo_uri"] = self.userinfo_uri
        if self.revocation_uri:
            config["revocation_uri"] = self.revocation_uri
        if self.extra_params:
            config.update(self.extra_params)

        return config


# Pre-configured service templates for common services
class ServiceTemplates:
    """Pre-configured templates for popular OAuth2 services."""

    @staticmethod
    def dropbox(client_id: str, client_secret: str) -> ServiceConfig:
        """Dropbox service configuration template."""
        return ServiceConfig(
            name="dropbox",
            client_id=client_id,
            client_secret=client_secret,
            scopes=["files.content.read", "files.metadata.read"],
            auth_uri="https://www.dropbox.com/oauth2/authorize",
            token_uri="https://api.dropboxapi.com/oauth2/token",
            base_api_url="https://api.dropboxapi.com",
        )

    @staticmethod
    def gmail(
        client_id: str, client_secret: str, readonly: bool = True
    ) -> ServiceConfig:
        """Gmail service configuration template."""
        scopes = (
            ["https://www.googleapis.com/auth/gmail.readonly"]
            if readonly
            else ["https://www.googleapis.com/auth/gmail.modify"]
        )
        return ServiceConfig(
            name="gmail",
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes,
            auth_uri="https://accounts.google.com/o/oauth2/v2/auth",
            token_uri="https://oauth2.googleapis.com/token",
            userinfo_uri="https://www.googleapis.com/oauth2/v2/userinfo",
            revocation_uri="https://oauth2.googleapis.com/revoke",
            base_api_url="https://www.googleapis.com/gmail/v1",
            extra_params={"access_type": "offline", "prompt": "consent"},
        )

    @staticmethod
    def github(client_id: str, client_secret: str) -> ServiceConfig:
        """GitHub service configuration template."""
        return ServiceConfig(
            name="github",
            client_id=client_id,
            client_secret=client_secret,
            scopes=["repo", "user"],
            auth_uri="https://github.com/login/oauth/authorize",
            token_uri="https://github.com/login/oauth/access_token",
            userinfo_uri="https://api.github.com/user",
            base_api_url="https://api.github.com",
        )

    @staticmethod
    def box(client_id: str, client_secret: str) -> ServiceConfig:
        """Box service configuration template."""
        return ServiceConfig(
            name="box",
            client_id=client_id,
            client_secret=client_secret,
            scopes=["root_readwrite"],
            auth_uri="https://account.box.com/api/oauth2/authorize",
            token_uri="https://api.box.com/oauth2/token",
            base_api_url="https://api.box.com/2.0",
        )
