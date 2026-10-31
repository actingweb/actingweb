"""Is a request one a page on another site started?

A browser attaches the web UI's session cookie (``SameSite=Lax``: on any
same-site request, and on a top-level GET navigation from any site) and
cached basic-auth credentials to requests it did not choose to make. The
integrations turn the cookie into a Bearer header. So a request that
changes state with such *ambient* credentials must show it came from the
application's own origin (scheme, host and port of ``config.root``; a base
path does not matter). An explicit Bearer token cannot be attached by
another site, so a request carrying one is never refused here.

Pure functions over a header lookup, shared by ``BaseHandler`` and the
Flask and FastAPI integrations.
"""

from collections.abc import Callable
from urllib.parse import urlsplit

HeaderLookup = Callable[[str], str | None]


def _origin(value: str) -> tuple[str, str, int | None]:
    parts = urlsplit(value)
    scheme = (parts.scheme or "").lower()
    try:
        port = parts.port
    except ValueError:
        port = -1
    if port is None:
        port = {"https": 443, "http": 80}.get(scheme)
    return scheme, (parts.hostname or "").lower(), port


def same_origin(url: str, root: str) -> bool:
    """Whether ``url``'s origin is ``root``'s: case-insensitive host,
    default ports filled in, paths ignored."""
    return bool(url) and _origin(url) == _origin(root or "")


def cross_site(
    header: HeaderLookup,
    root: str,
    *,
    require_evidence: bool = False,
    session_cookie: bool = False,
) -> bool:
    """True when the request shows, or (with ``require_evidence``) fails
    to disprove, that another site started it.

    ``Sec-Fetch-Site`` decides when the browser sends it (every current
    one): ``same-origin`` passes, and so does ``none`` (typed, a bookmark)
    unless ``require_evidence``. Without it, an ``Origin``, then a
    ``Referer``, must be ``root``'s origin; ``Origin: null`` is refused. A
    request with none of the three passes (a script, a peer), except, with
    ``require_evidence``, one that carries the ``session_cookie``: only a
    browser holds it.

    ``require_evidence`` is for a GET that changes state (a ``_method``
    override): a link opened from a mail client arrives as ``none``, and a
    no-referrer link from a browser without Fetch Metadata arrives with no
    headers at all.
    """
    fetch_site = (header("Sec-Fetch-Site") or "").lower()
    if fetch_site:
        allowed = ("same-origin",) if require_evidence else ("same-origin", "none")
        return fetch_site not in allowed
    origin = header("Origin")
    if origin:
        return origin == "null" or not same_origin(origin, root)
    referer = header("Referer")
    if referer:
        return not same_origin(referer, root)
    return require_evidence and session_cookie


def ambient_credentials(authorization: str | None, session_cookie: bool) -> bool:
    """Whether the request may authenticate with something the browser
    attaches on its own: the session cookie, or basic auth (browsers cache
    it). An explicit Bearer token without the cookie is not ambient."""
    if session_cookie:
        return True
    return (authorization or "").strip().lower().startswith("basic ")


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def may_use_session_cookie(method: str, header: HeaderLookup, root: str) -> bool:
    """For the integrations: whether the ``oauth_token`` cookie may stand in
    for a Bearer header on this request. Always for a safe method (viewing a
    page; a GET ``_method`` override is checked again by the handler), and
    for a state-changing one only when the browser does not say another
    site started it, so a form on a sibling subdomain or another site
    cannot act with the owner's session."""
    if (method or "").upper() in SAFE_METHODS:
        return True
    return not cross_site(header, root)
