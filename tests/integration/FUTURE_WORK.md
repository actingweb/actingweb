# Future Integration Testing Enhancements

## Current Status (2025-10-02)

### ✅ Completed
- **Phase 1**: Test Infrastructure (Docker, test harness, fixtures) - DONE
- **Phase 2**: Runscope Test Converter - DONE
- **Phase 3**: Core REST Protocol Tests - DONE (117 tests passing)
  - `test_basic_flow.py` - 37 tests (actor lifecycle, properties, meta)
  - `test_trust_flow.py` - 33 tests (trust relationships, proxy actors)
  - `test_subscription_flow.py` - 39 tests (subscriptions with diffs)
  - `test_attributes.py` - 8 tests (property attributes)

### 🚧 In Progress
- **Phase 6**: CI/CD Integration - Implementing GitHub Actions workflow

### 📋 Future Enhancements

#### OAuth2 Testing (Phase 4)

**Why Deferred**: OAuth2 integration testing requires complex mocking of external providers (Google/GitHub) and proper system actor initialization. The OAuth2 functionality is an optional feature for binding actors to external services.

**What's Needed**:
1. **External Provider Mocking**:
   - Mock Google OAuth2 flow (auth redirect, token exchange, userinfo)
   - Mock GitHub OAuth2 flow
   - Email validation testing
   - State parameter CSRF protection testing

2. **MCP OAuth2 Server Testing**:
   - Dynamic client registration (RFC 7591)
   - Authorization code flow
   - Client credentials grant
   - Token refresh flow
   - System actor (`_actingweb_oauth2`) initialization

3. **Test Files to Create**:
   - `tests/integration/test_oauth2_external.py` - External provider flows
   - `tests/integration/test_oauth2_mcp.py` - MCP client token issuance

4. **Dependencies**:
   ```toml
   responses = "^0.23.0"  # HTTP mocking library
   ```

5. **Challenges to Resolve**:
   - System actor creation during test harness initialization
   - Singleton warmup for OAuth2 server components
   - Complex OAuth2 state encryption/decryption testing
   - Email validation and identity confusion attack prevention

**References**:
- Plan: `thoughts/shared/plans/2025-10-02-rest-test-suite-implementation.md#phase-4`
- Spec: `docs/actingweb-spec.rst:990-1020` (OAuth2 endpoints)
- Implementation: `actingweb/oauth2_server/` and `actingweb/handlers/oauth2_endpoints.py`

#### MCP Protocol Testing (Phase 5)

**Why Deferred**: MCP (Model Context Protocol) testing depends on OAuth2 authentication working properly. MCP is a newer feature for exposing ActingWeb functionality to AI models.

**What's Needed**:
1. **MCP Tools Tests** (`test_mcp_tools.py`):
   - List available tools (ActingWeb actions → MCP tools)
   - Invoke tools with arguments
   - Permission enforcement for trust relationships
   - Error handling and MCP-compliant error responses

2. **MCP Resources Tests** (`test_mcp_resources.py`):
   - List available resources (ActingWeb resources → MCP resources)
   - Retrieve resource content
   - URI template support (e.g., `properties://{key}`)

3. **MCP Prompts Tests** (`test_mcp_prompts.py`):
   - List available prompts (ActingWeb methods → MCP prompts)
   - Invoke prompts
   - Session binding to actor context

4. **MCP Integration Tests** (`test_mcp_integration.py`):
   - Complete OAuth2 → MCP flow
   - Trust establishment with MCP relationship
   - Tool invocation with bearer token
   - Resource retrieval with authorization
   - Permission scope enforcement

**References**:
- Plan: `thoughts/shared/plans/2025-10-02-rest-test-suite-implementation.md#phase-5`
- Spec: `docs/actingweb-spec.rst:1021-1091` (MCP support)
- Implementation: `actingweb/handlers/mcp.py` and `actingweb/mcp/`

#### Additional Test Coverage

**Areas for Expansion**:
1. **Optional REST Endpoints**:
   - `/methods` - Custom methods (if used in applications)
   - `/actions` - Custom actions (if used in applications)
   - `/resources` - Custom resources (if used in applications)
   - `/www` - Web UI endpoints (HTML responses)

2. **Error Handling**:
   - Rate limiting tests
   - Invalid JSON payloads
   - Malformed trust relationships
   - Network timeout handling
   - Large payload handling

3. **Security Tests**:
   - Authorization bypass attempts
   - CSRF token validation
   - Passphrase strength requirements
   - Trust secret rotation
   - Property access control

4. **Performance Tests**:
   - Large number of properties (1000+)
   - Deep nesting levels (10+ levels)
   - Many trust relationships (100+)
   - Subscription callback delivery time
   - DynamoDB query optimization

## Implementation Guide for Future Contributors

### Adding OAuth2 Tests

1. **Setup System Actor**:
   ```python
   # In conftest.py
   @pytest.fixture(scope="session")
   def system_actor_setup(test_app):
       """Create _actingweb_oauth2 system actor."""
       from actingweb.singleton_warmup import initialize_actingweb_singletons
       # Initialize singletons including OAuth2 system actor
       ...
   ```

2. **Use OAuth2 Mocks**:
   ```python
   from tests.integration.utils.oauth2_mocks import GoogleOAuth2Mock

   def test_google_oauth(http_client):
       with responses.RequestsMock() as rsps:
           google_mock = GoogleOAuth2Mock()
           google_mock.mock_token_exchange(rsps)
           google_mock.mock_userinfo_endpoint(rsps)
           # Test OAuth flow...
   ```

3. **Test OAuth2 Registration**:
   ```python
   def test_client_registration(http_client, base_url):
       response = http_client.post(
           f"{base_url}/oauth/register",
           json={"client_name": "Test", "redirect_uris": [...]},
       )
       assert response.status_code == 201
       assert "client_id" in response.json()
   ```

### Adding MCP Tests

1. **Establish MCP Trust**:
   ```python
   def test_mcp_tools(actor_factory, trust_helper):
       client = actor_factory.create("mcp@example.com")
       user = actor_factory.create("user@example.com")
       trust = trust_helper.establish(client, user, "mcp", approve=True)
       # Use trust.secret as bearer token...
   ```

2. **Test MCP Endpoints**:
   ```python
   def test_list_tools(http_client, actor):
       response = http_client.get(
           f"{actor['url']}/mcp/tools",
           headers={"Authorization": f"Bearer {token}"},
       )
       assert response.status_code == 200
       tools = response.json()
       assert isinstance(tools, list)
   ```

## Rationale for Current Scope

### Why Core Protocol First?

The current implementation focuses on **mandatory REST protocol endpoints** that every ActingWeb application must implement:

1. **Actor Lifecycle** (factory, GET, DELETE)
2. **Properties** (CRUD operations, nested properties)
3. **Meta** (actor metadata)
4. **Trust** (relationships, approval, proxy access)
5. **Subscriptions** (property change notifications, diffs)

These 117 tests provide **comprehensive validation** of the ActingWeb specification's core functionality. This ensures any breaking changes to the fundamental protocol are caught immediately.

### Why Defer OAuth2/MCP?

1. **Complexity**: OAuth2 flows require complex state management and external provider mocking
2. **Optional Features**: Not all ActingWeb applications use OAuth2 or MCP
3. **Dependencies**: MCP tests depend on OAuth2 working correctly
4. **Time-to-Value**: 117 core tests provide immediate value; OAuth2/MCP can be added incrementally
5. **Test Infrastructure**: Core test infrastructure is in place for future additions

### Incremental Enhancement Strategy

The test suite is designed for **incremental enhancement**:

1. ✅ **v1.0**: Core REST protocol (current state)
2. 📋 **v1.1**: OAuth2 testing (when needed by applications)
3. 📋 **v1.2**: MCP protocol testing (when MCP adoption grows)
4. 📋 **v1.3**: Performance and security testing
5. 📋 **v1.4**: Edge cases and error scenarios

This approach follows the **80/20 rule**: 80% of the value (core protocol validation) with 20% of the complexity (simpler test scenarios first).

## Getting Help

If you want to add OAuth2 or MCP tests:

1. **Read the Plan**: `thoughts/shared/plans/2025-10-02-rest-test-suite-implementation.md`
2. **Check the Spec**: `docs/actingweb-spec.rst` for protocol details
3. **Review Examples**: Existing test files for patterns and fixtures
4. **Mock Utilities**: `tests/integration/utils/oauth2_mocks.py` (ready to use)
5. **Ask Questions**: Open an issue with the `testing` label

## Conclusion

The integration test suite provides **production-ready validation** of the ActingWeb core protocol. OAuth2 and MCP testing are valuable future enhancements that can be added when needed, using the solid foundation already in place.

**Current coverage**: 117 tests validating all mandatory REST endpoints
**Estimated time to add OAuth2**: 4-8 hours
**Estimated time to add MCP**: 4-6 hours
**Total future work**: ~10-15 hours for complete coverage
