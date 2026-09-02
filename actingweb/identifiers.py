"""Shared checks for ActingWeb *identifiers*.

An identifier is a name the library matches against permission rules or uses
as a storage key: property and list names, path segments under
``/properties``, MCP tool, prompt, method and resource names, peer ids, the
configured ``fqdn``. Values -- property content, list items, tool input -- are
never identifiers and are never passed through these checks.

C0 (``\\x00-\\x1f``) and C1 (``\\x7f-\\x9f``) control characters have no
legitimate place in an identifier and defeat glob matching: ``*`` compiled
without ``re.DOTALL`` cannot cross a newline, so ``private/\\nsecret`` slipped
past ``excluded_patterns: ["private/*"]``. The permission evaluator denies
any such target outright, and the property store refuses to create one.
"""

import re

CONTROL_CHARACTERS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def has_control_characters(value: str) -> bool:
    """Return True if ``value`` contains a C0 or C1 control character."""
    return CONTROL_CHARACTERS_RE.search(value) is not None


def first_control_character(value: str) -> str | None:
    """Return ``repr()`` of the first control character in ``value``, or None.

    ``repr`` so a newline reads as ``'\\n'`` in an error message rather than
    as an invisible line break.
    """
    m = CONTROL_CHARACTERS_RE.search(value)
    return repr(m.group(0)) if m else None
