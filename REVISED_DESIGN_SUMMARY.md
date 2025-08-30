# Unified Access Control System - Revised Design Summary

## Key Design Changes

This revised design implements a **simplified, transparent access control system** that integrates seamlessly with ActingWeb's existing hook architecture:

### 1. Storage Architecture
- **USE EXISTING STORAGE LAYERS** instead of creating new database schemas
  - **Attribute Buckets**: For global trust type definitions (not property store)
  - **Attribute Store**: For private per-relationship permissions and OAuth tokens
  - **Existing Trust Model**: Expanded with new optional fields
- **REUSE EXISTING FIELDS** (relationship, peerid) rather than creating parallel systems

### 2. Simplified Developer Experience
- **TRANSPARENT PERMISSION CHECKING** - developers write hooks normally
- **NO EXPLICIT PERMISSION CHECKS** required in application code
- **ActingWeb handles all security** before calling hooks
- **Simple trust type configuration** with fluent API

### 3. Unified Trust Model

#### Enhanced db_trust Model (Using Existing Fields)
```python
# Expand existing Trust model with new optional attributes
class Trust(Model):
    # Existing attributes (unchanged for backward compatibility)
    id = UnicodeAttribute(hash_key=True)  # actor_id
    peerid = UnicodeAttribute(range_key=True)
    relationship = UnicodeAttribute()  # REUSED for trust type name
    # ... existing fields ...
    
    # New optional unified attributes
    peer_identifier = UnicodeAttribute(null=True)  # Generic identifier (email, username, UUID)
    established_via = UnicodeAttribute(null=True)  # 'actingweb', 'oauth2', 'mcp'
    last_accessed = UTCDateTimeAttribute(null=True)
    created_at = UTCDateTimeAttribute(null=True)
```

#### Global Trust Types in Attribute Buckets
```python
# Global trust type storage using standardized system actor
from actingweb.constants import ACTINGWEB_SYSTEM_ACTOR, TRUST_TYPES_BUCKET

# Store trust type definitions globally
actor = Actor(ACTINGWEB_SYSTEM_ACTOR)
actor.set_attribute_bucket(TRUST_TYPES_BUCKET, 'viewer', {
    'display_name': 'Viewer',
    'description': 'Read-only access',
    'base_permissions': {...},
    'oauth_scope': 'actingweb.viewer'
})
```

#### Permission Storage in Attribute Buckets
```python
# Per-relationship permission overrides
from actingweb.constants import TRUST_PERMISSIONS_BUCKET

actor.set_attribute_bucket(TRUST_PERMISSIONS_BUCKET, f"{actor_id}:{peer_id}", {
    'trust_type': 'viewer',
    'properties': {...},  # User overrides
    'methods': {...},
    'tools': {...}
})
```

### 4. Simplified Permission Integration

#### Transparent Hook Integration
```python
# Developers only need to define trust types and write hooks
access_control = AccessControlConfig(app.config)
access_control.add_trust_type(
    name="api_client",
    display_name="API Client",
    permissions={
        "properties": ["public/*", "api/*"],
        "methods": ["get_*", "list_*"],
        "tools": []
    }
)

# Write hooks normally - ActingWeb handles permission checking automatically
@app.property_hook("email")
def handle_email(actor, operation, value, path):
    # No permission checking needed - ActingWeb already verified access
    return validate_and_store_email(value)
```

### 5. OAuth2 and Trust Establishment Rules

1. **Web Google Auth (non-MCP)**: Authenticate user and set session/actor tokens. Do not create a trust unless `state.trust_type` is explicitly provided.
2. **MCP OAuth**: Create/refresh trust at token issuance (authorization_code exchange), with `trust_type` from state (default `mcp_client`).
3. **REST Trust API**: Unchanged; supports actor↔actor relationships side-by-side with MCP trusts.
4. **Unified Management** through trust management UI.

### 6. Key Benefits

- **No Breaking Changes**: Fully backward compatible
- **Simplified Developer Experience**: No explicit permission checking required
- **Leverages Existing Infrastructure**: Uses established ActingWeb patterns
- **Transparent Security**: Permission checking happens automatically
- **Unified Model**: All external entities are trust relationships
- **Granular Permissions**: Fine-grained control per trust
- **Extensible**: Easy to add new trust types

## Implementation Status

### Phase 1: Foundation ✅ COMPLETED
- ✅ Expanded db_trust model with optional new attributes
- ✅ Implemented trust type registry using attribute buckets
- ✅ Set up permission storage in attribute buckets
- ✅ Standardized system actor naming conventions
- ✅ Created comprehensive test suite

### Phase 2: Permission System ✅ COMPLETED
- ✅ Built permission evaluation engine with pattern matching
- ✅ Implemented transparent hook integration
- ✅ Added caching layer for performance
- ✅ Created simplified AccessControlConfig API

### Phase 3: OAuth2 Integration (Future)
- Trust establishment through OAuth2
- Trust type selection in auth flow
- Token management in attribute store

### Phase 4: MCP Unification (Future)
- MCP clients as trust relationships
- Permission-based resource filtering
- Unified authentication

### Phase 5: Template Variables (Future)
- Enhance WWW handler
- Update actingweb_mcp templates
- Create management UI

### Phase 6: Migration (Future)
- Migrate existing data
- Deploy with feature flags
- Monitor and optimize

## Testing Strategy ✅ COMPLETED

- ✅ **Comprehensive test suite** covering all components
- ✅ **Unit tests** for trust type registry, permission storage, and evaluation
- ✅ **Integration tests** with real ActingWeb infrastructure
- ✅ **Pattern matching validation** for glob and URI patterns
- ✅ **Performance benchmarks** for permission evaluation

## Migration Path

1. **Existing trusts** automatically work with new model (backward compatible)
2. **Optional migration** to populate new fields (peer_identifier, established_via)
3. **Gradual adoption** of permission system in hooks
4. **Full backward compatibility** maintained throughout
5. **Coexistence**: Actor↔Actor trusts via REST continue side-by-side with Actor↔MCP trusts.

## Security Considerations

- **Fail-secure design** - denies access when rules don't match
- **Precedence rules** - explicit deny > explicit allow > trust type allow > default deny
- **Attribute bucket security** for private permission storage
- **Pattern validation** to prevent malicious patterns
- **Performance caching** with security boundaries

## Architectural Decisions Made

1. **Reuse existing fields** (relationship, peerid) instead of creating parallel systems
2. **Attribute buckets for global data** instead of system actors in property store
3. **Standardized system actor naming** (ACTINGWEB_SYSTEM_ACTOR, OAUTH2_SYSTEM_ACTOR)
4. **Transparent hook integration** instead of explicit permission checking
5. **Optional new database fields** to maintain backward compatibility
6. **Generic peer_identifier** to support different services (email, username, UUID)

## Files Implemented

- `actingweb/constants.py` - Standardized system constants
- `actingweb/trust_type_registry.py` - Global trust type storage and management
- `actingweb/trust_permissions.py` - Per-relationship permission storage
- `actingweb/permission_evaluator.py` - Core permission evaluation engine
- `actingweb/permission_integration.py` - Simplified developer API
- `actingweb/db_dynamodb/db_trust.py` - Enhanced trust model
- `docs/unified-access-control.rst` - Complete architecture documentation
- `docs/unified-access-control-simple.rst` - Simple developer guide
- Comprehensive test suite in `tests/` directory

## Next Steps

1. **Phase 3**: Implement OAuth2 trust establishment with trust type selection
2. **Phase 4**: Unify MCP client authentication with trust system
3. **Phase 5**: Enhance WWW handler for template variable generation
4. **Phase 6**: Create migration tools and deployment strategy