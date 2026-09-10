"""
Tests for ``actingweb.secret_compare`` (3.14.5): constant-time comparison
helpers that replace ten in-process ``==``/``!=`` secret compares.
"""

import hashlib

from actingweb.secret_compare import secret_digest_equals, secret_equals


class TestSecretEquals:
    def test_equal_str(self):
        assert secret_equals("abc123", "abc123") is True

    def test_unequal_str(self):
        assert secret_equals("abc123", "abc124") is False

    def test_equal_bytes(self):
        assert secret_equals(b"abc123", b"abc123") is True

    def test_unequal_bytes(self):
        assert secret_equals(b"abc123", b"abc124") is False

    def test_str_and_bytes_of_same_content_are_equal(self):
        # str is UTF-8 encoded before comparing, so a str and bytes operand
        # carrying the same content compare equal.
        assert secret_equals("abc", b"abc") is True

    def test_non_ascii_str_no_exception(self):
        assert secret_equals("pässword", "pässword") is True
        assert secret_equals("pässword", "password") is False

    def test_none_on_either_side_is_false(self):
        assert secret_equals(None, "abc") is False
        assert secret_equals("abc", None) is False
        assert secret_equals(None, None) is False

    def test_non_str_bytes_operands_are_false_not_exceptions(self):
        assert secret_equals(123, "123") is False
        assert secret_equals("123", 123) is False
        assert secret_equals(["a"], ["a"]) is False
        assert secret_equals({"a": 1}, {"a": 1}) is False

    def test_empty_strings_equal(self):
        assert secret_equals("", "") is True


class TestSecretDigestEquals:
    def test_equal_values_different_types_still_digest_equal_when_same_bytes(self):
        assert secret_digest_equals("abc", "abc") is True

    def test_unequal_values(self):
        assert secret_digest_equals("abc", "abd") is False

    def test_different_length_operands(self):
        short = "a" * 10
        long = "a" * 200
        assert secret_digest_equals(short, long) is False
        assert secret_digest_equals(long, long) is True

    def test_none_operands_false(self):
        assert secret_digest_equals(None, "abc") is False

    def test_matches_manual_sha256_comparison(self):
        a = "some-challenge-value"
        b = "some-challenge-value"
        assert secret_digest_equals(a, b) == (
            hashlib.sha256(a.encode()).digest() == hashlib.sha256(b.encode()).digest()
        )
