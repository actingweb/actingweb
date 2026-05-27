"""URI-template matching for MCP resources.

Shared by the sync and async MCP handlers to match a concrete resource URI
against a registered template containing ``{variable}`` placeholders.
"""

import re


def match_uri_template(template: str, uri: str) -> dict[str, str] | None:
    """Match a URI against a simple template with ``{variables}``.

    Returns a dict of extracted variables on match, otherwise ``None``.
    """
    pattern_parts: list[str] = []
    last_index = 0
    for m in re.finditer(r"{(\w+)}", template):
        start, end = m.span()
        var_name = m.group(1)
        # Escape the static part preceding the variable.
        pattern_parts.append(re.escape(template[last_index:start]))
        # Conservative matcher for the variable (no slashes).
        pattern_parts.append(f"(?P<{var_name}>[^/]+)")
        last_index = end
    pattern_parts.append(re.escape(template[last_index:]))
    pattern = "^" + "".join(pattern_parts) + "$"

    match = re.match(pattern, uri)
    if not match:
        return None
    return {k: v for k, v in match.groupdict().items() if v is not None}
