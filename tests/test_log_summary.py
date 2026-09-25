"""``log_summary.summarize_payload`` describes a payload without its values."""

from actingweb.log_summary import summarize_payload


def test_dict_lists_sorted_keys_and_size() -> None:
    out = summarize_payload({"password": "hunter2", "note": "x"}, encoded_len=34)
    assert out == "keys=[note, password] bytes=34"
    assert "hunter2" not in out


def test_non_dict_is_size_only() -> None:
    assert summarize_payload(["secret"], encoded_len=10) == "bytes=10"
    assert summarize_payload("secret") == "bytes=6"
    assert summarize_payload(None) == "bytes=?"


def test_key_cap() -> None:
    payload = {f"k{i:02d}": i for i in range(25)}
    out = summarize_payload(payload, encoded_len=1)
    assert out.count(", ") == 20  # 20 names plus the "+5 more" item
    assert "+5 more" in out
    assert "k19" in out
    assert "k20" not in out


def test_key_names_are_sanitised_and_capped() -> None:
    """A peer controls the key names; a newline in one must not start a new
    log line, and a huge key must not flood the log."""
    out = summarize_payload({"a\nFAKE LOG LINE": 1, "k" * 500: 2})
    assert "\n" not in out
    assert "a FAKE LOG LINE" in out
    assert "k" * 65 not in out
