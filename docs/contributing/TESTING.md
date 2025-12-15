# ActingWeb Integration Testing

## Overview

The ActingWeb library includes comprehensive integration tests that validate the REST API protocol against the official specification in `docs/actingweb-spec.rst`.

**Current Test Coverage**: 117 tests covering all mandatory ActingWeb REST protocol endpoints.

## Quick Start

### Run All Tests

```bash
# Run all integration tests
make test-integration

# Run specific test file
poetry run pytest tests/integration/test_basic_flow.py -v

# Run tests matching a pattern
poetry run pytest tests/integration/ -k "property" -v
```

### Prerequisites

- Docker and Docker Compose
- Python 3.11+
- Poetry

### Test Environment

Integration tests use:
- **DynamoDB**: Local DynamoDB running in Docker (port 8000)
- **Test Harness**: Minimal Flask application (port 5555)
- **No External APIs**: All tests run locally

## Test Organization

```
tests/integration/
├── conftest.py              # Shared fixtures
├── test_harness.py          # Minimal ActingWeb app
├── test_basic_flow.py       # Actor lifecycle, properties, meta (37 tests)
├── test_trust_flow.py       # Trust relationships (33 tests)
├── test_subscription_flow.py # Subscriptions (39 tests)
├── test_attributes.py       # Property attributes (8 tests)
├── test_devtest.py          # DevTest endpoints
├── test_infrastructure.py   # Infrastructure health checks
├── FUTURE_WORK.md           # OAuth2/MCP testing roadmap
└── utils/
    ├── oauth2_mocks.py      # OAuth2 mock helpers (for future use)
    └── __init__.py
```

## What's Tested

### ✅ Core REST Protocol (117 tests)

1. **Actor Lifecycle**
   - Factory endpoint (POST /)
   - Actor creation with JSON
   - Actor deletion
   - Authentication (basic auth)
   - Authorization (creator, passphrase)

2. **Properties** (/properties)
   - Create, read, update, delete properties
   - Nested properties (multi-level JSON)
   - Unicode and special characters
   - Form data and JSON payloads
   - Property-level access control

3. **Meta** (/meta)
   - Actor metadata retrieval
   - Specific meta variables
   - Meta updates

4. **Trust** (/trust)
   - Trust relationship initiation
   - Trust approval/rejection
   - Multiple relationship types (friend, lover, associate, etc.)
   - Reciprocal trust
   - Proxy actor access (selfproxy)
   - Trust-based authorization

5. **Subscriptions** (/subscriptions)
   - Subscription creation
   - Property change notifications
   - Diff tracking
   - Subscription queries by peer/target
   - Subscription deletion

### 📋 Future Enhancements

See `tests/integration/FUTURE_WORK.md` for planned additions:
- OAuth2 testing (external providers and MCP server)
- MCP protocol testing (tools, resources, prompts)
- Performance testing
- Security testing
- Edge case scenarios

## Test Fixtures

### `actor_factory`

Creates test actors with automatic cleanup.

```python
def test_example(actor_factory):
    actor = actor_factory.create("test@example.com")
    # actor["id"], actor["url"], actor["creator"], actor["passphrase"]
    # ... use actor ...
    # Cleanup happens automatically
```

### `trust_helper`

Establishes trust relationships between actors.

```python
def test_trust(actor_factory, trust_helper):
    actor1 = actor_factory.create("user1@example.com")
    actor2 = actor_factory.create("user2@example.com")
    trust = trust_helper.establish(actor1, actor2, "friend", approve=True)
    # trust["secret"], trust["url"]
```

### `http_client`

HTTP client for making requests.

```python
def test_request(http_client):
    response = http_client.get(f"{http_client.base_url}/some/path")
    assert response.status_code == 200
```

## Running Tests Locally

### Full Test Suite

```bash
# Start Docker, run tests, clean up
make test-integration

# Expected output: 117 passed in ~30 seconds
```

### Individual Test Files

```bash
# Basic flow (37 tests)
poetry run pytest tests/integration/test_basic_flow.py -v

# Trust flow (33 tests)
poetry run pytest tests/integration/test_trust_flow.py -v

# Subscriptions (39 tests)
poetry run pytest tests/integration/test_subscription_flow.py -v

# Attributes (8 tests)
poetry run pytest tests/integration/test_attributes.py -v
```

### Test Selection

```bash
# Run tests matching pattern
poetry run pytest tests/integration/ -k "property" -v

# Run specific test
poetry run pytest tests/integration/test_basic_flow.py::TestBasicActorFlow::test_003_create_actor_with_json -v

# Run with verbose output
poetry run pytest tests/integration/ -v -s

# Run with detailed failure info
poetry run pytest tests/integration/ -v --tb=long
```

## Debugging Tests

### Check Docker Services

```bash
# Verify DynamoDB is running
docker ps | grep dynamodb

# Check DynamoDB health
curl http://localhost:8000/

# View DynamoDB logs
docker logs actingweb-test-dynamodb
```

### Manual Test Harness

```bash
# Run test harness manually
python -c "from tests.integration.test_harness import create_test_app; app, _ = create_test_app(); app.run(debug=True, port=5555)"

# Test factory endpoint
curl -X POST http://localhost:5555/ \
  -H "Content-Type: application/json" \
  -d '{"creator": "test@example.com"}'
```

### Clean Test Environment

```bash
# Remove all test data
docker-compose -f docker-compose.test.yml down -v
rm -rf tests/integration/dynamodb-data/*

# Restart fresh
make test-integration
```

### Common Issues

**Issue**: `DynamoDB failed to start within 30 seconds`
```bash
# Solution: Check if port 8000 is already in use
lsof -i :8000
# Kill the process or use a different port
```

**Issue**: `Test app failed to start within 30 seconds`
```bash
# Solution: Check if port 5555 is in use
lsof -i :5555
# Kill the process or change TEST_APP_PORT in conftest.py
```

**Issue**: Tests hang or timeout
```bash
# Solution: Check Docker resources
docker stats
# Increase Docker memory/CPU limits if needed
```

## CI/CD Integration

### GitHub Actions

Integration tests run automatically on:
- Every push to `master`, `main`, or `develop`
- Every pull request to these branches

**Workflow**: `.github/workflows/integration-tests.yml`

**Features**:
- Automatic test execution
- Test result publishing
- Coverage report generation
- PR comment with test status
- Blocks merge if tests fail

### Branch Protection

To enable test-required merges, configure branch protection:

1. Go to repository **Settings** → **Branches**
2. Add branch protection rule for `master`/`main`
3. Enable: **Require status checks to pass before merging**
4. Select: **integration-tests**
5. Save changes

Now all PRs must pass tests before merging.

## Writing New Tests

### Test File Template

```python
"""
Description of what this test file covers.

Spec: docs/actingweb-spec.rst:LINE_START-LINE_END
"""

import pytest


class TestFeatureName:
    """Test suite for specific feature."""

    def test_basic_functionality(self, actor_factory, http_client):
        """
        Test description.

        Spec: docs/actingweb-spec.rst:SPECIFIC_LINES
        """
        # Arrange
        actor = actor_factory.create("test@example.com")

        # Act
        response = http_client.get(
            f"{http_client.base_url}{actor['url']}/endpoint"
        )

        # Assert
        assert response.status_code == 200
```

### Best Practices

1. **Use Fixtures**: `actor_factory`, `trust_helper`, `http_client`
2. **Reference Spec**: Include spec line numbers in docstrings
3. **Clean Up**: Fixtures handle cleanup automatically
4. **Descriptive Names**: `test_001_create_actor_with_json` not `test1`
5. **Test One Thing**: Each test should verify a single behavior
6. **Use Classes**: Group related tests in classes

### Test Patterns

**Pattern: Create Actor**
```python
actor = actor_factory.create("email@example.com", passphrase="custom")
```

**Pattern: Make Authenticated Request**
```python
response = http_client.get(
    f"{http_client.base_url}{actor['url']}/properties",
    auth=(actor['creator'], actor['passphrase'])
)
```

**Pattern: Establish Trust**
```python
trust = trust_helper.establish(from_actor, to_actor, "friend", approve=True)
```

**Pattern: Assert JSON Response**
```python
assert response.status_code == 200
data = response.json()
assert data["property"] == "value"
```

## Coverage Reports

### Generate Coverage Report

```bash
# Run tests with coverage
poetry run pytest tests/integration/ \
  --cov=actingweb \
  --cov-report=html \
  --cov-report=term

# Open HTML report
open htmlcov/index.html
```

### Coverage Goals

- **Core Handlers**: 80%+ coverage
- **REST Endpoints**: 100% coverage
- **Database Operations**: 70%+ coverage
- **Overall**: 75%+ coverage

Current integration tests primarily cover REST endpoint handlers. Unit tests cover internal library components.

## Performance

**Test Execution Time**:
- Infrastructure setup: ~5 seconds (Docker)
- Basic flow tests: ~7 seconds (37 tests)
- Trust flow tests: ~9 seconds (33 tests)
- Subscription flow tests: ~13 seconds (39 tests)
- Attributes tests: ~7 seconds (8 tests)
- **Total**: ~40-45 seconds for full suite

**Optimization Tips**:
- Use session-scoped fixtures (already implemented)
- Run tests in parallel: `pytest -n auto` (requires pytest-xdist)
- Skip slow tests: `pytest -m "not slow"`

## Troubleshooting

### Test Failures

**Read the Error**:
```bash
# Run with detailed output
poetry run pytest tests/integration/ -v --tb=long

# Show print statements
poetry run pytest tests/integration/ -v -s
```

**Check Logs**:
```bash
# View captured logs
poetry run pytest tests/integration/ -v --log-cli-level=DEBUG
```

**Isolate the Issue**:
```bash
# Run single failing test
poetry run pytest tests/integration/test_file.py::test_name -v -s

# Add debugging
def test_name(actor_factory):
    actor = actor_factory.create("test@example.com")
    print(f"Actor: {actor}")  # Will show with -s flag
    import pdb; pdb.set_trace()  # Drop into debugger
```

### Docker Issues

```bash
# Clean Docker state
docker-compose -f docker-compose.test.yml down -v
docker system prune

# Rebuild containers
docker-compose -f docker-compose.test.yml up -d --force-recreate
```

### Port Conflicts

```bash
# Find processes on test ports
lsof -i :8000  # DynamoDB
lsof -i :5555  # Test harness
lsof -i :5556  # Peer app

# Kill process
kill -9 <PID>
```

## FAQ

**Q: Do I need to start Docker manually?**
A: No, `make test-integration` handles Docker lifecycle.

**Q: Can I run tests without Docker?**
A: No, tests require local DynamoDB. You could modify to use real AWS DynamoDB, but that's not recommended.

**Q: How do I add OAuth2/MCP tests?**
A: See `tests/integration/FUTURE_WORK.md` for implementation guide.

**Q: Why are tests sometimes slow?**
A: DynamoDB startup (5s) and actor creation. Session fixtures minimize this.

**Q: Can I run tests in parallel?**
A: Yes, but requires careful handling of shared DynamoDB state. Not recommended currently.

**Q: Do tests clean up after themselves?**
A: Yes, `actor_factory` fixture automatically deletes created actors.

**Q: What Python version is required?**
A: Python 3.11+, matching the library's requirements.

## Contributing

### Adding Tests

1. Identify spec section to test
2. Create test file if needed: `test_<feature>.py`
3. Use existing fixtures
4. Reference spec in docstrings
5. Run locally: `poetry run pytest tests/integration/test_<feature>.py -v`
6. Verify CI passes

### Reporting Issues

If tests fail on your system but pass in CI:
1. Check Python version: `python --version`
2. Check Docker version: `docker --version`
3. Clean environment: `make test-integration`
4. Collect logs: `poetry run pytest tests/integration/ -v --log-cli-level=DEBUG > test.log 2>&1`
5. Open issue with logs

## Resources

- **ActingWeb Spec**: `docs/actingweb-spec.rst`
- **Test Plan**: `thoughts/shared/plans/2025-10-02-rest-test-suite-implementation.md`
- **Future Work**: `tests/integration/FUTURE_WORK.md`
- **CI Workflow**: `.github/workflows/integration-tests.yml`
- **pytest Documentation**: https://docs.pytest.org/

## Summary

The integration test suite provides comprehensive validation of the ActingWeb REST protocol with 117 tests covering all mandatory endpoints. Tests run automatically in CI/CD and block PRs on failure, ensuring protocol compliance for all changes.

For OAuth2 and MCP testing, see `FUTURE_WORK.md`.
