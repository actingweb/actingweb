"""A disconnect removes the client's authorization codes (4.0.0rc2).

``thoughts/plans/2026-11-21-trust-request-answer-secret.md``, phase 4: the
sweep that revokes an actor's tokens for a client (``revoke_client_tokens``,
which ``Trust.delete`` runs before the row goes) also removes the actor's
codes for it, fail closed; an exchange in flight when the sweep runs leaves
no token that works.
"""

from __future__ import annotations

from typing import Any

import pytest

from actingweb.constants import AUTH_CODE_INDEX_BUCKET
from actingweb.oauth2_server.token_manager import (
    ActingWebTokenManager,
    TokenStoreUnavailable,
)
from tests.mcp_token_double import PKCE_VERIFIER, MemoryStore, index_actor, make_config

ACTOR = "actor-sweep"
CLIENT = "mcp_client_sweep"
OTHER = "mcp_client_other"
CODES = "mcp_auth_codes"
PROVIDER = "mcp_google_tokens"


def _setup() -> tuple[ActingWebTokenManager, MemoryStore]:
    config, store = make_config()
    return ActingWebTokenManager(config), store


def _code(tm: ActingWebTokenManager, client: str = CLIENT) -> str:
    return tm.create_authorization_code(
        ACTOR,
        client,
        {"access_token": "g"},
        code_challenge=PKCE_VERIFIER,
        code_challenge_method="plain",
    )


def test_a_disconnect_removes_the_clients_codes() -> None:
    """AC-20 at the token manager: the code, its index row and its
    provider-token row go; another client's code stays."""
    tm, store = _setup()
    code = _code(tm)
    other = _code(tm, OTHER)
    tm.revoke_client_tokens(ACTOR, CLIENT)
    assert code not in store.names(ACTOR, CODES)
    assert index_actor(store, AUTH_CODE_INDEX_BUCKET, code) is None
    assert f"google_token_{code}" not in store.names(ACTOR, PROVIDER)
    assert (
        tm.exchange_authorization_code(code, CLIENT, code_verifier=PKCE_VERIFIER)
        is None
    )
    assert other in store.names(ACTOR, CODES)
    assert (
        tm.exchange_authorization_code(other, OTHER, code_verifier=PKCE_VERIFIER)
        is not None
    )


def test_a_sweep_during_an_exchange_leaves_no_live_token() -> None:
    """AC-35: the sweep runs after the exchange consumed its code and
    before it writes its tokens, so the sweep's token pass sees none; the
    exchange's own check after it mints must catch it."""
    tm, store = _setup()
    code = _code(tm)
    original = tm._create_access_token  # noqa: SLF001
    swept: list[bool] = []

    def disconnect_then_mint(*args: Any, **kwargs: Any) -> Any:
        if not swept:
            swept.append(True)
            tm.revoke_client_tokens(ACTOR, CLIENT)
        return original(*args, **kwargs)

    tm._create_access_token = disconnect_then_mint  # type: ignore[method-assign]  # noqa: SLF001
    result = tm.exchange_authorization_code(code, CLIENT, code_verifier=PKCE_VERIFIER)
    assert swept
    assert result is None
    assert store.names(ACTOR, tm.tokens_bucket) == set()
    assert store.names(ACTOR, tm.refresh_tokens_bucket) == set()


def test_a_code_that_cannot_be_removed_fails_the_disconnect() -> None:
    """AC-36: an unconfirmed removal raises, so ``Trust.delete`` keeps the
    row as the retry handle (it raises ``DbError`` before the row goes)."""
    tm, store = _setup()
    code = _code(tm)
    store.delete_faults.add((ACTOR, CODES, code))
    with pytest.raises(TokenStoreUnavailable):
        tm.revoke_client_tokens(ACTOR, CLIENT)
    store.delete_faults.clear()
    tm.revoke_client_tokens(ACTOR, CLIENT)
    assert code not in store.names(ACTOR, CODES)


@pytest.mark.parametrize("which", ["index", "provider"])
def test_a_half_removed_code_is_finished_by_the_retry(which: str) -> None:
    """AC-36: the code row goes last, so a removal stopped at its index or
    provider-token row leaves the code for the retry to find."""
    tm, store = _setup()
    code = _code(tm)
    fault = (ACTOR, PROVIDER, f"google_token_{code}")
    if which == "index":
        system_actor = next(
            key.split(":", 1)[0]
            for key in store.rows
            if key.endswith(f":{AUTH_CODE_INDEX_BUCKET}")
        )
        fault = (system_actor, AUTH_CODE_INDEX_BUCKET, code)
    store.delete_faults.add(fault)
    with pytest.raises(TokenStoreUnavailable, match="authorization code"):
        tm.revoke_client_tokens(ACTOR, CLIENT)
    assert code in store.names(ACTOR, CODES)
    store.delete_faults.clear()
    tm.revoke_client_tokens(ACTOR, CLIENT)
    assert code not in store.names(ACTOR, CODES)
    assert index_actor(store, AUTH_CODE_INDEX_BUCKET, code) is None
    assert f"google_token_{code}" not in store.names(ACTOR, PROVIDER)


def test_a_fault_on_the_re_read_leaves_no_token() -> None:
    """AC-35's fail-closed half: the exchange cannot tell whether its code
    was swept, so it revokes what it minted and raises."""
    tm, store = _setup()
    code = _code(tm)

    def unreadable(_actor_id: str, _code: str) -> bool:
        raise TokenStoreUnavailable("authorization code re-read")

    tm._consumed_code_still_there = unreadable  # type: ignore[method-assign]  # noqa: SLF001
    with pytest.raises(TokenStoreUnavailable):
        tm.exchange_authorization_code(code, CLIENT, code_verifier=PKCE_VERIFIER)
    assert store.names(ACTOR, tm.tokens_bucket) == set()
    assert store.names(ACTOR, tm.refresh_tokens_bucket) == set()
