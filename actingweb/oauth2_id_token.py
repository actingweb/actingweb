"""
JWKS-based OIDC ``id_token`` validator.

Used by Apple and Google native sign-in to validate RS256-signed id_tokens
without a userinfo round-trip. Validation is fail-closed: if the signing key
cannot be resolved (JWKS unreachable, kid miss), ``validate`` returns ``None``.

We do the ``aud`` check ourselves (PyJWT's ``verify_aud`` only accepts a single
audience or exact-list match semantics that don't fit our "any of N acceptable
audiences" model), and tolerate ``iss`` being one of several accepted values
(Apple has historically used both ``appleid.apple.com`` and
``account.apple.com``).
"""

import hashlib
import logging
import secrets
from typing import Any

import jwt
from jwt.algorithms import RSAAlgorithm

from . import oauth2_jwks

logger = logging.getLogger(__name__)


class JWKSIdTokenValidator:
    """Validate an OIDC id_token against a provider's JWKS."""

    def __init__(
        self,
        jwks_uri: str,
        expected_iss: str | tuple[str, ...],
        audiences: list[str],
        algorithms: list[str] | None = None,
        leeway: int = 60,
        nonce_hash_tolerant: bool = False,
    ) -> None:
        self.jwks_uri = jwks_uri
        self.expected_iss: tuple[str, ...] = (
            (expected_iss,) if isinstance(expected_iss, str) else tuple(expected_iss)
        )
        self.audiences = list(audiences)
        self.algorithms = algorithms or ["RS256"]
        self.leeway = leeway
        # Apple's native Sign-in convention is for the client to put
        # ``SHA256(raw_nonce)`` (hex) in the authorization request, so the token's
        # ``nonce`` claim is the hash — whereas Google echoes the nonce verbatim.
        # When True, the nonce check accepts either the raw value or its hex
        # SHA-256, so callers can pass the *raw* nonce uniformly regardless of
        # provider. Both forms equally prove the caller possessed the nonce.
        self.nonce_hash_tolerant = nonce_hash_tolerant

    def validate(
        self, id_token: str, *, nonce: str | None = None
    ) -> dict[str, Any] | None:
        """Validate ``id_token`` and return its claims, or None on any failure.

        Args:
            id_token: The compact-serialized JWT.
            nonce: If provided, the token's ``nonce`` claim must match it. With
                ``nonce_hash_tolerant`` (Apple), a hex ``SHA256(nonce)`` claim is
                also accepted, so the *raw* nonce can be passed for any provider.

        Returns:
            The validated claims dict, or None if validation failed.
        """
        if not id_token:
            return None

        # Read the unverified header to find the signing key.
        try:
            header = jwt.get_unverified_header(id_token)
        except Exception as e:
            logger.warning("id_token header could not be parsed: %s", e)
            return None

        kid = header.get("kid")
        alg = header.get("alg")
        if alg not in self.algorithms:
            logger.warning("id_token alg %r not in allowed %r", alg, self.algorithms)
            return None
        if not kid:
            logger.warning("id_token header missing 'kid'")
            return None

        jwk = oauth2_jwks.get_key_for_kid(self.jwks_uri, kid)
        if jwk is None:
            # Fail-closed: cannot resolve the signing key.
            logger.warning(
                "No JWKS key for kid (signature key unavailable) at %s", self.jwks_uri
            )
            return None

        try:
            public_key = RSAAlgorithm.from_jwk(jwk)
        except Exception as e:
            logger.warning("Could not build public key from JWK: %s", e)
            return None

        # Verify signature + standard time claims. We disable aud verification
        # here and check it ourselves below to support a list of acceptable
        # audiences.
        try:
            claims = jwt.decode(
                id_token,
                public_key,  # type: ignore[arg-type]
                algorithms=self.algorithms,
                leeway=self.leeway,
                options={
                    "verify_signature": True,
                    "verify_aud": False,
                    "verify_exp": True,
                    "verify_iat": False,
                    "require": ["exp", "iss", "sub"],
                },
            )
        except Exception as e:
            logger.warning("id_token signature/claim verification failed: %s", e)
            return None

        # Manual issuer check (tolerate multiple accepted issuers).
        iss = claims.get("iss")
        if iss not in self.expected_iss:
            logger.warning("id_token iss %r not in accepted issuers", iss)
            return None

        # Manual audience check (accept any configured audience).
        aud = claims.get("aud")
        aud_values = aud if isinstance(aud, list) else [aud]
        if self.audiences and not any(a in self.audiences for a in aud_values):
            logger.warning("id_token aud not in configured audiences")
            return None

        # Nonce check (when required by caller).
        if nonce is not None:
            claim_nonce = claims.get("nonce") or ""
            ok = secrets.compare_digest(str(claim_nonce), nonce)
            if not ok and self.nonce_hash_tolerant:
                hashed = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
                ok = secrets.compare_digest(str(claim_nonce), hashed)
            if not ok:
                logger.warning("id_token nonce mismatch")
                return None

        return dict(claims)
