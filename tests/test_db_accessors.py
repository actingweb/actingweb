"""Tests for DB accessor functions in actingweb.db module.

These tests verify the DB accessor pattern provides a clean API surface.
They don't require actual database connections.
"""

from actingweb.db import (
    get_actor,
    get_actor_list,
    get_attribute,
    get_attribute_bucket_list,
    get_db_accessors,
    get_peer_trustee,
    get_peer_trustee_list,
    get_property,
    get_property_list,
    get_subscription,
    get_subscription_diff,
    get_subscription_diff_list,
    get_subscription_list,
    get_subscription_suspension,
    get_trust,
    get_trust_list,
)


class TestAccessorAPI:
    """Test that accessor functions are properly exported and callable."""

    def test_all_accessors_are_callable(self) -> None:
        """Test that all accessor functions are callable."""
        accessors = [
            get_property,
            get_property_list,
            get_actor,
            get_actor_list,
            get_trust,
            get_trust_list,
            get_peer_trustee,
            get_peer_trustee_list,
            get_subscription,
            get_subscription_list,
            get_subscription_diff,
            get_subscription_diff_list,
            get_subscription_suspension,
            get_attribute,
            get_attribute_bucket_list,
        ]

        for accessor in accessors:
            assert callable(accessor), f"{accessor.__name__} should be callable"

    def test_get_db_accessors_returns_all_functions(self) -> None:
        """Test get_db_accessors returns all accessor functions."""
        accessors = get_db_accessors()
        assert isinstance(accessors, dict)

        # Verify all expected accessors are present
        expected_keys = [
            "property",
            "property_list",
            "actor",
            "actor_list",
            "trust",
            "trust_list",
            "peer_trustee",
            "peer_trustee_list",
            "subscription",
            "subscription_list",
            "subscription_diff",
            "subscription_diff_list",
            "subscription_suspension",
            "attribute",
            "attribute_bucket_list",
        ]

        for key in expected_keys:
            assert key in accessors, f"Expected accessor '{key}' not found"
            assert callable(accessors[key]), f"Accessor '{key}' should be callable"

    def test_accessor_functions_have_docstrings(self) -> None:
        """Test that all accessor functions have documentation."""
        accessors = [
            get_property,
            get_property_list,
            get_actor,
            get_actor_list,
            get_trust,
            get_trust_list,
            get_peer_trustee,
            get_peer_trustee_list,
            get_subscription,
            get_subscription_list,
            get_subscription_diff,
            get_subscription_diff_list,
            get_subscription_suspension,
            get_attribute,
            get_attribute_bucket_list,
        ]

        for accessor in accessors:
            assert accessor.__doc__, f"{accessor.__name__} should have a docstring"
            assert "Args:" in accessor.__doc__, (
                f"{accessor.__name__} docstring should document Args"
            )
            assert "Returns:" in accessor.__doc__, (
                f"{accessor.__name__} docstring should document Returns"
            )


class TestAccessorSignatures:
    """Test that accessor functions have the expected signatures."""

    def test_property_accessor_takes_config_param(self) -> None:
        """Test get_property signature."""
        import inspect

        sig = inspect.signature(get_property)
        assert "config" in sig.parameters
        assert len(sig.parameters) == 1

    def test_all_single_instance_accessors_take_config_param(self) -> None:
        """Test all single-instance accessors take a config parameter."""
        import inspect

        accessors = [
            get_property,
            get_actor,
            get_trust,
            get_peer_trustee,
            get_subscription,
            get_subscription_diff,
            get_subscription_suspension,
            get_attribute,
        ]

        for accessor in accessors:
            sig = inspect.signature(accessor)
            assert "config" in sig.parameters, (
                f"{accessor.__name__} should have a 'config' parameter"
            )
            assert len(sig.parameters) == 1, (
                f"{accessor.__name__} should have exactly one parameter"
            )

    def test_all_list_accessors_take_config_param(self) -> None:
        """Test all list accessors take a config parameter."""
        import inspect

        accessors = [
            get_property_list,
            get_actor_list,
            get_trust_list,
            get_peer_trustee_list,
            get_subscription_list,
            get_subscription_diff_list,
            get_attribute_bucket_list,
        ]

        for accessor in accessors:
            sig = inspect.signature(accessor)
            assert "config" in sig.parameters, (
                f"{accessor.__name__} should have a 'config' parameter"
            )
            assert len(sig.parameters) == 1, (
                f"{accessor.__name__} should have exactly one parameter"
            )
