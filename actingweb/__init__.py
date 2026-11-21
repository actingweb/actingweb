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

__version__ = "4.0.0rc2"

# Modules below are lazy-loaded on-demand (`from actingweb import actor`,
# etc.). Most are here for backward compatibility with pre-3.x code and are
# NOT the recommended API -- use `from actingweb.interface import
# ActingWebApp` and `from actingweb.mcp import mcp_tool` instead, per the
# module docstring above. attribute_list and attribute_list_store are
# current: reach them through ActorInterface.attribute_lists(bucket).
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
    "ListItemTooLargeError",
    "ListItemSpanError",
    "ListItemNewerFormatError",
    "UNRESOLVED",
    "AppendOnceResult",
]

# Make the new interface easily accessible
from . import interface

# Typed list errors, importable without reaching into actingweb.property_list:
# - ListMetadataContentionError: a list's metadata row stayed under sustained
#   compare-and-swap contention through every retry. handlers/properties.py
#   maps it to 503 with Retry-After.
# - ListItemTooLargeError: an item's encoded size is over list_item_max_bytes
#   (or the span threshold where it cannot span), raised before any write.
#   handlers/properties.py maps it to 413.
# - ListItemSpanError: a spanned item's body rows are missing (a
#   ListCorruptionError; handlers/properties.py maps it to 409).
# - ListItemNewerFormatError: an item or list a later library version
#   stored (its envelope's need, or the list's format); not corruption, and
#   no repair touches it. Answered 409 with the code list_item_newer_format.
# - UNRESOLVED: the slot value items_with_handles(resolve=False) leaves for a
#   spanned item whose bodies it did not read.
# - AppendOnceResult: what ListProperty.append_once() returns.
from .property_list import (
    UNRESOLVED,
    AppendOnceResult,
    ListItemNewerFormatError,
    ListItemSpanError,
    ListItemTooLargeError,
    ListMetadataContentionError,
)
