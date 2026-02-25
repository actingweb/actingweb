# Plan: AttributeListProperty and AttributeListStore Implementation

## Summary

Implement `AttributeListProperty` and `AttributeListStore` classes that provide the exact same distributed list storage functionality as `ListProperty` and `PropertyListStore`, but using the internal attributes storage backend instead of the externally-exposed properties storage.

This enables applications to store lists in internal attribute buckets, bypassing DynamoDB's 400KB per-item limit while keeping data internal (not exposed via HTTP).

---

## Rationale

- DynamoDB has a 400KB limit per item
- Current `ListProperty` stores each item as a separate property (`list:{name}-{index}`)
- `AttributeListProperty` will use the same distributed storage pattern but with attributes
- Attributes are internal-only (not exposed via REST API), suitable for caching and internal state

---

## Storage Model

### Key Difference: Properties vs Attributes

| Aspect | Properties (ListProperty) | Attributes (AttributeListProperty) |
|--------|---------------------------|-------------------------------------|
| **Storage Key** | `actor_id` + `property_name` | `actor_id` + `bucket` + `attribute_name` |
| **Exposure** | HTTP-accessible via REST API | Internal-only, never exposed |
| **Use Case** | User-facing data | Internal caching/state |
| **Naming** | `list:{name}-{index}` | `list:{name}:{index}` within bucket |

### Naming Patterns

| Aspect | ListProperty | AttributeListProperty |
|--------|--------------|----------------------|
| **Item Pattern** | `list:{name}-{index}` | `list:{name}:{index}` |
| **Meta Pattern** | `list:{name}-meta` | `list:{name}:meta` |
| **Separator** | Hyphen `-` | Colon `:` |

---

## API Comparison: ListProperty vs AttributeListProperty

The `AttributeListProperty` class MUST be a drop-in replacement for `ListProperty`. This section documents the exact API that must be replicated.

### Constructor Differences

| Aspect | ListProperty | AttributeListProperty |
|--------|--------------|----------------------|
| **Signature** | `__init__(actor_id: str, name: str, config: Any)` | `__init__(actor_id: str, bucket: str, name: str, config: Any)` |
| **Key Difference** | No bucket (flat namespace) | Requires bucket parameter |
| **DB Backend** | `config.DbProperty.DbProperty()` | `config.DbAttribute.DbAttribute()` |

### Metadata Fields (Identical Structure)

Both classes use identical metadata structure:

```python
{
    "length": 0,           # Number of items in list
    "created_at": "...",   # ISO timestamp
    "updated_at": "...",   # ISO timestamp
    "item_type": "json",   # Storage type (always "json")
    "chunk_size": 1,       # Items per storage unit (always 1)
    "version": "1.0",      # Schema version
    "description": "",     # Human-readable description
    "explanation": "",     # LLM-readable explanation
}
```

### Complete Method API (Must Match Exactly)

#### Initialization & Internal Methods

```python
# ListProperty
def __init__(self, actor_id: str, name: str, config: Any) -> None

# AttributeListProperty (bucket added)
def __init__(self, actor_id: str, bucket: str, name: str, config: Any) -> None

# Both classes implement these internal methods (identical behavior):
def _get_meta_attribute_name(self) -> str      # Returns meta attribute name
def _get_item_attribute_name(self, index: int) -> str  # Returns item name for index
def _load_metadata(self) -> dict[str, Any]    # Load/create metadata with caching
def _create_default_metadata(self) -> dict[str, Any]  # Default metadata structure
def _save_metadata(self, meta: dict[str, Any]) -> None  # Persist metadata
def _invalidate_cache(self) -> None           # Clear metadata cache
```

#### Public API Methods (Identical Behavior Required)

| Method | Signature | Behavior |
|--------|-----------|----------|
| `get_description` | `() -> str` | Returns description from metadata, empty string if None |
| `set_description` | `(description: str) -> None` | Sets description, saves metadata |
| `get_explanation` | `() -> str` | Returns explanation from metadata, empty string if None |
| `set_explanation` | `(explanation: str) -> None` | Sets explanation, saves metadata |
| `__len__` | `() -> int` | Returns length from metadata (no item loading) |
| `__getitem__` | `(index: int) -> Any` | Get item, supports negative index, raises IndexError |
| `__setitem__` | `(index: int, value: Any) -> None` | Set item, supports negative index, raises IndexError |
| `__delitem__` | `(index: int) -> None` | Delete item, shift remaining items, update length |
| `__iter__` | `() -> Iterator` | Returns lazy-loading iterator |
| `append` | `(item: Any) -> None` | Add item at end, increment length |
| `extend` | `(items: list[Any]) -> None` | Add multiple items (calls append for each) |
| `clear` | `() -> None` | Delete all items, reset metadata to defaults |
| `delete` | `() -> None` | Delete all items AND metadata attribute |
| `to_list` | `() -> list[Any]` | Load entire list into memory, return copy |
| `slice` | `(start: int, end: int) -> list[Any]` | Load range, handles negative indices |
| `pop` | `(index: int = -1) -> Any` | Remove and return item, raises IndexError if empty |
| `insert` | `(index: int, item: Any) -> None` | Insert at index, shift items up |
| `remove` | `(value: Any) -> None` | Remove first occurrence, raises ValueError |
| `index` | `(value: Any, start: int = 0, stop: int \| None = None) -> int` | Find value index, raises ValueError |
| `count` | `(value: Any) -> int` | Count occurrences |

#### Error Handling (Must Match)

| Scenario | Error |
|----------|-------|
| Index out of range | `raise IndexError(f"List index {index} out of range (length: {length})")` |
| No database | `raise RuntimeError("No database connection available")` |
| Item not found in DB | `raise IndexError(f"List item at index {index} not found in database")` |
| pop() empty list | `raise IndexError("pop from empty list")` |
| remove() not found | `raise ValueError(f"{value} not in list")` |
| index() not found | `raise ValueError(f"{value} is not in list")` |

### Store Classes Comparison

| Aspect | PropertyListStore | AttributeListStore |
|--------|-------------------|-------------------|
| **Signature** | `__init__(actor_id, config)` | `__init__(actor_id, bucket, config)` |
| **Key Difference** | Per-actor only | Per-actor AND per-bucket |
| **exists(name)** | Check for `list:{name}-meta` property | Check for `list:{name}:meta` attribute |
| **list_all()** | Scan all properties, filter for `-meta` | Scan bucket, filter for `:meta` |
| **__getattr__(k)** | Return `ListProperty(actor_id, k, config)` | Return `AttributeListProperty(actor_id, bucket, k, config)` |

### Usage Pattern Comparison

```python
# Using PropertyListStore (existing)
actor = ActorInterface.create(creator="test@example.com", config=config)
memory_list = actor.property_lists.personal_memories
memory_list.append({"content": "Remember this"})

# Using AttributeListStore (new)
store = AttributeListStore(actor_id=actor.id, bucket="my_bucket", config=config)
memory_list = store.personal_memories
memory_list.append({"content": "Remember this"})
```

---

## Files to Create/Modify

### 1. New File: `actingweb/attribute_list.py`

Create `AttributeListProperty` class mirroring `ListProperty` (property_list.py:39-469):

```python
class AttributeListIterator:
    """Lazy-loading iterator for AttributeListProperty."""

class AttributeListProperty:
    """
    Distributed list storage using attributes within a bucket.

    Stores items as: list:{name}:{index} attributes
    Stores metadata as: list:{name}:meta attribute
    """

    def __init__(self, actor_id: str, bucket: str, name: str, config: Any) -> None:
        self.actor_id = actor_id
        self.bucket = bucket
        self.name = name
        self.config = config
        self._meta_cache: dict[str, Any] | None = None
```

**Key Implementation Details:**

1. **Lazy Attribute Loading**: Don't call `Attributes()` in `__init__` (it loads entire bucket). Create fresh instances on-demand for specific operations.

2. **Efficient get_attr calls**: Use `Attributes.get_attr(name)` for single-item access instead of `get_bucket()`.

3. **Fresh DB Instances**: Create fresh `Attributes` instances for each operation to avoid handle conflicts (same pattern as `ListProperty`).

4. **Data Storage Difference**: ListProperty stores JSON strings via `DbProperty.set(value=json_str)`. AttributeListProperty stores data directly via `DbAttribute.set_attr(data=dict)` since attributes support native JSON.

### 2. New File: `actingweb/attribute_list_store.py`

Create `AttributeListStore` class mirroring `PropertyListStore` (property.py:6-64):

```python
class AttributeListStore:
    """
    Explicit interface for managing list attributes within a bucket.

    Unlike PropertyListStore (which is per-actor), this is per-actor-per-bucket.
    """

    def __init__(
        self,
        actor_id: str | None = None,
        bucket: str | None = None,
        config: Any | None = None
    ) -> None:
        self._actor_id = actor_id
        self._bucket = bucket
        self._config = config
        self._list_cache: dict[str, AttributeListProperty] = {}
        self.__initialised = True

    def exists(self, name: str) -> bool:
        """Check if a list exists by checking for its metadata attribute."""

    def list_all(self) -> list[str]:
        """List all existing attribute list names in this bucket."""

    def __getattr__(self, k: str) -> AttributeListProperty:
        """Return an AttributeListProperty for the requested list name."""
```

### 3. Update: `actingweb/__init__.py`

Export new classes:

```python
from .attribute_list import AttributeListProperty, AttributeListIterator
from .attribute_list_store import AttributeListStore
```

---

## Implementation Order

| Step | Task | Dependencies |
|------|------|--------------|
| 1 | Create `attribute_list.py` with `AttributeListProperty` class | None |
| 2 | Create `attribute_list_store.py` with `AttributeListStore` class | Step 1 |
| 3 | Update `actingweb/__init__.py` to export new classes | Steps 1, 2 |
| 4 | Write unit tests for `AttributeListProperty` | Step 1 |
| 5 | Write unit tests for `AttributeListStore` | Step 2 |
| 6 | Write integration tests | Steps 1-3 |
| 7 | Run full test suite, fix any issues | All above |
| 8 | Run type checking (`pyright`) and linting (`ruff`) | All above |

---

## Test Specifications

### Unit Tests: `tests/test_attribute_list.py`

Mirror patterns from `tests/test_attribute.py`.

#### TestAttributeListPropertyInitialization

```python
def test_init_with_all_params():
    """Test initialization with actor_id, bucket, name, config."""

def test_init_without_config():
    """Test initialization without config (no database)."""

def test_get_meta_attribute_name():
    """Test _get_meta_attribute_name() returns 'list:{name}:meta'."""

def test_get_item_attribute_name():
    """Test _get_item_attribute_name(index) returns 'list:{name}:{index}'."""
```

#### TestAttributeListPropertyMetadata

```python
def test_load_metadata_creates_default():
    """Test _load_metadata() creates default if none exists."""

def test_load_metadata_from_cache():
    """Test _load_metadata() returns cached value on subsequent calls."""

def test_save_metadata_persists():
    """Test _save_metadata() writes to database."""

def test_metadata_fields():
    """Test metadata includes length, created_at, updated_at, version."""
```

#### TestAttributeListPropertyBasicOperations

```python
def test_append_single_item():
    """Test append() adds item at end."""

def test_append_updates_metadata_length():
    """Test append() increments metadata length."""

def test_extend_multiple_items():
    """Test extend() adds multiple items."""

def test_extend_empty_list():
    """Test extend([]) is no-op."""

def test_len_empty_list():
    """Test __len__ returns 0 for empty list."""

def test_len_after_operations():
    """Test __len__ returns correct count after appends/deletes."""
```

#### TestAttributeListPropertyIndexing

```python
def test_getitem_positive_index():
    """Test __getitem__ with positive index."""

def test_getitem_negative_index():
    """Test __getitem__ with -1, -2, etc."""

def test_getitem_out_of_range():
    """Test __getitem__ raises IndexError."""

def test_setitem_positive_index():
    """Test __setitem__ with positive index."""

def test_setitem_negative_index():
    """Test __setitem__ with negative index."""

def test_setitem_out_of_range():
    """Test __setitem__ raises IndexError."""

def test_delitem_shifts_items():
    """Test __delitem__ removes item and shifts subsequent items."""

def test_delitem_negative_index():
    """Test __delitem__ with negative index."""

def test_delitem_updates_length():
    """Test __delitem__ decrements metadata length."""
```

#### TestAttributeListPropertyBulkOperations

```python
def test_clear_removes_all_items():
    """Test clear() removes all items."""

def test_clear_resets_metadata():
    """Test clear() resets metadata to defaults."""

def test_delete_removes_all_including_metadata():
    """Test delete() removes items AND metadata attribute."""

def test_delete_allows_recreation():
    """Test list can be recreated after delete()."""

def test_to_list_preserves_order():
    """Test to_list() returns items in order."""

def test_slice_returns_range():
    """Test slice(start, end) returns correct range."""
```

#### TestAttributeListPropertyIteration

```python
def test_iter_empty_list():
    """Test iteration over empty list yields nothing."""

def test_iter_returns_all_items():
    """Test iteration returns all items in order."""

def test_iterator_lazy_loading():
    """Test AttributeListIterator loads items on-demand."""
```

#### TestAttributeListPropertyAdvanced

```python
def test_pop_default_last():
    """Test pop() removes and returns last item."""

def test_pop_specific_index():
    """Test pop(index) removes and returns item at index."""

def test_pop_empty_raises():
    """Test pop() from empty list raises IndexError."""

def test_insert_at_index():
    """Test insert(index, item) shifts items."""

def test_remove_value():
    """Test remove(value) removes first occurrence."""

def test_remove_not_found():
    """Test remove(value) raises ValueError if not found."""

def test_index_finds_value():
    """Test index(value) returns correct index."""

def test_count_occurrences():
    """Test count(value) returns occurrence count."""
```

### Unit Tests: `tests/test_attribute_list_store.py`

#### TestAttributeListStoreInitialization

```python
def test_init_with_all_params():
    """Test initialization with actor_id, bucket, config."""

def test_init_requires_actor_id():
    """Test __getattr__ raises if actor_id is None."""

def test_init_requires_bucket():
    """Test __getattr__ raises if bucket is None."""
```

#### TestAttributeListStoreOperations

```python
def test_exists_returns_false_for_nonexistent():
    """Test exists() returns False for non-existent list."""

def test_exists_returns_true_for_existing():
    """Test exists() returns True for list with metadata."""

def test_list_all_empty():
    """Test list_all() returns empty list when no lists exist."""

def test_list_all_returns_all_lists():
    """Test list_all() returns all list names."""

def test_list_all_filters_non_list_attributes():
    """Test list_all() ignores attributes without :meta suffix."""

def test_getattr_returns_attribute_list_property():
    """Test __getattr__ returns AttributeListProperty instance."""

def test_getattr_caches_instance():
    """Test __getattr__ returns same instance on repeated calls."""

def test_getattr_rejects_private_names():
    """Test __getattr__ raises AttributeError for _private names."""
```

### Integration Tests: `tests/integration/test_attribute_lists_advanced.py`

Mirror patterns from `tests/integration/test_property_lists_advanced.py`.

#### TestAttributeListDynamicCreation

```python
def test_create_multiple_attribute_lists_dynamically(test_actor):
    """Test creating multiple lists with arbitrary names."""

def test_attribute_list_names_with_special_characters(test_actor):
    """Test list names with underscores, numbers."""
```

#### TestAttributeListMetadataStorage

```python
def test_description_and_explanation_persist(test_actor):
    """Test get/set description and explanation."""

def test_metadata_accessible_with_many_items(test_actor):
    """Test metadata retrieval with 100+ items."""
```

#### TestAttributeListDiscovery

```python
def test_list_all_returns_all_lists(test_actor):
    """Test list_all() discovers all lists in bucket."""

def test_exists_check(test_actor):
    """Test exists() accurately reports list existence."""

def test_exists_false_for_accessed_but_empty(test_actor):
    """Test exists() returns False for lists never populated."""
```

#### TestAttributeListDeletion

```python
def test_complete_list_deletion(test_actor):
    """Test delete() removes list completely."""

def test_delete_item_by_index(test_actor):
    """Test deleting items by index shifts remaining items."""
```

#### TestAttributeListLargeData

```python
def test_list_with_100_items(test_actor):
    """Test list operations with 100 items."""

def test_multiple_large_lists(test_actor):
    """Test multiple lists each with many items."""

def test_large_item_content(test_actor):
    """Test items with large JSON content."""
```

#### TestAttributeListBucketIsolation

```python
def test_lists_in_different_buckets_isolated(test_actor):
    """Test lists in different buckets don't interfere."""

def test_same_list_name_in_different_buckets(test_actor):
    """Test same list name can exist independently in different buckets."""
```

---

## Verification Checklist

- [ ] `poetry run pytest tests/test_attribute_list.py -v` - Unit tests pass
- [ ] `poetry run pytest tests/test_attribute_list_store.py -v` - Unit tests pass
- [ ] `poetry run pytest tests/integration/test_attribute_lists_advanced.py -v` - Integration tests pass
- [ ] `make test-all-parallel` - All 900+ tests pass
- [ ] `poetry run pyright actingweb tests` - 0 type errors
- [ ] `poetry run ruff check actingweb tests` - 0 linting errors
- [ ] `poetry run ruff format actingweb tests` - Formatted

---

## Reference Files

| File | Purpose |
|------|---------|
| `actingweb/property_list.py` | ListProperty implementation to mirror |
| `actingweb/property.py` | PropertyListStore implementation to mirror |
| `actingweb/attribute.py` | Attributes class (storage backend) |
| `tests/test_attribute.py` | Unit test patterns |
| `tests/integration/test_property_lists_advanced.py` | Integration test patterns |
| `actingweb/db/protocols.py` | Database interface protocols |

---

## Critical Behavioral Details to Preserve

1. **Fresh DB Instances**: Create new `DbAttribute` instance for each operation to avoid handle conflicts

2. **Metadata Caching**: Cache metadata in `_meta_cache`, invalidate appropriately

3. **Lazy Loading**: Iterator loads items one at a time, not all at once

4. **Index Shifting**: On delete, shift all subsequent items down by one

5. **Empty List Handling**:
   - `len()` returns 0
   - `to_list()` returns `[]`
   - `pop()` raises `IndexError`
   - Iteration yields nothing

6. **Negative Index Support**: `-1` means last item, `-2` means second to last, etc.

7. **Clear vs Delete**:
   - `clear()`: Removes items, resets metadata with new timestamps
   - `delete()`: Removes items AND metadata attribute

---

## Edge Cases to Test

1. **Empty string values**: `append("")` should store empty string, not be treated as None/delete
2. **None values**: `append(None)` should store JSON `null`
3. **Special characters in list names**: Names like `my_list`, `my.list` should work
4. **Unicode in values**: Full Unicode support including emoji
5. **Nested structures**: Deeply nested dicts/lists should serialize correctly
6. **Boundary conditions**:
   - `slice(0, 0)` returns `[]`
   - `slice(5, 3)` returns `[]` (start > end after normalization)
   - `index(value, 0, 0)` raises ValueError
   - `pop(0)` on single-item list leaves empty list

---

## Storage Implementation Note

**Important difference in data storage**:

```python
# ListProperty stores JSON strings
db.set(name="list:foo-0", value='{"key": "value"}')  # String

# AttributeListProperty stores data directly (attributes support native JSON)
db.set_attr(name="list:foo:0", data={"key": "value"})  # Dict directly
```

From the user's perspective, behavior is identical - they interact with Python objects. The serialization is handled internally.
