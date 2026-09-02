"""ActingWeb: per-user micro-services with per-actor MCP servers and peer-to-peer data sharing.

Each user gets their own "actor" instance with a unique URL, its own data,
and its own trust relationships to other actors. Two headline capabilities:

- **MCP servers per user** -- ``@app.action_hook(...)`` + ``@mcp_tool(...)``
  exposes a hook as an authenticated, per-actor MCP tool.
- **Peer-to-peer data sharing** -- actors establish trust with each other
  and subscribe to one another's property changes.

Start here::

    from actingweb.interface import ActingWebApp, ActorInterface
    from actingweb.mcp import mcp_tool, mcp_prompt, mcp_resource

    app = ActingWebApp(aw_type="urn:actingweb:example.com:myapp", fqdn="myapp.example.com")

MCP quickstart: https://actingweb.readthedocs.io/en/latest/docs/guides/mcp-quickstart.html
Peer-to-peer quickstart: https://actingweb.readthedocs.io/en/latest/docs/guides/p2p-quickstart.html

Note on types: ``py.typed`` ships, but every hook boundary --
``@app.property_hook``, ``@app.action_hook``, ``@app.method_hook``,
``@app.callback_hook``, and the ``@mcp_tool``/``@mcp_prompt``/``@mcp_resource``
decorators -- is erased to ``Callable[..., Any] -> Callable[..., Any]``, and
``actingweb.actor`` is unannotated below the interface layer. A type checker
will not catch a wrong hook signature; see
https://actingweb.readthedocs.io/en/latest/docs/reference/hooks-reference.html
for the real signatures.
"""

__version__ = "3.14.4"

# Modules below are lazy-loaded on-demand for backward compatibility with
# pre-3.x code (`from actingweb import actor`, etc.). This is NOT the
# recommended API -- use `from actingweb.interface import ActingWebApp` and
# `from actingweb.mcp import mcp_tool` instead, per the module docstring
# above.
__all__ = [
    "actor",  # pyright: ignore[reportUnsupportedDunderAll]
    "attribute",  # pyright: ignore[reportUnsupportedDunderAll]
    "attribute_list",  # pyright: ignore[reportUnsupportedDunderAll]
    "attribute_list_store",  # pyright: ignore[reportUnsupportedDunderAll]
    "oauth",  # pyright: ignore[reportUnsupportedDunderAll]
    "auth",  # pyright: ignore[reportUnsupportedDunderAll]
    "aw_proxy",  # pyright: ignore[reportUnsupportedDunderAll]
    "peertrustee",  # pyright: ignore[reportUnsupportedDunderAll]
    "property",  # pyright: ignore[reportUnsupportedDunderAll]
    "subscription",  # pyright: ignore[reportUnsupportedDunderAll]
    "trust",  # pyright: ignore[reportUnsupportedDunderAll]
    "config",  # pyright: ignore[reportUnsupportedDunderAll]
    "aw_web_request",  # pyright: ignore[reportUnsupportedDunderAll]
    # New modern interface
    "interface",
    "ListMetadataContentionError",
]

# Make the new interface easily accessible
from . import interface

# A list's metadata row stayed under sustained compare-and-swap contention
# through every retry -- callers that want to catch this without importing
# actingweb.property_list directly can do `from actingweb import
# ListMetadataContentionError`. handlers/properties.py maps it to 503 with
# Retry-After.
from .property_list import ListMetadataContentionError
