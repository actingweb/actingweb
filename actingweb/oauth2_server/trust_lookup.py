"""Exact lookup of an OAuth2 client's trust row on its actor (internal).

Shared by the MCP authentication resolver and client deletion, so the row a
request is authorised by and the row a deletion removes are found the same
way. Never a substring or prefix match: a peer id from an unrelated trust
must not satisfy a different client's lookup. Imports nothing from the
package, so neither caller gains an import cycle.
"""

from collections.abc import Iterable
from typing import Any

# Sources trust creation writes as a peer id's first segment
# (``established_via or "oauth2"``, ``TrustManager.create_or_update_oauth_trust``).
OAUTH2_SOURCES = ("oauth2", "oauth2_client", "oauth2_interactive")


def normalize_client_id(client_id: str) -> str:
    """The client id as trust creation writes it into a peer id. The one
    copy: ``TrustManager.create_or_update_oauth_trust`` calls it too, so
    creation and lookup cannot drift apart."""
    return client_id.replace("@", "_at_").replace(".", "_dot_").replace(":", "_colon_")


def _oauth2_origin(trust: Any) -> bool:
    """An OAuth2-family ``established_via``, or none with an OAuth2-family
    peer-id prefix (rows from before the field): never a peer-protocol row."""
    via = getattr(trust, "established_via", None)
    if via in OAUTH2_SOURCES:
        return True
    peer_id = str(getattr(trust, "peerid", ""))
    return via is None and peer_id.split(":", 1)[0] in OAUTH2_SOURCES


def find_client_trust(
    trusts: Iterable[Any], client_id: str, *, legacy_segment_match: bool = False
) -> Any | None:
    """The trust row that belongs to ``client_id``, or None.

    1. ``oauth_client_id == client_id``: every row created since the field
       was introduced.
    2. A legacy row (``oauth_client_id`` absent) with an OAuth2-family
       ``established_via`` (or none and an ``oauth2:``/``oauth2_client:``
       prefix) whose peer id equals ``{source}:{normalized}:{normalized}``,
       the shape the client-credentials flow wrote with the client id as
       its email.
    3. Deletion only (``legacy_segment_match=True``): a legacy row of OAuth2
       origin (as arm 2 judges it) whose peer id is
       ``<source>:<…>:<client_id>`` for any source trust creation writes
       (``oauth2``, ``oauth2_client``, ``oauth2_interactive``), three or more
       segments with the **last one equal** to the client id (as given or
       normalised). That keeps deleting the real-email legacy rows the
       interactive flow wrote, which the resolver deliberately does not
       authorise.
    """
    rows = list(trusts)
    for trust in rows:
        if getattr(trust, "oauth_client_id", None) == client_id:
            return trust

    normalized = normalize_client_id(client_id)
    candidates = {
        f"oauth2_client:{normalized}:{normalized}",
        f"oauth2:{normalized}:{normalized}",
    }
    for trust in rows:
        if getattr(trust, "oauth_client_id", None) is not None:
            continue  # arm 1 already looked at it
        via = getattr(trust, "established_via", None)
        peer_id = str(getattr(trust, "peerid", ""))
        oauth2_family = via in ("oauth2", "oauth2_client")
        legacy_prefixed = via is None and (
            peer_id.startswith("oauth2:") or peer_id.startswith("oauth2_client:")
        )
        if (oauth2_family or legacy_prefixed) and peer_id in candidates:
            return trust

    if not legacy_segment_match:
        return None
    for trust in rows:
        if getattr(trust, "oauth_client_id", None) is not None:
            continue
        if not _oauth2_origin(trust):
            continue
        parts = str(getattr(trust, "peerid", "")).split(":")
        if (
            len(parts) >= 3
            and parts[0] in OAUTH2_SOURCES
            and parts[-1] in (client_id, normalized)
        ):
            return trust
    return None
