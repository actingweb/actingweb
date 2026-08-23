"""
Guards the actingweb/__init__.py module docstring (Phase 5 of
thoughts/plans/2026-08-22-ai-agent-discoverability.md) against being dropped
in a future refactor, and __all__ against an over-eager edit that would
break the lazy-load path it drives.
"""

import actingweb


def test_init_docstring_present_and_names_key_things():
    assert actingweb.__doc__
    assert "ActingWebApp" in actingweb.__doc__
    assert "readthedocs.io" in actingweb.__doc__


def test_init_all_unchanged():
    assert actingweb.__all__ == [
        "actor",
        "attribute",
        "attribute_list",
        "attribute_list_store",
        "oauth",
        "auth",
        "aw_proxy",
        "peertrustee",
        "property",
        "subscription",
        "trust",
        "config",
        "aw_web_request",
        "interface",
        "ListMetadataContentionError",
    ]


def test_init_lazy_load_still_works():
    # __all__ driving the lazy-load path must still resolve.
    import importlib

    module = importlib.import_module("actingweb.actor")
    assert module is not None
