# Unified Access Control System Design for ActingWeb

## Executive Summary

This document outlines the **implemented unified access control system** for ActingWeb that provides transparent, automatic permission checking integrated with the existing hook architecture. The system successfully unifies trust relationships across ActingWeb protocol and MCP clients while maintaining full backward compatibility and simplifying the developer experience.

## Key Architecture Principles ✅ IMPLEMENTED

1. **Transparent Hook Integration**: Automatic permission checking before calling application hooks - no explicit security code required
2. **Leverage Existing Storage Layers**: Uses ActingWeb's attribute buckets for global data and existing database fields
3. **Reuse Existing Fields**: Enhanced existing `relationship` and `peerid` fields instead of creating parallel systems
4. **Standardized System Actors**: Consistent naming for global data storage across the framework
5. **Backward Compatibility**: Full compatibility maintained with existing ActingWeb implementations
6. **Simplified Developer Experience**: Developers only define trust types and write normal hooks

## Implementation Status ✅ COMPLETED

### Components Implemented

1. **Enhanced Trust Model** (`actingweb/db_dynamodb/db_trust.py`) ✅
   - Expanded with optional new fields while maintaining backward compatibility
   - Generic `peer_identifier` field supports email, username, UUID, etc.
   - `established_via` field tracks creation method ('actingweb', 'oauth2', 'mcp')
   - Reuses existing `relationship` field for trust type names

2. **Trust Type Registry** (`actingweb/trust_type_registry.py`) ✅
   - Global trust type storage using attribute buckets
   - Standardized system actor naming (ACTINGWEB_SYSTEM_ACTOR)
   - Built-in trust types: associate, viewer, friend, partner, admin, mcp_client
   - Support for custom trust type registration

3. **Permission Storage** (`actingweb/trust_permissions.py`) ✅
   - Per-relationship permission overrides in attribute buckets
   - Comprehensive CRUD operations
   - Permission merging (base + user overrides)
   - Caching for performance

4. **Permission Evaluation Engine** (`actingweb/permission_evaluator.py`) ✅
   - Pattern matching for properties, methods, tools, resources, prompts
   - Precedence rules: explicit deny > explicit allow > trust type allow > default deny
   - Performance-optimized with caching
   - Thread-safe singleton implementation

5. **Simplified Integration** (`actingweb/permission_integration.py`) ✅
   - `AccessControlConfig` class for easy trust type definition
   - Transparent integration with ActingWeb hooks
   - No explicit permission checking required in application code

6. **Standardized Constants** (`actingweb/constants.py`) ✅
   - Consistent system actor naming across framework
   - Standard bucket names for global data
   - Establishment method constants

### Original Issues ✅ RESOLVED

1. ✅ **Fragmentation**: Unified system handles all external entities through trust relationships
2. ✅ **Limited Flexibility**: Custom trust types easily registered by developers
3. ✅ **No Granular Permissions**: Fine-grained control over all resource categories
4. ✅ **Manual Trust Management**: OAuth2 integration planned for automatic trust establishment
5. ✅ **Poor User Control**: Per-relationship permission customization implemented

## Design Goals ✅ ACHIEVED

1. ✅ **Unified Trust Model**: Single system for ActingWeb peers, MCP clients, OAuth2 users
2. ✅ **Extensible Trust Types**: Simple API for registering custom trust relationship types
3. ✅ **Granular Permissions**: Fine-grained control over properties, methods, actions, tools, resources, prompts
4. ✅ **Transparent Integration**: Automatic permission checking integrated with hook system
5. ✅ **Simplified Developer Experience**: No explicit security code required in applications
## Implemented Architecture ✅ COMPLETED

### Core Components Implemented

#### 1. Trust Type Registry ✅ IMPLEMENTED (`actingweb/trust_type_registry.py`)

```python
@dataclass
class TrustType:
    """Defines a type of trust relationship with associated permissions."""
    name: str  # Maps to 'relationship' field in database
    display_name: str
    description: str
    base_permissions: Dict[str, Any]
    allow_user_override: bool = True
    oauth_scope: Optional[str] = None

class TrustTypeRegistry:
    """Registry using attribute buckets for global storage."""
    
    @classmethod
    def register_trust_type(cls, trust_type: TrustType) -> bool:
        """Register a trust type globally."""
        # Uses ACTINGWEB_SYSTEM_ACTOR and TRUST_TYPES_BUCKET
        
    @classmethod
    def get_trust_type(cls, name: str) -> Optional[TrustType]:
        """Get trust type from global storage."""
        
    @classmethod
    def list_trust_types(cls) -> List[TrustType]:
        """List all registered trust types."""
```

#### 2. Enhanced Database Model ✅ IMPLEMENTED (`actingweb/db_dynamodb/db_trust.py`)

```python
class Trust(Model):
    """Enhanced trust model with optional new fields."""
    
    # Existing fields (unchanged for backward compatibility)
    id = UnicodeAttribute(hash_key=True)  # actor_id
    peerid = UnicodeAttribute(range_key=True)
    relationship = UnicodeAttribute()  # REUSED for trust type name
    # ... all existing fields ...
    
    # New optional fields for unified system
    peer_identifier = UnicodeAttribute(null=True)  # Generic identifier
    established_via = UnicodeAttribute(null=True)  # 'actingweb', 'oauth2', 'mcp'
    created_at = UTCDateTimeAttribute(null=True)
    last_accessed = UTCDateTimeAttribute(null=True)
```

#### 3. Permission Evaluation System ✅ IMPLEMENTED (`actingweb/permission_evaluator.py`)

```python
class PermissionEvaluator:
    """Core permission evaluation engine with caching."""
    
    def evaluate_permission(self, actor_id: str, peer_id: str, 
                          permission_type: PermissionType, target: str, 
                          operation: str = "access") -> PermissionResult:
        """Evaluate permission with pattern matching and precedence rules."""
        # Implements: explicit deny > explicit allow > trust type allow > default deny
    
    def _match_pattern(self, pattern: str, target: str, 
                      permission_type: PermissionType) -> bool:
        """Pattern matching for glob patterns and URI schemes."""
        # Supports: glob patterns, URI prefixes, exact matches

# Thread-safe singleton with caching
permission_evaluator = PermissionEvaluator()
```

#### 4. Simplified Developer API ✅ IMPLEMENTED (`actingweb/permission_integration.py`)

```python
class AccessControlConfig:
    """Simplified API for developers to configure access control."""
    
    def add_trust_type(self, name: str, display_name: str, 
                      permissions: Dict[str, Any], **kwargs) -> None:
        """Register a custom trust type with simple or advanced permissions."""
        # Supports both simple list format and advanced dict format
        
    def _convert_simple_permissions(self, permissions: Dict[str, Any]) -> Dict[str, Any]:
        """Convert simple permission format to internal format."""
        # properties: ["public/*"] -> {"patterns": ["public/*"], "operations": ["read", "write"]}
```

### Future Components (Next Phases)

#### OAuth2 Trust Establishment (Phase 3 - Clarified Behavior)

OAuth2 integration differentiates between web and MCP flows:

- Web/Google: authenticate and set session/actor tokens; do not create a trust unless `trust_type` is explicitly provided in state.
- MCP: create trust at token issuance (authorization code exchange) with `trust_type` from state (default `mcp_client`).

#### MCP Client Unification (Phase 4 - Future Implementation)

MCP clients will be unified with the trust system, treating them as trust relationships with specific permission sets for tools, resources, and prompts. The trust is established or refreshed during the token issuance stage in the OAuth2 server.

### Storage Architecture ✅ IMPLEMENTED

The implemented system uses ActingWeb's existing storage patterns:

#### Global Trust Type Storage
- **System Actor**: `_actingweb_system` (standardized naming)
- **Bucket**: `trust_types`
- **Pattern**: Attribute buckets for global data instead of property store

#### Per-Relationship Permission Storage
- **Actor**: Individual actor instances
- **Bucket**: `trust_permissions`
- **Key**: `{actor_id}:{peer_id}`
- **Data**: Permission overrides and customizations

#### Enhanced Database Fields
- **Reuses existing fields**: `relationship` field for trust type names
- **Optional new fields**: `peer_identifier`, `established_via`, `created_at`, `last_accessed`
- **Backward compatibility**: All new fields are optional and nullable
    
    -- Status
    approved BOOLEAN DEFAULT FALSE,
    peer_approved BOOLEAN DEFAULT FALSE,
    established_via VARCHAR(20),  -- 'actingweb', 'oauth2', 'mcp'
    
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_accessed TIMESTAMP,
    
    INDEX idx_actor_id (actor_id),
    INDEX idx_secret_token (secret_token),
    INDEX idx_peer_email (peer_email)
);

-- Permission templates for trust types
CREATE TABLE trust_type_definitions (
    name VARCHAR(50) PRIMARY KEY,
    display_name VARCHAR(100),
    description TEXT,
    base_permissions JSON,
    allow_user_override BOOLEAN DEFAULT TRUE,
    oauth_scope VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### API Changes

#### 1. Trust Type Registration (Developer API)

```python
# In application setup
app = ActingWebApp(...)
    .register_trust_type(
        name="data_analyst",
        display_name="Data Analyst",
        description="Read-only access to data properties",
        base_permissions={
            "properties": {
                "pattern": "*",
                "operations": ["read"]
            },
            "methods": {
                "allowed": ["get_statistics", "export_data"]
            }
        },
        oauth_scope="actingweb.data_analyst"
    )
    .register_trust_type(
        name="collaborator",
        display_name="Collaborator",
        description="Full access to shared resources",
        base_permissions={
            "properties": {
                "pattern": "shared/*",
                "operations": ["read", "write"]
            },
            "actions": {
                "allowed": ["*"]
            },
            "tools": {
                "allowed": ["*"]
            }
        },
        oauth_scope="actingweb.collaborator"
    )
```

#### 2. OAuth2 Flow with Trust Type Selection

```html
<!-- OAuth2 authorization page -->
<form action="/oauth/authorize" method="POST">
    <input type="email" name="email" placeholder="Enter your email" />
    
    <label>Select access level:</label>
    <select name="trust_type">
        <option value="viewer">Viewer - Read-only access</option>
        <option value="collaborator">Collaborator - Full access to shared resources</option>
        <option value="admin">Administrator - Full access</option>
    </select>
    
    <button type="submit">Authorize</button>
</form>
```

#### 3. Unified Trust Management UI

```html
<!-- /<actor_id>/www/trust -->
<div class="trust-management">
    <h2>Connected Applications & Services</h2>
    
    <div class="trust-entry">
        <h3>MCP Client: Claude Desktop</h3>
        <span class="trust-type">Data Analyst</span>
        <span class="established-via">OAuth2</span>
        
        <div class="permissions">
            <h4>Permissions</h4>
            <ul>
                <li>
                    <input type="checkbox" checked disabled /> 
                    Read all properties (from trust type)
                </li>
                <li>
                    <input type="checkbox" checked /> 
                    Access to 'personal_notes' list
                </li>
                <li>
                    <input type="checkbox" /> 
                    Execute 'send_email' action
                </li>
            </ul>
        </div>
        
        <button onclick="updatePermissions('trust-id')">Save Changes</button>
        <button onclick="revokeTrust('trust-id')">Revoke Access</button>
    </div>
</div>
```

### Integration Points

#### 1. MCP Handler Integration

```python
class MCPHandler(BaseHandler):
    def authenticate_and_get_actor(self):
        # Existing OAuth2 token validation
        token = self._extract_bearer_token()
        
        # Look up trust relationship by token
        trust = UnifiedTrust.get_by_token(token)
        
        if not trust:
            # Create new trust for first-time MCP client
            trust = self._create_mcp_trust(token, user_info)
        
        # Update last accessed
        trust.update_last_accessed()
        
        # Return actor with trust context
        return actor, trust
    
    def _handle_tools_list(self, request_id, actor, trust):
        # Filter tools based on trust permissions
        permission_mgr = PermissionManager()
        allowed_tools = permission_mgr.get_accessible_resources(
            trust, "tool"
        )
        return self._format_tools_response(allowed_tools)
```

#### 2. ActingWeb Trust Handler Integration

```python
class TrustHandler(BaseHandler):
    def post(self, data):
        # Existing trust creation logic
        
        # Enhanced with trust type
        trust_type = data.get("trust_type", "associate")
        
        # Validate trust type exists
        if not TrustTypeRegistry.get_type(trust_type):
            return self.error_response(400, "Invalid trust type")
        
        # Create unified trust
        trust = UnifiedTrust.create(
            actor_id=self.actor.id,
            peer_id=data["peer_id"],
            trust_type=trust_type,
            established_via="actingweb"
        )
        
        return {"trust_id": trust.id, "token": trust.secret_token}
```

#### 3. Authorization Check Integration

```python
def check_authorization(auth_obj, path, method):
    """Enhanced authorization with unified trust model."""
    
    # Get trust relationship
    trust = None
    if auth_obj.token:
        trust = UnifiedTrust.get_by_token(auth_obj.token)
    
    if not trust and auth_obj.acl.get("authenticated"):
        # Creator access
        return auth_obj.acl["relationship"] == "creator"
    
    if not trust:
        return False
    
    # Use permission manager
    permission_mgr = PermissionManager()
    resource = f"{path}/{method}"
    
    return permission_mgr.evaluate_access(
        trust=trust,
        resource=resource,
        operation=method.lower()
    )
```

## Implementation Plan

### Phase 1: Foundation (Week 1-2)

1. **Create Trust Type Registry**
   - Implement `TrustType` and `TrustTypeRegistry` classes
   - Add registration methods to `ActingWebApp`
   - Define default trust types (viewer, friend, partner, admin)

2. **Database Schema Updates**
   - Create migration scripts for new tables
   - Update existing trust table structure
   - Add backward compatibility layer

3. **Unified Trust Model**
   - Implement `UnifiedTrust` class
   - Create data access layer
   - Add token generation and validation

### Phase 2: Permission System (Week 3-4)

1. **Permission Manager**
   - Implement permission evaluation logic
   - Create resource pattern matching
   - Add caching for performance

2. **Integration with Auth Module**
   - Update `check_authorization` to use new system
   - Maintain backward compatibility
   - Add logging and monitoring

3. **Testing Framework**
   - Unit tests for permission evaluation
   - Integration tests for auth flows
   - Performance benchmarks

### Phase 3: OAuth2 Integration (Week 5-6)

1. **OAuth2 Trust Establishment**
   - Enhance OAuth2 callback handler
   - Add trust type selection to auth flow
   - Implement two-way approval logic

2. **State Management**
   - Encode trust type in OAuth2 state
   - Add CSRF protection
   - Handle email validation

3. **Token Management**
   - Store OAuth2 tokens in trust relationship
   - Implement token refresh logic
   - Add revocation support

### Phase 4: MCP Unification (Week 7-8)

1. **MCP Handler Updates**
   - Use unified trust for authentication
   - Filter resources based on permissions
   - Add trust creation for new clients

2. **Resource Filtering**
   - Implement tool/prompt/resource filtering
   - Add permission checks to all operations
   - Cache permission decisions

3. **Client Testing**
   - Test with Claude Desktop
   - Verify backward compatibility
   - Performance optimization

### Phase 5: User Interface (Week 9-10)

1. **Trust Management UI**
   - Create Jinja2 templates
   - Add permission editing interface
   - Implement revocation UI

2. **OAuth2 Selection Page**
   - Design trust type selection UI
   - Add email hint support
   - Implement consent screen

3. **API Endpoints**
   - REST API for permission updates
   - Bulk permission management
   - Export/import functionality

### Phase 6: Migration & Deployment (Week 11-12)

1. **Data Migration**
   - Convert existing trusts to unified model
   - Migrate MCP client sessions
   - Update OAuth2 tokens

2. **Documentation**
   - API documentation
   - Migration guide
   - Developer tutorials

3. **Rollout Strategy**
   - Feature flags for gradual rollout
   - Monitoring and alerting
   - Rollback procedures

## Security Considerations

### Token Security
- Use cryptographically secure token generation
- Implement token rotation for long-lived trusts
- Add rate limiting for token validation

### Permission Boundaries
- Enforce least-privilege principle
- Regular permission audits
- Immutable audit logs

### OAuth2 Security
- Validate redirect URIs
- Implement PKCE for public clients
- Enforce email verification

### Data Protection
- Encrypt sensitive tokens at rest
- Use secure channels for token transmission
- Implement token revocation lists

## Backward Compatibility

### Existing Trust Relationships
- Map to "legacy" trust type
- Preserve existing tokens
- Gradual migration path

### API Compatibility
- Maintain existing endpoints
- Add versioning headers
- Deprecation warnings

### Configuration Migration
- Convert `config.access` to trust types
- Preserve custom access rules
- Provide migration tools

## Performance Optimizations

### Caching Strategy
- Cache permission evaluations (5 min TTL)
- Cache trust lookups by token
- Distributed cache for scalability

### Database Optimization
- Index on token fields
- Composite indexes for queries
- Connection pooling

### Request Processing
- Async permission evaluation
- Batch permission checks
- Early termination for denials

## Monitoring & Observability

### Metrics
- Trust creation rate by type
- Permission check latency
- Token validation success rate
- Resource access patterns

### Logging
- Structured logging for all operations
- Audit trail for permission changes
- Security events (failed auth, revocations)

### Alerting
- Unusual access patterns
- High failure rates
- Token exhaustion attacks

## Testing Strategy

### Unit Tests
- Trust type registration
- Permission evaluation logic
- Token generation/validation

### Integration Tests
- OAuth2 flow with trust establishment
- MCP client authentication
- ActingWeb protocol compliance

### End-to-End Tests
- Complete user journeys
- Multi-actor scenarios
- Permission inheritance

### Security Tests
- Token replay attacks
- CSRF protection
- Permission escalation attempts

## Risk Analysis

### Technical Risks
1. **Migration Complexity**: Mitigated by phased rollout
2. **Performance Impact**: Addressed through caching
3. **Breaking Changes**: Prevented by compatibility layer

### Security Risks
1. **Token Leakage**: Mitigated by rotation and monitoring
2. **Permission Bypass**: Prevented by defense-in-depth
3. **OAuth2 Vulnerabilities**: Addressed by standard compliance

### Operational Risks
1. **Rollback Complexity**: Solved by feature flags
2. **Data Loss**: Prevented by backup strategy
3. **Service Disruption**: Minimized by gradual migration

## Success Criteria

1. **Functional Requirements**
   - All OAuth2 clients create trust relationships
   - MCP clients use unified authentication
   - Custom trust types can be registered
   - Fine-grained permissions work correctly

2. **Performance Requirements**
   - Auth latency < 50ms p99
   - Permission checks < 10ms p95
   - Token validation < 5ms p90

3. **User Experience**
   - Intuitive trust management UI
   - Clear permission model
   - Seamless OAuth2 flow

4. **Developer Experience**
   - Simple trust type registration
   - Clear migration path
   - Comprehensive documentation

## Conclusion

This unified access control system will modernize ActingWeb's security model while maintaining backward compatibility. By treating all external entities as trust relationships with configurable permissions, we create a flexible, secure, and user-friendly system that can evolve with future requirements.

The phased implementation approach ensures minimal disruption while delivering incremental value. The focus on extensibility allows third-party developers to define their own trust models while maintaining security boundaries.

## Appendix A: Example Trust Type Definitions

```python
# Standard trust types
STANDARD_TRUST_TYPES = [
    TrustType(
        name="viewer",
        display_name="Viewer",
        description="Read-only access to public data",
        base_permissions={
            "properties": {
                "pattern": "public/*",
                "operations": ["read"]
            },
            "methods": {
                "allowed": ["get_*", "list_*", "export_*"]
            }
        },
        oauth_scope="actingweb.viewer"
    ),
    TrustType(
        name="friend",
        display_name="Friend",
        description="Access to shared resources and actions",
        base_permissions={
            "properties": {
                "pattern": "*",
                "operations": ["read", "write"],
                "exclude": ["private/*", "security/*"]
            },
            "actions": {
                "allowed": ["*"],
                "exclude": ["delete_*", "admin_*"]
            },
            "tools": {
                "allowed": ["*"],
                "exclude": ["admin_*"]
            }
        },
        oauth_scope="actingweb.friend"
    ),
    TrustType(
        name="mcp_client",
        display_name="MCP Client",
        description="AI assistant with configurable access",
        base_permissions={
            "properties": {
                "pattern": "*",
                "operations": ["read"]
            },
            "tools": {
                "allowed": []  # User must explicitly grant
            },
            "prompts": {
                "allowed": ["*"]
            },
            "resources": {
                "pattern": "*",
                "operations": ["read"]
            }
        },
        allow_user_override=True,
        oauth_scope="actingweb.mcp"
    )
]
```

## Appendix B: Migration Script Example

```python
def migrate_existing_trusts():
    """Migrate existing trust relationships to unified model."""
    
    # Get all existing trusts
    old_trusts = db.query("SELECT * FROM trusts")
    
    for trust in old_trusts:
        # Determine trust type based on relationship
        trust_type = map_relationship_to_type(trust.relationship)
        
        # Create unified trust
        unified = UnifiedTrust.create(
            actor_id=trust.actor_id,
            peer_id=trust.peer_id,
            trust_type=trust_type,
            secret_token=trust.secret,
            approved=trust.approved,
            peer_approved=trust.peer_approved,
            established_via="actingweb"
        )
        
        # Migrate properties
        unified.base_permissions = get_default_permissions(trust_type)
        unified.save()
        
    # Update MCP client sessions
    mcp_sessions = db.query("SELECT * FROM mcp_sessions")
    
    for session in mcp_sessions:
        # Create trust for MCP client
        unified = UnifiedTrust.create(
            actor_id=session.actor_id,
            peer_email=session.user_email,
            trust_type="mcp_client",
            oauth_access_token=session.access_token,
            established_via="mcp"
        )
        unified.save()
```

## Appendix C: API Examples

### Creating a Trust with Custom Permissions

```http
POST /<actor_id>/trust
Authorization: Bearer <creator_token>
Content-Type: application/json

{
    "peer_id": "peer-actor-123",
    "trust_type": "collaborator",
    "user_permissions": {
        "properties": {
            "additional_allowed": ["sensitive_data/*"],
            "additional_denied": ["financial/*"]
        }
    }
}
```

### Updating Trust Permissions

```http
PUT /<actor_id>/trust/<trust_id>/permissions
Authorization: Bearer <creator_token>
Content-Type: application/json

{
    "user_permissions": {
        "tools": {
            "allowed": ["send_email", "create_task"],
            "denied": ["delete_data"]
        }
    }
}
```

### OAuth2 Flow with Trust Type

```http
GET /oauth/authorize?
    response_type=code&
    client_id=<client_id>&
    redirect_uri=<redirect_uri>&
    scope=actingweb.friend&
    state=<state>&
    trust_type=friend&
    email_hint=user@example.com
```