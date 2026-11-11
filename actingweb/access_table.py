"""The access table (``config.access``) as pure functions (3.16).

``Auth._match_access_row`` and the shared access decision
(:mod:`actingweb.access_decision`) both ask it; nothing here holds request
state or imports the actor, so either may import it.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from actingweb.config import Config


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
) -> tuple[str, str, str, str] | None:
    """The first ``config.access`` row admitting ``relationship`` on
    ``path/subpath`` with ``method``, or None (3.16: the access table as a
    pure function, with no ``Auth`` state; :meth:`Auth._match_access_row`
    and the shared access decision both use it). ``owner`` rows match when
    ``caller_peerid`` is the peer ``path_peerid`` names."""
    relationship = (relationship or "").lower()
    method = (method or "").upper()
    if not path:
        return None
    fullpath = path.lower() + "/" + (subpath or "").lower()
    for acl in config.access:
        if acl[0] == "any" and not authenticated:
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
    ``relationship`` on ``path/subpath`` with ``method`` (3.16). An
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
        )
        is not None
    )
