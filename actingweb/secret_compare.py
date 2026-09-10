"""
Constant-time comparison helpers for secrets (passphrases, tokens, PKCE
verifiers).

A leaf module: no ``actingweb`` imports, so it cannot introduce an import
cycle — ``auth.py`` imports ``actor``/``trust``/``config`` and
``oauth2_server/*`` import ``attribute``/``config``.
"""

import hashlib
import secrets


def secret_equals(a: object, b: object) -> bool:
    """Constant-time equality check for a secret against an untrusted value.

    Returns ``False`` unless both operands are ``str`` or ``bytes`` — an
    attacker-typed JSON body can hand a submitted "secret" as an ``int`` or
    ``list`` (a PKCE ``code_verifier``, a passphrase, a verification token),
    and ``.encode()`` on a non-string would turn a 401/403 into a 500.
    ``str`` operands are UTF-8 encoded before ``secrets.compare_digest``,
    which raises on non-ASCII ``str`` input.
    """
    if not isinstance(a, (str, bytes)) or not isinstance(b, (str, bytes)):
        return False
    a_bytes = a.encode("utf-8") if isinstance(a, str) else a
    b_bytes = b.encode("utf-8") if isinstance(b, str) else b
    return secrets.compare_digest(a_bytes, b_bytes)


def secret_digest_equals(a: object, b: object) -> bool:
    """Constant-time equality for operands that may differ in length.

    Hashes both sides with SHA-256 before delegating to :func:`secret_equals`,
    so the comparison itself is always over fixed-length digests (used for
    PKCE S256, where the challenge and the verifier are not the same length
    to begin with).
    """
    if not isinstance(a, (str, bytes)) or not isinstance(b, (str, bytes)):
        return False
    a_bytes = a.encode("utf-8") if isinstance(a, str) else a
    b_bytes = b.encode("utf-8") if isinstance(b, str) else b
    return secret_equals(
        hashlib.sha256(a_bytes).digest(), hashlib.sha256(b_bytes).digest()
    )
