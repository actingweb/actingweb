"""Shared helpers for OAuth2 handlers.

Lives in its own module so both ``oauth2_spa`` and ``oauth2_callback`` can use
it without importing each other (the two handler modules already cross-import,
so a shared helper on either side would create a circular import).
"""

from typing import Any


def normalize_user_info(provider_name: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Produce a consistent user_info shape across providers.

    Maps provider-specific name fields onto a common
    ``display_name`` / ``given_name`` / ``family_name`` / ``email`` shape so that
    application ``oauth_success`` hooks read one shape regardless of provider:

    - Apple: ``firstName`` / ``lastName`` -> ``given_name`` / ``family_name``
    - Google: ``given_name`` / ``family_name`` pass through
    - GitHub: ``name`` -> ``display_name`` (falls back to ``login`` when the
      user has no profile name set — GitHub's ``name`` is optional, ``login``
      is always present)

    The original keys (``sub``, ``email``, etc.) are preserved as passthrough.
    """
    info = dict(raw or {})

    given = info.get("given_name") or info.get("firstName") or ""
    family = info.get("family_name") or info.get("lastName") or ""
    if given:
        info["given_name"] = given
    if family:
        info["family_name"] = family

    # GitHub's ``name`` is optional but ``login`` (username) is always present,
    # so it is a safe last-resort display name — but ONLY for GitHub. Other
    # providers may carry a ``login`` field with different semantics, so the
    # fallback is gated on the provider rather than applied unconditionally.
    github_login = (
        info.get("login") if str(provider_name or "").startswith("github") else None
    )

    display = (
        info.get("display_name")
        or info.get("name")
        or (f"{given} {family}".strip() if (given or family) else "")
        or github_login
    )
    if display:
        info["display_name"] = display

    return info
