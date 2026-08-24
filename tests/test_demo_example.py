"""
Imports examples/demo/application.py directly, so the demo application that
ships alongside this repository is exercised by the same suite that gates
every other change to the library -- the point of moving it here in the
first place.

Unlike examples/mcp_quickstart.py and examples/p2p_quickstart.py, this
module calls integrate_flask() at *import* time rather than under
__main__ -- a WSGI deployment (Serverless/gunicorn) imports
`application:app` and needs it fully wired as a module attribute, so it
cannot be deferred. That triggers DynamoDB table-existence and
lookup-backfill checks (_prewarm_dynamodb_tables /
_check_lookup_backfill_needed in actingweb/interface/app.py), both of
which catch and degrade gracefully on connection failure. tests/conftest.py
always points AWS_DB_HOST at localhost before any test module is imported,
so this import never reaches real AWS regardless of whether DynamoDB Local
is actually running.
"""

import sys
from pathlib import Path

import pytest

DEMO_DIR = Path(__file__).resolve().parent.parent / "examples" / "demo"


def _import_demo_application():
    sys.path.insert(0, str(DEMO_DIR))
    try:
        import application  # type: ignore[import-not-found]

        return application
    finally:
        sys.path.remove(str(DEMO_DIR))


def test_demo_example_app_builds():
    module = _import_demo_application()

    assert module.aw_app is not None
    assert module.app is not None


def test_demo_example_imports_without_sys_path_scaffolding():
    """
    Regression guard for the sys.path.insert hack Phase 1 removed. A WSGI
    loader (Serverless/gunicorn importing a dotted module path such as
    examples.demo.application) puts the deployment root on sys.path, not
    examples/demo/ itself -- unlike running the file directly (Python adds
    the script's own directory) or _import_demo_application() above (which
    inserts examples/demo/ itself, the same thing the removed hack did, so
    it cannot catch this). Loading by file path with no sys.path scaffolding
    reproduces the WSGI case: application.py must add its own directory to
    sys.path itself for `from shared_hooks import ...` to resolve.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "demo_application_wsgi_check", DEMO_DIR / "application.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.app is not None


def test_demo_example_registers_all_shared_hook_categories():
    """
    shared_hooks/__init__.py's docstring promises eight hook categories --
    this checks all eight actually landed on the registry, not just that
    register_all_shared_hooks(app) ran without raising.
    """
    module = _import_demo_application()
    hooks = module.aw_app.hooks

    assert hooks._subscription_hooks, "subscription hook not registered"
    assert hooks._lifecycle_hooks.get("trust_approved"), "trust hook not registered"
    assert hooks._lifecycle_hooks.get("actor_created"), "lifecycle hook not registered"
    assert hooks._method_hooks, "method hooks not registered"
    assert hooks._action_hooks, "action hooks not registered"
    assert hooks._callback_hooks.get("email_verify"), "callback hook not registered"
    assert hooks._property_hooks.get("email"), "property hook not registered"
    assert hooks._callback_hooks.get("www"), "ui hook (www callback) not registered"


def test_demo_example_protected_properties_are_actually_blocked():
    """
    Regression test for a real access-control bug a review pass caught:
    the wildcard "*" property hook tried to identify protected properties
    via path[0], but HookRegistry.execute_property_hooks only ever passes
    the nested-subkey remainder as `path` -- never the top-level property
    name -- so protection for auth_token/created_at/actor_type silently
    never fired for ordinary top-level access (path is always [] there).
    Fixed by registering exact-name hooks instead. Exercises the real
    hook-execution path (not just that a hook is registered under the
    name) with auth_context=None, which _check_hook_permission treats as
    unauthenticated/no-peer-context and allows through unconditionally --
    so a None result here can only come from the hook itself blocking it.
    """
    module = _import_demo_application()
    hooks = module.aw_app.hooks

    class _FakeActor:
        id = "test-actor"

    actor = _FakeActor()
    assert hooks.execute_property_hooks("auth_token", "get", actor, "secret") is None
    assert hooks.execute_property_hooks("auth_token", "put", actor, "new-value") is None
    assert (
        hooks.execute_property_hooks("created_at", "delete", actor, "2024-01-01")
        is None
    )
    assert hooks.execute_property_hooks("actor_type", "delete", actor, "myself") is None


def test_demo_example_nuke_endpoint_rejects_missing_or_wrong_secret():
    """
    /nuke deletes every actor in the configured DynamoDB tables -- a
    destructive endpoint gated behind NUKE_SECRET. This guards the gate
    itself (missing secret -> 403, wrong secret -> 403) so a future refactor
    can't accidentally loosen it without a test noticing. Does not exercise
    the unset-NUKE_SECRET -> 503 path, since tests/conftest.py doesn't set
    NUKE_SECRET and module caching (see _import_demo_application) means an
    earlier test in this file may have already imported the module under a
    different environment.
    """
    import os

    os.environ.setdefault("NUKE_SECRET", "test-nuke-secret-not-real")
    module = _import_demo_application()
    client = module.app.test_client()

    resp = client.get("/nuke")
    assert resp.status_code == 403

    resp = client.get("/nuke?secret=wrong")
    assert resp.status_code == 403


@pytest.mark.slow
def test_demo_example_not_in_built_wheel():
    """
    examples/ is deliberately absent from pyproject.toml's [tool.poetry]
    include -- this guards that decision against a future edit reintroducing
    it. Builds to the repo's own dist/ (CI pins Poetry 1.7.0, whose `build`
    command has no --output/-o flag -- a scratch-directory build was tried
    first and fails there) and finds the wheel by its exact, deterministic
    filename rather than by scanning dist/, which accumulates wheels from
    every past release with no naming convention that sorts newest-last.
    """
    import subprocess
    import zipfile

    import actingweb

    repo_root = Path(__file__).resolve().parent.parent
    try:
        subprocess.run(
            ["poetry", "build", "--format", "wheel"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise AssertionError(
            f"poetry build failed:\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}"
        ) from e

    wheel_path = (
        repo_root / "dist" / f"actingweb-{actingweb.__version__}-py3-none-any.whl"
    )
    assert wheel_path.exists(), f"expected wheel not found: {wheel_path}"

    with zipfile.ZipFile(wheel_path) as wheel:
        leaked = [n for n in wheel.namelist() if n.startswith("examples/")]
    assert not leaked, f"examples/ leaked into wheel: {leaked}"
