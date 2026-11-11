"""
Permission Evaluation System for ActingWeb Unified Access Control.

This module provides the core permission evaluation logic that combines:
1. Base permissions from trust types
2. Individual trust relationship overrides
3. Pattern matching and permission resolution
4. Unified permission checking API

The evaluator supports checking permissions for:
- Properties (read/write/delete operations on property paths)
- Methods (ActingWeb method calls)
- Actions (ActingWeb action calls)
- Tools (MCP tool access)
- Resources (MCP resource access)
- Prompts (MCP prompt access)
"""

import functools
import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from actingweb.db import get_trust

from . import config as config_class
from .db.exceptions import DbError
from .identifiers import has_control_characters
from .trust_permissions import (
    get_trust_permission_store,
    is_client_peer,
    merge_permissions,
    override_applies,
)
from .trust_type_registry import get_registry as get_trust_type_registry

logger = logging.getLogger(__name__)

# Upper bound on cached compiled glob patterns per evaluator; see __init__.
_PATTERN_CACHE_MAX_ENTRIES = 1024


def _glob_tokens(pattern: str) -> list[tuple[str, str]]:
    r"""Scan a glob pattern into ``("lit", char)``, ``("any", "")`` (``?``)
    and ``("star", "")`` tokens.

    A backslash escapes the next character when it is ``*``, ``?`` or
    ``\\``: ``\*`` is a literal ``*``, ``\?`` a literal ``?``, ``\\`` a
    literal backslash. A backslash before anything else, or at the end, is a
    literal backslash. There are no character classes: ``[abc]`` is literal.
    """
    tokens: list[tuple[str, str]] = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "\\":
            if i + 1 < n and pattern[i + 1] in "*?\\":
                tokens.append(("lit", pattern[i + 1]))
                i += 2
                continue
            tokens.append(("lit", "\\"))
        elif c == "*":
            if not tokens or tokens[-1][0] != "star":
                tokens.append(("star", ""))
        elif c == "?":
            tokens.append(("any", ""))
        else:
            tokens.append(("lit", c))
        i += 1
    return tokens


def glob_has_wildcard(pattern: str) -> bool:
    """Whether the pattern holds an unescaped ``*`` or ``?``."""
    return any(kind != "lit" for kind, _ in _glob_tokens(pattern))


def glob_to_regex(pattern: str) -> str:
    """Translate a glob pattern into an anchored regex source (``^...\\Z``,
    to be compiled with ``re.DOTALL``).

    Linear-time: each ``*`` that is followed by another ``*`` later in the
    pattern becomes an atomic lazy segment ``(?>.*?fixed)`` as
    ``fnmatch.translate`` emits, and the last ``*`` a plain ``.*`` before the
    final literal run, so a pattern of many stars cannot backtrack
    exponentially. The patterns come from peers (permission callbacks, property
    filters), so that matters.
    """
    segments: list[list[str]] = [[]]
    for kind, char in _glob_tokens(pattern):
        if kind == "star":
            segments.append([])
        else:
            segments[-1].append("." if kind == "any" else re.escape(char))
    stars = len(segments) - 1
    parts = ["".join(segments[0])]
    for index in range(1, stars + 1):
        fixed = "".join(segments[index])
        if index < stars:
            parts.append(f"(?>.*?{fixed})")
        else:
            parts.append(f".*{fixed}")
    # ``\\Z`` rather than ``$``: ``$`` also matches just before a trailing
    # newline, so ``notes$`` accepted ``notes\n``.
    return "^" + "".join(parts) + "\\Z"


@functools.lru_cache(maxsize=_PATTERN_CACHE_MAX_ENTRIES)
def _compile_glob(pattern: str) -> re.Pattern[str]:
    # DOTALL makes ``*`` and ``?`` match a newline the way they match every
    # other character, which is what a glob means. An LRU, not a dict that
    # clears itself: a peer sending distinct patterns must not flush the
    # authorization hot set.
    return re.compile(glob_to_regex(pattern), re.DOTALL)


def glob_match(target: str, pattern: str) -> bool:
    """Whether ``target`` matches the glob ``pattern``.

    Supports ``*`` (any characters), ``?`` (one character) and the escapes
    ``\\*``, ``\\?`` and ``\\\\``; matching is case-sensitive and there are no
    character classes. A pattern of ``"*"`` matches everything. A pattern
    ending in ``://`` with no unescaped wildcard is matched as that pattern
    plus ``*``, so ``notes://`` matches ``notes://work/projects``. ``..``
    segments are not normalised: a resource reader that maps URIs to storage
    validates its own path.
    """
    if pattern == "*":
        return True
    # The equality shortcut is only for patterns without a backslash:
    # otherwise ``a\*b`` would match the literal string ``a\*b`` as well as
    # ``a*b``.
    if "\\" not in pattern and pattern == target:
        return True
    if pattern.endswith("://") and not glob_has_wildcard(pattern):
        pattern = pattern + "*"
    return bool(_compile_glob(pattern).match(target))


class PermissionResult(Enum):
    """Permission evaluation results."""

    ALLOWED = "allowed"
    DENIED = "denied"
    NOT_FOUND = "not_found"  # No matching rule found


class PermissionType(Enum):
    """Types of permissions that can be evaluated."""

    PROPERTIES = "properties"
    METHODS = "methods"
    ACTIONS = "actions"
    TOOLS = "tools"
    RESOURCES = "resources"
    PROMPTS = "prompts"


# Categories where an exclusion covers a path's descendants (a property or
# resource tree), and where a rule the grant states but does not match denies
# (3.16; methods and actions follow in a later phase of the same plan).
TREE_CATEGORIES = frozenset({PermissionType.PROPERTIES, PermissionType.RESOURCES})
# Categories where a rule the grant states but that does not match a named
# target denies (DENIED, not NOT_FOUND): the access table never overrides a
# stated rule (3.16). Tools and prompts are MCP's, which denies anything but
# ALLOWED already.
STATED_RULE_CATEGORIES = TREE_CATEGORIES | {
    PermissionType.METHODS,
    PermissionType.ACTIONS,
}


def exclusion_patterns(rules: Any) -> list[str]:
    """The patterns a rule excludes: its ``denied`` and ``excluded_patterns``."""
    if not isinstance(rules, dict):
        return []
    out: list[str] = []
    for key in ("denied", "excluded_patterns"):
        value = rules.get(key)
        if isinstance(value, list):
            out.extend(str(p) for p in value)
    return out


def _excluded_by(patterns: list[str], node: str) -> bool:
    """Whether ``node`` itself is excluded: a pattern matches it, or a pattern
    ending in ``/*`` has a head (the pattern without those two characters)
    that matches it -- ``private/*`` names the node ``private`` too."""
    for pattern in patterns:
        if glob_match(node, pattern):
            return True
        if pattern.endswith("/*") and glob_match(node, pattern[:-2]):
            return True
    return False


def path_excluded(rules: Any, path: str) -> bool:
    """Whether ``path`` or any ancestor of it is excluded by ``rules`` (3.16).

    An exclusion covers its node and the node's descendants: with
    ``settings/private`` excluded, ``settings/private/x`` is excluded too.
    The one matcher (:func:`glob_match`, where ``*`` crosses ``/``) decides
    each node.
    """
    patterns = exclusion_patterns(rules)
    if not patterns or not path:
        return False
    parts = path.split("/")
    return any(
        _excluded_by(patterns, "/".join(parts[: i + 1])) for i in range(len(parts))
    )


def drop_excluded(rules: Any, path: str, value: Any) -> Any:
    """``value`` (the value at ``path``) without its excluded descendants.

    An object is walked at any depth; a key whose path (``<path>/<key>``) is
    excluded is dropped with everything under it. Arrays are not descended
    (a list's unit is its name), and anything that is not an object is
    returned as it is. With no exclusion in ``rules`` the value is returned
    untouched, without a walk.

    A value nested deeper than :data:`MAX_FILTER_DEPTH` (or text nested
    beyond the JSON parser, :data:`TOO_DEEP`) cannot be walked safely: it is
    withheld, ``None``, rather than returned unfiltered (3.16).
    """
    patterns = exclusion_patterns(rules)
    if not patterns:
        return value
    if value is TOO_DEEP:
        return None
    try:
        return _drop(patterns, path, value, 1)
    except _TooDeepToWalk:
        return None


MAX_FILTER_DEPTH = 100
"""How deep the exclusion filter walks a value (objects and arrays). A value
nested deeper is withheld from a peer whose grant excludes anything, and a
peer's write of one is refused (3.16): the walk and the comparisons after it
recurse, and Python's recursion limit would end them with an error."""


class _TooDeep:
    """The type of :data:`TOO_DEEP`."""

    def __repr__(self) -> str:
        return "TOO_DEEP"


TOO_DEEP: Any = _TooDeep()
"""What :func:`as_json_object` answers for JSON text nested beyond the
parser: an object the filter cannot read, so it is withheld, not sent as
text."""


def _deeper_than(value: Any, limit: int) -> bool:
    """Whether ``value`` nests objects or arrays more than ``limit`` deep
    (walked without recursion)."""
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, dict):
            children: Any = node.values()
        elif isinstance(node, list):
            children = node
        else:
            continue
        if depth > limit:
            return True
        stack.extend((child, depth + 1) for child in children)
    return False


class _TooDeepToWalk(Exception):
    """A kept part of the value nests deeper than :data:`MAX_FILTER_DEPTH`."""


def _drop(patterns: list[str], path: str, value: Any, depth: int) -> Any:
    """One walk (3.16): objects are filtered, kept arrays only measured; a
    kept part deeper than :data:`MAX_FILTER_DEPTH` raises (an excluded part
    is dropped unwalked, whatever its depth)."""
    if isinstance(value, list):
        if _deeper_than(value, MAX_FILTER_DEPTH - depth + 1):
            raise _TooDeepToWalk()
        return value
    if not isinstance(value, dict):
        return value
    if depth > MAX_FILTER_DEPTH:
        raise _TooDeepToWalk()
    kept: dict[str, Any] = {}
    for key, child in value.items():
        child_path = f"{path}/{key}" if path else str(key)
        if _excluded_by(patterns, child_path):
            continue
        kept[key] = _drop(patterns, child_path, child, depth + 1)
    return kept


def as_json_object(value: Any) -> Any:
    """A value that is JSON text of an object or array, parsed; None for
    anything else (a plain string, a number, text that is not JSON);
    :data:`TOO_DEEP` for text nested beyond the parser (withheld by the
    filter, not sent as text). The stores hand objects back as text, and a
    property can be written as the text of an object (3.16: the grant filter
    walks objects only).

    Text is read as a JSON client reads it (3.16): a client parses the UTF-8
    bytes it receives with ``json.loads(bytes)``, which skips a byte-order
    mark and reads UTF-16/32, so such text is JSON here too (a filter that
    took it for plain text sent the client an object it never filtered).
    Text that opens no object or array that way is not parsed."""
    if isinstance(value, str):
        head = value.lstrip()[:1]
        if head in ("[", "{") and "\x00" not in value[:4]:
            text: str = value
        elif head in ("\ufeff", "\x00") or "\x00" in value[:4]:
            # What a client reads from the UTF-8 bytes of this text.
            client = _client_text(value.encode("utf-8", "surrogatepass"))
            if client is None:
                return None
            text = client
        else:
            return None
    elif isinstance(value, bytes | bytearray):
        client = _client_text(bytes(value))
        if client is None:
            return None
        text = client
    else:
        return None
    try:
        parsed = json.loads(text)
    except RecursionError:
        return TOO_DEEP
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict | list) else None


def _client_text(data: bytes) -> str | None:
    """``data`` decoded as ``json.loads`` decodes bytes (BOM, UTF-16/32,
    ``surrogatepass``), when it opens an object or array; else None."""
    try:
        text = data.decode(json.detect_encoding(data), "surrogatepass")
    except (UnicodeDecodeError, LookupError):
        return None
    # The codec consumed the one byte-order mark ``json.loads`` skips; no
    # other is stripped (3.16: every leading one was, so text a client
    # rejects was parsed here).
    return text if text.lstrip()[:1] in ("[", "{") else None


def withheld(value: Any, filtered: Any) -> bool:
    """Whether :func:`drop_excluded` withheld ``value`` (too deep to
    filter): it answered ``None`` for a value that was not ``None``. The
    caller leaves the value out (3.16), never sends it as ``null``."""
    return filtered is None and value is not None


def beyond_parser(value: Any) -> bool:
    """Whether ``value`` is JSON text nested beyond the parser (3.16). Such
    text is never sent to a peer, whatever its grant (nothing about it can
    be checked: a sub-path, an exclusion, a read hook); the owner reads it
    as plain text is read. A caller that parses the value anyway uses
    :func:`as_json_object` and compares with :data:`TOO_DEEP` instead."""
    return as_json_object(value) is TOO_DEEP


def holds_excluded(rules: Any, path: str, *values: Any) -> bool:
    """Whether any of ``values`` (each the value at ``path``) holds an
    excluded descendant. Decided on the data, so it is defined for every
    pattern (``*/secret``, ``*private*``, ``mem*/x``)."""
    for v in values:
        kept = drop_excluded(rules, path, v)
        if (kept is None and v is not None) or kept != v:
            return True  # a withheld value counts as holding one
    return False


@dataclass(frozen=True)
class GrantSnapshot:
    """What one peer is granted at one actor, read once (3.16).

    ``has_row``/``approved``: the actor's trust row for the peer and its
    approval. ``relationship``: the row's trust type. ``is_client``: the peer
    is an OAuth2/MCP client. ``permissions``: the effective rules (the type's
    base merged with the peer's override), ``None`` when the type is not in
    the registry (such a peer's categories are all "not mentioned").
    """

    actor_id: str
    peer_id: str
    has_row: bool
    approved: bool
    relationship: str
    is_client: bool
    permissions: dict[str, Any] | None

    def mentions(self, category: PermissionType) -> bool:
        """Whether the grant states a rule for ``category`` (even an empty one)."""
        return self.permissions is not None and category.value in self.permissions

    def rules(self, category: PermissionType) -> Any:
        return (self.permissions or {}).get(category.value)


def _is_client_row(peer_id: str, row: Any) -> bool:
    via = row.get("established_via") if isinstance(row, dict) else None
    return peer_id.startswith("oauth2_client:") or via == "oauth2_client"


class PermissionEvaluator:
    """
    Core permission evaluation engine.

    This class combines trust type base permissions with individual trust
    relationship overrides to make authorization decisions.
    """

    def __init__(self, config: config_class.Config):
        self.config = config
        self.trust_type_registry = get_trust_type_registry(config)
        self._permission_store: Any = None

    @property
    def permission_store(self) -> Any:
        """The trust permission store, looked up on each use (3.16): the
        store is a singleton rebuilt when another application's config asks
        for it (two apps in one process), and an evaluator that kept the one
        it was built with read that store's cache while writes went to the
        new one, so a narrowed grant was not seen. An assigned store (tests)
        is used as given."""
        if self._permission_store is not None:
            return self._permission_store
        return get_trust_permission_store(self.config)

    @permission_store.setter
    def permission_store(self, store: Any) -> None:
        self._permission_store = store

    def evaluate_permission(
        self,
        actor_id: str,
        peer_id: str,
        permission_type: PermissionType,
        target: str,
        operation: str = "access",
    ) -> PermissionResult:
        """
        Evaluate a specific permission request.

        Args:
            actor_id: The actor being accessed
            peer_id: The peer requesting access
            permission_type: Type of permission to check
            target: The target being accessed (property path, method name, etc.)
            operation: The operation being performed (read, write, delete, etc.)

        Returns:
            PermissionResult indicating whether access is allowed
        """
        try:
            # Ahead of the permission-map lookup, not only inside
            # _evaluate_rules: a peer with no effective permissions, or none
            # for this type, would otherwise return NOT_FOUND here, which the
            # handlers treat permissively (legacy fallback, keep in listing).
            # The blanket denial has to be blanket.
            if has_control_characters(target):
                logger.warning(
                    f"Permission denied: {actor_id}:{peer_id} -> "
                    f"{permission_type.value}:{target!r}:{operation} "
                    f"(identifier contains a control character)"
                )
                return PermissionResult.DENIED

            unapproved, row_type = self._approval(actor_id, peer_id)
            if unapproved:
                return PermissionResult.DENIED

            # Get the effective permissions for this trust relationship
            effective_perms = self._get_effective_permissions(
                actor_id, peer_id, relationship=row_type
            )
            if not effective_perms:
                logger.warning(
                    f"No effective permissions found for {actor_id}:{peer_id}"
                )
                return PermissionResult.NOT_FOUND

            # Get the permission rules for this type
            if permission_type.value not in effective_perms:
                logger.debug(
                    f"No {permission_type.value} permissions defined for {actor_id}:{peer_id}"
                )
                return PermissionResult.NOT_FOUND
            result = self.evaluate_rules_for(
                permission_type,
                effective_perms.get(permission_type.value),
                target,
                operation,
            )

            # Only log denials for security monitoring. repr() so a
            # peer-controlled identifier cannot inject lines into the log.
            if result == PermissionResult.DENIED:
                logger.warning(
                    f"Permission denied: {actor_id}:{peer_id} -> {permission_type.value}:{target!r}:{operation}"
                )
            return result

        except DbError:
            raise
        except Exception as e:
            logger.error(
                f"Error evaluating permission for {actor_id}:{peer_id} -> {permission_type.value}:{target!r}: {e}"
            )
            return PermissionResult.DENIED

    def evaluate_property_access(
        self, actor_id: str, peer_id: str, property_path: str, operation: str
    ) -> PermissionResult:
        """
        Evaluate property access permissions.

        Args:
            actor_id: The actor owning the property
            peer_id: The peer requesting access
            property_path: The property path (e.g., "public/profile", "notes/work/project1")
            operation: Operation type ("read", "write", "delete")

        Returns:
            PermissionResult
        """
        return self.evaluate_permission(
            actor_id=actor_id,
            peer_id=peer_id,
            permission_type=PermissionType.PROPERTIES,
            target=property_path,
            operation=operation,
        )

    def evaluate_bulk_property_access(
        self, actor_id: str, peer_id: str, property_paths: list[str], operation: str
    ) -> dict[str, PermissionResult]:
        """
        Evaluate property access permissions for multiple properties at once.

        This method is more efficient than calling evaluate_property_access() multiple
        times because it:
        1. Fetches effective permissions only once
        2. Logs only a single summary line instead of one per property
        3. Reuses compiled regex patterns

        Args:
            actor_id: The actor owning the properties
            peer_id: The peer requesting access
            property_paths: List of property paths to check
            operation: Operation type ("read", "write", "delete")

        Returns:
            Dict mapping property_path to PermissionResult
        """
        results: dict[str, PermissionResult] = {}

        # Same blanket denial as evaluate_permission(), applied before the
        # early returns below so a control-character name is DENIED even
        # when the peer has no properties rule at all.
        clean_paths: list[str] = []
        for property_path in property_paths:
            if has_control_characters(property_path):
                results[property_path] = PermissionResult.DENIED
            else:
                clean_paths.append(property_path)
        if len(clean_paths) < len(property_paths):
            logger.warning(
                f"Permission denied: {actor_id}:{peer_id} -> "
                f"{len(property_paths) - len(clean_paths)} property name(s) "
                f"containing control characters"
            )

        try:
            unapproved, row_type = self._approval(actor_id, peer_id)
            if unapproved:
                results.update(dict.fromkeys(clean_paths, PermissionResult.DENIED))
                return results

            # Get the effective permissions once for all properties
            effective_perms = self._get_effective_permissions(
                actor_id, peer_id, relationship=row_type
            )
            if not effective_perms:
                logger.warning(
                    f"No effective permissions found for {actor_id}:{peer_id}"
                )
                results.update(dict.fromkeys(clean_paths, PermissionResult.NOT_FOUND))
                return results

            # Get the permission rules
            if PermissionType.PROPERTIES.value not in effective_perms:
                logger.debug(
                    f"No properties permissions defined for {actor_id}:{peer_id}"
                )
                results.update(dict.fromkeys(clean_paths, PermissionResult.NOT_FOUND))
                return results
            permission_rules = effective_perms.get(PermissionType.PROPERTIES.value)

            # Evaluate each property (suppress individual logging for bulk operations)
            for property_path in clean_paths:
                results[property_path] = self.evaluate_rules_for(
                    PermissionType.PROPERTIES,
                    permission_rules,
                    property_path,
                    operation,
                    suppress_logging=True,
                )

            # Log summary instead of individual evaluations
            allowed_count = sum(
                1 for r in results.values() if r == PermissionResult.ALLOWED
            )
            denied_count = sum(
                1 for r in results.values() if r == PermissionResult.DENIED
            )
            not_found_count = sum(
                1 for r in results.values() if r == PermissionResult.NOT_FOUND
            )

            logger.debug(
                f"Bulk property evaluation for {actor_id}:{peer_id} - "
                f"{len(property_paths)} properties: "
                f"{allowed_count} allowed, {denied_count} denied, {not_found_count} not found"
            )

            # Log only denied properties for security monitoring
            if denied_count > 0:
                denied_props = [
                    p for p, r in results.items() if r == PermissionResult.DENIED
                ]
                logger.warning(
                    f"Bulk property access denied for {actor_id}:{peer_id} -> "
                    f"{operation} on {denied_props}"
                )

        except DbError:
            raise
        except Exception as e:
            logger.error(
                f"Error in bulk property evaluation for {actor_id}:{peer_id}: {e}"
            )
            return dict.fromkeys(property_paths, PermissionResult.DENIED)

        return results

    def evaluate_method_access(
        self, actor_id: str, peer_id: str, method_name: str
    ) -> PermissionResult:
        """
        Evaluate method access permissions.

        Args:
            actor_id: The actor owning the method
            peer_id: The peer requesting access
            method_name: The method name (e.g., "get_profile", "list_notes")

        Returns:
            PermissionResult
        """
        return self.evaluate_permission(
            actor_id=actor_id,
            peer_id=peer_id,
            permission_type=PermissionType.METHODS,
            target=method_name,
            operation="call",
        )

    def evaluate_action_access(
        self, actor_id: str, peer_id: str, action_name: str
    ) -> PermissionResult:
        """
        Evaluate action access permissions.

        Args:
            actor_id: The actor owning the action
            peer_id: The peer requesting access
            action_name: The action name (e.g., "create_note", "send_message")

        Returns:
            PermissionResult
        """
        return self.evaluate_permission(
            actor_id=actor_id,
            peer_id=peer_id,
            permission_type=PermissionType.ACTIONS,
            target=action_name,
            operation="execute",
        )

    def evaluate_tool_access(
        self, actor_id: str, peer_id: str, tool_name: str
    ) -> PermissionResult:
        """
        Evaluate MCP tool access permissions.

        Args:
            actor_id: The actor providing the tool
            peer_id: The MCP client requesting access
            tool_name: The tool name (e.g., "search", "fetch", "create_note")

        Returns:
            PermissionResult
        """
        return self.evaluate_permission(
            actor_id=actor_id,
            peer_id=peer_id,
            permission_type=PermissionType.TOOLS,
            target=tool_name,
            operation="use",
        )

    def evaluate_resource_access(
        self, actor_id: str, peer_id: str, resource_path: str, operation: str = "read"
    ) -> PermissionResult:
        """
        Evaluate MCP resource access permissions.

        Args:
            actor_id: The actor owning the resource
            peer_id: The MCP client requesting access
            resource_path: The resource path (e.g., "notes://", "usage://")
            operation: Operation type ("read", "write", "subscribe")

        Returns:
            PermissionResult
        """
        return self.evaluate_permission(
            actor_id=actor_id,
            peer_id=peer_id,
            permission_type=PermissionType.RESOURCES,
            target=resource_path,
            operation=operation,
        )

    def evaluate_prompt_access(
        self, actor_id: str, peer_id: str, prompt_name: str
    ) -> PermissionResult:
        """
        Evaluate MCP prompt access permissions.

        Args:
            actor_id: The actor providing the prompt
            peer_id: The MCP client requesting access
            prompt_name: The prompt name (e.g., "analyze_notes", "create_summary")

        Returns:
            PermissionResult
        """
        return self.evaluate_permission(
            actor_id=actor_id,
            peer_id=peer_id,
            permission_type=PermissionType.PROMPTS,
            target=prompt_name,
            operation="invoke",
        )

    def get_allowed_items(
        self,
        actor_id: str,
        peer_id: str,
        permission_type: PermissionType,
        operation: str = "access",
    ) -> list[str]:
        """
        Get list of explicitly allowed items for a permission type.

        This returns the 'allowed' patterns/items from the permission rules,
        which can be used for capabilities discovery (e.g., listing available tools).

        Args:
            actor_id: The actor being accessed
            peer_id: The peer requesting access
            permission_type: Type of permission to check
            operation: The operation being performed

        Returns:
            List of allowed patterns/items
        """
        try:
            unapproved, row_type = self._approval(actor_id, peer_id)
            if unapproved:
                return []
            effective_perms = self._get_effective_permissions(
                actor_id, peer_id, relationship=row_type
            )
            if not effective_perms:
                return []

            permission_rules = effective_perms.get(permission_type.value, {})

            # Extract allowed patterns/items
            allowed_items = []

            # Check for direct 'allowed' list
            if "allowed" in permission_rules:
                allowed = permission_rules["allowed"]
                if isinstance(allowed, list):
                    allowed_items.extend(allowed)

            # Check for 'patterns' with matching operations
            if "patterns" in permission_rules and "operations" in permission_rules:
                operations = permission_rules["operations"]
                if isinstance(operations, list) and operation in operations:
                    patterns = permission_rules["patterns"]
                    if isinstance(patterns, list):
                        allowed_items.extend(patterns)

            return allowed_items

        except DbError:
            raise
        except Exception as e:
            logger.error(
                f"Error getting allowed items for {actor_id}:{peer_id} -> {permission_type.value}: {e}"
            )
            return []

    def evaluate_rules_for(
        self,
        permission_type: PermissionType,
        rules: Any,
        target: str,
        operation: str,
        *,
        suppress_logging: bool = False,
    ) -> PermissionResult:
        """A stated rule (the category is in the grant, even empty) applied to
        ``target`` (3.16).

        For properties and resources an exclusion holds on the path and its
        descendants (:func:`path_excluded`) ahead of every allow, and a rule
        that does not match a named target denies (DENIED, not NOT_FOUND), as
        it does for methods and actions. An empty target (a listing) stays
        NOT_FOUND: the caller decides per name. Tools and prompts keep
        NOT_FOUND (MCP denies anything but ALLOWED).
        """
        tree = permission_type in TREE_CATEGORIES
        if tree and target and path_excluded(rules, target):
            if not suppress_logging:
                logger.debug(f"Target {target!r} or an ancestor is excluded")
            return PermissionResult.DENIED
        if not rules:
            result = PermissionResult.NOT_FOUND
        elif isinstance(rules, dict):
            result = self._evaluate_rules(
                rules, target, operation, suppress_logging=suppress_logging
            )
        else:
            result = PermissionResult.NOT_FOUND
        if (
            permission_type in STATED_RULE_CATEGORIES
            and target
            and result == PermissionResult.NOT_FOUND
        ):
            return PermissionResult.DENIED
        return result

    def snapshot(
        self, actor_id: str, peer_id: str, *, row: Any = None
    ) -> GrantSnapshot:
        """What ``peer_id`` is granted at ``actor_id``, from one trust-row
        read and the (cached) override and registry lookups (3.16). ``row``:
        the trust row when the caller read it already (no second read). A
        storage fault raises ``DbError``."""
        if row is None and self.config and hasattr(self.config, "DbTrust"):
            db_trust = get_trust(self.config)
            if db_trust:
                row = db_trust.get(actor_id=actor_id, peerid=peer_id)
        if isinstance(row, dict):
            relationship = str(row.get("relationship") or "")
            approved = row.get("approved") is not False
        elif row is not None:
            relationship = str(getattr(row, "relationship", "") or "")
            approved = getattr(row, "approved", None) is not False
        else:
            relationship, approved = "", False
        has_row = bool(row)
        permissions = (
            self._get_effective_permissions(
                actor_id, peer_id, relationship=relationship
            )
            if has_row
            else None
        )
        return GrantSnapshot(
            actor_id=actor_id,
            peer_id=peer_id,
            has_row=has_row,
            approved=has_row and approved,
            relationship=relationship,
            is_client=_is_client_row(peer_id, row),
            permissions=permissions,
        )

    def evaluate_snapshot(
        self,
        snapshot: GrantSnapshot,
        permission_type: PermissionType,
        target: str,
        operation: str,
        *,
        suppress_logging: bool = True,
    ) -> PermissionResult:
        """``evaluate_permission`` on a snapshot: no read. An unapproved or
        absent row and a control character are DENIED; a category the grant
        does not mention is NOT_FOUND (the caller's access table decides)."""
        if has_control_characters(target):
            return PermissionResult.DENIED
        if not snapshot.approved:
            return PermissionResult.DENIED
        if not snapshot.mentions(permission_type):
            return PermissionResult.NOT_FOUND
        result = self.evaluate_rules_for(
            permission_type,
            snapshot.rules(permission_type),
            target,
            operation,
            suppress_logging=suppress_logging,
        )
        if result == PermissionResult.DENIED:
            # Debug: a filter runs this per subscriber on every write, where
            # a denial is routine.
            logger.debug(
                f"Permission denied: {snapshot.actor_id}:{snapshot.peer_id} -> "
                f"{permission_type.value}:{target!r}:{operation}"
            )
        return result

    def _is_unapproved(self, actor_id: str, peer_id: str) -> bool:
        """Whether the peer has no trust row, or one this actor has not
        approved (:meth:`_approval`)."""
        return self._approval(actor_id, peer_id)[0]

    def _approval(self, actor_id: str, peer_id: str) -> tuple[bool, str | None]:
        """``(unapproved, relationship)``: whether the peer has no trust row,
        or one this actor has not approved, and the row's type (None when no
        row was read), so the effective permissions need no second read
        (3.16). Such a peer is granted nothing here: its secret authenticates
        it (``auth.py``), and anyone can file a trust request with a
        relationship of its choice, so a grant may only follow an approval.
        The access table refuses it the same way
        (``Auth._match_access_row``); its own trust row stays reachable there.
        A storage fault raises ``DbError``."""
        if not self.config or not hasattr(self.config, "DbTrust"):
            return False, None
        db_trust = get_trust(self.config)
        if not db_trust:
            return False, None
        row = db_trust.get(actor_id=actor_id, peerid=peer_id)
        if not row:
            # No trust at all: nothing it holds can grant (a permission
            # override a failed delete left behind grants nothing either).
            logger.warning(f"Permission denied: {actor_id}:{peer_id} has no trust")
            return True, None
        if isinstance(row, dict):
            approved = row.get("approved")
            relationship = str(row.get("relationship") or "")
        else:
            approved = getattr(row, "approved", None)
            relationship = str(getattr(row, "relationship", "") or "")
        if approved is False:
            logger.warning(f"Permission denied: {actor_id}:{peer_id} is not approved")
            return True, relationship
        return False, relationship

    def _get_effective_permissions(
        self, actor_id: str, peer_id: str, *, relationship: str | None = None
    ) -> dict[str, Any] | None:
        """
        Get the effective permissions for a trust relationship.

        This combines base trust type permissions with individual overrides.
        ``relationship``: the trust row's type when the caller has read the
        row already (no second read).
        """
        permission_override = self.permission_store.get_permissions(actor_id, peer_id)
        row_type: str | None = relationship
        if row_type is None and (
            permission_override is None or is_client_peer(peer_id)
        ):
            # The row's type is needed (no override, or a client's, which
            # applies only for the row's type): read once.
            row_type = self._lookup_trust_type_from_database(actor_id, peer_id)
        if permission_override is not None and not override_applies(
            permission_override, peer_id, row_type
        ):
            # An OAuth2/MCP client's level is the one the user approved, the
            # row's type: an override for another type (before a re-type, or
            # set that way) is not applied (owner decision 2026-11-11), so a
            # stale one never decides, whatever a cleanup managed to remove.
            logger.debug(
                f"Override for {actor_id}:{peer_id} names "
                f"'{permission_override.trust_type}', the row is "
                f"'{row_type}': not applied"
            )
            permission_override = None
        # A peer's override names its base type (it decides over the row's).
        trust_type_name = (
            permission_override.trust_type if permission_override else row_type
        ) or None

        if not trust_type_name:
            logger.debug(f"No trust relationship found for {actor_id}:{peer_id}")
            return None

        logger.debug(f"Found trust type '{trust_type_name}' for {actor_id}:{peer_id}")

        # Get base permissions from trust type
        trust_type = self.trust_type_registry.get_type(trust_type_name)
        if not trust_type:
            logger.error(f"Unknown trust type: {trust_type_name}")
            return None

        base_permissions = trust_type.base_permissions
        logger.debug(f"Base permissions for '{trust_type_name}': {base_permissions}")

        # If we have permission overrides, merge them
        if permission_override:
            override_dict = {}

            # Extract non-None override fields
            for field in [
                "properties",
                "methods",
                "actions",
                "tools",
                "resources",
                "prompts",
            ]:
                override_value = getattr(permission_override, field, None)
                if override_value is not None:
                    override_dict[field] = override_value

            # Merge base permissions with overrides
            effective_permissions = merge_permissions(base_permissions, override_dict)
        else:
            effective_permissions = base_permissions

        return effective_permissions

    def _lookup_trust_type_from_database(
        self, actor_id: str, peer_id: str
    ) -> str | None:
        """
        Look up trust type (relationship) from the database.

        Args:
            actor_id: The actor ID
            peer_id: The peer ID

        Returns:
            Trust type name (relationship) or None if not found
        """
        try:
            # Use the configured database backend
            if not self.config or not hasattr(self.config, "DbTrust"):
                logger.error("Database backend (DbTrust) not configured")
                return None
            db_trust = get_trust(self.config)
            if not db_trust:
                logger.error("Failed to instantiate database backend")
                return None
            trust_record = db_trust.get(actor_id=actor_id, peerid=peer_id)

            # DbTrust.get() returns a dict; support both dicts and objects defensively
            if isinstance(trust_record, dict):
                relationship = trust_record.get("relationship")
                if relationship:
                    return str(relationship)
            elif trust_record is not None and hasattr(trust_record, "relationship"):
                return str(trust_record.relationship)

            return None

        except DbError:
            raise
        except Exception as e:
            logger.error(
                f"Error looking up trust relationship {actor_id}:{peer_id}: {e}"
            )
            return None

    def _evaluate_rules(
        self,
        permission_rules: dict[str, Any],
        target: str,
        operation: str,
        suppress_logging: bool = False,
    ) -> PermissionResult:
        """
        Evaluate permission rules against a specific target and operation.

        Permission rules can have different formats:

        1. Simple allowed/denied lists:
           {"allowed": ["pattern1", "pattern2"], "denied": ["pattern3"]}

        2. Pattern-based with operations:
           {"patterns": ["pattern1"], "operations": ["read", "write"], "excluded_patterns": ["pattern2"]}

        3. Mixed format (combines both approaches)

        Args:
            permission_rules: The permission rules to evaluate
            target: The target being accessed
            operation: The operation being performed
            suppress_logging: If True, suppress verbose DEBUG logging (for bulk operations)
        """
        if not suppress_logging:
            logger.debug(
                f"Evaluating rules: target='{target}', operation='{operation}', rules={permission_rules}"
            )

        # An identifier carrying a control character is denied before any
        # rule is consulted. This is the single funnel every evaluate_*_access
        # path goes through, so one guard covers property, list, method,
        # action, tool, prompt and resource names. Two reasons it lives here
        # rather than relying on the whole-string anchoring below: a
        # wildcard rule must not be the only thing standing between
        # ``private/\nsecret`` and a protected namespace, and a bare-literal
        # ``denied: ["notes"]`` used to catch ``notes\n`` by accident (the
        # old ``$`` anchor tolerated a trailing newline) -- narrowing the
        # anchor alone would have turned that deny into an allow.
        if has_control_characters(target):
            logger.warning(
                f"Denying {operation} on identifier {target!r}: identifiers "
                f"must not contain control characters"
            )
            return PermissionResult.DENIED

        # Check explicit denied patterns first (highest priority)
        if "denied" in permission_rules:
            denied_patterns = permission_rules["denied"]
            if self._matches_any_pattern(target, denied_patterns):
                if not suppress_logging:
                    logger.debug(f"Target '{target}' matched denied pattern")
                return PermissionResult.DENIED

        # Check allowed patterns
        if "allowed" in permission_rules:
            allowed_patterns = permission_rules["allowed"]
            if self._matches_any_pattern(target, allowed_patterns):
                if not suppress_logging:
                    logger.debug(f"Target '{target}' matched allowed pattern")
                return PermissionResult.ALLOWED

        # Check pattern-based permissions with operations
        if "patterns" in permission_rules and "operations" in permission_rules:
            patterns = permission_rules["patterns"]
            operations = permission_rules["operations"]

            if not suppress_logging:
                logger.debug(
                    f"Pattern-based check: patterns={patterns}, operations={operations}"
                )

            # Check if operation is allowed
            if operation not in operations:
                if not suppress_logging:
                    logger.debug(
                        f"Operation '{operation}' not in allowed operations {operations}"
                    )
                return PermissionResult.DENIED

            # Check if target matches allowed patterns
            if self._matches_any_pattern(target, patterns):
                # Check excluded patterns
                excluded = permission_rules.get("excluded_patterns", [])
                if excluded and self._matches_any_pattern(target, excluded):
                    if not suppress_logging:
                        logger.debug(f"Target '{target}' matched excluded pattern")
                    return PermissionResult.DENIED
                if not suppress_logging:
                    logger.debug(
                        f"Target '{target}' matched pattern, operation '{operation}' allowed"
                    )
                return PermissionResult.ALLOWED
            else:
                # When patterns are explicitly defined, non-match means DENIED
                # EXCEPT: empty target (listing requests) should return NOT_FOUND to allow
                # the listing endpoint to proceed - individual properties are filtered there
                if target == "":
                    if not suppress_logging:
                        logger.debug(
                            f"Empty target with patterns {patterns} - allowing listing (filter at response level)"
                        )
                    return PermissionResult.NOT_FOUND
                if not suppress_logging:
                    logger.debug(
                        f"Target '{target}' did not match any patterns {patterns} - denying access"
                    )
                return PermissionResult.DENIED

        # No matching rule found (no patterns/operations configured at all)
        if not suppress_logging:
            logger.debug(
                f"No matching rule found for target='{target}', operation='{operation}'"
            )
        return PermissionResult.NOT_FOUND

    def _matches_any_pattern(self, target: str, patterns: list[str]) -> bool:
        """
        Check if target matches any of the given patterns.

        Supports glob-style patterns with * and ? wildcards.
        """
        if not patterns:
            return False

        for pattern in patterns:
            if self._matches_pattern(target, pattern):
                return True
        return False

    def _matches_pattern(self, target: str, pattern: str) -> bool:
        """Check if target matches a single pattern (see :func:`glob_match`)."""
        return glob_match(target, pattern)


# Convenience functions for common permission checks


def check_property_access(
    config: config_class.Config,
    actor_id: str,
    peer_id: str,
    property_path: str,
    operation: str,
) -> bool:
    """
    Quick property access check.

    Returns:
        True if access is allowed, False otherwise
    """
    evaluator = get_permission_evaluator(config)
    result = evaluator.evaluate_property_access(
        actor_id, peer_id, property_path, operation
    )
    return result == PermissionResult.ALLOWED


def check_method_access(
    config: config_class.Config, actor_id: str, peer_id: str, method_name: str
) -> bool:
    """
    Quick method access check.

    Returns:
        True if access is allowed, False otherwise
    """
    evaluator = get_permission_evaluator(config)
    result = evaluator.evaluate_method_access(actor_id, peer_id, method_name)
    return result == PermissionResult.ALLOWED


def check_tool_access(
    config: config_class.Config, actor_id: str, peer_id: str, tool_name: str
) -> bool:
    """
    Quick MCP tool access check.

    Returns:
        True if access is allowed, False otherwise
    """
    evaluator = get_permission_evaluator(config)
    result = evaluator.evaluate_tool_access(actor_id, peer_id, tool_name)
    return result == PermissionResult.ALLOWED


def batch_check_property_access(
    config: config_class.Config,
    actor_id: str,
    peer_id: str,
    property_paths: list[str],
    operation: str,
) -> list[str]:
    """
    Batch property access check - more efficient than calling check_property_access in a loop.

    This function optimizes database access by fetching effective permissions once
    and then evaluating all property paths against those permissions.

    Args:
        config: ActingWeb config
        actor_id: The actor granting access
        peer_id: The peer requesting access
        property_paths: List of property paths to check
        operation: Operation to check ("read", "write", etc.)

    Returns:
        List of property paths that passed the permission check
    """
    evaluator = get_permission_evaluator(config)

    # Use the optimized bulk evaluation method
    results = evaluator.evaluate_bulk_property_access(
        actor_id, peer_id, property_paths, operation
    )

    # Return only the allowed property paths
    accessible = [
        path for path, result in results.items() if result == PermissionResult.ALLOWED
    ]

    return accessible


# Singleton instance
_permission_evaluator: PermissionEvaluator | None = None
# Config the singleton above was built with -- see get_permission_evaluator().
_permission_evaluator_config: config_class.Config | None = None


def initialize_permission_evaluator(config: config_class.Config) -> None:
    """Initialize the permission evaluator at application startup."""
    global _permission_evaluator, _permission_evaluator_config
    if _permission_evaluator is None or _permission_evaluator_config is not config:
        logger.info("Initializing permission evaluator...")
        _permission_evaluator = PermissionEvaluator(config)
        _permission_evaluator_config = config
        logger.info("Permission evaluator initialized")


def get_permission_evaluator(config: config_class.Config) -> PermissionEvaluator:
    """Get the singleton permission evaluator (must be initialized first).

    Falls back to lazy initialization with a warning if not initialized at startup.
    This prevents hard failures but may cause performance issues on first use.
    """
    global _permission_evaluator
    if _permission_evaluator is not None and _permission_evaluator_config is not config:
        # A different application's config: rebuild rather than serve the
        # first app's evaluator (which may even use another database backend).
        initialize_permission_evaluator(config)
    if _permission_evaluator is None:
        logger.warning(
            "Permission evaluator not initialized at startup - falling back to lazy initialization. "
            "This may cause performance issues (4+ minute delays in OAuth2 flows). "
            "Call initialize_permission_evaluator() at application startup to avoid this."
        )
        initialize_permission_evaluator(config)
    assert _permission_evaluator is not None, (
        "PermissionEvaluator should be initialized"
    )
    return _permission_evaluator
