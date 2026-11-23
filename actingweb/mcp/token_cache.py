"""A read-only view of the MCP token cache, for code in front of ``/mcp``."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from actingweb.config import Config


def is_token_cached(token: str, config: Config) -> bool:
    """Whether this process holds a fresh MCP token-cache entry for ``token``.

    For middleware in front of ``/mcp`` that wants to know whether the
    library will validate the token against the token store on this request.
    ``config`` is the application's own object (``app.get_config()``): an
    entry written under another one is a miss, as it is for the handler.

    **True does not authorize and False does not mean invalid.**

    - True: the handler will start from the entry and not read the token
      store, unless the actor row turns out to be gone: it then drops the
      entry and validates the token against the store after all (which can
      raise ``TokenStoreUnavailable``). It still loads the actor and its
      trust, and a request with no trust is refused at the method. A token
      revoked in another process stays cached here until its entry expires
      (five minutes).
    - False: not cached *in this process*. That is every token on a fresh
      worker or a cold function instance. Let the request through and the
      handler validates it; to know whether a token is valid, call
      ``get_actingweb_token_manager(config).validate_access_token(token)``.

    Reads no store and changes nothing: no entry is added, refreshed or
    evicted, and no counter moves. The caches themselves stay internal.
    """
    # Imported here: the handler module imports this package's decorators.
    from actingweb.handlers import mcp as handler

    if not token:
        return False
    return handler._token_cache_entry_is_fresh(
        handler._token_cache.get(token), config, time.time()
    )
