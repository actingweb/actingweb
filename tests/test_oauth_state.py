from actingweb.oauth_state import encode_state, decode_state, validate_expected_email


def test_encode_decode_roundtrip_minimal():
    state = encode_state(csrf="abc123")
    csrf, redirect, actor_id, trust_type, expected_email = decode_state(state)
    assert csrf == "abc123"
    assert redirect == ""
    assert actor_id == ""
    assert trust_type == ""
    assert expected_email == ""


def test_encode_decode_with_all_fields_and_extra():
    state = encode_state(
        csrf="csrf-token",
        redirect="https://example.com/return",
        actor_id="actor_1",
        trust_type="mcp_client",
        expected_email="user@example.com",
        extra={"foo": "bar"},
    )
    csrf, redirect, actor_id, trust_type, expected_email = decode_state(state)
    assert csrf == "csrf-token"
    assert redirect == "https://example.com/return"
    assert actor_id == "actor_1"
    assert trust_type == "mcp_client"
    assert expected_email == "user@example.com"


def test_validate_expected_email_allows_when_not_present():
    # No state provided -> allowed for backward compatibility
    assert validate_expected_email("", "user@example.com") is True


def test_validate_expected_email_matches():
    state = encode_state(csrf="c", expected_email="user@example.com")
    assert validate_expected_email(state, "user@example.com") is True


def test_validate_expected_email_rejects_mismatch():
    state = encode_state(csrf="c", expected_email="user@example.com")
    assert validate_expected_email(state, "other@example.com") is False

