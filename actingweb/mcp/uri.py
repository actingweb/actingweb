"""URI-template matching for MCP resources.

Shared by the sync and async MCP handlers to match a concrete resource URI
against a registered template containing ``{variable}`` placeholders.
"""

import logging
import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any

logger = logging.getLogger(__name__)


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
    pattern = "^" + "".join(pattern_parts) + "\\Z"

    match = re.match(pattern, uri)
    if not match:
        return None
    return {k: v for k, v in match.groupdict().items() if v is not None}


def resolve_resource(
    uri: str, method_hooks: Mapping[str, Iterable[Callable[..., Any]]]
) -> tuple[str, Callable[..., Any], dict[str, Any], dict[str, str]] | None:
    """Find the resource hook that serves ``uri``.

    A hook's ``uri_template`` (or legacy ``uri``, or ``actingweb://<name>``)
    is matched first; when it does not match, a declared ``uri_pattern`` is
    tried as a full regex match (a resource declared only by pattern). The
    first hook that matches wins.

    Returns:
        ``(method_name, hook, metadata, variables)``, where ``variables``
        holds the template's extracted values (empty for a pattern match),
        or None when no resource serves ``uri``.
    """
    from .decorators import get_mcp_metadata, is_mcp_exposed

    for method_name, hooks in method_hooks.items():
        for hook in hooks:
            if not is_mcp_exposed(hook):
                continue
            metadata = get_mcp_metadata(hook)
            if not metadata or metadata.get("type") != "resource":
                continue
            template = (
                metadata.get("uri_template")
                or metadata.get("uri")
                or f"actingweb://{method_name}"
            )
            try:
                variables = match_uri_template(str(template), str(uri))
            except Exception:  # folds DbError: no DB access
                variables = None
            if variables is not None:
                return method_name, hook, metadata, variables
            pattern = metadata.get("uri_pattern")
            if not pattern:
                continue
            try:
                if re.fullmatch(pattern, str(uri)):
                    return method_name, hook, metadata, {}
            except re.error:
                logger.warning(f"Invalid URI pattern in resource metadata: {pattern}")
    return None
