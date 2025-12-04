# TODO

A living checklist for near‑term tasks, quality gates, and release prep. Keep items small and actionable. Use commands from the repo guidelines.

## Performance & Caching

- [ ] Review and finalize caching strategy documented in `cache.md`.
- [ ] Implement a shared cache across other high‑volume endpoints; define keys/TTLs and invalidation rules.

## O(n) Pattern Improvements

### HIGH PRIORITY

#### Token Revocation by ID - NOT IMPLEMENTED
**Location:** `actingweb/oauth2_server/token_manager.py:821-866`

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
**Location:** `actingweb/oauth2_server/token_manager.py:973-1034`

- [ ] Optimize `revoke_client_tokens()` which scans ALL tokens in actor's bucket

**Proposed Solution:**
Add `client_id_to_tokens_index` in `OAUTH2_SYSTEM_ACTOR` for O(1) lookup.

### LOW PRIORITY - Database Schema Issues

These use DynamoDB `scan()` which is O(n). Consider GSI optimization only if bottleneck:

- [ ] `db_property.py:fetch()` - Property scan by actor_id
- [ ] `db_trust.py:fetch()` - Trust scan by actor_id
- [ ] `db_peertrustee.py:get()` - PeerTrustee scan with filters

### Reference: Already Optimized

These already use the system actor global index pattern (O(1)). See `docs/oauth2-client-management.rst` for architecture details:
- Client lookup: `client_registry.py:_load_from_global_index()`
- Auth code lookup: `token_manager.py:_search_auth_code_in_actors()`
- Access/Refresh token lookup: `token_manager.py:_search_token_in_actors()`
