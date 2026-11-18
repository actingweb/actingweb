"""The access table (``config.access``) as pure functions (4.0).

``Auth._match_access_row`` and the shared access decision
(:mod:`actingweb.access_decision`) both ask it; nothing here holds request
state or imports the actor, so either may import it.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from actingweb.config import Config

# The access-table relationships that name a role, not a trust: their rows
# admit the creator and the trustee only, never a peer (4.0).
ROLE_RELATIONSHIPS = frozenset({"creator", "trustee"})

# Names a trust relationship may not take (4.0): the two roles, and the
# access table's own keywords (``owner`` matches the peer a path names,
# ``any`` every authenticated caller).
RESERVED_RELATIONSHIPS = frozenset({"creator", "trustee", "owner", "any"})


def is_reserved_relationship(name: str | None) -> bool:
    """Whether ``name`` may not be a trust relationship's name."""
    return (name or "").strip().lower() in RESERVED_RELATIONSHIPS


def matching_access_row(
    config: "Config",
    *,
    relationship: str,
    path: str,
    subpath: str = "",
    method: str = "",
    authenticated: bool = True,
    caller_peerid: str = "",
    path_peerid: str = "",
    caller_is_peer: bool = False,
) -> tuple[str, str, str, str] | None:
    """The first ``config.access`` row admitting ``relationship`` on
    ``path/subpath`` with ``method``, or None (4.0: the access table as a
    pure function, with no ``Auth`` state; :meth:`Auth._match_access_row`
    and the shared access decision both use it). ``owner`` rows match when
    ``caller_peerid`` is the peer ``path_peerid`` names. The ``creator`` and
    ``trustee`` rows never match a peer (``caller_peerid`` or
    ``caller_is_peer``), whatever its relationship is named (4.0: a peer
    whose trust was named ``creator`` matched the creator's rows)."""
    relationship = (relationship or "").lower()
    is_peer = caller_is_peer or bool(caller_peerid)
    method = (method or "").upper()
    if not path:
        return None
    fullpath = path.lower() + "/" + (subpath or "").lower()
    for acl in config.access:
        if acl[0] == "any" and not authenticated:
            continue
        if is_peer and acl[0] in ROLE_RELATIONSHIPS:
            continue
        if (
            len(acl[0]) > 0
            and acl[0] != "any"
            and acl[0] != relationship
            and acl[0] != "owner"
        ):
            continue  # no match on relationship
        if (
            acl[0] == relationship
            or acl[0] == "any"
            or len(acl[0]) == 0
            or (
                acl[0] == "owner"
                and len(path_peerid) > 0
                and caller_peerid == path_peerid
            )
        ):
            if fullpath.find(acl[1]) == 0:
                if len(acl[2]) == 0 or acl[2].find(method) != -1:
                    return acl
    return None


def access_table_admits(
    config: "Config",
    *,
    relationship: str,
    approved: bool,
    path: str,
    subpath: str = "",
    method: str = "",
) -> bool:
    """Whether the access table admits an authenticated peer of
    ``relationship`` on ``path/subpath`` with ``method`` (4.0). An
    unapproved peer is refused, as :meth:`Auth._match_access_row` refuses
    it (a trust DELETE excepted, which no grant decision asks about)."""
    if not approved:
        return False
    return (
        matching_access_row(
            config,
            relationship=relationship,
            path=path,
            subpath=subpath,
            method=method,
            caller_is_peer=True,
        )
        is not None
    )
