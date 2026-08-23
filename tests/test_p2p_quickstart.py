"""
Imports examples/p2p_quickstart.py directly -- the same file
docs/guides/p2p-quickstart.rst pulls in with ``literalinclude`` -- so this
tests the code the reader actually sees, not a copy pasted into the docs.
"""

import inspect
import sys
from pathlib import Path

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _import_p2p_quickstart():
    sys.path.insert(0, str(EXAMPLES_DIR))
    try:
        import p2p_quickstart  # type: ignore[import-not-found]

        return p2p_quickstart
    finally:
        sys.path.remove(str(EXAMPLES_DIR))


def test_p2p_quickstart_app_builds_and_registers_hook():
    module = _import_p2p_quickstart()

    assert module.app._subscription_data_hooks.get("properties"), (
        "examples/p2p_quickstart.py did not register a subscription_data_hook "
        "for the 'properties' target"
    )


def test_p2p_quickstart_subscribe_to_peer_keywords_match():
    """
    Guard against a subscribe_to_peer() signature rename silently
    invalidating establish_trust_and_subscribe() -- and the doc it's
    literalincluded into.
    """
    from actingweb.interface.subscription_manager import SubscriptionManager

    sig = inspect.signature(SubscriptionManager.subscribe_to_peer)
    assert "peer_id" in sig.parameters
    assert "target" in sig.parameters


def test_p2p_quickstart_literalinclude_targets_exist():
    """
    p2p-quickstart.rst literalinclude's examples/p2p_quickstart.py by path and
    by "start:"/"end:" marker comments -- a renamed file or marker would
    otherwise leave the published page with an empty or missing code block,
    and -W does not reliably catch that.
    """
    docs_root = Path(__file__).resolve().parent.parent / "docs"
    rst_path = docs_root / "guides" / "p2p-quickstart.rst"
    assert rst_path.exists(), f"{rst_path} does not exist"

    rst_text = rst_path.read_text(encoding="utf-8")
    assert "p2p_quickstart.py" in rst_text

    source_text = (EXAMPLES_DIR / "p2p_quickstart.py").read_text(encoding="utf-8")
    for marker in ("app-setup", "publish", "subscribe"):
        assert f"start: {marker}" in source_text, f"missing '# start: {marker}' marker"
        assert f"end: {marker}" in source_text, f"missing '# end: {marker}' marker"
        assert f":start-after: start: {marker}" in rst_text, (
            f"p2p-quickstart.rst has no literalinclude for marker '{marker}'"
        )
