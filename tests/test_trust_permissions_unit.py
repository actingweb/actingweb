"""
Trust Permissions Unit Tests.

Pure unit tests for trust permission pattern matching and merge logic.
No DynamoDB required.

References:
- actingweb/trust_permissions.py - merge_permissions() function
- actingweb/permission_evaluator.py:442-498 - Pattern matching logic
"""


class TestTrustPermissionsPatternMatching:
    """Test pattern matching with wildcards."""

    def test_wildcard_pattern_matches_multiple_properties(self):
        """
        Test that memory_* pattern matches all memory types.

        actingweb_mcp uses memory_* to match all memory property lists.

        Spec: actingweb/permission_evaluator.py:487-497 - Glob to regex conversion
        """
        import fnmatch

        # Test pattern matching logic
        pattern = "memory_*"

        matching_names = [
            "memory_personal",
            "memory_travel",
            "memory_food",
            "memory_health",
            "memory_work",
        ]

        non_matching_names = ["settings_private", "notes_general", "user_profile"]

        # All memory_ names should match
        for name in matching_names:
            assert fnmatch.fnmatch(name, pattern), f"{name} should match {pattern}"

        # Non-memory names should not match
        for name in non_matching_names:
            assert not fnmatch.fnmatch(name, pattern), (
                f"{name} should not match {pattern}"
            )

    def test_method_pattern_matching(self):
        """
        Test that get_* pattern matches method names.

        actingweb_mcp allows method patterns like get_*, list_*, search_*.

        Spec: actingweb_mcp uses method patterns for permission control
        """
        import fnmatch

        pattern = "get_*"

        matching_methods = ["get_profile", "get_notes", "get_memory", "get_settings"]

        non_matching_methods = [
            "list_items",
            "search_memories",
            "update_profile",
            "delete_note",
        ]

        for method in matching_methods:
            assert fnmatch.fnmatch(method, pattern)

        for method in non_matching_methods:
            assert not fnmatch.fnmatch(method, pattern)

    def test_multiple_wildcard_patterns(self):
        """
        Test permissions with multiple wildcard patterns.

        actingweb_mcp defines multiple allowed patterns for different categories.

        Spec: actingweb/permission_evaluator.py:442-454 - Matches any pattern
        """
        import fnmatch

        patterns = ["memory_*", "notes_*", "public_*"]

        matching_names = [
            "memory_personal",
            "notes_work",
            "public_profile",
            "memory_travel",
            "notes_2025",
        ]

        non_matching_names = ["private_settings", "user_config", "auth_token"]

        # Should match at least one pattern
        for name in matching_names:
            matched = any(fnmatch.fnmatch(name, pattern) for pattern in patterns)
            assert matched, f"{name} should match at least one pattern"

        # Should not match any pattern
        for name in non_matching_names:
            matched = any(fnmatch.fnmatch(name, pattern) for pattern in patterns)
            assert not matched, f"{name} should not match any pattern"


class TestMergePermissionsFunction:
    """
    Unit tests for merge_permissions() function.

    These tests verify the merge_base parameter behavior:
    - merge_base=True (default): Union merge for patterns and excluded_patterns
    - merge_base=False: Full replace behavior for all fields

    No DynamoDB required - pure unit tests.
    """

    def test_merge_base_true_unions_patterns(self):
        """
        Test that merge_base=True (default) unions patterns arrays.

        Base patterns should be preserved when override adds new patterns.
        """
        from actingweb.trust_permissions import merge_permissions

        base = {
            "properties": {
                "patterns": ["public/*", "shared/*", "profile/*"],
                "operations": ["read"],
            }
        }
        override = {
            "properties": {"patterns": ["memory_*"], "operations": ["read", "write"]}
        }

        result = merge_permissions(base, override)

        # Patterns should be unioned
        assert result["properties"]["patterns"] == [
            "public/*",
            "shared/*",
            "profile/*",
            "memory_*",
        ]
        # Operations should be replaced
        assert result["properties"]["operations"] == ["read", "write"]

    def test_merge_base_true_unions_excluded_patterns(self):
        """
        Test that merge_base=True unions excluded_patterns arrays.

        Base security exclusions should be preserved when override adds more.
        """
        from actingweb.trust_permissions import merge_permissions

        base = {
            "properties": {
                "patterns": ["*"],
                "excluded_patterns": ["private/*", "security/*", "oauth_*"],
            }
        }
        override = {"properties": {"excluded_patterns": ["memory_personal"]}}

        result = merge_permissions(base, override)

        # Excluded patterns should be unioned
        assert result["properties"]["excluded_patterns"] == [
            "private/*",
            "security/*",
            "oauth_*",
            "memory_personal",
        ]

    def test_merge_base_true_preserves_base_on_empty_override(self):
        """
        Test that empty override arrays don't clear base patterns.

        Security: An override with excluded_patterns=[] should NOT remove
        base security exclusions.
        """
        from actingweb.trust_permissions import merge_permissions

        base = {
            "properties": {
                "patterns": ["public/*", "shared/*"],
                "excluded_patterns": ["private/*", "security/*"],
            }
        }
        override = {
            "properties": {
                "patterns": [],  # Empty - should not clear base
                "excluded_patterns": [],  # Empty - should not clear base
            }
        }

        result = merge_permissions(base, override)

        # Base values should be preserved when override is empty
        assert result["properties"]["patterns"] == ["public/*", "shared/*"]
        assert result["properties"]["excluded_patterns"] == ["private/*", "security/*"]

    def test_merge_base_false_replaces_patterns(self):
        """
        Test that merge_base=False replaces patterns arrays entirely.

        This allows full override when explicitly needed.
        """
        from actingweb.trust_permissions import merge_permissions

        base = {
            "properties": {
                "patterns": ["public/*", "shared/*", "profile/*"],
                "operations": ["read"],
            }
        }
        override = {
            "properties": {"patterns": ["memory_*"], "operations": ["read", "write"]}
        }

        result = merge_permissions(base, override, merge_base=False)

        # Patterns should be replaced
        assert result["properties"]["patterns"] == ["memory_*"]
        # Operations should still be replaced
        assert result["properties"]["operations"] == ["read", "write"]

    def test_merge_base_false_clears_excluded_patterns(self):
        """
        Test that merge_base=False allows clearing excluded_patterns.

        When explicitly set, this enables full override capability.
        """
        from actingweb.trust_permissions import merge_permissions

        base = {
            "properties": {
                "patterns": ["*"],
                "excluded_patterns": ["private/*", "security/*", "oauth_*"],
            }
        }
        override = {"properties": {"excluded_patterns": []}}

        result = merge_permissions(base, override, merge_base=False)

        # Excluded patterns should be cleared
        assert result["properties"]["excluded_patterns"] == []

    def test_merge_base_true_deduplicates_patterns(self):
        """
        Test that merge_base=True deduplicates patterns.

        When override contains patterns already in base, they should not be
        duplicated.
        """
        from actingweb.trust_permissions import merge_permissions

        base = {"properties": {"patterns": ["public/*", "shared/*"]}}
        override = {"properties": {"patterns": ["shared/*", "memory_*"]}}

        result = merge_permissions(base, override)

        # shared/* should appear only once
        assert result["properties"]["patterns"] == ["public/*", "shared/*", "memory_*"]

    def test_merge_base_affects_only_pattern_fields(self):
        """
        Test that merge_base only affects patterns and excluded_patterns.

        Other fields (operations, allowed, denied) should always be replaced.
        """
        from actingweb.trust_permissions import merge_permissions

        base = {
            "methods": {"allowed": ["get_*", "list_*"], "denied": ["admin_*"]},
            "actions": {"allowed": ["search"]},
        }
        override = {
            "methods": {"allowed": ["get_*"], "denied": []},
            "actions": {"allowed": ["search", "export"]},
        }

        result = merge_permissions(base, override, merge_base=True)

        # allowed and denied should be replaced, not merged
        assert result["methods"]["allowed"] == ["get_*"]
        assert result["methods"]["denied"] == []
        assert result["actions"]["allowed"] == ["search", "export"]

    def test_merge_base_with_none_override(self):
        """
        Test that None override returns base permissions unchanged.
        """
        from actingweb.trust_permissions import merge_permissions

        base = {
            "properties": {"patterns": ["public/*"], "excluded_patterns": ["private/*"]}
        }

        result = merge_permissions(base, None)

        assert result == base
        # Should be a copy, not the same object
        assert result is not base

    def test_merge_base_with_category_none_values(self):
        """
        Test that None values in override categories are ignored.

        This allows selective override of only specific categories.
        """
        from actingweb.trust_permissions import merge_permissions

        base = {
            "properties": {"patterns": ["public/*"]},
            "methods": {"allowed": ["get_*"]},
        }
        override = {
            "properties": {"patterns": ["memory_*"]},
            "methods": None,  # Should use base methods
        }

        result = merge_permissions(base, override)

        # Properties should be merged
        assert result["properties"]["patterns"] == ["public/*", "memory_*"]
        # Methods should remain from base
        assert result["methods"]["allowed"] == ["get_*"]

    def test_merge_base_adds_new_categories(self):
        """
        Test that override can add new permission categories.
        """
        from actingweb.trust_permissions import merge_permissions

        base = {"properties": {"patterns": ["public/*"]}}
        override = {"tools": {"allowed": ["search", "export"]}}

        result = merge_permissions(base, override)

        # Original category preserved
        assert result["properties"]["patterns"] == ["public/*"]
        # New category added
        assert result["tools"]["allowed"] == ["search", "export"]
