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
poetry run pytest tests/integration/ -n auto -v --dist loadgroup
```

**Note**: Use `--dist loadgroup` to respect `@pytest.mark.xdist_group` markers, which keeps related tests together on the same worker.

See `../../CONTRIBUTING.rst` for detailed parallel testing documentation.

## Test Suite

One file per area of the REST protocol and the library's flows
(`test_basic_flow.py`, `test_trust_flow.py`, `test_subscription_*.py`, and
so on); `XDIST_GROUPS.md` lists the groups that keep each file's tests on
one worker.

## Wire recordings

The `test_wire_*.py` files record what crosses the wire between two actors
and what each side holds afterwards: every request a row's steps cause,
nested by what started it, the hooks the apps ran, and a snapshot of the
publisher's queue and the subscriber's replica after every step. Each row
variant has one checked-in file under `wire/` that serves both backends;
a run compares against it byte for byte.

- `wire/rows.toml` is the only list of rows: the scenario that records
  each, what it records (known faults included), and the plan phases
  allowed to change it (`owners`). Its schema is documented at its top.
- One tier: every row is in the regression set. A recording that differs
  is a behaviour change, not a flake; the wire step never reruns.
- Re-record a row only on purpose, by id, never all at once:
  `WIRE_RECORD=WS1.subtarget,WD9 poetry run pytest tests/integration/test_wire_delivery.py`
  (refused under `CI`), and add a dated line to the row's `reason`. A
  mismatch leaves `wire/<row>.actual.json` beside the expected file;
  delete it once read.
- A commit that changes or removes a recording carries a
  `Wire-Phase: <plan>:<phase>` trailer naming one of the row's owners;
  `verify_groups.py` checks the branch's commits since `master` (locally:
  CI's shallow checkout skips that check).
- `exposure = true` marks a row that records data reaching a peer that may
  not read it; `verify_groups.py` lists them.
- The harness is `_wire.py` (recorder, driver, snapshot, normaliser,
  comparer) and the `wire_pair` fixture in `conftest.py`.

## Documentation

- **[docs/contributing/testing.rst](../../docs/contributing/testing.rst)** - Complete testing guide
- **[XDIST_GROUPS.md](XDIST_GROUPS.md)** - The xdist groups and their files

## Requirements

- Docker & Docker Compose
- Python 3.11+
- Poetry

## CI/CD

Tests run on GitHub Actions for every PR (`.github/workflows/tests.yml`), on both backends; the wire recordings run in their own step, sequentially and without reruns.

## Status

✅ **Production Ready** - All mandatory REST endpoints validated with comprehensive test coverage.
