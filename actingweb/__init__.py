__version__ = "3.13.0"

# Modules are lazy-loaded on-demand, so they're not imported here
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
