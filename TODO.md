# TODO

A living checklist for near‑term tasks, quality gates, and release prep. Keep items small and actionable. Use commands from the repo guidelines.

## Performance & Caching

- [ ] Review and finalize caching strategy documented in `docs/guides/caching.md`.
- [ ] Implement a shared cache across other high‑volume endpoints; define keys/TTLs and invalidation rules.

## Code TODOs

### <www.py> Handler
**Location:** `actingweb/handlers/www.py:751`
- [ ] Store human-readable relationship name separately if different from trust_type

## O(n) Pattern Improvements

### HIGH PRIORITY

#### Token Revocation by ID - NOT IMPLEMENTED
**Location:** `actingweb/oauth2_server/token_manager.py:842-885`

- [ ] Implement `_revoke_access_token_by_id()` - currently logs warning and does nothing
- [ ] Implement `_revoke_refresh_tokens_for_access_token()` - currently logs warning and does nothing

**Impact:**
- Refresh flow: Old access tokens remain valid until natural expiry
- Explicit revocation: Revoking one token type doesn't cascade to linked token

**Proposed Solution:**
Add reverse indexes in `OAUTH2_SYSTEM_ACTOR`:
- `token_id_to_token_index` - Maps internal token_id to token string
- `access_token_id_to_refresh_tokens_index` - Maps access_token_id to refresh tokens

#### Client Token Revocation - O(n) Scan
**Location:** `actingweb/oauth2_server/token_manager.py:994-1055`

- [ ] Optimize `revoke_client_tokens()` which scans ALL tokens in actor's bucket

**Current Implementation:**
```python
# Scans entire tokens_bucket for matching client_id
access_tokens_data = tokens_bucket.get_bucket()
for token_name, token_attr in access_tokens_data.items():
    if token_data.get("client_id") == client_id:
        # Revoke token
```

**Proposed Solution:**
Add `client_id_to_tokens_index` in `OAUTH2_SYSTEM_ACTOR` for O(1) lookup.

### LOW PRIORITY - Database Schema Issues

These use DynamoDB `scan()` which is O(n). Consider GSI optimization only if bottleneck:

- [ ] `db/dynamodb/property.py:fetch()` - Property scan by actor_id
- [ ] `db/dynamodb/trust.py:fetch()` - Trust scan by actor_id
- [ ] `db/dynamodb/peertrustee.py:get()` - PeerTrustee scan with filters

### Reference: Already Optimized

These already use the system actor global index pattern (O(1)). See `docs/oauth2-client-management.rst` for architecture details:
- Client lookup: `client_registry.py:_load_from_global_index()`
- Auth code lookup: `token_manager.py:_search_auth_code_in_actors()`
- Access/Refresh token lookup: `token_manager.py:_search_token_in_actors()`

## Quality Gates

Before each release:
- [ ] Run `make test-all-parallel` - all 900+ tests must pass
- [ ] Run `poetry run pyright actingweb tests` - 0 errors, 0 warnings
- [ ] Run `poetry run ruff check actingweb tests` - all checks pass
- [ ] Update version in 3 files: `pyproject.toml`, `actingweb/__init__.py`, `CHANGELOG.rst`
- [ ] Review CHANGELOG.rst for completeness
