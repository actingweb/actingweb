"""The migration guide's commands run, and the sections the library quotes exist.

Two ways the guide and the library drift apart without the docs build
noticing (its references are prose, not Sphinx labels):

- a command line in the guide names a console script that is not installed,
  or arguments its parser refuses, and an operator copying it gets an error
  in the middle of an upgrade;
- a message of the library names a guide section (``guide_section("...")``)
  whose heading was renamed or removed in a restructure.

The guide is found through ``actingweb.migration_guide.GUIDE_PATH``, the
constant the library's messages use, never by a file name of its own.
"""

from __future__ import annotations

import argparse
import importlib
import re
import shlex
import sys
import tomllib
from pathlib import Path

import pytest

from actingweb.migration_guide import GUIDE_PATH

REPO_ROOT = Path(__file__).resolve().parent.parent
GUIDE = REPO_ROOT / GUIDE_PATH

# An operator command as the guide shows it: a console script with at least
# one argument, in an inline literal or on a line of a code block. A bare
# script name in prose is a name, not a command line.
_LITERAL_COMMAND_RE = re.compile(r"``(actingweb-[a-z][a-z-]* [^`]+)``")
_BLOCK_COMMAND_RE = re.compile(r"^\s+(?:\$ )?(actingweb-[a-z][a-z-]* [^#\n]+)")
_PLACEHOLDER_RE = re.compile(r"<[^>]+>|\.\.\.")


def _console_scripts() -> dict[str, str]:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return dict(data["tool"]["poetry"]["scripts"])


def _guide_commands() -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    in_block = False
    for number, line in enumerate(GUIDE.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(".. code-block::") or stripped.endswith("::"):
            in_block = True
            continue
        if in_block and stripped and not line.startswith((" ", "\t")):
            in_block = False
        matches = [m.group(1) for m in _LITERAL_COMMAND_RE.finditer(line)]
        if in_block:
            block = _BLOCK_COMMAND_RE.match(line)
            if block:
                matches.append(block.group(1))
        for command in matches:
            found.append((number, command.strip().rstrip(".,;:)\\").strip()))
    return found


class _Parsed(Exception):
    """Raised right after a successful parse, so ``main`` does no work."""


def _parses(entry_point: str, argv: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    module_name, _, function = entry_point.partition(":")
    module = importlib.import_module(module_name)
    original = argparse.ArgumentParser.parse_args

    def parse_then_stop(self, args=None, namespace=None):  # type: ignore[no-untyped-def]
        original(self, args, namespace)
        raise _Parsed

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", parse_then_stop)
    monkeypatch.setattr(sys, "argv", ["prog", *argv])
    with pytest.raises(_Parsed):
        getattr(module, function)()


def test_guide_commands_exist_and_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    scripts = _console_scripts()
    commands = _guide_commands()
    assert commands, f"no operator command found in {GUIDE_PATH}"
    for number, command in commands:
        words = shlex.split(_PLACEHOLDER_RE.sub("x", command))
        name, argv = words[0], words[1:]
        assert name in scripts, f"{GUIDE_PATH}:{number}: {name} is not a console script"
        with monkeypatch.context() as patch:
            try:
                _parses(scripts[name], argv, patch)
            except SystemExit as exit_:
                pytest.fail(
                    f"{GUIDE_PATH}:{number}: `{command}` is refused by its parser "
                    f"(exit {exit_.code})"
                )


_QUOTED_RE = re.compile(r"""guide_section\(\s*(["'])(.+?)\1\s*\)""")


def _quoted_titles() -> dict[str, str]:
    titles: dict[str, str] = {}
    for path in (REPO_ROOT / "actingweb").rglob("*.py"):
        for match in _QUOTED_RE.finditer(path.read_text(encoding="utf-8")):
            titles.setdefault(match.group(2), str(path.relative_to(REPO_ROOT)))
    return titles


def _headings() -> set[str]:
    lines = GUIDE.read_text(encoding="utf-8").splitlines()
    return {
        line.strip()
        for line, under in zip(lines, lines[1:], strict=False)
        if line.strip() and re.fullmatch(r"([=\-~^\"'*+#])\1{2,}", under.strip())
    }


def test_quoted_guide_sections_are_headings() -> None:
    titles = _quoted_titles()
    assert titles, "no library message quotes a guide section"
    headings = _headings()
    missing = {t: where for t, where in titles.items() if t not in headings}
    assert not missing, (
        f"quoted sections that are not headings in {GUIDE_PATH}: {missing}"
    )


def test_no_message_spells_the_guide_path_itself() -> None:
    """Every reference goes through the constant, so a rename is one edit."""
    stem = Path(GUIDE_PATH).name
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "actingweb").rglob("*.py")
        if path.name != "migration_guide.py"
        and re.search(r"migration/v\d+\.\d+\.rst", path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        f"spell the guide through migration_guide ({stem}): {offenders}"
    )
