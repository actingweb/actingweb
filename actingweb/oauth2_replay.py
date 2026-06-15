"""
id_token replay protection for the native OIDC / JWT-bearer grant.

When a mobile client presents a provider id_token directly (rather than an
authorization code), the same token could be replayed within its validity
window. RFC 9700 §4.7 and OIDC security guidance call for single-use semantics.

This module records each accepted id_token by a stable per-token key (``jti``
when present, otherwise ``sha256(iss + sub + iat)``) in the persistent attribute
backend with a TTL covering the token's lifetime, and rejects any second sighting
within that window.
"""

import hashlib
import logging
import time
from typing import Any

from . import config as config_class

logger = logging.getLogger(__name__)


class IdTokenReplayCache:
    """Single-use id_token tracker backed by the attribute storage system."""

    def __init__(self, config: config_class.Config) -> None:
        self.config = config

    @staticmethod
    def _key_for_claims(claims: dict[str, Any]) -> str:
        jti = claims.get("jti")
        if jti:
            return hashlib.sha256(f"jti:{jti}".encode()).hexdigest()
        iss = str(claims.get("iss", ""))
        sub = str(claims.get("sub", ""))
        iat = str(claims.get("iat", ""))
        return hashlib.sha256(f"{iss}|{sub}|{iat}".encode()).hexdigest()

    def check_and_record(self, claims: dict[str, Any]) -> bool:
        """Record an id_token as seen.

        Args:
            claims: Validated id_token claims (must include ``exp``; ideally
                ``jti`` or ``iss``/``sub``/``iat``).

        Returns:
            True if this is the first sighting (accept), False if it is a replay.
        """
        from . import attribute
        from .constants import (
            ID_TOKEN_REPLAY_BUCKET,
            ID_TOKEN_REPLAY_TTL,
            OAUTH2_SYSTEM_ACTOR,
        )

        key = self._key_for_claims(claims)
        now = int(time.time())

        # TTL = remaining token lifetime + leeway, floored at the configured TTL.
        exp = int(claims.get("exp", 0) or 0)
        ttl = max(ID_TOKEN_REPLAY_TTL, (exp - now) + 60) if exp else ID_TOKEN_REPLAY_TTL

        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=ID_TOKEN_REPLAY_BUCKET,
            config=self.config,
        )

        existing = bucket.get_attr(name=key)
        if existing and "data" in existing:
            record = existing["data"]
            recorded_exp = int(record.get("exp", 0) or 0)
            # If the previous record is still within its validity window, reject.
            if recorded_exp == 0 or recorded_exp + 60 > now:
                logger.warning("id_token replay detected (key=%s...)", key[:12])
                return False

        bucket.set_attr(
            name=key,
            data={"seen_at": now, "exp": exp},
            ttl_seconds=ttl,
        )
        return True
