"""Authorization codes are single-use, atomically (RFC 6749 §4.1.2).

``exchange_authorization_code`` consumes the code with a compare-and-swap
before PKCE is validated: of two exchanges exactly one mints tokens, and a
wrong verifier burns the code.
"""

import base64
import hashlib
import logging
import time

import pytest

from actingweb.constants import AUTH_CODE_INDEX_BUCKET
from actingweb.oauth2_server.token_manager import (
    ActingWebTokenManager,
    TokenStoreUnavailable,
)
from tests.mcp_token_double import MemoryStore, index_actor, make_config

ACTOR = "actor-code"
CLIENT = "mcp_client_code"
CODES = "mcp_auth_codes"
VERIFIER = "v" * 64


def _s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _setup() -> tuple[ActingWebTokenManager, MemoryStore]:
    config, store = make_config()
    return ActingWebTokenManager(config), store


def test_second_exchange_of_a_code_fails() -> None:
    tm, store = _setup()
    code = tm.create_authorization_code(ACTOR, CLIENT, {"access_token": "g"})

    first = tm.exchange_authorization_code(code, CLIENT)
    second = tm.exchange_authorization_code(code, CLIENT)

    assert first is not None
    assert second is None
    assert code not in store.names(ACTOR, CODES)
    assert index_actor(store, AUTH_CODE_INDEX_BUCKET, code) is None


def test_cas_loser_gets_none_and_winner_tokens_stand() -> None:
    tm, store = _setup()
    code = tm.create_authorization_code(ACTOR, CLIENT, {"access_token": "g"})

    def lose(actor_id: str, bucket: str, name: str) -> bool:
        if bucket == CODES and name == code:
            row = store.bucket(actor_id, bucket)[name]["data"]
            row["used"] = True
            row["used_at"] = int(time.time())
            return False
        return True

    store.cas_hook = lose
    assert tm.exchange_authorization_code(code, CLIENT) is None
    store.cas_hook = None
    # The loser leaves the (winner's) code row and provider row alone.
    assert code in store.names(ACTOR, CODES)
    assert store.names(ACTOR, "mcp_google_tokens")


def test_wrong_verifier_burns_the_code() -> None:
    tm, store = _setup()
    code = tm.create_authorization_code(
        ACTOR,
        CLIENT,
        {"access_token": "g"},
        code_challenge=_s256(VERIFIER),
        code_challenge_method="S256",
    )

    assert tm.exchange_authorization_code(code, CLIENT, code_verifier="w" * 64) is None
    assert tm.exchange_authorization_code(code, CLIENT, code_verifier=VERIFIER) is None
    assert code not in store.names(ACTOR, CODES)


def test_code_row_ttl_is_never_restamped() -> None:
    tm, store = _setup()
    code = tm.create_authorization_code(ACTOR, CLIENT, {"access_token": "g"})
    stamped = store.ttls[(ACTOR, CODES, code)]

    tokens = tm.exchange_authorization_code(code, CLIENT)

    assert tokens is not None
    # The only TTL written for the code row is the one from its creation.
    assert store.ttls[(ACTOR, CODES, code)] == stamped


def test_cas_fault_leaves_the_code_exchangeable() -> None:
    """A swap that faults is not "already used": the exchange errors, and the
    code still works once the store recovers."""
    tm, store = _setup()
    code = tm.create_authorization_code(ACTOR, CLIENT, {"access_token": "g"})

    store.cas_fault = True
    with pytest.raises(TokenStoreUnavailable):
        tm.exchange_authorization_code(code, CLIENT)
    store.cas_fault = False

    assert tm.exchange_authorization_code(code, CLIENT) is not None


def test_a_swap_whose_response_was_lost_still_exchanges_the_code() -> None:
    """The swap landed but the backend answered False (a lost response):
    the exchange recognises its own write instead of burning the code."""
    tm, store = _setup()
    code = tm.create_authorization_code(ACTOR, CLIENT, {"access_token": "g"})

    store.cas_lost_response = True
    tokens = tm.exchange_authorization_code(code, CLIENT)
    store.cas_lost_response = False

    assert tokens is not None
    assert tm.exchange_authorization_code(code, CLIENT) is None


def test_a_competing_consume_is_still_refused() -> None:
    """Another caller's write carries another consume id: still a loss."""
    tm, store = _setup()
    code = tm.create_authorization_code(ACTOR, CLIENT, {"access_token": "g"})
    row = store.bucket(ACTOR, CODES)[code]["data"]
    loaded = dict(row)
    row.update({"used": True, "used_at": int(time.time()), "consume_id": "other"})

    consumed, current = tm._consume(ACTOR, CODES, code, loaded, consumed_ttl=None)

    assert consumed is False
    assert current is not None and current["consume_id"] == "other"


def test_code_is_never_logged_in_full(caplog: pytest.LogCaptureFixture) -> None:
    tm, _ = _setup()
    code = tm.create_authorization_code(ACTOR, CLIENT, {"access_token": "g"})
    with caplog.at_level(logging.DEBUG, logger="actingweb.oauth2_server"):
        assert tm.exchange_authorization_code(code, CLIENT)
        assert tm.exchange_authorization_code(code, CLIENT) is None
        tm.exchange_authorization_code("never-issued-code-value", CLIENT)
    assert caplog.records
    assert code not in caplog.text
    assert "never-issued-code-value" not in caplog.text


# ---------------------------------------------------------------------------
# A store fault during an exchange is retryable, not "invalid_grant"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bucket", [AUTH_CODE_INDEX_BUCKET, "mcp_google_tokens"])
def test_a_fault_during_the_exchange_raises_and_leaves_the_code_exchangeable(
    bucket: str,
) -> None:
    tm, store = _setup()
    code = tm.create_authorization_code(ACTOR, CLIENT, {"access_token": "g"})
    store.faulty_buckets.add(bucket)

    with pytest.raises(TokenStoreUnavailable):
        tm.exchange_authorization_code(code, CLIENT)

    store.faulty_buckets.clear()
    # Not consumed: the provider read (and the code read) precede the consume.
    assert tm.exchange_authorization_code(code, CLIENT) is not None


@pytest.mark.parametrize("bucket", [AUTH_CODE_INDEX_BUCKET, "mcp_google_tokens"])
def test_the_token_endpoint_answers_server_error_on_an_exchange_fault(
    bucket: str,
) -> None:
    from tests.mcp_oauth_server_helpers import make_server, register

    config, store = make_config()
    server = make_server(config)
    resp = register(server)
    code = server.token_manager.create_authorization_code(
        ACTOR,
        resp["client_id"],
        {"access_token": "g"},
        redirect_uri="https://client/cb",
    )
    params = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "https://client/cb",
        "client_id": resp["client_id"],
        "client_secret": resp["client_secret"],
    }
    store.faulty_buckets.add(bucket)
    assert server.handle_token_request(params)["error"] == "server_error"

    store.faulty_buckets.clear()
    assert "access_token" in server.handle_token_request(params)
