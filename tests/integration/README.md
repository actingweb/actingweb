# ActingWeb Integration Tests

## Quick Start

```bash
# Run all integration tests
make test-integration

# Run specific test file
poetry run pytest tests/integration/test_basic_flow.py -v

# Run with coverage
poetry run pytest tests/integration/ --cov=actingweb --cov-report=html
```

## Test Suite

**117 tests** covering all mandatory ActingWeb REST protocol endpoints:

- **test_basic_flow.py** (37 tests) - Actor lifecycle, properties, meta
- **test_trust_flow.py** (33 tests) - Trust relationships, proxy actors
- **test_subscription_flow.py** (39 tests) - Subscriptions with diffs
- **test_attributes.py** (8 tests) - Property attributes

## Documentation

- **[docs/TESTING.md](../../docs/TESTING.md)** - Complete testing guide
- **[FUTURE_WORK.md](FUTURE_WORK.md)** - OAuth2/MCP testing roadmap
- **[Plan](../../thoughts/shared/plans/2025-10-02-rest-test-suite-implementation.md)** - Implementation plan

## Requirements

- Docker & Docker Compose
- Python 3.11+
- Poetry

## CI/CD

Tests run automatically on GitHub Actions for every PR. See `.github/workflows/integration-tests.yml`.

## Status

✅ **Production Ready** - All mandatory REST endpoints validated with comprehensive test coverage.
