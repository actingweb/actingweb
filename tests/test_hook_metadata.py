"""Tests for hook metadata functionality.

Tests the HookMetadata dataclass, get_hook_metadata() helper,
and metadata list methods in HookRegistry.
"""

from actingweb.interface.hooks import (
    HookMetadata,
    HookRegistry,
    get_hook_metadata,
)


class TestHookMetadata:
    """Tests for HookMetadata dataclass."""

    def test_default_values(self) -> None:
        """Test HookMetadata default values."""
        metadata = HookMetadata()
        assert metadata.description == ""
        assert metadata.input_schema is None
        assert metadata.output_schema is None
        assert metadata.annotations is None

    def test_with_all_values(self) -> None:
        """Test HookMetadata with all values specified."""
        metadata = HookMetadata(
            description="Test description",
            input_schema={"type": "object", "properties": {"x": {"type": "number"}}},
            output_schema={"type": "object", "properties": {"result": {"type": "number"}}},
            annotations={"readOnlyHint": True, "idempotentHint": True},
        )
        assert metadata.description == "Test description"
        assert metadata.input_schema == {"type": "object", "properties": {"x": {"type": "number"}}}
        assert metadata.output_schema == {"type": "object", "properties": {"result": {"type": "number"}}}
        assert metadata.annotations == {"readOnlyHint": True, "idempotentHint": True}

    def test_partial_values(self) -> None:
        """Test HookMetadata with partial values."""
        metadata = HookMetadata(description="Only description")
        assert metadata.description == "Only description"
        assert metadata.input_schema is None
        assert metadata.output_schema is None
        assert metadata.annotations is None


class TestGetHookMetadata:
    """Tests for get_hook_metadata() function."""

    def test_with_hook_metadata(self) -> None:
        """Test get_hook_metadata returns _hook_metadata when present."""
        def sample_hook(actor, name, data):
            return {"result": "ok"}

        expected = HookMetadata(
            description="Test method",
            input_schema={"type": "object"},
        )
        sample_hook._hook_metadata = expected

        result = get_hook_metadata(sample_hook)
        # Note: result may be a new object due to auto-schema filling, so check values
        assert result.description == expected.description
        assert result.input_schema == expected.input_schema
        assert result.description == "Test method"

    def test_fallback_to_mcp_metadata(self) -> None:
        """Test get_hook_metadata falls back to _mcp_metadata."""
        def sample_hook(actor, name, data):
            return {"result": "ok"}

        mcp_metadata = {
            "description": "MCP description",
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
            "output_schema": {"type": "array"},
            "annotations": {"destructiveHint": False},
        }
        sample_hook._mcp_metadata = mcp_metadata

        result = get_hook_metadata(sample_hook)
        assert result.description == "MCP description"
        assert result.input_schema == {"type": "object", "properties": {"query": {"type": "string"}}}
        assert result.output_schema == {"type": "array"}
        assert result.annotations == {"destructiveHint": False}

    def test_hook_metadata_takes_precedence_over_mcp(self) -> None:
        """Test _hook_metadata takes precedence over _mcp_metadata."""
        def sample_hook(actor, name, data):
            return {"result": "ok"}

        hook_metadata = HookMetadata(description="Hook description")
        mcp_metadata = {"description": "MCP description"}
        sample_hook._hook_metadata = hook_metadata
        sample_hook._mcp_metadata = mcp_metadata

        result = get_hook_metadata(sample_hook)
        assert result.description == "Hook description"

    def test_returns_default_when_no_metadata(self) -> None:
        """Test get_hook_metadata returns defaults when no metadata."""
        def sample_hook(actor, name, data):
            return {"result": "ok"}

        result = get_hook_metadata(sample_hook)
        assert result.description == ""
        assert result.input_schema is None
        assert result.output_schema is None
        assert result.annotations is None

    def test_mcp_metadata_none_description(self) -> None:
        """Test MCP metadata with None description converts to empty string."""
        def sample_hook(actor, name, data):
            return {"result": "ok"}

        mcp_metadata = {
            "description": None,
            "input_schema": {"type": "object"},
        }
        sample_hook._mcp_metadata = mcp_metadata

        result = get_hook_metadata(sample_hook)
        assert result.description == ""


class TestHookRegistryMetadataLists:
    """Tests for HookRegistry metadata list methods."""

    def test_get_method_metadata_list_empty(self) -> None:
        """Test get_method_metadata_list with no hooks."""
        registry = HookRegistry()
        result = registry.get_method_metadata_list()
        assert result == []

    def test_get_action_metadata_list_empty(self) -> None:
        """Test get_action_metadata_list with no hooks."""
        registry = HookRegistry()
        result = registry.get_action_metadata_list()
        assert result == []

    def test_get_method_metadata_list_with_metadata(self) -> None:
        """Test get_method_metadata_list with hooks that have metadata."""
        registry = HookRegistry()

        def method1(actor, name, data):
            return {"result": 1}

        def method2(actor, name, data):
            return {"result": 2}

        method1._hook_metadata = HookMetadata(description="Method 1 description", input_schema={"type": "object"}, annotations={"readOnlyHint": True})
        method2._hook_metadata = HookMetadata(description="Method 2 description")

        registry.register_method_hook("method1", method1)
        registry.register_method_hook("method2", method2)

        result = registry.get_method_metadata_list()
        assert len(result) == 2

        # Find method1 in results
        method1_data = next(m for m in result if m["name"] == "method1")
        assert method1_data["description"] == "Method 1 description"
        assert method1_data["input_schema"] == {"type": "object"}
        assert method1_data["annotations"] == {"readOnlyHint": True}

        # Find method2 in results
        method2_data = next(m for m in result if m["name"] == "method2")
        assert method2_data["description"] == "Method 2 description"
        assert method2_data["input_schema"] is None

    def test_get_action_metadata_list_with_metadata(self) -> None:
        """Test get_action_metadata_list with hooks that have metadata."""
        registry = HookRegistry()

        def action1(actor, name, data):
            return {"status": "ok"}

        action1._hook_metadata = HookMetadata(description="Action 1 description", annotations={"destructiveHint": True})

        registry.register_action_hook("action1", action1)

        result = registry.get_action_metadata_list()
        assert len(result) == 1
        assert result[0]["name"] == "action1"
        assert result[0]["description"] == "Action 1 description"
        assert result[0]["annotations"] == {"destructiveHint": True}

    def test_wildcard_hooks_excluded(self) -> None:
        """Test that wildcard hooks are excluded from metadata lists."""
        registry = HookRegistry()

        def wildcard_method(actor, name, data):
            return {"result": "wildcard"}

        def specific_method(actor, name, data):
            return {"result": "specific"}

        wildcard_method._hook_metadata = HookMetadata(description="Wildcard")
        specific_method._hook_metadata = HookMetadata(description="Specific")

        registry.register_method_hook("*", wildcard_method)
        registry.register_method_hook("specific", specific_method)

        result = registry.get_method_metadata_list()
        assert len(result) == 1
        assert result[0]["name"] == "specific"
        assert result[0]["description"] == "Specific"

    def test_hooks_without_metadata_get_defaults(self) -> None:
        """Test that hooks without metadata return default values."""
        registry = HookRegistry()

        def bare_method(actor, name, data):
            return {"result": "bare"}

        registry.register_method_hook("bare_method", bare_method)

        result = registry.get_method_metadata_list()
        assert len(result) == 1
        assert result[0]["name"] == "bare_method"
        assert result[0]["description"] == ""
        assert result[0]["input_schema"] is None
        assert result[0]["output_schema"] is None
        assert result[0]["annotations"] is None

    def test_multiple_hooks_same_name_uses_first(self) -> None:
        """Test that when multiple hooks registered for same name, first one's metadata is used."""
        registry = HookRegistry()

        def first_hook(actor, name, data):
            return {"result": "first"}

        def second_hook(actor, name, data):
            return {"result": "second"}

        first_hook._hook_metadata = HookMetadata(description="First hook")
        second_hook._hook_metadata = HookMetadata(description="Second hook")

        registry.register_method_hook("mymethod", first_hook)
        registry.register_method_hook("mymethod", second_hook)

        result = registry.get_method_metadata_list()
        assert len(result) == 1
        assert result[0]["description"] == "First hook"


class TestDecoratorMetadataStorage:
    """Tests that decorators properly store metadata on functions."""

    def test_method_hook_decorator_stores_metadata(self) -> None:
        """Test that method_hook decorator stores metadata."""
        from actingweb.interface.hooks import method_hook

        @method_hook(
            "test_method",
            description="Test method description",
            input_schema={"type": "object"},
            output_schema={"type": "string"},
            annotations={"readOnlyHint": True},
        )
        def test_func(actor, name, data):
            return "test"

        assert hasattr(test_func, "_hook_metadata")
        metadata = test_func._hook_metadata
        assert isinstance(metadata, HookMetadata)
        assert metadata.description == "Test method description"
        assert metadata.input_schema == {"type": "object"}
        assert metadata.output_schema == {"type": "string"}
        assert metadata.annotations == {"readOnlyHint": True}

    def test_action_hook_decorator_stores_metadata(self) -> None:
        """Test that action_hook decorator stores metadata."""
        from actingweb.interface.hooks import action_hook

        @action_hook(
            "test_action",
            description="Test action description",
            annotations={"destructiveHint": True},
        )
        def test_func(actor, name, data):
            return {"status": "ok"}

        assert hasattr(test_func, "_hook_metadata")
        metadata = test_func._hook_metadata
        assert isinstance(metadata, HookMetadata)
        assert metadata.description == "Test action description"
        assert metadata.annotations == {"destructiveHint": True}

    def test_decorator_without_metadata_stores_defaults(self) -> None:
        """Test decorator without metadata args stores default HookMetadata."""
        from actingweb.interface.hooks import method_hook

        @method_hook("simple_method")
        def simple_func(actor, name, data):
            return "simple"

        assert hasattr(simple_func, "_hook_metadata")
        metadata = simple_func._hook_metadata
        assert metadata.description == ""
        assert metadata.input_schema is None


class TestAutoSchemaGeneration:
    """Tests for automatic schema generation from TypedDict type hints."""

    def test_auto_input_schema_from_typeddict(self) -> None:
        """Test auto-generation of input_schema from TypedDict parameter."""
        from typing import TypedDict

        from actingweb.interface.hooks import get_hook_metadata

        class CalculateInput(TypedDict):
            x: float
            y: float

        def calculate(actor, method_name, data: CalculateInput):
            return {"result": data["x"] + data["y"]}

        metadata = get_hook_metadata(calculate)

        assert metadata.input_schema is not None
        assert metadata.input_schema["type"] == "object"
        assert "properties" in metadata.input_schema
        assert "x" in metadata.input_schema["properties"]
        assert "y" in metadata.input_schema["properties"]
        assert metadata.input_schema["properties"]["x"]["type"] == "number"
        assert metadata.input_schema["properties"]["y"]["type"] == "number"

    def test_auto_output_schema_from_return_type(self) -> None:
        """Test auto-generation of output_schema from TypedDict return type."""
        from typing import TypedDict

        from actingweb.interface.hooks import get_hook_metadata

        class CalculateOutput(TypedDict):
            result: float

        def calculate(actor, method_name, data) -> CalculateOutput:
            return {"result": 42.0}

        metadata = get_hook_metadata(calculate)

        assert metadata.output_schema is not None
        assert metadata.output_schema["type"] == "object"
        assert "properties" in metadata.output_schema
        assert "result" in metadata.output_schema["properties"]
        assert metadata.output_schema["properties"]["result"]["type"] == "number"

    def test_auto_both_schemas(self) -> None:
        """Test auto-generation of both input and output schemas."""
        from typing import TypedDict

        from actingweb.interface.hooks import get_hook_metadata

        class SearchInput(TypedDict):
            query: str
            limit: int

        class SearchOutput(TypedDict):
            results: list[str]
            count: int

        def search(actor, action_name, data: SearchInput) -> SearchOutput:
            return {"results": [], "count": 0}

        metadata = get_hook_metadata(search)

        # Check input schema
        assert metadata.input_schema is not None
        assert "query" in metadata.input_schema["properties"]
        assert metadata.input_schema["properties"]["query"]["type"] == "string"
        assert metadata.input_schema["properties"]["limit"]["type"] == "integer"

        # Check output schema
        assert metadata.output_schema is not None
        assert "results" in metadata.output_schema["properties"]
        assert metadata.output_schema["properties"]["results"]["type"] == "array"
        assert metadata.output_schema["properties"]["count"]["type"] == "integer"

    def test_explicit_schema_overrides_auto(self) -> None:
        """Test that explicit schema takes precedence over auto-generated."""
        from typing import TypedDict

        from actingweb.interface.hooks import HookMetadata, get_hook_metadata

        class AutoInput(TypedDict):
            auto_field: str

        def my_method(actor, method_name, data: AutoInput):
            return {"result": "ok"}

        # Set explicit schema that differs from type hint
        explicit_schema = {"type": "object", "properties": {"explicit_field": {"type": "number"}}}
        my_method._hook_metadata = HookMetadata(input_schema=explicit_schema)

        metadata = get_hook_metadata(my_method)

        # Should use explicit, not auto-generated
        assert metadata.input_schema == explicit_schema
        assert "explicit_field" in metadata.input_schema["properties"]

    def test_auto_schema_fills_missing_in_explicit(self) -> None:
        """Test that auto-schema fills in missing schemas even when explicit metadata exists."""
        from typing import TypedDict

        from actingweb.interface.hooks import HookMetadata, get_hook_metadata

        class MyOutput(TypedDict):
            status: str

        def my_action(actor, action_name, data) -> MyOutput:
            return {"status": "ok"}

        # Set explicit metadata with only description, no schemas
        my_action._hook_metadata = HookMetadata(description="My action")

        metadata = get_hook_metadata(my_action)

        # Description should be from explicit
        assert metadata.description == "My action"
        # output_schema should be auto-generated
        assert metadata.output_schema is not None
        assert "status" in metadata.output_schema["properties"]

    def test_no_auto_schema_for_plain_dict(self) -> None:
        """Test that plain dict type hints don't generate schemas."""
        from actingweb.interface.hooks import get_hook_metadata

        def my_method(actor, method_name, data: dict) -> dict:
            return {}

        metadata = get_hook_metadata(my_method)

        # Should not auto-generate from plain dict
        assert metadata.input_schema is None
        assert metadata.output_schema is None

    def test_optional_fields_in_typeddict(self) -> None:
        """Test handling of optional fields in TypedDict."""
        from typing import NotRequired, TypedDict

        from actingweb.interface.hooks import get_hook_metadata

        class InputWithOptional(TypedDict):
            required_field: str
            optional_field: NotRequired[int]

        def my_method(actor, method_name, data: InputWithOptional):
            return {}

        metadata = get_hook_metadata(my_method)

        assert metadata.input_schema is not None
        assert "required_field" in metadata.input_schema["properties"]
        assert "optional_field" in metadata.input_schema["properties"]
        # required_field should be in required list
        assert "required" in metadata.input_schema
        assert "required_field" in metadata.input_schema["required"]

    def test_nested_typeddict(self) -> None:
        """Test handling of nested TypedDict."""
        from typing import TypedDict

        from actingweb.interface.hooks import get_hook_metadata

        class Address(TypedDict):
            street: str
            city: str

        class Person(TypedDict):
            name: str
            address: Address

        def create_person(actor, action_name, data: Person):
            return {"id": "123"}

        metadata = get_hook_metadata(create_person)

        assert metadata.input_schema is not None
        assert "address" in metadata.input_schema["properties"]
        # Nested TypedDict should be converted to nested object schema
        address_schema = metadata.input_schema["properties"]["address"]
        assert address_schema["type"] == "object"
        assert "street" in address_schema["properties"]


class TestPythonTypeToJsonSchema:
    """Tests for the _python_type_to_json_schema helper function."""

    def test_basic_types(self) -> None:
        """Test conversion of basic Python types."""
        from actingweb.interface.hooks import _python_type_to_json_schema

        assert _python_type_to_json_schema(str) == {"type": "string"}
        assert _python_type_to_json_schema(int) == {"type": "integer"}
        assert _python_type_to_json_schema(float) == {"type": "number"}
        assert _python_type_to_json_schema(bool) == {"type": "boolean"}

    def test_list_types(self) -> None:
        """Test conversion of list types."""
        from actingweb.interface.hooks import _python_type_to_json_schema

        schema = _python_type_to_json_schema(list[str])
        assert schema["type"] == "array"
        assert schema["items"]["type"] == "string"

    def test_optional_types(self) -> None:
        """Test conversion of Optional/nullable types."""
        from actingweb.interface.hooks import _python_type_to_json_schema

        schema = _python_type_to_json_schema(str | None)
        assert "type" in schema
        assert "null" in schema["type"] or schema["type"] == ["string", "null"]
