"""
Centralized OAuth state encoding/decoding and validation helpers.

This module avoids duplicated state handling across web and MCP flows.
"""

from __future__ import annotations

import json
import re
from typing import Any


def encode_state(
    csrf: str,
    redirect: str = "",
    actor_id: str = "",
    trust_type: str = "",
    expected_email: str = "",
    user_agent: str = "",
    extra: dict[str, Any] | None = None,
) -> str:
    data: dict[str, Any] = {
        "csrf": csrf,
        "redirect": redirect,
        "actor_id": actor_id,
        "trust_type": trust_type,
        "expected_email": expected_email,
        "user_agent": user_agent[:100]
        if user_agent
        else "",  # Truncate to prevent large state
    }
    if extra:
        data.update(extra)
    return json.dumps(data)


def decode_state(state: str) -> tuple[str, str, str, str, str, str]:
    """
    Decode state into (csrf, redirect, actor_id, trust_type, expected_email, user_agent).
    Supports legacy forms (raw actor_id or raw CSRF token).
    """
    if not state:
        return "", "", "", "", "", ""

    # If it starts with '{' it's likely JSON (standard state)
    if state.strip().startswith("{"):
        try:
            data = json.loads(state)
            # Use `or ""` to handle None values from JSON null
            # (dict.get returns None if key exists with null value, not the default)
            return (
                str(data.get("csrf") or ""),
                str(data.get("redirect") or ""),
                str(data.get("actor_id") or ""),
                str(data.get("trust_type") or ""),
                str(data.get("expected_email") or ""),
                str(data.get("user_agent") or ""),
            )
        except (json.JSONDecodeError, TypeError):
            pass

    # Base64-like encrypted MCP state should be handled upstream; return minimal tuple
    if len(state) > 50 and re.match(r"^[A-Za-z0-9+/_=-]+$", state):
        return "", "", "", "", "", ""

    # Legacy: 32 hex actor id
    if len(state) == 32 and all(c in "0123456789abcdef" for c in state.lower()):
        return "", "", state, "", "", ""

    # Otherwise treat as CSRF token only
    return state, "", "", "", "", ""


def validate_expected_email(state: str, authenticated_email: str) -> bool:
    """
    Validate that authenticated_email matches expected_email in state (if present).
    Non-JSON states pass validation for backward compatibility.
    """
    if not authenticated_email:
        return False
    if not state:
        # No state -> allow for backward compatibility
        return True
    if not state.strip().startswith("{"):
        return True
    try:
        data = json.loads(state)
        expected = str(data.get("expected_email", "")).strip().lower()
        if not expected:
            return True
        return expected == authenticated_email.strip().lower()
    except Exception:
        return True
