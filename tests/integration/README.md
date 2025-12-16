# ActingWeb Integration Tests

## Quick Start

```bash
# Run all integration tests (parallel - 3-4x faster!)
make test-parallel

# Run all integration tests (sequential)
make test-integration

# Run specific test file
poetry run pytest tests/integration/test_basic_flow.py -v

# Run with coverage
poetry run pytest tests/integration/ --cov=actingweb --cov-report=html

# Run in parallel with specific worker count
poetry run pytest tests/integration/ -n 4 -v
```

## Parallel Execution

The test suite supports parallel execution using `pytest-xdist` for significantly faster test runs:

- **3-4x speedup** on multi-core systems
- **Automatic worker isolation** - each worker gets unique database tables, ports, and actor emails
- **No code changes needed** - tests run safely in parallel without modification

```bash
make test-parallel           # Auto-detect CPU cores
make test-parallel-fast      # Skip slow tests
poetry run pytest tests/integration/ -n auto -v --dist loadscope
```

**Note**: Use `--dist loadscope` to keep test classes together on the same worker, which is required for tests that use class-level state.

See `../../CONTRIBUTING.rst` for detailed parallel testing documentation.

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
