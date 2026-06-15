"""
Sign in with Apple helpers: ES256 ``client_secret`` JWT generation and key loading.

Apple does not accept a static ``client_secret``. Every token / refresh / revoke
request must carry a freshly-signed ES256 JWT (RFC 7523-style client assertion)
built from the Team ID, Key ID, Services ID / Bundle ID (the ``sub``), and the
``.p8`` private key. See Apple's "Creating a client secret" docs.

The JWT is cached via ``functools.lru_cache`` keyed by a 5-minute time bucket and
the provider name — NOT by the PEM bytes — so the private key never appears in a
cache key. Credentials are re-read from a module-level registry inside the cached
function.
"""

import functools
import logging
import os
import time
from typing import Any

import jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key

logger = logging.getLogger(__name__)

# Apple's documented maximum client_secret lifetime is ~6 months. We use a
# comfortably-short window; the value just needs to be a valid future exp.
APPLE_CLIENT_SECRET_LIFETIME = 15777000  # seconds (~6 months, Apple's max)
APPLE_AUDIENCE = "https://appleid.apple.com"
_TIME_BUCKET_SECONDS = 300  # 5 minutes

# Registry of Apple provider credentials, keyed by provider name. Populated when
# an AppleOAuth2Provider is constructed. The PEM lives here (not in any cache key).
_APPLE_CREDS: dict[str, dict[str, str]] = {}


def register_apple_credentials(
    provider_name: str,
    *,
    team_id: str,
    key_id: str,
    client_id: str,
    private_key_pem: str,
) -> None:
    """Register Apple credentials for later client_secret minting."""
    _APPLE_CREDS[provider_name] = {
        "team_id": team_id,
        "key_id": key_id,
        "client_id": client_id,
        "private_key_pem": private_key_pem,
    }


def make_apple_client_secret(
    team_id: str,
    key_id: str,
    client_id: str,
    private_key_pem: str,
    *,
    now: int,
) -> str:
    """Build and sign an ES256 ``client_secret`` JWT for Apple.

    Args:
        team_id: Apple Team ID (the ``iss`` claim).
        key_id: Key ID for the ``.p8`` (the JWT header ``kid``).
        client_id: Services ID or Bundle ID (the ``sub`` claim).
        private_key_pem: PEM-encoded EC P-256 private key (the ``.p8`` contents).
        now: Current Unix time (seconds) for ``iat``.

    Returns:
        The compact-serialized ES256 JWT.
    """
    headers = {"kid": key_id, "alg": "ES256"}
    payload = {
        "iss": team_id,
        "iat": now,
        "exp": now + APPLE_CLIENT_SECRET_LIFETIME,
        "aud": APPLE_AUDIENCE,
        "sub": client_id,
    }
    return jwt.encode(payload, private_key_pem, algorithm="ES256", headers=headers)


@functools.lru_cache(maxsize=4)
def _cached_client_secret(time_bucket: int, provider_name: str) -> str:
    """Return a cached ES256 client_secret for ``provider_name``.

    Keyed by ``(time_bucket, provider_name)`` only — the PEM is re-read from the
    credential registry inside the function so it never enters the cache key.
    """
    creds = _APPLE_CREDS.get(provider_name)
    if not creds:
        raise ValueError(
            f"No Apple credentials registered for provider '{provider_name}'"
        )
    return make_apple_client_secret(
        team_id=creds["team_id"],
        key_id=creds["key_id"],
        client_id=creds["client_id"],
        private_key_pem=creds["private_key_pem"],
        now=int(time.time()),
    )


def get_client_secret(provider_name: str) -> str:
    """Return a (cached) ES256 client_secret for the given Apple provider."""
    time_bucket = int(time.time() // _TIME_BUCKET_SECONDS)
    return _cached_client_secret(time_bucket, provider_name)


def load_private_key_pem(provider_config: dict[str, Any]) -> str:
    """Resolve and validate the Apple ``.p8`` private key as a PEM string.

    Resolution order (file path wins over inline PEM):
        1. ``provider_config["apple_private_key_path"]`` or env ``APPLE_PRIVATE_KEY_PATH``
        2. ``provider_config["apple_private_key_pem"]`` or env ``APPLE_PRIVATE_KEY_PEM``

    Validates that the key parses as an EC private key. Raises ``ValueError``
    with the failing path/reason on any problem so misconfiguration surfaces at
    config-build time, not first request.
    """
    path = provider_config.get("apple_private_key_path") or os.getenv(
        "APPLE_PRIVATE_KEY_PATH", ""
    )
    pem = provider_config.get("apple_private_key_pem") or os.getenv(
        "APPLE_PRIVATE_KEY_PEM", ""
    )

    source = ""
    if path:
        try:
            with open(path, "rb") as f:
                pem_bytes = f.read()
            pem = pem_bytes.decode("utf-8")
            source = f"file '{path}'"
        except OSError as e:
            raise ValueError(
                f"Apple private key file could not be read at '{path}': {e}"
            ) from e
    elif pem:
        # Inline PEM may arrive with literal \n sequences from env vars.
        if "\\n" in pem and "\n" not in pem:
            pem = pem.replace("\\n", "\n")
        source = "inline PEM (APPLE_PRIVATE_KEY_PEM)"
    else:
        raise ValueError(
            "Apple private key not provided: set private_key_path / "
            "APPLE_PRIVATE_KEY_PATH or private_key_pem / APPLE_PRIVATE_KEY_PEM"
        )

    # Validate the key parses as an EC private key.
    try:
        key = load_pem_private_key(pem.encode("utf-8"), password=None)
    except Exception as e:
        raise ValueError(
            f"Apple private key from {source} is not a valid PEM key: {e}"
        ) from e

    # cryptography's EC key exposes a curve; Apple keys are P-256, but we accept
    # any EC key and let signing fail loudly if the curve is wrong.
    if not hasattr(key, "curve"):
        raise ValueError(f"Apple private key from {source} is not an EC (ES256) key")

    return pem


def _reset_credentials() -> None:
    """Test helper: clear registered credentials and the secret cache."""
    _APPLE_CREDS.clear()
    _cached_client_secret.cache_clear()
