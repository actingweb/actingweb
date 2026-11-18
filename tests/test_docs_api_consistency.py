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


def test_skill_api_exists_hook_decorators():
    """Every `@app.*_hook` decorator named in skills/**/*.md exists on ActingWebApp.

    A skill teaching a nonexistent decorator is Phase 0's defect with wider
    distribution -- consumers install skills/, not docs/.
    """
    from actingweb.interface.app import ActingWebApp

    skills_root = DOCS_ROOT.parent / "skills"
    names: set[str] = set()
    for md_file in skills_root.rglob("*.md"):
        text = md_file.read_text(encoding="utf-8", errors="ignore")
        names.update(HOOK_DECORATOR_RE.findall(text))

    assert names, (
        "No hook decorators found in skills/ -- the regex or skills root is wrong"
    )

    missing = sorted(
        name for name in names if not callable(getattr(ActingWebApp, name, None))
    )
    assert not missing, (
        f"skills/**/*.md reference hook decorator(s) that do not exist on "
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


# ---------------------------------------------------------------------------
# The release notes name only what the release has
# ---------------------------------------------------------------------------

REPO_ROOT = DOCS_ROOT.parent

# Names the release notes use that belong to another system or are an
# example value, not a name of this library.
NOT_LIBRARY_NAMES = {
    # DynamoDB actions and expressions (the IAM tables, the fault entries)
    "BatchGetItem",
    "ConditionCheckItem",
    "CreateTable",
    "DeleteItem",
    "DescribeTable",
    "GetItem",
    "PutItem",
    "TransactWriteItems",
    "UpdateItem",
    "attribute_not_exists",
    # JSON, JavaScript and URL text
    "NaN",
    "confirm",
    "http",
    # An OAuth2 grant's short name
    "jwt_bearer",
}

# Names the release removed: the text that names them says so. A name stays
# here only while the notes still mention it and the library still lacks it
# (``test_release_notes_removed_list_is_current``).
REMOVED_IN_RELEASE = {
    "CircuitBreaker",
    "CircuitState",
    "DeliveryResult",
    "close_shared_client",
    "get_shared_client",
    "lookup_mode_enabled",
    "validate_google_token_and_check_actor_email",
    "ListAttributeIterator",
    "PropertyIndex",
    "PropertyLegacy",
    "decrease_seq",
    "excluded_properties",
    "get_v1",
    "supports_resync_callbacks_cached",
}

_LITERAL_RE = re.compile(r"``([^`]+)``")
_CALL_RE = re.compile(r"^([A-Za-z_][\w.]*)\(")
_CAMEL_RE = re.compile(
    r"^(?:[A-Za-z_]\w*\.)*[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+(?:\.[a-z_]\w*)*$"
)
_DOTTED_RE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")
_WORD_RE = re.compile(r"[A-Za-z_]\w*")


def _library_names() -> set[str]:
    """Every identifier the library, its examples and its packaging define
    or spell: classes, functions, parameters, attributes, keyword arguments,
    module names, and the words of string constants (JSON keys, settings)."""
    import ast

    names: set[str] = set()
    sources = [
        *(REPO_ROOT / "actingweb").rglob("*.py"),
        *(REPO_ROOT / "examples").rglob("*.py"),
    ]
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names.update(path.relative_to(REPO_ROOT).with_suffix("").parts)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                names.add(node.name)
            elif isinstance(node, ast.arg):
                names.add(node.arg)
            elif isinstance(node, ast.keyword) and node.arg:
                names.add(node.arg)
            elif isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.alias):
                names.add((node.asname or node.name).split(".")[-1])
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names.update(_WORD_RE.findall(node.value))
    for path in [
        REPO_ROOT / "pyproject.toml",
        *(REPO_ROOT / "actingweb").rglob("*.html"),
    ]:
        names.update(_WORD_RE.findall(path.read_text(encoding="utf-8")))
    return names


def _newest_migration_guide() -> Path:
    def version(path: Path) -> tuple[int, ...]:
        return tuple(int(part) for part in path.stem[1:].split("."))

    guides = [
        p
        for p in (DOCS_ROOT / "migration").glob("v*.rst")
        if re.fullmatch(r"v\d+(\.\d+)*", p.stem)
    ]
    return max(guides, key=version)


def _first_changelog_section_with_entries() -> str:
    """The newest changelog section that has entries, padded with blank lines
    so that its line numbers are the file's: the
    ``Unreleased`` section while a release is being written, the release's
    own section once the bump has emptied ``Unreleased``."""
    lines = (REPO_ROOT / "CHANGELOG.rst").read_text(encoding="utf-8").splitlines()
    starts = [
        i - 1
        for i, line in enumerate(lines)
        if i and re.fullmatch(r"-{3,}", line) and lines[i - 1].strip()
    ]
    for start, end in zip(starts, [*starts[1:], len(lines)], strict=True):
        section = lines[start:end]
        if any(line.startswith("- ") for line in section):
            return "\n" * start + "\n".join(section)
    raise AssertionError("CHANGELOG.rst has no section with entries")


def _code_names(text: str) -> dict[str, int]:
    """The literals of ``text`` that are shaped like a name of code, with the
    line each first appears on: a call (``name()``, ``Owner.name(...)``), a
    CamelCase name, a dotted ``actingweb.`` path, or a ``snake_case`` name."""
    found: dict[str, int] = {}
    for number, line in enumerate(text.splitlines(), 1):
        for literal in _LITERAL_RE.findall(line):
            call = _CALL_RE.match(literal)
            if call:
                name = call.group(1)
            elif _CAMEL_RE.match(literal):
                name = literal
            elif _DOTTED_RE.match(literal) and (
                "_" in literal or literal.startswith("actingweb.")
            ):
                name = literal
            else:
                continue
            found.setdefault(name, number)
    return found


def _release_notes() -> dict[str, str]:
    guide = _newest_migration_guide()
    return {
        str(guide.relative_to(REPO_ROOT)): guide.read_text(encoding="utf-8"),
        "CHANGELOG.rst (newest section with entries)": (
            _first_changelog_section_with_entries()
        ),
    }


def test_release_notes_name_only_what_exists():
    """A class, function, option or exception the newest migration guide or
    the newest changelog section names exists in the library, unless the
    release removed it (and the text says so) or it is another system's."""
    known = _library_names()
    allowed = NOT_LIBRARY_NAMES | REMOVED_IN_RELEASE
    problems: list[str] = []
    for source, text in _release_notes().items():
        names = _code_names(text)
        assert len(names) > 50, f"{source}: only {len(names)} names found"
        for name, line in sorted(names.items()):
            missing = [
                part
                for part in name.split(".")
                if part not in known and part not in allowed
            ]
            if missing:
                problems.append(f"{source} line {line}: {name} ({missing[0]})")
    assert not problems, (
        "the release notes name something the library does not have:\n  "
        + "\n  ".join(problems)
    )


def test_release_notes_removed_list_is_current():
    """Every name on the removed list is still named by the notes and still
    absent from the library, so the list cannot outlive what it excuses."""
    known = _library_names()
    text = "\n".join(_release_notes().values())
    stale = sorted(
        name for name in REMOVED_IN_RELEASE if name in known or name not in text
    )
    assert not stale, f"REMOVED_IN_RELEASE has names to drop: {stale}"


# ---------------------------------------------------------------------------
# What is taught does not teach a name the release removed
# ---------------------------------------------------------------------------

# Names that are gone, or only raise, since the release after 3.15.1, and
# the one deprecated hook name. The migration guides and the changelog name
# them on purpose; everything else a consumer learns from may name one only
# to say that it is gone.
REMOVED_OR_DEPRECATED_NAMES = sorted(
    REMOVED_IN_RELEASE
    | {
        "CallbackOauthHandler",
        "FanOutManager",
        "FanOutResult",
        "USE_PROPERTY_LOOKUP_TABLE",
        "circuit_breaker_cooldown",
        "circuit_breaker_threshold",
        "max_payload_for_high_granularity",
        "trust_approved",
        "use_lookup_table",
        "with_legacy_property_index",
    }
)
_SAYS_GONE_RE = re.compile(
    r"\b(removed|is gone|are gone|no longer|deprecated|were removed)\b", re.IGNORECASE
)


def _taught_files() -> list[Path]:
    files = [REPO_ROOT / "README.rst"]
    for root, patterns in (
        (REPO_ROOT / "skills", ("*.md",)),
        (REPO_ROOT / "examples", ("*.py", "*.md", "*.example")),
        (DOCS_ROOT, ("*.rst",)),
    ):
        for pattern in patterns:
            files.extend(root.rglob(pattern))
    return [
        f
        for f in files
        if DOCS_ROOT / "migration" not in f.parents
        and DOCS_ROOT / "_build" not in f.parents
    ]


def _teaches_removed_names(text: str) -> list[tuple[int, str]]:
    """``(line, name)`` for each removed name ``text`` uses without saying,
    within two lines either side, that it is removed or deprecated."""
    lines = text.splitlines()
    found: list[tuple[int, str]] = []
    for name in REMOVED_OR_DEPRECATED_NAMES:
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")
        for index, line in enumerate(lines):
            if not pattern.search(line):
                continue
            around = " ".join(lines[max(0, index - 2) : index + 3])
            if not _SAYS_GONE_RE.search(around):
                found.append((index + 1, name))
    return found


def test_taught_names_are_not_removed():
    """``README.rst``, ``skills/``, ``examples/`` and ``docs/`` outside the
    migration guides name a removed or deprecated name only to say so."""
    files = _taught_files()
    assert len(files) > 40, f"only {len(files)} files scanned"
    problems = [
        f"{path.relative_to(REPO_ROOT)}:{line}: {name}"
        for path in files
        for line, name in _teaches_removed_names(
            path.read_text(encoding="utf-8", errors="ignore")
        )
    ]
    assert not problems, "taught content uses a removed name:\n  " + "\n  ".join(
        problems
    )


def test_the_removed_name_scan_sees_a_use_and_excuses_a_notice():
    """The scan itself: a use is found, a sentence that says the name is
    removed is not, and a longer identifier that contains a name is not."""
    assert _teaches_removed_names("app.with_legacy_property_index(enable=False)") == [
        (1, "with_legacy_property_index")
    ]
    assert not _teaches_removed_names(
        "``with_legacy_property_index()`` was removed in 4.0."
    )
    assert not _teaches_removed_names("def on_trust_approved(actor): ...")
