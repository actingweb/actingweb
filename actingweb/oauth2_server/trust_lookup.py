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


def legacy_oauth2_row(peer_id: Any, baseuri: Any, actor_id: str | None) -> bool:
    """Whether a row with no ``established_via`` (written before 3.4) came
    from an OAuth2 flow: an OAuth2-family peer-id prefix, and no baseuri or
    this actor's own (``TrustManager.create_or_update_oauth_trust``), never a
    peer's. The baseuri is compared by its ``/<actor_id>`` suffix, as
    ``Actor.delete_reciprocal_trust`` spots a self-pointing row, so a row
    written before the deployment's fqdn or protocol changed still matches.
    The one copy: ``Trust`` and the deletion lookup both call it."""
    if str(peer_id or "").split(":", 1)[0] not in OAUTH2_SOURCES:
        return False
    uri = str(baseuri or "").rstrip("/")
    return not uri or (bool(actor_id) and uri.endswith(f"/{actor_id}"))


def _oauth2_origin(trust: Any, actor_id: str | None = None) -> bool:
    """An OAuth2-family ``established_via``, or none and
    :func:`legacy_oauth2_row` (rows from before the field): never a
    peer-protocol row."""
    via = getattr(trust, "established_via", None)
    if via in OAUTH2_SOURCES:
        return True
    baseuri = getattr(trust, "base_uri", None)
    if baseuri is None:
        baseuri = getattr(trust, "baseuri", "")
    return via is None and legacy_oauth2_row(
        getattr(trust, "peerid", ""), baseuri, actor_id
    )


def _tagged(trust: Any, client_id: str) -> bool:
    """Arm 1: ``oauth_client_id == client_id``."""
    return getattr(trust, "oauth_client_id", None) == client_id


def _untagged(trust: Any) -> bool:
    return getattr(trust, "oauth_client_id", None) is None


def _client_credentials_shape(
    trust: Any, normalized: str, actor_id: str | None
) -> bool:
    """Arm 2: a legacy client-credentials row, ``{source}:{n}:{n}``. With no
    ``established_via``, only a row :func:`legacy_oauth2_row` admits."""
    if not _untagged(trust):
        return False
    via = getattr(trust, "established_via", None)
    peer_id = str(getattr(trust, "peerid", ""))
    oauth2_family = via in ("oauth2", "oauth2_client")
    legacy = via is None and _oauth2_origin(trust, actor_id)
    return (oauth2_family or legacy) and peer_id in (
        f"oauth2_client:{normalized}:{normalized}",
        f"oauth2:{normalized}:{normalized}",
    )


def _real_email_shape(
    trust: Any, client_id: str, normalized: str, actor_id: str | None
) -> bool:
    """Arm 3: a legacy per-client row, ``<source>:<email>:<client_id>``."""
    if not _untagged(trust) or not _oauth2_origin(trust, actor_id):
        return False
    parts = str(getattr(trust, "peerid", "")).split(":")
    return (
        len(parts) == 3
        and parts[0] in OAUTH2_SOURCES
        and parts[2] in (client_id, normalized)
    )


def find_client_trust(
    trusts: Iterable[Any], client_id: str, actor_id: str | None = None
) -> Any | None:
    """The one trust row that authorises ``client_id``, or None (the MCP
    authentication resolver).

    1. ``oauth_client_id == client_id``: every row created since the field
       was introduced. Wins over any legacy row.
    2. A legacy row (``oauth_client_id`` absent) with an ``oauth2`` or
       ``oauth2_client`` ``established_via`` (or none and an ``oauth2:`` /
       ``oauth2_client:`` prefix) whose peer id equals
       ``{source}:{normalized}:{normalized}``, the shape the
       client-credentials flow wrote with the client id as its email. A row
       with no ``established_via`` must also have no baseuri or
       ``actor_id``'s own (:func:`legacy_oauth2_row`).

    Arm 3 (:func:`client_trusts_for_deletion`) is never consulted here.
    """
    rows = list(trusts)
    for trust in rows:
        if _tagged(trust, client_id):
            return trust
    normalized = normalize_client_id(client_id)
    for trust in rows:
        if _client_credentials_shape(trust, normalized, actor_id):
            return trust
    return None


def client_trusts_for_deletion(
    trusts: Iterable[Any], client_id: str, actor_id: str | None = None
) -> list[Any]:
    """Every trust row that belongs to ``client_id``, in row order (client
    deletion). ``actor_id`` is the actor the rows belong to: a legacy row
    with a baseuri is this client's only when the baseuri is that actor's
    own (:func:`legacy_oauth2_row`).

    An upgraded actor can hold a tagged row and a legacy row for the same
    client under different peer ids; deleting only the first would leave
    the other with its permissions. So this returns each row that arm 1 or
    arm 2 of :func:`find_client_trust` matches, plus arm 3:

    3. A legacy row of OAuth2 origin whose peer id is exactly
       ``<source>:<email>:<client_id>`` (three segments, the last equal to
       the client id as given or normalised) for any source trust creation
       writes (``oauth2``, ``oauth2_client``, ``oauth2_interactive``). These
       are the real-email rows the interactive flow wrote.

    Arm 3's origin gate (:func:`_oauth2_origin`) is deliberately **wider**
    than arm 2's: it admits ``oauth2_interactive``, because deletion must
    remove those rows. The resolver must not authorise them, so never reuse
    this gate (or this function) for authorisation.
    """
    normalized = normalize_client_id(client_id)
    return [
        trust
        for trust in trusts
        if _tagged(trust, client_id)
        or _client_credentials_shape(trust, normalized, actor_id)
        or _real_email_shape(trust, client_id, normalized, actor_id)
    ]
