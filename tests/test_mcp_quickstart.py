"""
Imports examples/mcp_quickstart.py directly -- the same file
docs/guides/mcp-quickstart.rst pulls in with ``literalinclude`` -- so this
tests the code the reader actually sees, not a copy pasted into the docs.
"""

import sys
from pathlib import Path

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _import_mcp_quickstart():
    sys.path.insert(0, str(EXAMPLES_DIR))
    try:
        import mcp_quickstart  # type: ignore[import-not-found]

        return mcp_quickstart
    finally:
        sys.path.remove(str(EXAMPLES_DIR))


def test_mcp_quickstart_app_builds_and_registers_mcp_tool():
    """
    Importing the module must not touch the database -- integrate_fastapi()
    (which triggers table existence checks) only runs under __main__, so
    this assertion doubles as a regression guard against that leaking back
    into module scope.
    """
    module = _import_mcp_quickstart()

    tool_hooks = module.aw.hooks._action_hooks.get("create_note", [])
    assert tool_hooks, "create_note action hook was not registered"
    assert getattr(tool_hooks[0], "_mcp_type", None) == "tool"


def test_mcp_quickstart_registers_mcp_prompt():
    module = _import_mcp_quickstart()

    method_hooks = module.aw.hooks._method_hooks.get("analyze_notes", [])
    assert method_hooks, "analyze_notes method hook was not registered"
    assert getattr(method_hooks[0], "_mcp_type", None) == "prompt"


def test_mcp_quickstart_literalinclude_targets_exist():
    """
    mcp-quickstart.rst literalinclude's examples/mcp_quickstart.py by path
    and by "start:"/"end:" marker comments -- a renamed file or marker
    would otherwise leave the published page with an empty or missing code
    block, and -W does not reliably catch that.
    """
    docs_root = Path(__file__).resolve().parent.parent / "docs"
    rst_path = docs_root / "guides" / "mcp-quickstart.rst"
    assert rst_path.exists(), f"{rst_path} does not exist"

    rst_text = rst_path.read_text(encoding="utf-8")
    assert "mcp_quickstart.py" in rst_text

    source_text = (EXAMPLES_DIR / "mcp_quickstart.py").read_text(encoding="utf-8")
    assert "start: app-setup" in source_text
    assert "end: app-setup" in source_text
    assert ":start-after: start: app-setup" in rst_text
