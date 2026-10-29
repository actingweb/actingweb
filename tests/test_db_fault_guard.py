"""Guard: no broad ``except`` in the library folds a database fault by accident.

The fault contract (3.16) makes a backend fault raise ``DbError`` and has the
integrations answer it with 503. A broad handler (``except:``,
``except Exception``, ``except BaseException`` or a tuple containing one)
catches ``DbError`` too and can turn it into absence, success or "allowed".
Two review rounds each found the next such handler one frame further up, so
this test enumerates them instead.

An ``except DbError`` clause that does not re-raise is a fold too and needs
the marker. Every broad handler under ``actingweb/`` must do one of:

- come after an ``except DbError`` (or ``CreatorTaken``) clause of the same
  ``try``;
- always re-raise (its last statement is a bare ``raise``, ``raise e``, or a
  raise of a fault type such as ``DbError`` or ``TokenStoreUnavailable``), so
  it folds nothing; raising another type converts the fault and counts as a
  fold;
- carry the marker ``# folds DbError: <reason>`` on its ``except`` line, for a
  fold that is deliberate (best-effort work after the real write committed,
  a notification that must not fail the request).

``contextlib.suppress(Exception)`` needs the same marker on its line.

``actingweb/db/`` is excluded: it is where ``DbError`` is raised, and its
folds are the ``strict=False`` reads that ``tests/test_db_fault_contract.py``
pins.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "actingweb"
MARKER = "# folds DbError:"
DB_NAMES = {"DbError", "CreatorTaken"}
BROAD = {"Exception", "BaseException"}


def _names(node: ast.expr | None) -> set[str]:
    if node is None:
        return {"<bare>"}
    if isinstance(node, ast.Tuple):
        out: set[str] = set()
        for elt in node.elts:
            out |= _names(elt)
        return out
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {node.attr}
    return set()


def _is_broad(handler: ast.ExceptHandler) -> bool:
    names = _names(handler.type)
    return "<bare>" in names or bool(names & BROAD)


# Exceptions a broad handler may raise in place of a caught fault: the fault
# itself, or the store-fault types callers already answer with 503.
FAULT_TYPES = DB_NAMES | {"TokenStoreUnavailable", "StoreFault"}


def _always_raises(handler: ast.ExceptHandler) -> bool:
    """The handler ends in a bare ``raise`` or raises a fault type.

    One that raises another type (``raise ValueError("...") from e``) converts
    a fault into a different answer, so it needs a ``DbError`` clause ahead
    of it like any fold.
    """
    if not handler.body or not isinstance(handler.body[-1], ast.Raise):
        return False
    exc = handler.body[-1].exc
    if exc is None:
        return True
    target = exc.func if isinstance(exc, ast.Call) else exc
    names = _names(target)
    if handler.name and isinstance(exc, ast.Name) and exc.id == handler.name:
        return True  # ``raise e`` re-raises the caught exception
    return bool(names & FAULT_TYPES)


def _violations() -> list[str]:
    found: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT.parent)
        if rel.parts[:2] == ("actingweb", "db"):
            continue
        source = path.read_text()
        lines = source.splitlines()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Try | ast.TryStar):
                seen_db = False
                for handler in node.handlers:
                    names = _names(handler.type)
                    if names & DB_NAMES:
                        seen_db = True
                        # An ``except DbError`` that does not re-raise folds
                        # the fault itself, so it needs the same marker.
                        if (
                            not _always_raises(handler)
                            and MARKER not in (lines[handler.lineno - 1])
                        ):
                            found.append(f"{rel}:{handler.lineno} (except DbError)")
                        continue
                    if not _is_broad(handler) or seen_db:
                        continue
                    if _always_raises(handler):
                        continue
                    if MARKER in lines[handler.lineno - 1]:
                        continue
                    found.append(f"{rel}:{handler.lineno}")
            elif isinstance(node, ast.With):
                for item in node.items:
                    call = item.context_expr
                    if (
                        isinstance(call, ast.Call)
                        and _names(call.func) & {"suppress"}
                        and any(_names(a) & BROAD for a in call.args)
                        and MARKER not in lines[node.lineno - 1]
                    ):
                        found.append(f"{rel}:{node.lineno} (suppress)")
    return found


def test_no_broad_except_folds_a_db_fault_unmarked() -> None:
    violations = _violations()
    assert not violations, (
        "Broad except without a DbError clause ahead of it or a "
        f"'{MARKER} <reason>' marker ({len(violations)}):\n" + "\n".join(violations)
    )
