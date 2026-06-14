"""
Server-side OAuth state nonce store.

Apple's ``response_mode=form_post`` sends the authorization response as a
cross-site ``POST`` to the registered ``redirect_uri``. A cleartext-JSON ``state``
(as used for Google/GitHub query-mode callbacks) is unauthenticated and offers no
CSRF protection for that POST, and SameSite=Lax cookies do not survive the
cross-site POST either.

Following RFC 9700 §4.7 / OIDC Core §15.5.2 / the OWASP OAuth Cheat Sheet (and
matching django-allauth / python-social-auth / Curity), we send Apple only an
opaque single-use nonce as ``state`` and hold the full state payload server-side,
keyed by that nonce. The callback consumes the nonce (single-use) to recover the
payload and reject forged or replayed POSTs.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from . import config as config_class


class StateNonceStore:
    """Single-use server-side store mapping opaque nonces to state payloads."""

    def __init__(self, config: config_class.Config) -> None:
        self.config = config

    def create(self, state_payload: dict[str, Any], *, ttl: int | None = None) -> str:
        """Store ``state_payload`` server-side and return an opaque nonce.

        Args:
            state_payload: The full state dict (provider, csrf, return path,
                mcp_context, etc.).
            ttl: Override TTL in seconds (defaults to OAUTH_STATE_NONCE_TTL).

        Returns:
            A URL-safe opaque nonce to send as the ``state`` parameter.
        """
        from . import attribute
        from .constants import (
            OAUTH2_SYSTEM_ACTOR,
            OAUTH_STATE_NONCE_BUCKET,
            OAUTH_STATE_NONCE_TTL,
        )

        nonce = secrets.token_urlsafe(32)
        effective_ttl = ttl or OAUTH_STATE_NONCE_TTL

        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=OAUTH_STATE_NONCE_BUCKET,
            config=self.config,
        )
        bucket.set_attr(name=nonce, data=state_payload, ttl_seconds=effective_ttl)
        return nonce

    def consume(self, nonce: str) -> dict[str, Any] | None:
        """Return the payload for ``nonce`` and delete it (single-use).

        Returns:
            The stored payload, or None on miss / already-consumed / malformed.
        """
        from . import attribute
        from .constants import OAUTH2_SYSTEM_ACTOR, OAUTH_STATE_NONCE_BUCKET

        if not nonce:
            return None

        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=OAUTH_STATE_NONCE_BUCKET,
            config=self.config,
        )
        attr = bucket.get_attr(name=nonce)
        if not attr or "data" not in attr:
            return None

        # Single-use: delete before returning so a replay finds nothing.
        bucket.delete_attr(name=nonce)
        payload = attr["data"]
        if not isinstance(payload, dict):
            return None
        return payload


class AppleTicketStore:
    """Short-lived exchange-ticket store for the Android Apple deep-link flow.

    Apple's ``redirect_uri`` must be HTTPS, so the Android Capacitor app cannot
    receive Apple's POST directly. Instead the server validates Apple's POST,
    persists the IdP ``code`` against an opaque ticket, and deep-links the app
    with only the ticket. The app then POSTs the ticket to ``/oauth/spa/token``
    where the server performs the JWT-client_secret exchange. No ActingWeb token
    ever appears in a deep link.
    """

    def __init__(self, config: config_class.Config) -> None:
        self.config = config

    def create(
        self,
        *,
        code: str,
        redirect_uri: str,
        provider: str,
        extra: dict[str, Any] | None = None,
        ttl: int | None = None,
    ) -> str:
        from . import attribute
        from .constants import (
            APPLE_TICKET_BUCKET,
            APPLE_TICKET_TTL,
            OAUTH2_SYSTEM_ACTOR,
        )

        ticket = secrets.token_urlsafe(32)
        payload: dict[str, Any] = {
            "code": code,
            "redirect_uri": redirect_uri,
            "provider": provider,
        }
        if extra:
            payload["extra"] = extra

        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=APPLE_TICKET_BUCKET,
            config=self.config,
        )
        bucket.set_attr(name=ticket, data=payload, ttl_seconds=ttl or APPLE_TICKET_TTL)
        return ticket

    def consume(self, ticket: str) -> dict[str, Any] | None:
        from . import attribute
        from .constants import APPLE_TICKET_BUCKET, OAUTH2_SYSTEM_ACTOR

        if not ticket:
            return None
        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=APPLE_TICKET_BUCKET,
            config=self.config,
        )
        attr = bucket.get_attr(name=ticket)
        if not attr or "data" not in attr:
            return None
        bucket.delete_attr(name=ticket)
        payload = attr["data"]
        if not isinstance(payload, dict):
            return None
        return payload


def looks_like_state_nonce(state: str) -> bool:
    """Heuristic: an opaque URL-safe token (no JSON, no Fernet ``=`` padding run).

    ``secrets.token_urlsafe(32)`` yields ~43 chars of ``[A-Za-z0-9_-]``.
    """
    if not state or state.strip().startswith("{"):
        return False
    # token_urlsafe uses only URL-safe base64 chars without '=' padding.
    return 30 <= len(state) <= 64 and all(c.isalnum() or c in "-_" for c in state)
