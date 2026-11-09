import logging
import re
from typing import Any

from actingweb.db import get_trust, get_trust_list

from .db.exceptions import DbError

# What a peer may call itself, and where it may say it lives. Both arrive
# from the peer (an unauthenticated trust request, or the peer's /meta) and
# end up in the owner's web UI and in URLs built from them, so they are
# refused at the door unless they are plainly an id and plainly a base URL.
# Ids the library makes for OAuth2/MCP trusts never come through here.
_PEER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+=-]{0,254}$")

# Peer-id prefixes of rows an OAuth2 login wrote (trust_lookup.OAUTH2_SOURCES),
# repeated here so this module imports nothing from oauth2_server at load.
_OAUTH2_PREFIXES = ("oauth2", "oauth2_client", "oauth2_interactive")


def is_valid_peer_id(value: Any) -> bool:
    """A peer-supplied id: letters, digits and ``_ . : @ + = -``, starting
    with a letter or digit, at most 255 characters. No ``/``, ``?``, ``#``,
    ``%``, quotes or whitespace, so it can sit in a URL path segment and a
    page without escaping surprises.

    Never one of the library's OAuth2 peer ids (``oauth2:``,
    ``oauth2_client:``, ``oauth2_interactive:``): those are deterministic
    (``<source>:<email>:<client_id>``) and a trust create overwrites a row
    with the same peer id, so a peer that could name one would replace a
    user's client connection and could then delete it with its own secret."""
    return (
        isinstance(value, str)
        and bool(_PEER_ID_RE.fullmatch(value))
        and value.split(":", 1)[0] not in _OAUTH2_PREFIXES
    )


def is_valid_peer_baseuri(value: Any) -> bool:
    """A peer-supplied base URI: ``http`` or ``https``, a host, no user
    info, query or fragment, and no whitespace, control characters, quotes
    or angle brackets. A link to it can then never carry a ``_method``
    override or a script."""
    from urllib.parse import urlsplit

    if not isinstance(value, str) or not value or len(value) > 2048:
        return False
    if any(c.isspace() or ord(c) < 32 or c in "\"'<>`\\" for c in value):
        return False
    try:
        parts = urlsplit(value)
        parts.port  # noqa: B018 -- raises ValueError on a bad port
    except ValueError:
        return False
    return (
        parts.scheme in ("http", "https")
        and bool(parts.hostname)
        and parts.username is None
        and parts.password is None
        and not parts.query
        and not parts.fragment
        and "?" not in value
        and "#" not in value
    )


logger = logging.getLogger(__name__)


def canonical_connection_method(method: str | None) -> str | None:
    """
    Normalize connection hints to canonical channels.

    Args:
        method: Connection method hint (e.g., "oauth2:interactive", "trust", "mcp")

    Returns:
        Canonical connection method or original value if not recognized

    Examples:
        - "oauth2:interactive" -> "oauth"
        - "OAUTH" -> "oauth"
        - "trust" -> "trust"
        - "subscription" -> "subscription"
        - "mcp" -> "mcp"
        - "unknown_method" -> "unknown_method"
    """
    if not method:
        return None

    # Validate input is a string
    if not isinstance(method, str):
        logger.warning(
            f"Connection method must be string, got {type(method)}: {method}"
        )
        return None

    lowered = method.lower().strip()

    # Handle empty or whitespace-only strings
    if not lowered:
        return None

    # Known canonical methods
    VALID_CONNECTION_METHODS = {"oauth", "trust", "subscription", "mcp"}

    # Handle oauth variants (oauth, oauth2, oauth2:interactive, etc.)
    if lowered.startswith("oauth"):
        return "oauth"

    # Handle known exact matches
    if lowered in VALID_CONNECTION_METHODS:
        return lowered

    # Log unknown methods for monitoring but still return them
    logger.debug(f"Unknown connection method: {method}")
    return method


class Trust:
    def get(self) -> dict[str, Any] | None:
        """Retrieve a trust relationship with either peerid or token"""
        if self.trust and len(self.trust) > 0:
            return self.trust
        if not self.handle:
            return None
        if not self.peerid and self.token:
            self.trust = self.handle.get(actor_id=self.actor_id, token=self.token)
        elif self.peerid and not self.token:
            self.trust = self.handle.get(actor_id=self.actor_id, peerid=self.peerid)
        else:
            self.trust = self.handle.get(
                actor_id=self.actor_id, peerid=self.peerid, token=self.token
            )
        return self.trust

    def delete(self) -> bool:
        """Delete the trust relationship"""
        if not self.handle:
            return False

        # Load the row: which OAuth2 client it connects is read from it.
        if not self.trust:
            self.get()

        # Which OAuth2 client this row connects, read *before* the local trust
        # data is dropped.
        oauth2_client_id: str | None = None
        if self.config:
            oauth2_client_id = self._oauth2_client_id()

        # A row connects this actor to a client; it owns the client only when
        # the client is registered under this actor. Deleting a connection
        # ends this actor's tokens and rows of the client and nothing else:
        # the client's index row is global, and deleting it here would
        # disable the client for every other actor it is connected to.
        registry: Any = None
        if oauth2_client_id and self.config:
            from .oauth2_server.client_registry import get_mcp_client_registry

            registry = get_mcp_client_registry(self.config)
            # Before the row goes, so a fault leaves the row as the retry
            # handle (the integrations answer DbError with 503), never a
            # deleted row beside a live client or live tokens. The owner
            # disables the client (tokens, client row, index row); any other
            # actor revokes only its own tokens for it. A retry after the
            # owner's client is gone takes the connection path.
            # Owned: the client row is in this actor's bucket and the index
            # does not name another actor (a copied or restored row would
            # make every disable refuse, and the row could never go).
            if registry.client_owned_by(
                self.actor_id, oauth2_client_id
            ) and registry.indexed_owner(oauth2_client_id) in (None, self.actor_id):
                if not registry.disable_client(
                    oauth2_client_id, actor_id=self.actor_id
                ):
                    raise DbError("OAuth2 client deletion", self.actor_id)
                logger.info(
                    f"Deleted OAuth2 client {oauth2_client_id} as part of trust "
                    f"deletion"
                )
            else:
                registry.revoke_connection_tokens(self.actor_id, oauth2_client_id)

        peerid = getattr(self, "peerid", None) or str(
            (self.trust or {}).get("peerid", "")
        )

        # The provider tokens an OAuth2 login stored for the row
        # (TrustManager.create_or_update_oauth_trust), Google's refresh token
        # among them, also before the row: they grant nothing here, and a
        # fault then leaves the row for the retry instead of an orphan.
        if (
            self.config
            and self.actor_id
            and peerid
            and (oauth2_client_id or peerid.split(":", 1)[0] in _OAUTH2_PREFIXES)
        ):
            from . import attribute
            from .constants import OAUTH_TOKENS_PREFIX

            store = attribute.InternalStore(actor_id=self.actor_id, config=self.config)
            if not store.set_confirmed(
                f"{OAUTH_TOKENS_PREFIX}{peerid}", None, raise_on_fault=True
            ):
                raise DbError("OAuth2 provider token delete", self.actor_id)

        # This actor's other rows of the client, before this row goes: a
        # fault then leaves this row, so retrying the same route (one row,
        # whose retry would otherwise answer 404) sweeps again. The sweep
        # deletes each sibling through delete_relationship() -> Trust.delete();
        # while it runs, those nested deletes skip their own sweep (the
        # registry's in-progress guard), so nothing recurses. A fault raises:
        # the caller must not report success while another row is live.
        if (
            oauth2_client_id
            and registry is not None
            and self.actor_id
            and not registry.sweeping(self.actor_id, oauth2_client_id)
        ):
            registry._delete_client_trust_relationship(
                self.actor_id, oauth2_client_id, exclude_peer_id=peerid
            )

        self.trust = {}
        result = self.handle.delete()

        try:
            # The row's custom permissions go right after the row, never
            # before it: a fault in between would leave a live row on its
            # trust type's defaults, which can be wider. Through the shared
            # store, whose cache the permission evaluator reads. A fault here
            # raises with the row gone; the next row created for the same
            # peer id clears them first (Trust.create, and
            # TrustManager.create_or_update_oauth_trust for OAuth2 rows).
            if result and self.config and self.actor_id and peerid:
                from .trust_permissions import get_trust_permission_store

                # Unconditionally: the store's cache has no TTL, and a "none"
                # it cached before another instance or process wrote the
                # permissions would skip the delete. Deleting an absent
                # attribute succeeds.
                permission_store = get_trust_permission_store(self.config)
                if not permission_store.delete_permissions(self.actor_id, peerid):
                    raise DbError("trust permissions delete", self.actor_id)
        finally:
            if result and self.actor_id:
                # A deleted trust relationship must stop authorizing
                # immediately, not at the end of the MCP caches' five-minute
                # TTL, also when the cleanup above raised. Actor-wide because
                # the cached ActorInterface carries the trust list itself —
                # see evict_mcp_caches_for_actor(). No-op when MCP is not in
                # use.
                from .mcp.invalidation import evict_caches_for_actor

                evict_caches_for_actor(self.actor_id)

        return result

    def _oauth2_client_id(self) -> str | None:
        """The OAuth2 client this row connects, or None for any other trust.

        The tagged ``oauth_client_id`` wins; an untagged legacy row is read
        from its peer id (:meth:`_extract_client_id_from_peerid`).
        """
        if not self.trust or not isinstance(self.trust, dict):
            return None
        from .oauth2_server.trust_lookup import OAUTH2_SOURCES, legacy_oauth2_row

        # Only a row an OAuth2 flow wrote. A peer can create a row with any
        # peer id through POST /trust (the pattern allows ':'), and the
        # library records those as established via "trust": a peer id of
        # the form oauth2_client:x:mcp_<id> must never let a remote peer
        # end, or delete, a client connection on this actor. A row older
        # than the "trust" tag (3.4) has no established_via; the one gate
        # for those is legacy_oauth2_row (its baseuri is none or this
        # actor's own, never a peer's).
        via = self.trust.get("established_via")
        if via is None:
            if not legacy_oauth2_row(
                self.trust.get("peerid"), self.trust.get("baseuri"), self.actor_id
            ):
                return None
        elif via not in OAUTH2_SOURCES:
            return None
        tagged = self.trust.get("oauth_client_id")
        if isinstance(tagged, str) and tagged:
            return tagged
        return self._extract_client_id_from_peerid()

    def _extract_client_id_from_peerid(self) -> str | None:
        """Extract client_id from peer_id format ``<source>:<email>:<client_id>``.

        ``<source>`` is any OAuth2 source trust creation writes
        (``oauth2_client``, ``oauth2``, ``oauth2_interactive``), so a legacy
        ``oauth2:`` row of a client is cleaned up like an ``oauth2_client:``
        one. The client id is the last segment and starts with ``mcp_``, the
        registry's prefix."""
        if not self.trust or not isinstance(self.trust, dict):
            return None

        peerid = self.trust.get("peerid", "")
        if not peerid or not isinstance(peerid, str):
            return None

        from .oauth2_server.trust_lookup import OAUTH2_SOURCES

        parts = peerid.split(":")
        if len(parts) >= 3 and parts[0] in OAUTH2_SOURCES:
            client_id = parts[-1]
            if client_id.startswith("mcp_"):
                return client_id

        return None

    def modify(
        self,
        baseuri: str | None = None,
        secret: str | None = None,
        desc: str | None = None,
        approved: bool | None = None,
        verified: bool | None = None,
        verification_token: str | None = None,
        peer_approved: bool | None = None,
        # New unified trust attributes
        peer_identifier: str | None = None,
        established_via: str | None = None,
        created_at: str | None = None,
        last_accessed: str | None = None,
        last_connected_via: str | None = None,
        # Client metadata for OAuth2 clients
        client_name: str | None = None,
        client_version: str | None = None,
        client_platform: str | None = None,
        oauth_client_id: str | None = None,
        # Peer capability tracking
        aw_supported: str | None = None,
        aw_version: str | None = None,
        capabilities_fetched_at: str | None = None,
        *,
        only_if_secret: str | None = None,
    ) -> bool:
        """Write the attributes given, in one write conditioned on the row
        existing. ``approved=True`` is written only to a row stored verified
        (3.16): a row whose secret an unproven requester chose is never
        approved, whatever route asks (``Actor.reverify_pending_trust`` first
        re-runs the verification). ``only_if_secret`` writes only while the
        row holds that secret (a re-pair's swap). False when nothing was
        written; a fault raises ``DbError``."""
        if not self.handle:
            logger.debug("Attempted modifcation of trust without handle")
            return False
        assert self.trust is not None  # Always initialized in __init__
        before = dict(self.trust)
        if baseuri:
            self.trust["baseuri"] = baseuri
        if secret:
            self.trust["secret"] = secret
        if desc:
            self.trust["desc"] = desc
        if approved is not None:
            self.trust["approved"] = str(approved).lower()
        if verified is not None:
            self.trust["verified"] = str(verified).lower()
        if verification_token:
            self.trust["verification_token"] = verification_token
        if peer_approved is not None:
            self.trust["peer_approved"] = str(peer_approved).lower()
        # Update capability fields in local trust dict
        if aw_supported is not None:
            self.trust["aw_supported"] = aw_supported
        if aw_version is not None:
            self.trust["aw_version"] = aw_version
        if capabilities_fetched_at is not None:
            self.trust["capabilities_fetched_at"] = capabilities_fetched_at
        modified = self.handle.modify(
            baseuri=baseuri,
            secret=secret,
            desc=desc,
            approved=approved,
            verified=verified,
            verification_token=verification_token,
            peer_approved=peer_approved,
            # Pass through new unified trust attributes
            peer_identifier=peer_identifier,
            established_via=established_via,
            created_at=created_at,
            last_accessed=last_accessed,
            last_connected_via=last_connected_via,
            # Pass through client metadata
            client_name=client_name,
            client_version=client_version,
            client_platform=client_platform,
            oauth_client_id=oauth_client_id,
            # Pass through peer capability tracking
            aw_supported=aw_supported,
            aw_version=aw_version,
            capabilities_fetched_at=capabilities_fetched_at,
            only_if_verified=approved is True,
            only_if_secret=only_if_secret,
        )
        if not modified:
            # Not written (the row is gone, or a condition failed): keep the
            # copy as it was.
            self.trust.clear()
            self.trust.update(before)
        return bool(modified)

    def create(
        self,
        baseuri: str = "",
        peer_type: str = "",
        relationship: str = "",
        secret: str = "",
        approved: bool = False,
        verified: bool = False,
        verification_token: str = "",
        desc: str = "",
        peer_approved: bool = False,
        peer_identifier: str | None = None,
        established_via: str | None = None,
        created_at: str | None = None,
        last_accessed: str | None = None,
        last_connected_via: str | None = None,
        *,
        known_absent: bool = False,
        only_if_absent: bool = False,
        only_if_pending: bool = False,
    ) -> bool:
        """Create a new trust relationship.

        ``known_absent``: the caller has just read that no row exists for the
        peer, so the read that decides whether stale custom permissions are
        cleared is skipped (one read per creation).

        ``only_if_absent``: write only if no row exists for the peer, in one
        conditional write; False when one does (a creation request never
        replaces a row, even one created since the caller's read). Stale
        custom permissions are cleared after the write succeeds, so a lost
        race never touches the winner's.

        ``only_if_pending``: the same, but the write also replaces a row that
        is neither verified nor approved (a pending request nobody proved or
        accepted); a lost condition answers False."""
        self.trust = {"baseuri": baseuri, "type": peer_type}
        if not relationship or len(relationship) == 0:
            self.trust["relationship"] = (
                self.config.default_relationship if self.config else ""
            )
        else:
            self.trust["relationship"] = relationship
        if not secret or len(secret) == 0:
            self.trust["secret"] = self.config.new_token() if self.config else ""
        else:
            self.trust["secret"] = secret
        # Be absolutely sure that the secret is not already used
        if self.config:
            testhandle = get_trust(self.config)
            if testhandle.is_token_in_db(
                actor_id=self.actor_id, token=self.trust["secret"]
            ):
                logger.warning("Found a non-unique token where it should be unique")
                return False
        self.trust["approved"] = str(approved).lower()
        self.trust["peer_approved"] = str(peer_approved).lower()
        self.trust["verified"] = str(verified).lower()
        if verification_token:
            self.trust["verification_token"] = verification_token
        else:
            self.trust["verification_token"] = (
                self.config.new_token() if self.config else ""
            )
        self.trust["desc"] = desc or ""
        self.trust["id"] = self.actor_id or ""
        self.trust["peerid"] = self.peerid or ""
        if not self.trust.get("verification_token"):
            self.trust["verification_token"] = (
                self.config.new_token() if self.config else ""
            )
        if not self.handle:
            return False
        if only_if_absent or only_if_pending:
            if not self._create_row(
                approved,
                verified,
                peer_approved,
                peer_identifier,
                established_via,
                created_at,
                last_accessed,
                last_connected_via,
                only_if_absent=only_if_absent,
                only_if_pending=only_if_pending and not only_if_absent,
            ):
                return False
            if self.config and self.actor_id and self.peerid:
                from .trust_permissions import get_trust_permission_store

                permission_store = get_trust_permission_store(self.config)
                if not permission_store.delete_permissions(self.actor_id, self.peerid):
                    raise DbError("trust permissions delete", self.actor_id)
            return True
        # A new row starts from its trust type's permissions. Trust.delete
        # deletes a row's custom permissions right after the row, and a fault
        # there raises with the row gone; the peer id is stable (a peer's
        # actor id), so those permissions would otherwise come back with the
        # next row for the same peer. Only when no row exists: create is an
        # upsert, and a re-sent request must not reset the custom permissions
        # an owner set on a live row.
        if (
            self.config
            and self.actor_id
            and self.peerid
            and (
                known_absent
                or self.handle.get(actor_id=self.actor_id, peerid=self.peerid) is None
            )
        ):
            from .trust_permissions import get_trust_permission_store

            # The shared store, unconditionally, as in Trust.delete.
            permission_store = get_trust_permission_store(self.config)
            if not permission_store.delete_permissions(self.actor_id, self.peerid):
                raise DbError("trust permissions delete", self.actor_id)
        return self._create_row(
            approved,
            verified,
            peer_approved,
            peer_identifier,
            established_via,
            created_at,
            last_accessed,
            last_connected_via,
        )

    def _create_row(
        self,
        approved: bool,
        verified: bool,
        peer_approved: bool,
        peer_identifier: str | None,
        established_via: str | None,
        created_at: str | None,
        last_accessed: str | None,
        last_connected_via: str | None,
        *,
        only_if_absent: bool = False,
        only_if_pending: bool = False,
    ) -> bool:
        assert self.handle is not None and self.trust is not None
        return self.handle.create(
            actor_id=self.actor_id,
            peerid=self.peerid,
            baseuri=self.trust["baseuri"],
            peer_type=self.trust["type"],
            relationship=self.trust["relationship"],
            secret=self.trust["secret"],
            approved=approved,
            verified=verified,
            peer_approved=peer_approved,
            verification_token=self.trust["verification_token"],
            desc=self.trust["desc"],
            peer_identifier=peer_identifier,
            established_via=established_via,
            created_at=created_at,
            last_accessed=last_accessed,
            last_connected_via=last_connected_via,
            only_if_absent=only_if_absent,
            only_if_pending=only_if_pending,
        )

    def __init__(
        self,
        actor_id: str | None = None,
        peerid: str | None = None,
        token: str | None = None,
        config: Any | None = None,
    ) -> None:
        self.config = config
        if self.config:
            self.handle = get_trust(self.config)
        else:
            self.handle = None
        self.trust = {}
        # Initialize attributes before any early returns to avoid AttributeError
        self.actor_id = actor_id
        self.peerid = peerid
        self.token = token
        if not actor_id or len(actor_id) == 0:
            logger.debug("No actorid set in initialisation of trust")
            return
        if not peerid and not token:
            logger.debug(
                "Both peerid and token are not set in initialisation of trust. One must be set."
            )
            return
        if not token and (not peerid or len(peerid) == 0):
            logger.debug("No peerid set in initialisation of trust")
            return
        self.get()


class Trusts:
    """Handles all trusts of a specific actor_id

    Access the indvidual trusts in .dbtrusts and the trust data
    in .trusts as a dictionary
    """

    def fetch(self, strict: bool = True) -> list[dict[str, Any]] | list[Any] | None:
        """The actor's trusts. A read fault raises ``DbError``;
        ``strict=False`` answers ``[]`` instead (and caches nothing)."""
        if self.trusts is not None:
            return self.trusts
        if not self.list and self.config:
            self.list = get_trust_list(self.config)
        if not self.trusts and self.list:
            try:
                self.trusts = self.list.fetch(actor_id=self.actor_id)
            except DbError:  # folds DbError: strict=False read, the caller asked
                if strict:
                    raise
                logger.error(
                    f"Trusts of {self.actor_id} could not be read; "
                    "answering [] (strict=False)"
                )
                return []
        return self.trusts

    def delete(self) -> bool:
        if not self.list:
            logger.debug("Already deleted list in trusts")
            return False
        if self.trusts is None:
            self.fetch()  # strict: the list deletes the rows it fetched
        self.list.delete()
        return True

    def __init__(self, actor_id: str | None = None, config: Any | None = None) -> None:
        """Properties must always be initialised with an actor_id"""
        self.config = config
        # Initialize attributes before any early returns to avoid AttributeError
        self.actor_id = actor_id
        self.trusts = None
        self.list = None
        if not actor_id:
            logger.debug("No actor_id in initialisation of trusts")
            return
        if self.config:
            self.list = get_trust_list(self.config)
        # The caller's own fetch() decides: a failed read caches nothing,
        # so fetch() re-reads and raises, or folds with strict=False. A
        # strict read here made every strict=False fold on this list
        # unreachable.
        try:
            self.fetch()
        except DbError:  # folds DbError: the caller's fetch() re-reads and decides
            pass
