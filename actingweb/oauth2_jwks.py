"""
JWKS (JSON Web Key Set) fetching and caching for OIDC id_token validation.

Both Apple and Google native sign-in validate RS256-signed ``id_token`` JWTs
against the issuer's published JWKS. This module provides a process-local cache
of fetched key sets with:

- A positive TTL (default 1h) for successfully fetched key sets.
- A negative TTL (default 60s) suppressing repeat fetches of an unreachable
  endpoint (fail-fast, avoids hammering a down IdP).
- A ``kid``-miss force-refetch with a single debounced retry, so that key
  rotation is picked up promptly without a fetch storm.

The cache is a module-level dict (per-process / per-Lambda-container). This is
intentional and documented: each container fetches independently; no shared
store is needed because the JWKS is public and cheap to re-fetch.
"""

import logging
import threading
import time
from typing import Any

import requests  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# Positive cache: jwks_uri -> (fetched_at_epoch, jwks_dict)
_JWKS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
# Negative cache: jwks_uri -> last_failed_at_epoch
_JWKS_NEGATIVE_CACHE: dict[str, float] = {}
# Debounce: jwks_uri -> last_forced_refetch_at_epoch
_JWKS_FORCE_REFETCH: dict[str, float] = {}

_LOCK = threading.Lock()

JWKS_POSITIVE_TTL = 3600.0
JWKS_NEGATIVE_TTL = 60.0
JWKS_FORCE_REFETCH_DEBOUNCE = 5.0
JWKS_TIMEOUT = (3.0, 5.0)


def _now() -> float:
    return time.time()


def fetch_jwks(jwks_uri: str, *, force: bool = False) -> dict[str, Any] | None:
    """Fetch (and cache) the JWKS document for ``jwks_uri``.

    Args:
        jwks_uri: The JWKS endpoint URL.
        force: If True, bypass the positive cache and re-fetch (still honoring
            the force-refetch debounce window).

    Returns:
        The JWKS dict (``{"keys": [...]}``), or None if unavailable. On fetch
        failure, a previously-cached (even if stale) JWKS is returned if one
        exists (fail-soft for transient errors), otherwise None (fail-closed).
    """
    if not jwks_uri:
        return None

    now = _now()

    with _LOCK:
        cached = _JWKS_CACHE.get(jwks_uri)
        if not force and cached is not None:
            fetched_at, jwks = cached
            if now - fetched_at < JWKS_POSITIVE_TTL:
                return jwks

        # Negative cache: suppress repeat fetches of an unreachable endpoint.
        last_failed = _JWKS_NEGATIVE_CACHE.get(jwks_uri)
        if last_failed is not None and now - last_failed < JWKS_NEGATIVE_TTL:
            # Within negative window — return stale positive cache if present.
            if cached is not None:
                return cached[1]
            return None

        # Debounce forced refetches (kid-miss storms).
        if force:
            last_forced = _JWKS_FORCE_REFETCH.get(jwks_uri)
            if (
                last_forced is not None
                and now - last_forced < JWKS_FORCE_REFETCH_DEBOUNCE
            ):
                return cached[1] if cached is not None else None
            _JWKS_FORCE_REFETCH[jwks_uri] = now

    # Perform the network fetch outside the lock.
    try:
        response = requests.get(jwks_uri, timeout=JWKS_TIMEOUT)
        if response.status_code != 200:
            logger.warning(
                "JWKS fetch failed for %s: HTTP %s", jwks_uri, response.status_code
            )
            with _LOCK:
                _JWKS_NEGATIVE_CACHE[jwks_uri] = _now()
            return cached[1] if cached is not None else None

        jwks = response.json()
        if not isinstance(jwks, dict) or "keys" not in jwks:
            logger.warning("JWKS response for %s missing 'keys' field", jwks_uri)
            with _LOCK:
                _JWKS_NEGATIVE_CACHE[jwks_uri] = _now()
            return cached[1] if cached is not None else None

        with _LOCK:
            _JWKS_CACHE[jwks_uri] = (_now(), jwks)
            _JWKS_NEGATIVE_CACHE.pop(jwks_uri, None)
        return jwks

    except Exception as e:
        logger.warning("Exception fetching JWKS from %s: %s", jwks_uri, e)
        with _LOCK:
            _JWKS_NEGATIVE_CACHE[jwks_uri] = _now()
        return cached[1] if cached is not None else None


def get_key_for_kid(jwks_uri: str, kid: str) -> dict[str, Any] | None:
    """Return the JWK matching ``kid`` from the JWKS at ``jwks_uri``.

    On a ``kid`` miss against the cached JWKS, forces a single (debounced)
    re-fetch to pick up key rotation before giving up.

    Returns:
        The matching JWK dict, or None if no key matches.
    """
    if not jwks_uri or not kid:
        return None

    jwks = fetch_jwks(jwks_uri)
    key = _find_kid(jwks, kid)
    if key is not None:
        return key

    # kid miss — force one refetch in case keys rotated.
    jwks = fetch_jwks(jwks_uri, force=True)
    return _find_kid(jwks, kid)


def _find_kid(jwks: dict[str, Any] | None, kid: str) -> dict[str, Any] | None:
    if not jwks:
        return None
    for key in jwks.get("keys", []):
        if isinstance(key, dict) and key.get("kid") == kid:
            return key
    return None


def _reset_cache() -> None:
    """Test helper: clear all caches."""
    with _LOCK:
        _JWKS_CACHE.clear()
        _JWKS_NEGATIVE_CACHE.clear()
        _JWKS_FORCE_REFETCH.clear()
