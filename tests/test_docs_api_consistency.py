"""
Guards against documentation teaching hook decorators that do not exist.

Regression suite for the discoverability plan (thoughts/plans/2026-08-22-
ai-agent-discoverability.md, Phase 0): the docs previously taught
``@app.trust_hook``, ``@app.mcp_tool_hook`` and ``@resource_hook``, none of
which exist on ``ActingWebApp`` -- code copied from the docs could not run.
"""

import inspect
import re
from pathlib import Path

DOCS_ROOT = Path(__file__).resolve().parent.parent / "docs"

# Directories/files intentionally excluded from the scan:
# - _build: generated HTML output, not source documentation.
# - migration/: historical guides that deliberately show superseded APIs
#   "as they were" (banners added in Phase 7); not meant to reflect current API.
# - contributing/style-guide.rst: illustrative, deliberately non-real
#   signatures used to demonstrate documentation style (marked in Phase 7).
EXCLUDED_PATHS = {
    DOCS_ROOT / "_build",
    DOCS_ROOT / "migration",
    DOCS_ROOT / "contributing" / "style-guide.rst",
}

# Matches "@app.foo_hook", "@aw_app.foo_hook(", "@self.app.foo_hook" etc.
HOOK_DECORATOR_RE = re.compile(r"@[A-Za-z_][A-Za-z0-9_.]*\.([A-Za-z_]+_hook)\b")


def _is_excluded(path: Path) -> bool:
    return any(
        path == excluded or excluded in path.parents for excluded in EXCLUDED_PATHS
    )


def _hook_names_in_docs() -> set[str]:
    names: set[str] = set()
    for rst_file in DOCS_ROOT.rglob("*.rst"):
        if _is_excluded(rst_file):
            continue
        text = rst_file.read_text(encoding="utf-8", errors="ignore")
        names.update(HOOK_DECORATOR_RE.findall(text))
    return names


def test_doc_api_exists_hook_decorators():
    """Every `@app.*_hook` decorator named in docs/**/*.rst exists on ActingWebApp."""
    from actingweb.interface.app import ActingWebApp

    found = _hook_names_in_docs()
    assert found, "No hook decorators found in docs -- the regex or docs root is wrong"

    missing = sorted(
        name for name in found if not callable(getattr(ActingWebApp, name, None))
    )
    assert not missing, (
        f"docs/**/*.rst reference hook decorator(s) that do not exist on "
        f"ActingWebApp: {missing}"
    )


def test_doc_api_exists_lifecycle_hook_importable():
    """`from actingweb.interface import lifecycle_hook` must succeed."""
    from actingweb.interface import lifecycle_hook

    assert callable(lifecycle_hook)


def test_doc_api_exists_execute_action_hooks_signature():
    """execute_action_hooks' parameter order matches what docs pass positionally."""
    from actingweb.interface.hooks import HookRegistry

    sig = inspect.signature(HookRegistry.execute_action_hooks)
    params = list(sig.parameters)
    # self, action_name, actor, data, auth_context=None
    assert params[:4] == ["self", "action_name", "actor", "data"], (
        f"execute_action_hooks signature changed: {params}. "
        "docs/guides/mcp-applications.rst calls it positionally as "
        "(action_name, actor, data) -- update the docs if this signature moves."
    )
