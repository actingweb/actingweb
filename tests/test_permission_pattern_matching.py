"""Whole-identifier glob matching in the permission evaluator (3.14.4).

Before 3.14.4 ``_glob_to_regex()`` anchored with ``$`` and compiled without
``re.DOTALL``: ``$`` tolerates a trailing newline, and ``.*`` cannot cross
one. A ``friend`` peer could therefore write ``private/\\nsecret`` past
``excluded_patterns: ["private/*"]``. The fix is three-fold and each part is
pinned here on its own, because the anchor change alone would have flipped a
bare-literal deny into an allow -- the last test class shows why.
"""

import logging
import unittest
from unittest.mock import patch

from actingweb.permission_evaluator import (
    _PATTERN_CACHE_MAX_ENTRIES,
    PermissionEvaluator,
    PermissionResult,
)


def _evaluator() -> PermissionEvaluator:
    """A PermissionEvaluator with no registry or store.

    ``_matches_pattern``/``_evaluate_rules`` never touch either, and
    constructing one for real requires an initialised trust permission
    store (a database), which these pure-function tests do not need.
    """
    ev = object.__new__(PermissionEvaluator)
    ev._pattern_cache = {}
    return ev


class TestMatchesPattern(unittest.TestCase):
    def setUp(self) -> None:
        self.ev = _evaluator()

    def test_exact_pattern_rejects_trailing_newline(self) -> None:
        self.assertFalse(self.ev._matches_pattern("notes\n", "notes"))
        self.assertFalse(self.ev._matches_pattern("notes", "notes\n"))

    def test_star_crosses_newline(self) -> None:
        self.assertTrue(self.ev._matches_pattern("memory_a\nb", "memory_*"))
        self.assertTrue(self.ev._matches_pattern("private/\nsecret", "private/*"))

    def test_question_mark_matches_newline(self) -> None:
        # Documented over-match: ``?`` is "any single character" and a
        # newline is a character. The evaluator-level guard, not the glob,
        # is what keeps such an identifier out.
        self.assertTrue(self.ev._matches_pattern("notes\n", "notes?"))

    def test_glob_to_regex_uses_end_of_string_anchor(self) -> None:
        self.assertEqual(self.ev._glob_to_regex("a*b?"), r"^a.*b.\Z")

    def test_short_circuits_unchanged(self) -> None:
        self.assertTrue(self.ev._matches_pattern("anything\nat all", "*"))
        self.assertTrue(self.ev._matches_pattern("same\n", "same\n"))
        self.assertTrue(self.ev._matches_pattern("notes://work/x", "notes://"))

    def test_pattern_cache_is_bounded(self) -> None:
        for i in range(_PATTERN_CACHE_MAX_ENTRIES):
            self.ev._matches_pattern("x", f"p{i}_*")
        self.assertEqual(len(self.ev._pattern_cache), _PATTERN_CACHE_MAX_ENTRIES)
        self.ev._matches_pattern("x", "one_more_*")
        self.assertEqual(len(self.ev._pattern_cache), 1)
        self.assertIn("one_more_*", self.ev._pattern_cache)


class TestControlCharacterGuard(unittest.TestCase):
    """The two rule shapes from review, and why anchoring alone is not enough."""

    LITERAL_DENY = {"denied": ["secret"], "allowed": ["*"]}
    EXCLUDED = {
        "patterns": ["*"],
        "excluded_patterns": ["private/*"],
        "operations": ["read", "write"],
    }

    def setUp(self) -> None:
        self.ev = _evaluator()

    def test_literal_deny_with_trailing_newline_is_denied(self) -> None:
        with self.assertLogs("actingweb.permission_evaluator", level="WARNING"):
            result = self.ev._evaluate_rules(self.LITERAL_DENY, "secret\n", "read")
        self.assertEqual(result, PermissionResult.DENIED)

    def test_excluded_pattern_with_embedded_newline_is_denied(self) -> None:
        result = self.ev._evaluate_rules(self.EXCLUDED, "private/x\ny", "write")
        self.assertEqual(result, PermissionResult.DENIED)

    def test_every_control_character_class_is_denied(self) -> None:
        for ch in ("\x00", "\t", "\r", "\x1f", "\x7f", "\x85", "\x9f"):
            result = self.ev._evaluate_rules({"allowed": ["*"]}, f"notes{ch}", "read")
            self.assertEqual(result, PermissionResult.DENIED, repr(ch))

    def test_clean_identifiers_are_unaffected(self) -> None:
        self.assertEqual(
            self.ev._evaluate_rules(self.LITERAL_DENY, "secret", "read"),
            PermissionResult.DENIED,
        )
        self.assertEqual(
            self.ev._evaluate_rules(self.LITERAL_DENY, "notes", "read"),
            PermissionResult.ALLOWED,
        )
        self.assertEqual(
            self.ev._evaluate_rules(self.EXCLUDED, "private/x", "write"),
            PermissionResult.DENIED,
        )
        self.assertEqual(
            self.ev._evaluate_rules(self.EXCLUDED, "public/x", "write"),
            PermissionResult.ALLOWED,
        )

    def test_why_the_guard_exists(self) -> None:
        """With the guard removed, ``\\Z`` + DOTALL alone regresses the
        literal deny (``secret\\n`` no longer matches ``secret`` and falls
        through to ``allowed: ["*"]``) while fixing the excluded pattern.
        """
        with patch(
            "actingweb.permission_evaluator.has_control_characters",
            return_value=False,
        ):
            logging.disable(logging.WARNING)
            try:
                literal = self.ev._evaluate_rules(self.LITERAL_DENY, "secret\n", "read")
                excluded = self.ev._evaluate_rules(
                    self.EXCLUDED, "private/x\ny", "write"
                )
            finally:
                logging.disable(logging.NOTSET)
        self.assertEqual(literal, PermissionResult.ALLOWED)
        self.assertEqual(excluded, PermissionResult.DENIED)
