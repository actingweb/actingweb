# Attribute Storage Maintenance Plan

**Date:** 2025-12-26
**Status:** ✅ COMPLETED
**Related Documentation:** `docs/sdk/attributes-buckets.rst`, `docs/guides/database-maintenance.rst`

## Executive Summary

Investigation of the ActingWeb attribute bucket storage system revealed:
- 15 different bucket types storing various data
- Cleanup correctly happens on actor/client deletion
- **Critical gap**: No scheduled cleanup for expired tokens - they accumulate indefinitely
- No DynamoDB TTL configured

## Operational Context

**Critical constraints for solution design:**

- ActingWeb runs in **AWS Lambda containers**
- **Hundreds of containers** can scale up concurrently
- **Fast cold start** is a key value - time-to-serve must be minimal
- Any startup overhead multiplied by container count = thundering herd risk

**This eliminates:**
- ❌ Startup cleanup (adds cold start latency)
- ❌ Request-based periodic cleanup (unpredictable latency spikes)
- ❌ Any synchronous cleanup in serving path

**Viable approaches:**
- ✅ DynamoDB TTL (zero runtime overhead)
- ✅ Separate scheduled Lambda for cleanup
- ✅ Lazy cleanup during validation (current behavior - keep)

## Investigation Findings

### Data Types Stored

| Category | Buckets | Count |
|----------|---------|-------|
| System-level (global) | trust_types, oauth_sessions, spa_access_tokens, spa_refresh_tokens, auth_code_index, access_token_index, refresh_token_index, client_index | 8 |
| Per-actor | _internal, trust_permissions, mcp_clients, mcp_tokens, mcp_refresh_tokens, mcp_auth_codes, mcp_google_tokens, oauth_tokens:{peer_id} | 8+ |

### Cleanup Status

**What Works Correctly:**

- [x] Actor deletion cleans up ALL attribute buckets
- [x] MCP client deletion revokes tokens and cleans indexes
- [x] Trust deletion cleans up trust_permissions
- [x] Token validation removes expired tokens on access (lazy cleanup)

**What Doesn't Work:**

- [ ] No scheduled/proactive cleanup of expired tokens
- [ ] No DynamoDB TTL configured
- [ ] `_revoke_refresh_tokens_for_access_token()` not implemented (logs warning only)
- [ ] Orphaned Google token data possible when refresh token deleted first

### Risk Assessment

| Data Type | TTL | Accumulation Risk | Impact |
|-----------|-----|-------------------|--------|
| MCP refresh tokens | 30 days | **Critical** | Significant DB growth |
| SPA refresh tokens | 2 weeks | **High** | Moderate DB growth |
| OAuth sessions | 10 min | Medium | Low volume |
| Auth codes | 10 min | Medium | Low volume |
| Expired access tokens | 1 hour | Medium | Moderate if high traffic |

---

## Implementation Plan (Lambda-Optimized)

### Phase 1: Add TTL Support to Attribute Storage
**Priority:** Critical
**Effort:** Medium
**Lambda Impact:** Zero runtime overhead

DynamoDB TTL is the ideal solution for Lambda - it deletes expired items automatically in the background with no application code execution.

#### 1.1 Update Database Model

**File:** `actingweb/db_dynamodb/db_attribute.py`

```python
import os

from pynamodb.attributes import (
    JSONAttribute,
    NumberAttribute,  # ADD THIS
    UnicodeAttribute,
    UTCDateTimeAttribute,
)
from pynamodb.models import Model


class Attribute(Model):
    """
    DynamoDB data model for an attribute.
    """

    class Meta:
        table_name = os.getenv("AWS_DB_PREFIX", "demo_actingweb") + "_attributes"
        read_capacity_units = 26
        write_capacity_units = 2
        region = os.getenv("AWS_DEFAULT_REGION", "us-west-1")
        host = os.getenv("AWS_DB_HOST", None)

    id = UnicodeAttribute(hash_key=True)
    bucket_name = UnicodeAttribute(range_key=True)
    bucket = UnicodeAttribute()
    name = UnicodeAttribute()
    data = JSONAttribute(null=True)
    timestamp = UTCDateTimeAttribute(null=True)
    # NEW: TTL timestamp for automatic DynamoDB expiration
    ttl_timestamp = NumberAttribute(null=True)  # Unix epoch timestamp
```

Update `set_attr` method to accept TTL:

```python
@staticmethod
def set_attr(
    actor_id=None,
    bucket=None,
    name=None,
    data=None,
    timestamp=None,
    ttl_seconds=None,  # NEW PARAMETER
):
    """Sets a data value for a given attribute in a bucket.

    Args:
        actor_id: The actor ID
        bucket: The bucket name
        name: The attribute name
        data: The data to store (JSON-serializable)
        timestamp: Optional timestamp
        ttl_seconds: Optional TTL in seconds from now. If provided,
                     DynamoDB will automatically delete this item after expiry.
    """
    if not actor_id or not name or not bucket:
        return False
    if not data:
        try:
            item = Attribute.get(
                actor_id, bucket + ":" + name, consistent_read=True
            )
            item.delete()
        except Exception:
            pass
        return True

    # Calculate TTL timestamp if provided
    ttl_timestamp = None
    if ttl_seconds is not None:
        import time
        # Add 1 hour buffer for clock skew safety
        ttl_timestamp = int(time.time()) + ttl_seconds + 3600

    new = Attribute(
        id=actor_id,
        bucket_name=bucket + ":" + name,
        bucket=bucket,
        name=name,
        data=data,
        timestamp=timestamp,
        ttl_timestamp=ttl_timestamp,  # NEW FIELD
    )
    new.save()
    return True
```

#### 1.2 Update Attribute Wrapper Class

**File:** `actingweb/attribute.py`

Update the `Attributes.set_attr` method:

```python
def set_attr(
    self,
    name: str | None = None,
    data: Any | None = None,
    timestamp: Any | None = None,
    ttl_seconds: int | None = None,  # NEW PARAMETER
) -> bool:
    """Sets new data for this attribute.

    Args:
        name: Attribute name
        data: Data to store (JSON-serializable)
        timestamp: Optional timestamp
        ttl_seconds: Optional TTL in seconds. If provided, DynamoDB will
                     automatically delete this item after expiry.
    """
    if not self.actor_id or not self.bucket:
        return False
    if name not in self.data or self.data[name] is None:
        self.data[name] = {}
    self.data[name]["data"] = data
    self.data[name]["timestamp"] = timestamp
    if self.dbprop:
        return self.dbprop.set_attr(
            actor_id=self.actor_id,
            bucket=self.bucket,
            name=name,
            data=data,
            timestamp=timestamp,
            ttl_seconds=ttl_seconds,  # PASS THROUGH
        )
    return False
```

#### 1.3 Add TTL Constants

**File:** `actingweb/constants.py`

Add new constants:

```python
# TTL Values for Attribute Storage (in seconds)
# =============================================
# These define how long different data types should persist before
# DynamoDB automatically deletes them via TTL.

# OAuth session TTL (for postponed actor creation)
OAUTH_SESSION_TTL = 600  # 10 minutes

# SPA token TTLs
SPA_ACCESS_TOKEN_TTL = 3600  # 1 hour
SPA_REFRESH_TOKEN_TTL = 86400 * 14  # 2 weeks (1,209,600 seconds)

# MCP token TTLs
MCP_AUTH_CODE_TTL = 600  # 10 minutes
MCP_ACCESS_TOKEN_TTL = 3600  # 1 hour
MCP_REFRESH_TOKEN_TTL = 2592000  # 30 days

# Index entry TTLs (slightly longer than the data they reference)
# This ensures indexes aren't deleted before the data they point to
INDEX_TTL_BUFFER = 7200  # 2 hours extra buffer for indexes
```

---

### Phase 2: Update Token Storage to Include TTL
**Priority:** Critical
**Effort:** Medium
**Lambda Impact:** Zero - just adds field to stored data

#### 2.1 Update OAuth Session Manager

**File:** `actingweb/oauth_session.py`

Update `store_session`:

```python
def store_session(
    self,
    token_data: dict[str, Any],
    user_info: dict[str, Any],
    state: str = "",
    provider: str = "google",
    verified_emails: list[str] | None = None,
    pkce_verifier: str | None = None,
) -> str:
    from . import attribute
    from .constants import OAUTH2_SYSTEM_ACTOR, OAUTH_SESSION_BUCKET, OAUTH_SESSION_TTL

    session_id = secrets.token_urlsafe(32)

    session_data = {
        "token_data": token_data,
        "user_info": user_info,
        "state": state,
        "provider": provider,
        "created_at": int(time.time()),
    }

    if verified_emails:
        session_data["verified_emails"] = verified_emails

    if pkce_verifier:
        session_data["pkce_verifier"] = pkce_verifier

    bucket = attribute.Attributes(
        actor_id=OAUTH2_SYSTEM_ACTOR,
        bucket=OAUTH_SESSION_BUCKET,
        config=self.config,
    )
    # ADD TTL
    bucket.set_attr(name=session_id, data=session_data, ttl_seconds=OAUTH_SESSION_TTL)

    logger.debug(f"Stored OAuth session {session_id[:8]}... for provider {provider}")
    return session_id
```

Update `store_access_token`:

```python
def store_access_token(
    self, token: str, actor_id: str, identifier: str, ttl: int | None = None
) -> None:
    from . import attribute
    from .constants import OAUTH2_SYSTEM_ACTOR, SPA_ACCESS_TOKEN_TTL

    effective_ttl = ttl or SPA_ACCESS_TOKEN_TTL

    token_data = {
        "actor_id": actor_id,
        "identifier": identifier,
        "created_at": int(time.time()),
        "expires_at": int(time.time()) + effective_ttl,
    }

    bucket = attribute.Attributes(
        actor_id=OAUTH2_SYSTEM_ACTOR,
        bucket=_ACCESS_TOKEN_BUCKET,
        config=self.config,
    )
    # ADD TTL
    bucket.set_attr(name=token, data=token_data, ttl_seconds=effective_ttl)

    logger.debug(f"Stored access token for actor {actor_id}")
```

Update `create_refresh_token`:

```python
def create_refresh_token(
    self, actor_id: str, identifier: str | None = None, ttl: int | None = None
) -> str:
    from . import attribute
    from .constants import OAUTH2_SYSTEM_ACTOR, SPA_REFRESH_TOKEN_TTL

    effective_ttl = ttl or SPA_REFRESH_TOKEN_TTL
    refresh_token = secrets.token_urlsafe(48)

    token_data = {
        "actor_id": actor_id,
        "identifier": identifier or "",
        "created_at": int(time.time()),
        "expires_at": int(time.time()) + effective_ttl,
        "used": False,
    }

    bucket = attribute.Attributes(
        actor_id=OAUTH2_SYSTEM_ACTOR,
        bucket=_REFRESH_TOKEN_BUCKET,
        config=self.config,
    )
    # ADD TTL
    bucket.set_attr(name=refresh_token, data=token_data, ttl_seconds=effective_ttl)

    logger.debug(f"Created refresh token for actor {actor_id}")
    return refresh_token
```

#### 2.2 Update MCP Token Manager

**File:** `actingweb/oauth2_server/token_manager.py`

Update `_store_auth_code`:

```python
def _store_auth_code(
    self, actor_id: str, code: str, auth_data: dict[str, Any]
) -> None:
    """Store authorization code in private attributes."""
    try:
        from .. import attribute
        from ..constants import MCP_AUTH_CODE_TTL, INDEX_TTL_BUFFER

        # Store auth code in private attributes bucket
        auth_bucket = attribute.Attributes(
            actor_id=actor_id, bucket=self.auth_codes_bucket, config=self.config
        )
        # ADD TTL - auth codes expire in 10 minutes
        auth_bucket.set_attr(name=code, data=auth_data, ttl_seconds=MCP_AUTH_CODE_TTL)

        # Also store in global index for efficient lookup
        index_bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=AUTH_CODE_INDEX_BUCKET,
            config=self.config,
        )
        # Index entry gets slightly longer TTL
        index_bucket.set_attr(
            name=code,
            data=actor_id,
            ttl_seconds=MCP_AUTH_CODE_TTL + INDEX_TTL_BUFFER
        )

        logger.debug(f"Successfully stored auth code for actor {actor_id}")

    except Exception as e:
        logger.error(f"Error storing auth code for actor {actor_id}: {e}")
        raise
```

Update `_store_access_token`:

```python
def _store_access_token(
    self, actor_id: str, token: str, token_data: dict[str, Any]
) -> None:
    """Store access token in private attributes."""
    try:
        from .. import attribute
        from ..constants import MCP_ACCESS_TOKEN_TTL, INDEX_TTL_BUFFER

        # Store access token in private attributes bucket
        tokens_bucket = attribute.Attributes(
            actor_id=actor_id, bucket=self.tokens_bucket, config=self.config
        )
        # ADD TTL - access tokens expire in 1 hour
        tokens_bucket.set_attr(name=token, data=token_data, ttl_seconds=MCP_ACCESS_TOKEN_TTL)

        # Also store in global index for efficient lookup
        index_bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=ACCESS_TOKEN_INDEX_BUCKET,
            config=self.config,
        )
        # Index entry gets slightly longer TTL
        index_bucket.set_attr(
            name=token,
            data=actor_id,
            ttl_seconds=MCP_ACCESS_TOKEN_TTL + INDEX_TTL_BUFFER
        )

        logger.debug(f"Stored access token for actor {actor_id}")

    except Exception as e:
        logger.error(f"Error storing access token for actor {actor_id}: {e}")
        raise
```

Update `_store_refresh_token`:

```python
def _store_refresh_token(
    self, actor_id: str, token: str, refresh_data: dict[str, Any]
) -> None:
    """Store refresh token in private attributes."""
    try:
        from .. import attribute
        from ..constants import MCP_REFRESH_TOKEN_TTL, INDEX_TTL_BUFFER

        # Store refresh token in private attributes bucket
        refresh_bucket = attribute.Attributes(
            actor_id=actor_id, bucket=self.refresh_tokens_bucket, config=self.config
        )
        # ADD TTL - refresh tokens expire in 30 days
        refresh_bucket.set_attr(
            name=token,
            data=refresh_data,
            ttl_seconds=MCP_REFRESH_TOKEN_TTL
        )

        # Also store in global index for efficient lookup
        index_bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=REFRESH_TOKEN_INDEX_BUCKET,
            config=self.config,
        )
        # Index entry gets slightly longer TTL
        index_bucket.set_attr(
            name=token,
            data=actor_id,
            ttl_seconds=MCP_REFRESH_TOKEN_TTL + INDEX_TTL_BUFFER
        )

        logger.debug(f"Stored refresh token for actor {actor_id}")

    except Exception as e:
        logger.error(f"Error storing refresh token for actor {actor_id}: {e}")
        raise
```

Update `_store_google_token_data`:

```python
def _store_google_token_data(
    self, actor_id: str, token_key: str, google_token_data: dict[str, Any]
) -> None:
    """Store Google OAuth2 token data in private attributes."""
    try:
        from .. import attribute
        from ..constants import MCP_ACCESS_TOKEN_TTL

        # Store Google token data in private attributes bucket
        google_bucket = attribute.Attributes(
            actor_id=actor_id, bucket=self.google_tokens_bucket, config=self.config
        )
        # ADD TTL - tied to access token lifetime
        google_bucket.set_attr(
            name=token_key,
            data=google_token_data,
            ttl_seconds=MCP_ACCESS_TOKEN_TTL
        )
        logger.debug(
            f"Stored Google token data for actor {actor_id} with key {token_key}"
        )

    except Exception as e:
        logger.error(f"Error storing Google token data for actor {actor_id}: {e}")
        raise
```

---

### Phase 3: Add Cleanup Methods to Token Manager
**Priority:** High
**Effort:** Medium
**For use by:** Scheduled cleanup Lambda (deployed by applications)

**File:** `actingweb/oauth2_server/token_manager.py`

Add new cleanup method:

```python
def cleanup_expired_tokens(self) -> dict[str, int]:
    """
    Clean up expired MCP tokens and associated data.

    This method is intended to be called by a scheduled cleanup Lambda,
    NOT during request processing. It iterates through all token indexes
    and removes expired entries.

    Returns:
        Dictionary with counts of cleaned items by type
    """
    from .. import attribute

    current_time = int(time.time())
    cleaned = {
        "access_tokens": 0,
        "refresh_tokens": 0,
        "auth_codes": 0,
        "index_entries": 0,
    }

    # Clean up access token index
    access_index = attribute.Attributes(
        actor_id=OAUTH2_SYSTEM_ACTOR,
        bucket=ACCESS_TOKEN_INDEX_BUCKET,
        config=self.config,
    )
    access_index_data = access_index.get_bucket()

    if access_index_data:
        for token, index_attr in list(access_index_data.items()):
            if not index_attr or "data" not in index_attr:
                # Orphaned index entry
                access_index.delete_attr(name=token)
                cleaned["index_entries"] += 1
                continue

            actor_id = index_attr["data"]
            # Check if the actual token still exists and is valid
            token_data = self._load_access_token(token)
            if not token_data:
                # Token doesn't exist, clean index
                access_index.delete_attr(name=token)
                cleaned["index_entries"] += 1
            elif current_time > token_data.get("expires_at", 0):
                # Token expired, clean both
                self._remove_access_token(token)
                cleaned["access_tokens"] += 1

    # Clean up refresh token index
    refresh_index = attribute.Attributes(
        actor_id=OAUTH2_SYSTEM_ACTOR,
        bucket=REFRESH_TOKEN_INDEX_BUCKET,
        config=self.config,
    )
    refresh_index_data = refresh_index.get_bucket()

    if refresh_index_data:
        for token, index_attr in list(refresh_index_data.items()):
            if not index_attr or "data" not in index_attr:
                refresh_index.delete_attr(name=token)
                cleaned["index_entries"] += 1
                continue

            token_data = self._load_refresh_token(token)
            if not token_data:
                refresh_index.delete_attr(name=token)
                cleaned["index_entries"] += 1
            elif current_time > token_data.get("expires_at", 0):
                self._remove_refresh_token(token)
                cleaned["refresh_tokens"] += 1

    # Clean up auth code index
    auth_index = attribute.Attributes(
        actor_id=OAUTH2_SYSTEM_ACTOR,
        bucket=AUTH_CODE_INDEX_BUCKET,
        config=self.config,
    )
    auth_index_data = auth_index.get_bucket()

    if auth_index_data:
        for code, index_attr in list(auth_index_data.items()):
            if not index_attr or "data" not in index_attr:
                auth_index.delete_attr(name=code)
                cleaned["index_entries"] += 1
                continue

            auth_data = self._load_auth_code(code)
            if not auth_data:
                auth_index.delete_attr(name=code)
                cleaned["index_entries"] += 1
            elif current_time > auth_data.get("expires_at", 0):
                self._remove_auth_code(code)
                cleaned["auth_codes"] += 1

    total = sum(cleaned.values())
    if total > 0:
        logger.info(f"Cleanup complete: {cleaned}")

    return cleaned
```

---

### Phase 4: Keep Lazy Cleanup (Current Behavior)
**Priority:** N/A - Already Implemented
**Effort:** None
**Lambda Impact:** Minimal - only during validation

The current lazy cleanup is actually appropriate for Lambda:
- Runs only when tokens are validated (required anyway)
- Cleans up exactly when needed
- No extra overhead

**Keep as-is** - no changes needed.

---

### Phase 5: Fix Reverse Token Cleanup
**Priority:** Low
**Effort:** Medium

Fix unimplemented methods (called during explicit revocation, not serving path):

- [ ] `_revoke_access_token_by_id()` - currently logs warning only
- [ ] `_revoke_refresh_tokens_for_access_token()` - currently logs warning only

These are lower priority since DynamoDB TTL will handle cleanup automatically.

---

### Phase 6: Monitoring
**Priority:** Medium
**Effort:** Low

- [ ] CloudWatch metric for `_actingweb_oauth2` bucket item count
- [ ] Alert if item count exceeds threshold (indicates TTL not working)
- [ ] Dashboard showing:
  - Token creation rate
  - TTL deletion rate (from DynamoDB metrics)
  - Cleanup Lambda execution results
- [ ] Weekly audit of bucket sizes

---

## Phase 7: Documentation for Application Deployers
**Priority:** High
**Effort:** Medium

Create documentation in `docs/guides/` to help ActingWeb-based applications properly configure DynamoDB TTL and deploy cleanup jobs.

### 7.1 Create New Documentation File

**File:** `docs/guides/database-maintenance.rst`

**Purpose:** Guide for application developers on maintaining ActingWeb's DynamoDB storage.

**Structure:**

```rst
============================
Database Maintenance Guide
============================

Overview
--------

ActingWeb stores temporary data (tokens, sessions, auth codes) in DynamoDB's
attribute storage. This data has defined lifetimes and should be automatically
cleaned up to prevent unbounded database growth.

This guide explains how to configure your deployment for proper data lifecycle
management.

.. note::

   ActingWeb is designed for AWS Lambda deployments where hundreds of containers
   may scale concurrently. **Never add cleanup logic to your serving path** as
   this impacts cold start time and request latency.

DynamoDB TTL Configuration
--------------------------

ActingWeb stores a ``ttl_timestamp`` field on temporary data. You must enable
DynamoDB TTL on your attributes table for automatic cleanup.

**Why TTL?**

- Zero runtime overhead in your Lambda functions
- DynamoDB handles deletion automatically in the background
- No impact on cold start time or request latency
- Works reliably at any scale

**Enabling TTL:**

Using AWS CLI::

    aws dynamodb update-time-to-live \
      --table-name {your_prefix}_attributes \
      --time-to-live-specification "Enabled=true, AttributeName=ttl_timestamp"

Using Terraform::

    resource "aws_dynamodb_table" "actingweb_attributes" {
      # ... table configuration ...

      ttl {
        attribute_name = "ttl_timestamp"
        enabled        = true
      }
    }

Using CloudFormation::

    TimeToLiveSpecification:
      AttributeName: ttl_timestamp
      Enabled: true

**Verification:**

    aws dynamodb describe-time-to-live --table-name {your_prefix}_attributes

Scheduled Cleanup Lambda
------------------------

While DynamoDB TTL handles most cleanup automatically, orphaned index entries
may remain when the primary data is deleted. Deploy a scheduled cleanup Lambda
to handle these cases.

**Key Requirements:**

- Deploy as a **separate Lambda function** from your serving Lambdas
- Trigger via EventBridge/CloudWatch Events on a schedule (e.g., daily)
- Do NOT call cleanup methods from your request handling code
- Set appropriate timeout (5 minutes recommended)

**Cleanup Handler Example:**

.. code-block:: python

    from actingweb.config import Config
    from actingweb.oauth_session import OAuth2SessionManager
    from actingweb.oauth2_server.token_manager import ActingWebTokenManager

    def handler(event, context):
        config = Config(database="dynamodb", ...)

        session_mgr = OAuth2SessionManager(config)
        token_mgr = ActingWebTokenManager(config)

        results = {
            "oauth_sessions": session_mgr.clear_expired_sessions(),
            "spa_tokens": session_mgr.cleanup_expired_tokens(),
            "mcp_tokens": token_mgr.cleanup_expired_tokens(),
        }

        return {"statusCode": 200, "body": results}

**Deployment Options:**

- Serverless Framework with ``schedule`` event
- AWS SAM with ``Schedule`` event type
- CloudFormation with EventBridge rule
- Terraform with ``aws_cloudwatch_event_rule``

**Recommended Schedule:** Daily at low-traffic time (e.g., 03:00 UTC)

**Required IAM Permissions:**

- ``dynamodb:Query`` on attributes table
- ``dynamodb:GetItem`` on attributes table
- ``dynamodb:DeleteItem`` on attributes table

Monitoring
----------

Set up CloudWatch alarms to detect issues:

1. **Table Size Alarm**: Alert if attributes table item count grows beyond
   expected threshold (indicates TTL may not be working)

2. **Cleanup Lambda Errors**: Alert if the cleanup Lambda fails

3. **TTL Deletions**: Monitor DynamoDB's ``TimeToLiveDeletedItemCount`` metric
   to verify TTL is actively cleaning up data

Data Lifecycle Reference
------------------------

+-----------------------+------------+---------------------------+
| Data Type             | TTL        | Notes                     |
+=======================+============+===========================+
| OAuth sessions        | 10 minutes | Postponed actor creation  |
+-----------------------+------------+---------------------------+
| SPA access tokens     | 1 hour     | Web app authentication    |
+-----------------------+------------+---------------------------+
| SPA refresh tokens    | 2 weeks    | Web app token refresh     |
+-----------------------+------------+---------------------------+
| MCP auth codes        | 10 minutes | OAuth2 authorization flow |
+-----------------------+------------+---------------------------+
| MCP access tokens     | 1 hour     | MCP client authentication |
+-----------------------+------------+---------------------------+
| MCP refresh tokens    | 30 days    | MCP client token refresh  |
+-----------------------+------------+---------------------------+

See Also
--------

- :doc:`../sdk/attributes-buckets` - Attribute storage system details
- :doc:`../quickstart/deployment` - General deployment guide
```

### 7.2 Update Existing Documentation

**File:** `docs/sdk/attributes-buckets.rst`

Add cross-reference to the new maintenance guide in the "Maintenance Recommendations" section:

```rst
.. seealso::

   For detailed deployment instructions including DynamoDB TTL configuration
   and cleanup Lambda setup, see :doc:`../guides/database-maintenance`.
```

### 7.3 Update Documentation Index

**File:** `docs/guides/index.rst`

Add the new guide to the table of contents:

```rst
.. toctree::
   :maxdepth: 2

   # ... existing entries ...
   database-maintenance
```

### 7.4 Documentation Content Checklist

The new documentation should include:

- [ ] Why TTL is the right approach for Lambda deployments
- [ ] AWS CLI command for enabling TTL
- [ ] Terraform snippet for TTL configuration
- [ ] CloudFormation snippet for TTL configuration
- [ ] Cleanup Lambda handler code example
- [ ] Serverless Framework deployment example
- [ ] SAM template example
- [ ] Required IAM permissions
- [ ] CloudWatch monitoring recommendations
- [ ] Data lifecycle reference table with TTL values
- [ ] Cross-references to related documentation

---

## Files to Modify

### Library Code

| File | Changes |
|------|---------|
| `actingweb/db_dynamodb/db_attribute.py` | Add `ttl_timestamp` field, update `set_attr()` |
| `actingweb/attribute.py` | Add `ttl_seconds` parameter to `set_attr()` |
| `actingweb/constants.py` | Add TTL constants |
| `actingweb/oauth_session.py` | Pass TTL when storing sessions/tokens |
| `actingweb/oauth2_server/token_manager.py` | Pass TTL when storing tokens, add `cleanup_expired_tokens()` |

### Documentation

| File | Changes |
|------|---------|
| `docs/guides/database-maintenance.rst` | **New file** - DynamoDB TTL and cleanup Lambda guide |
| `docs/guides/index.rst` | Add `database-maintenance` to toctree |
| `docs/sdk/attributes-buckets.rst` | Add cross-reference to maintenance guide |

## Testing Requirements

### Unit Tests

- [ ] Test `ttl_timestamp` is correctly calculated with buffer
- [ ] Test `set_attr()` without TTL still works (backward compatible)
- [ ] Test `set_attr()` with TTL sets correct `ttl_timestamp`
- [ ] Test cleanup methods correctly identify expired tokens

### Integration Tests

- [ ] Create tokens with TTL, verify `ttl_timestamp` stored in DynamoDB
- [ ] Verify lazy cleanup still works during validation
- [ ] Test actor deletion still works with TTL fields
- [ ] Test `cleanup_expired_tokens()` removes correct entries

### Manual Verification (For Applications)

- [ ] Enable DynamoDB TTL on test table
- [ ] Create tokens, wait for expiry, verify auto-deletion
- [ ] Deploy cleanup Lambda, verify it runs successfully
- [ ] Verify CloudWatch alarms trigger on failures

---

## Rollout Plan

### Library Changes

1. **Development**:
   - Add `ttl_timestamp` field (backward compatible - null allowed)
   - Update token storage to include TTL
   - Add cleanup methods
   - Run unit and integration tests

2. **Release**:
   - Release new library version with TTL support
   - Update documentation with deployment guidance

### Application Deployment (Per Application)

1. **Update Library**: Upgrade to new ActingWeb version

2. **Deploy Code First**: Deploy application code changes
   - TTL values are stored but DynamoDB doesn't act on them yet

3. **Enable DynamoDB TTL**: Run AWS CLI or apply Terraform/CloudFormation
   - DynamoDB begins automatic cleanup

4. **Deploy Cleanup Lambda**: Deploy scheduled Lambda
   - Handles orphaned index entries

5. **Enable Monitoring**: Set up CloudWatch alarms

---

## Success Metrics

- Zero impact on Lambda cold start time
- Zero increase in request latency
- Attribute table size stabilizes (stops growing unbounded)
- DynamoDB TTL deletions visible in CloudWatch
- Cleanup Lambda completes successfully daily
- Zero data loss incidents

---

## Architecture Diagram

```text
┌─────────────────────────────────────────────────────────────────┐
│                     Serving Lambda (hundreds)                    │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ Lambda Instance │  │ Lambda Instance │  │ Lambda Instance │  │
│  │   (no cleanup)  │  │   (no cleanup)  │  │   (no cleanup)  │  │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘  │
│           │                    │                    │           │
│           │  Lazy cleanup only during validation    │           │
│           └────────────────────┼────────────────────┘           │
└────────────────────────────────┼────────────────────────────────┘
                                 │
                                 ▼
              ┌──────────────────────────────────────┐
              │           DynamoDB Table             │
              │      (TTL auto-deletes items)        │
              │  ┌────────────────────────────────┐  │
              │  │  ttl_timestamp field enables   │  │
              │  │  automatic background cleanup  │  │
              │  └────────────────────────────────┘  │
              └──────────────────┬───────────────────┘
                                 │
                                 │ Index references may remain
                                 ▼
              ┌──────────────────────────────────────┐
              │        Cleanup Lambda (single)       │
              │   Triggered daily by EventBridge     │
              │  ┌────────────────────────────────┐  │
              │  │  Cleans orphaned index entries │  │
              │  │  No impact on serving path     │  │
              │  └────────────────────────────────┘  │
              └──────────────────────────────────────┘
```

---

## Related Work

- `docs/sdk/attributes-buckets.rst` - Updated documentation
- `actingweb/oauth_session.py` - Existing cleanup methods (for cleanup Lambda)
- `actingweb/oauth2_server/token_manager.py` - Token management
