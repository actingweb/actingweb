__version__ = "3.1"

__all__ = [
    "actor",
    "attribute",
    "oauth",
    "auth",
    "aw_proxy",
    "peertrustee",
    "property",
    "subscription",
    "trust",
    "config",
    "aw_web_request",
    # New modern interface
    "interface",
]

# Make the new interface easily accessible
from . import interface
