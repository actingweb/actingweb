__version__ = "3.7.2"

# Modules are lazy-loaded on-demand, so they're not imported here
__all__ = [
    "actor",  # pyright: ignore[reportUnsupportedDunderAll]
    "attribute",  # pyright: ignore[reportUnsupportedDunderAll]
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
]

# Make the new interface easily accessible
from . import interface
