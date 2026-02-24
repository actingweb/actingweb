# PostgreSQL Backend Implementation Plan

## Executive Summary

Add PostgreSQL as an alternative database backend to ActingWeb alongside the existing DynamoDB implementation. The architecture already supports pluggable backends via dynamic module loading in `config.py` - we just need to implement the PostgreSQL backend following the established interface pattern.

**Selected Technologies:**
- **Library**: psycopg3 (modern sync/async support)
- **Migrations**: Alembic for schema versioning
- **Testing**: Backend-specific markers (most tests run once, DB-specific tests marked per backend)
- **Type Safety**: Add typing.Protocol classes to enforce interface consistency

---

## Architecture Overview

### Current State
- **7 database tables**: Actor, Property, Attribute, Trust, PeerTrustee, Subscription, SubscriptionDiff
- **Interface pattern**: Each backend provides `Db{Entity}` and `Db{Entity}List` classes
- **Dynamic loading**: `config.py` lines 181-201 use `importlib` to load `actingweb.db.{database}.{entity}`
- **Return convention**: All methods return plain dicts/bools (no ORM objects exposed)
- **Auto-table creation**: DynamoDB creates tables on first use in `__init__`

### Key Design Decisions for PostgreSQL

1. **Use Alembic migrations** instead of auto-table creation (production-ready approach)
2. **Raw psycopg3 queries** (SQLAlchemy only for Alembic schema definitions)
3. **Schema-based worker isolation** for parallel tests (like DynamoDB table prefixes)
4. **Add Protocol classes** to formalize the implicit interface contract
5. **Connection pooling** via psycopg3's built-in ConnectionPool

---

## Implementation Phases

### Phase 1: Foundation & Protocols

**Goal**: Set up infrastructure and define formal interfaces

#### 1.1 Protocol Definitions

**Create**: `actingweb/db/protocols.py`

Define `typing.Protocol` classes for all database interfaces:
- `DbActorProtocol`, `DbActorListProtocol`
- `DbPropertyProtocol`, `DbPropertyListProtocol`
- `DbAttributeProtocol`, `DbAttributeBucketListProtocol`
- `DbTrustProtocol`, `DbTrustListProtocol`
- `DbPeerTrusteeProtocol`, `DbPeerTrusteeListProtocol`
- `DbSubscriptionProtocol`, `DbSubscriptionListProtocol`
- `DbSubscriptionDiffProtocol`, `DbSubscriptionDiffListProtocol`

Each protocol defines required methods with exact signatures from DynamoDB implementation.

**Modify**: `actingweb/config.py`

Add type hints for loaded modules:
```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from actingweb.db.protocols import DbActorProtocol, DbPropertyProtocol, ...

class Config:
    DbActor: type[DbActorProtocol]
    DbProperty: type[DbPropertyProtocol]
    # ... etc
```

#### 1.2 PostgreSQL Module Structure

**Create directory**: `actingweb/db/postgresql/`

**Create files**:
- `__init__.py` - Export all Db* classes
- `connection.py` - Connection pool management
- `schema.py` - SQLAlchemy models (for Alembic only)
- `migrations/` - Alembic directory with initial migration

**Connection Pool Design** (`connection.py`):
```python
from psycopg.pool import ConnectionPool

_pool: ConnectionPool | None = None

def get_pool() -> ConnectionPool:
    """Thread-safe singleton pool"""
    # Load from env: PG_DB_HOST, PG_DB_PORT, PG_DB_NAME, PG_DB_USER, PG_DB_PASSWORD
    # Handle schema prefix: PG_DB_PREFIX for test isolation

def get_connection():
    """Get connection from pool"""

def get_schema_name() -> str:
    """Returns schema name with worker prefix: {PG_DB_PREFIX}public"""
```

#### 1.3 Dependencies

**Modify**: `pyproject.toml`

```toml
[tool.poetry.dependencies]
# PostgreSQL backend (optional)
psycopg = { version = "^3.1.0", extras = ["binary", "pool"], optional = true }
sqlalchemy = { version = "^2.0.0", optional = true }  # For Alembic only
alembic = { version = "^1.13.0", optional = true }

[tool.poetry.extras]
postgresql = ["psycopg", "sqlalchemy", "alembic"]
all = ["psycopg", "sqlalchemy", "alembic", "mcp", "flask", ...]
```

Install: `poetry install --extras postgresql`

#### 1.4 Alembic Setup

**Initialize Alembic**:
```bash
cd actingweb/db/postgresql/
alembic init migrations
```

**Create SQLAlchemy models** in `schema.py`:
- Match DynamoDB table structure exactly
- Use composite PRIMARY KEYs for tables with hash+range keys
- Add indexes matching DynamoDB GSIs

**Generate initial migration**:
```bash
alembic revision --autogenerate -m "Initial PostgreSQL schema"
```

**Validation**:
- Protocol compliance test on DynamoDB (should pass)
- PostgreSQL connection pool initializes
- Migration creates all 7 tables successfully

---

### Phase 2: Core Tables (Actor & Property)

**Goal**: Implement the two most frequently used tables, establish patterns for others

#### 2.1 Implement DbActor

**Create**: `actingweb/db/postgresql/actor.py`

**Classes**: `DbActor`, `DbActorList`

**Key methods to implement** (matching DynamoDB signatures):
```python
class DbActor:
    handle: dict[str, Any] | None = None

    def __init__(self):
        # NO auto-table creation (use migrations instead)
        self.handle = None

    def get(self, actor_id: str | None = None) -> dict[str, Any] | None:
        # SELECT id, creator, passphrase FROM actors WHERE id = %s
        # Returns: {"id": ..., "creator": ..., "passphrase": ...}

    def get_by_creator(self, creator: str | None = None) -> dict[str, Any] | list[dict[str, Any]] | None:
        # SELECT * FROM actors WHERE creator = %s
        # Uses creator index

    def create(self, actor_id: str | None = None, creator: str | None = None, passphrase: str | None = None) -> bool:
        # INSERT INTO actors (id, creator, passphrase) VALUES (%s, %s, %s)

    def modify(self, creator: str | None = None, passphrase: bytes | None = None) -> bool:
        # UPDATE actors SET ... WHERE id = self.handle['id']

    def delete(self) -> bool:
        # DELETE FROM actors WHERE id = self.handle['id']
```

**Important patterns**:
- Use `self.handle` to store current actor dict (not ORM object)
- Return plain dicts, never expose database objects
- Handle email lowercasing (if "@" in creator)
- Use consistent_read equivalent (PostgreSQL default)

#### 2.2 Implement DbProperty

**Create**: `actingweb/db/postgresql/property.py`

**Classes**: `DbProperty`, `DbPropertyList`

**Schema**: `(id, name)` composite primary key

**Key methods**:
- `get(actor_id, name)` → `str | None`
- `get_actor_id_from_property(name, value)` → `str | None` (reverse lookup via value index)
- `set(actor_id, name, value)` → `bool` (empty value = delete)
- `delete()` → `bool`

**Special handling**:
- JSON serialization for complex values
- List properties (prefix `list:`)
- Value index for reverse lookups

#### 2.3 Testing Infrastructure

**Modify**: `docker-compose.test.yml`

Add PostgreSQL service:
```yaml
postgres-test:
  image: postgres:16-alpine
  environment:
    POSTGRES_USER: actingweb
    POSTGRES_PASSWORD: testpassword
    POSTGRES_DB: actingweb_test
  ports:
    - '5433:5432'
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U actingweb"]
```

**Modify**: `tests/integration/conftest.py`

Add backend selection and multi-backend fixtures:
- Configure `DATABASE_BACKEND` env var
- Set PostgreSQL env vars (PG_DB_HOST, PG_DB_PORT, etc.)
- Schema-based worker isolation: `PG_DB_PREFIX=test_w{worker_num}_`
- Run migrations before tests

**Create**: `tests/test_db_protocols.py`

Protocol compliance tests:
```python
@pytest.mark.parametrize("backend", ["dynamodb", "postgresql"])
def test_actor_protocol_compliance(backend):
    mod = importlib.import_module(f"actingweb.db.{backend}.actor")
    assert isinstance(mod.DbActor(), DbActorProtocol)
```

**Validation**:
- Run existing Actor tests against PostgreSQL
- Run existing Property tests against PostgreSQL
- All tests pass with both backends

---

### Phase 3: Trust Tables (Trust & PeerTrustee)

**Goal**: Implement trust relationship tables

#### 3.1 Implement DbTrust

**Create**: `actingweb/db/postgresql/trust.py`

**Schema**: `(id, peerid)` composite primary key

**Key fields**:
- Core: `baseuri`, `type`, `relationship`, `secret`
- Approval: `approved`, `peer_approved`, `verified`, `verification_token`
- Unified trust: `peer_identifier`, `established_via`, `created_at`, `last_accessed`
- OAuth2 metadata: `client_name`, `client_version`, `client_platform`, `oauth_client_id`

**Index**: `secret` (for token lookups)

**Methods**: Match DynamoDB interface exactly

#### 3.2 Implement DbPeerTrustee

**Create**: `actingweb/db/postgresql/peertrustee.py`

**Schema**: `(id, peerid)` composite primary key

Simpler table, follows same pattern as Trust.

**Validation**:
- Trust flow integration tests pass
- OAuth trust tests pass
- Trust permissions tests pass

---

### Phase 4: Subscriptions & Attributes

**Goal**: Complete remaining tables

#### 4.1 Implement DbSubscription

**Create**: `actingweb/db/postgresql/subscription.py`

**Schema**: `(id, peer_sub_id)` composite primary key

**Composite key**: `peer_sub_id = peerid + ":" + subid`

**Fields**: `peerid`, `subid`, `granularity`, `target`, `subtarget`, `resource`, `seqnr`, `callback`

#### 4.2 Implement DbSubscriptionDiff

**Create**: `actingweb/db/postgresql/subscription_diff.py`

**Schema**: `(id, subid_seqnr)` composite primary key

**Composite key**: `subid_seqnr = subid + ":" + seqnr`

**Fields**: `subid`, `timestamp`, `diff`, `seqnr`

#### 4.3 Implement DbAttribute

**Create**: `actingweb/db/postgresql/attribute.py`

**Schema**: `(id, bucket_name)` composite primary key

**Fields**:
- `bucket`, `name`, `data` (JSONB)
- `timestamp`, `ttl_timestamp` (BIGINT for Unix epoch)

**Special handling**:
- JSONB storage for `data` field
- TTL cleanup: index on `ttl_timestamp` for efficient queries
- Consider pg_cron or manual cleanup job

**Validation**:
- Subscription tests pass
- Attribute tests pass (including TTL behavior)

---

### Phase 5: Comprehensive Testing & CI/CD

**Goal**: Ensure all 900+ tests pass and CI runs both backends

#### 5.1 Test Coverage

**Run full test suite**:
```bash
# Against PostgreSQL
DATABASE_BACKEND=postgresql make test-all-parallel

# Against DynamoDB (ensure no regressions)
DATABASE_BACKEND=dynamodb make test-all-parallel
```

**Identify backend-specific tests**:
- Tests that directly import DynamoDB models
- Tests that rely on DynamoDB-specific behavior (GSI, TTL, etc.)

**Add test markers**:
```python
@pytest.mark.dynamodb
def test_dynamodb_gsi_performance():
    """DynamoDB-specific test"""

@pytest.mark.postgresql
def test_postgresql_jsonb_queries():
    """PostgreSQL-specific test"""
```

**Update pytest.ini**:
```ini
[pytest]
markers =
    integration: integration tests requiring database
    dynamodb: DynamoDB-specific tests
    postgresql: PostgreSQL-specific tests
```

#### 5.2 CI/CD Integration

**Modify**: `.github/workflows/tests.yml`

Add matrix strategy:
```yaml
strategy:
  matrix:
    backend: [dynamodb, postgresql]
    python-version: ['3.11', '3.12']

services:
  dynamodb:
    image: amazon/dynamodb-local:latest
    ports: [8001:8000]
  postgres:
    image: postgres:16-alpine
    env:
      POSTGRES_USER: actingweb
      POSTGRES_PASSWORD: testpassword
      POSTGRES_DB: actingweb_test
    ports: [5433:5432]

steps:
  - name: Run migrations (PostgreSQL)
    if: matrix.backend == 'postgresql'
    run: |
      cd actingweb/db/postgresql/migrations
      alembic upgrade head

  - name: Run tests
    run: poetry run pytest tests/ -v
    env:
      DATABASE_BACKEND: ${{ matrix.backend }}
```

#### 5.3 Configuration Validation

**Modify**: `actingweb/interface/app.py`

Add backend validation:
```python
def __init__(self, database: str = "dynamodb", ...):
    if database not in ["dynamodb", "postgresql"]:
        raise ValueError(f"Unsupported database: {database}")
    self.database = database
```

**No changes needed** in `config.py` - dynamic loading already works!

---

### Phase 6: Documentation & Migration Tools

**Goal**: Document setup and provide migration path

#### 6.1 Documentation Updates

**Modify**: `CLAUDE.md`

Add PostgreSQL section:
```markdown
## PostgreSQL Setup

### Installation
```bash
poetry install --extras postgresql
```

### Configuration
```bash
DATABASE_BACKEND=postgresql
PG_DB_HOST=localhost
PG_DB_PORT=5432
PG_DB_NAME=actingweb
PG_DB_USER=actingweb
PG_DB_PASSWORD=secretpassword
```

### Migrations
```bash
cd actingweb/db/postgresql/migrations
alembic upgrade head
```
```

**Create**: `docs/guides/postgresql-migration.md`

Migration guide for existing DynamoDB deployments:
1. Set up PostgreSQL database
2. Run Alembic migrations
3. Export data from DynamoDB
4. Import data to PostgreSQL
5. Update configuration
6. Validate and switch over

#### 6.2 Data Migration Script

**Create**: `scripts/migrate_dynamodb_to_postgresql.py`

```python
"""
Migrate data from DynamoDB to PostgreSQL.
Exports all tables to JSON, then imports to PostgreSQL.
"""

def export_dynamodb():
    """Export all DynamoDB tables to JSON"""

def import_postgresql():
    """Import JSON data to PostgreSQL"""

def validate_migration():
    """Verify data integrity"""
```

#### 6.3 Performance Testing

**Create**: `tests/performance/test_backend_performance.py`

Benchmark operations:
- Actor creation/retrieval
- Property operations
- Trust relationship queries
- Subscription handling

Compare PostgreSQL vs DynamoDB performance.

---

## Database Schema Mapping

### DynamoDB → PostgreSQL

| DynamoDB Table | PostgreSQL Table | Primary Key | Indexes |
|---|---|---|---|
| `actors` | `actors` | `id` | `creator` |
| `properties` | `properties` | `(id, name)` | `value` |
| `trusts` | `trusts` | `(id, peerid)` | `secret` |
| `peertrustees` | `peertrustees` | `(id, peerid)` | - |
| `subscriptions` | `subscriptions` | `(id, peer_sub_id)` | - |
| `subscription_diffs` | `subscription_diffs` | `(id, subid_seqnr)` | - |
| `attributes` | `attributes` | `(id, bucket_name)` | `ttl_timestamp` |

**Key mappings**:
- DynamoDB hash_key → PostgreSQL first part of composite key
- DynamoDB range_key → PostgreSQL second part of composite key
- DynamoDB GSI → PostgreSQL standard index
- DynamoDB TTL → PostgreSQL ttl_timestamp + cleanup job

---

## Environment Variables

### PostgreSQL Configuration

```bash
# Backend selection
DATABASE_BACKEND=postgresql  # or "dynamodb"

# Connection
PG_DB_HOST=localhost
PG_DB_PORT=5432
PG_DB_NAME=actingweb
PG_DB_USER=actingweb
PG_DB_PASSWORD=secretpassword

# Test isolation
PG_DB_PREFIX=               # e.g., "test_w0_" for parallel tests
PG_DB_SCHEMA=public        # Schema name

# Migrations (DEV ONLY)
PG_AUTO_MIGRATE=false      # Auto-run migrations on startup

# Connection pool
PG_POOL_MIN_SIZE=2
PG_POOL_MAX_SIZE=10
PG_POOL_TIMEOUT=30
```

---

## Critical Files to Create/Modify

### New Files (Priority Order)

1. **`actingweb/db/protocols.py`** - Protocol definitions (foundation)
2. **`actingweb/db/postgresql/connection.py`** - Connection pool (infrastructure)
3. **`actingweb/db/postgresql/schema.py`** - SQLAlchemy models (for Alembic)
4. **`actingweb/db/postgresql/actor.py`** - First implementation (pattern-setting)
5. **`actingweb/db/postgresql/property.py`** - Second implementation
6. **`actingweb/db/postgresql/trust.py`** - Trust relationships
7. **`actingweb/db/postgresql/peertrustee.py`** - Peer trustees
8. **`actingweb/db/postgresql/subscription.py`** - Subscriptions
9. **`actingweb/db/postgresql/subscription_diff.py`** - Subscription diffs
10. **`actingweb/db/postgresql/attribute.py`** - Attributes with TTL
11. **`tests/test_db_protocols.py`** - Protocol compliance tests

### Modified Files

1. **`pyproject.toml`** - Add PostgreSQL dependencies
2. **`actingweb/config.py`** - Add type hints for protocols
3. **`actingweb/interface/app.py`** - Add backend validation
4. **`docker-compose.test.yml`** - Add PostgreSQL test service
5. **`tests/integration/conftest.py`** - Multi-backend fixtures
6. **`.github/workflows/tests.yml`** - Matrix testing
7. **`CLAUDE.md`** - PostgreSQL documentation

---

## Testing Strategy

### Test Categories

1. **Backend-agnostic tests** (run once): ~95% of tests
   - HTTP integration tests
   - Business logic tests
   - Handler tests

2. **Backend-specific tests** (run per backend): ~5% of tests
   - Direct database model tests
   - Backend-specific feature tests (GSI, JSONB queries)
   - Performance benchmarks

### Test Execution

```bash
# Run all tests with PostgreSQL
DATABASE_BACKEND=postgresql make test-all-parallel

# Run only PostgreSQL-specific tests
pytest -m postgresql

# Run backend compliance tests
pytest tests/test_db_protocols.py

# CI matrix runs full suite against both backends
```

### Worker Isolation

- **DynamoDB**: Table prefix per worker (`test_w0__actors`, `test_w1__actors`)
- **PostgreSQL**: Schema per worker (`test_w0_public`, `test_w1_public`)

---

## Success Criteria

- [ ] All 900+ integration tests pass with PostgreSQL backend
- [ ] Protocol compliance tests pass for both backends
- [ ] CI/CD runs matrix testing (2 backends × 2 Python versions)
- [ ] Zero regressions in DynamoDB backend
- [ ] Connection pooling works correctly under load
- [ ] Worker isolation prevents parallel test conflicts
- [ ] Documentation complete for PostgreSQL setup
- [ ] Migration script successfully transfers DynamoDB data to PostgreSQL
- [ ] Type checking (pyright) passes with 0 errors
- [ ] Linting (ruff) passes with 0 warnings

---

## Implementation Timeline Estimate

- **Phase 1** (Foundation): 1-2 weeks
- **Phase 2** (Core Tables): 1 week
- **Phase 3** (Trust Tables): 1 week
- **Phase 4** (Subscriptions): 1 week
- **Phase 5** (Testing): 1-2 weeks
- **Phase 6** (Documentation): 1 week

**Total**: 6-8 weeks for complete implementation and testing

---

## Risk Mitigation

**Risk**: Breaking existing DynamoDB functionality
- **Mitigation**: Run full test suite against DynamoDB after every change

**Risk**: PostgreSQL performance issues
- **Mitigation**: Benchmark early, optimize indexes, use connection pooling

**Risk**: Test isolation failures in parallel mode
- **Mitigation**: Schema-based isolation, comprehensive worker coordination

**Risk**: Migration data loss
- **Mitigation**: Dry-run mode, validation checksums, rollback procedures

**Risk**: Protocol interface mismatches
- **Mitigation**: Protocol compliance tests, runtime checks with `isinstance()`

---

## Notes

- The existing dynamic module loading in `config.py` (lines 181-201) already supports multiple backends - no changes needed!
- DynamoDB remains the default backend for backward compatibility
- PostgreSQL is opt-in via `DATABASE_BACKEND=postgresql` and `poetry install --extras postgresql`
- All backends must return plain dicts (never ORM objects) to maintain the implicit contract
- Use Alembic migrations (not auto-table creation) for production-ready schema management
