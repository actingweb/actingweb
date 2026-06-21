===========================
Database Backends Reference
===========================

ActingWeb supports two production-ready database backends: **DynamoDB** and **PostgreSQL**.
This document provides a detailed comparison to help you choose the right backend for your use case.

Quick Comparison
----------------

.. list-table::
   :header-rows: 1
   :widths: 25 35 40

   * - Feature
     - DynamoDB
     - PostgreSQL
   * - **Setup Complexity**
     - Low (auto-creates tables)
     - Medium (requires Alembic migrations)
   * - **Local Development**
     - DynamoDB Local (Docker)
     - PostgreSQL (Docker or native install)
   * - **Installation**
     - ``pip install 'actingweb[dynamodb]'``
     - ``pip install 'actingweb[postgresql]'``
   * - **Scaling**
     - Automatic, serverless
     - Manual (vertical/horizontal scaling)
   * - **Cost Model**
     - Pay-per-request or provisioned throughput
     - Instance-based (compute + storage)
   * - **Query Flexibility**
     - Key-based with Global Secondary Indexes
     - Full SQL with JOINs, aggregations, CTEs
   * - **Latency (local)**
     - Higher (network overhead to AWS)
     - Lower (direct database connection)
   * - **Latency (same region)**
     - Very low (<10ms)
     - Very low (<5ms)
   * - **Production Management**
     - Fully managed by AWS
     - Self-managed or RDS/Cloud SQL
   * - **Multi-region**
     - Built-in global tables
     - Manual replication (streaming/logical)
   * - **Transactions**
     - Limited (single table, conditions)
     - Full ACID transactions
   * - **Backup/Restore**
     - Point-in-time recovery built-in
     - pg_dump or continuous archiving
   * - **TTL/Cleanup**
     - Built-in automatic TTL deletion (enable TTL on ``attributes.ttl_timestamp``)
     - Self-contained opportunistic purge (no cron required)
   * - **Connection Pooling**
     - Not applicable (HTTP API)
     - Built-in (psycopg3 ConnectionPool)

When to Use DynamoDB
--------------------

**Best For:**

- **AWS-centric deployments**: Already using AWS Lambda, API Gateway, etc.
- **Global distribution**: Need multi-region active-active setup with minimal effort
- **Variable traffic**: Traffic patterns with large spikes or long idle periods
- **Serverless architecture**: Zero server management, automatic scaling
- **Key-value workloads**: Simple lookups by actor ID, property name, trust relationship
- **Pay-per-use economics**: Want to pay only for actual usage, not idle capacity

**Advantages:**

1. **Zero administration**: No servers to manage, no capacity planning
2. **Automatic scaling**: Handles traffic spikes without intervention
3. **Global tables**: Multi-region replication with conflict resolution
4. **Built-in TTL**: Automatic cleanup of expired data
5. **On-demand pricing**: Pay only for requests (or use provisioned capacity)
6. **High availability**: 99.99% SLA within region, 99.999% for global tables

**Considerations:**

1. **Cost at scale**: Can become expensive with sustained high traffic (>100k requests/day)
2. **AWS lock-in**: Difficult to migrate away from AWS ecosystem
3. **Index management**: Global Secondary Indexes have cost and design implications

**Example Use Cases:**

- Serverless web application on AWS Lambda
- Mobile backend with global user base
- IoT platform with burst traffic patterns
- Microservices with variable load

When to Use PostgreSQL
----------------------

**Best For:**

- **Predictable traffic**: Steady load or known capacity requirements
- **Cost optimization**: High-traffic apps where instance-based pricing is cheaper
- **Multi-cloud/on-prem**: Want to avoid cloud vendor lock-in
- **Existing PostgreSQL expertise**: Team already knows PostgreSQL
- **Transaction requirements**: Need complex multi-table transactions

**Advantages:**

1. **Lower latency**: Direct connection pool reduces overhead
2. **Cost efficiency**: Fixed monthly cost regardless of request volume
3. **Rich ecosystem**: Extensive tools, extensions (PostGIS, full-text search, etc.)
4. **ACID transactions**: Full transactional guarantees across operations
5. **No vendor lock-in**: Works on any cloud or on-premises
6. **Advanced features**: Triggers, stored procedures, custom functions

**Considerations:**

1. **Manual scaling**: Must provision capacity and handle scaling yourself
2. **Database management**: Need to manage backups, updates, monitoring
3. **Connection limits**: Connection pooling required for high concurrency
4. **Migration setup**: Must run Alembic migrations before first use
5. **TTL cleanup**: Handled by the library's self-contained opportunistic purge
   (see `Expired Token Cleanup (TTL)`_); no pg_cron required for ActingWeb's own
   token tables

**Example Use Cases:**

- Traditional web application with steady traffic
- Reporting/analytics requirements
- Multi-tenant SaaS application
- Enterprise deployment with on-premises requirements

Performance Characteristics
---------------------------

Actor Operations
~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 30 20 20 30

   * - Operation
     - DynamoDB
     - PostgreSQL
     - Notes
   * - Actor create
     - 5-15ms
     - 2-5ms
     - PostgreSQL faster for local/same-region
   * - Actor read
     - 5-10ms
     - 1-3ms
     - Both very fast for key-based lookup
   * - Actor update
     - 5-10ms
     - 2-4ms
     - PostgreSQL slightly faster
   * - Property write
     - 5-10ms
     - 1-3ms
     - PostgreSQL benefits from connection pooling
   * - Property read
     - 5-10ms
     - 1-2ms
     - Both efficient for primary key lookup
   * - Trust list
     - 10-20ms
     - 2-5ms
     - PostgreSQL better for complex queries

Scaling Characteristics
~~~~~~~~~~~~~~~~~~~~~~~

**DynamoDB:**

- Horizontal scaling: Automatic partition management
- Read capacity: Auto-scales to millions of requests/second
- Write capacity: Auto-scales to millions of requests/second
- Latency: Consistent regardless of table size
- Limits: 400KB item size, 25 operations per transaction

**PostgreSQL:**

- Vertical scaling: Larger instances for more CPU/RAM
- Horizontal scaling: Read replicas, sharding (manual setup)
- Connection pooling: Essential for Lambda/serverless (use external pool like RDS Proxy)
- Latency: Can degrade with very large tables without proper indexing
- Limits: 1GB per row, no practical transaction limit

Cost Analysis
-------------

Example: 1 million requests/day
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**DynamoDB Costs (us-east-1):**

.. code-block:: text

    On-Demand Pricing:
    - 1M writes/day × $1.25/million = $1.25/day = $37.50/month
    - 3M reads/day × $0.25/million = $0.75/day = $22.50/month
    - Storage: 10GB × $0.25/GB = $2.50/month
    Total: ~$63/month

    Provisioned Capacity (if steady load):
    - 12 WCU × 730 hours × $0.00065 = $5.69/month
    - 35 RCU × 730 hours × $0.00013 = $3.32/month
    - Storage: 10GB × $0.25/GB = $2.50/month
    Total: ~$12/month (62% savings with provisioned)

**PostgreSQL Costs (AWS RDS):**

.. code-block:: text

    db.t4g.small (2 vCPU, 2GB RAM):
    - Instance: $0.017/hour × 730 hours = $12.41/month
    - Storage: 20GB SSD × $0.115/GB = $2.30/month
    - Backup storage: 20GB × $0.095/GB = $1.90/month
    Total: ~$17/month

    db.t4g.medium (2 vCPU, 4GB RAM):
    - Instance: $0.034/hour × 730 hours = $24.82/month
    - Storage: 50GB SSD × $0.115/GB = $5.75/month
    - Backup storage: 50GB × $0.095/GB = $4.75/month
    Total: ~$35/month

**Analysis**: For this traffic level, PostgreSQL is more cost-effective. DynamoDB becomes competitive only with:
- Highly variable traffic (benefit from on-demand)
- Global replication requirements
- Zero-ops preference (worth the premium)

Expired Token Cleanup (TTL)
---------------------------

ActingWeb's SPA/mobile session tokens (the ``/oauth/spa/token`` flow) are stored
in the ``attributes`` table with a ``ttl_timestamp``. Access tokens are
short-lived (1 hour); refresh tokens rotate, and a *used* refresh token's TTL is
shortened to a bounded reuse-detection window (``SPA_REFRESH_TOKEN_REUSE_WINDOW``,
2 days) so consumed tokens do not accumulate. Expired rows still need to be
deleted from storage. How that happens depends on the backend:

**PostgreSQL — automatic, no configuration required.**
The library purges expired token rows itself. The ``/oauth/spa/token`` endpoint
opportunistically calls ``OAuth2SessionManager.maybe_purge_expired_tokens()``,
which runs at most once per ``SPA_TOKEN_PURGE_INTERVAL`` (1 hour) per process and
issues a single set-based ``DELETE`` backed by the ``idx_attributes_ttl`` partial
index (cost scales with the number of expired rows, not table size). No pg_cron
or scheduled job is needed for ActingWeb's own token tables. Applications may
still call ``purge_expired_tokens()`` directly from a scheduled job if they want
a deterministic cadence.

**DynamoDB — enable native TTL on the table (one-time setup).**
DynamoDB deletes expired items automatically, but **TTL must be enabled on the
attributes table**, pointed at the ``ttl_timestamp`` attribute. The library does
not (and cannot reliably) enable this for you, and a full-table ``Scan`` to purge
is deliberately avoided, so without this step expired tokens are never removed.

.. important::

   Enabling TTL on the shared ``attributes`` table is **safe** even though that
   table also holds permanent data (internal store, cached values, application
   attributes). DynamoDB TTL deletes an item *only* when its ``ttl_timestamp``
   attribute is present and in the past. ActingWeb writes ``ttl_timestamp`` only
   for temporary data that is *meant* to expire — SPA access/refresh tokens,
   OAuth login sessions, mobile exchange tickets, state nonces, and index
   entries. Every permanent write goes through ``set_attr`` with no ``ttl``, so
   those items have **no** ``ttl_timestamp`` and are never eligible for TTL
   deletion. (If your own code calls ``set_attr(..., ttl_seconds=...)`` it is
   likewise opting that item into expiry — don't pass a TTL for data you want to
   keep.)

Enable it once per environment:

.. code-block:: bash

   aws dynamodb update-time-to-live \
       --table-name <PREFIX>_attributes \
       --time-to-live-specification "Enabled=true, AttributeName=ttl_timestamp"

The table name is ``<AWS_DB_PREFIX>_attributes`` (default prefix
``demo_actingweb``). TTL deletion is asynchronous (AWS removes items within ~48h
of expiry), which is fine for token cleanup. The ``ttl_timestamp`` is written
with a clock-skew buffer so items are never deleted before they are logically
expired.

Migration Between Backends
---------------------------

ActingWeb provides full migration tooling to switch backends without data loss.

DynamoDB → PostgreSQL
~~~~~~~~~~~~~~~~~~~~~

See :doc:`../guides/postgresql-migration` for complete migration guide.

**Summary:**

1. Install PostgreSQL and run Alembic migrations
2. Export DynamoDB data: ``python scripts/migrate_dynamodb_to_postgresql.py export``
3. Import to PostgreSQL: ``python scripts/migrate_dynamodb_to_postgresql.py import``
4. Validate: ``python scripts/migrate_dynamodb_to_postgresql.py validate``
5. Update configuration: ``DATABASE_BACKEND=postgresql``
6. Deploy and verify

**Downtime**: Can be zero with blue-green deployment strategy.

PostgreSQL → DynamoDB
~~~~~~~~~~~~~~~~~~~~~

Reverse migration is possible but requires custom export logic:

1. Export PostgreSQL to JSON (use ``pg_dump`` or custom script)
2. Transform data to DynamoDB format (handle composite keys)
3. Import using boto3 batch writes
4. Enable DynamoDB TTL on attributes table
5. Update configuration: ``DATABASE_BACKEND=dynamodb``

Implementation Details
----------------------

Table Schema Mapping
~~~~~~~~~~~~~~~~~~~~~

ActingWeb uses the same logical schema for both backends:

.. list-table::
   :header-rows: 1
   :widths: 20 30 30 20

   * - Table
     - Primary Key
     - DynamoDB Implementation
     - PostgreSQL Implementation
   * - actors
     - ``id``
     - Hash key: ``id``
     - Primary key: ``id``
   * - properties
     - ``(id, name)``
     - Hash key: ``id``, Range: ``name``
     - Composite key: ``(id, name)``
   * - attributes
     - ``(id, bucket_name)``
     - Hash key: ``id``, Range: ``bucket_name``
     - Composite key: ``(id, bucket_name)``
   * - trusts
     - ``(id, peerid)``
     - Hash key: ``id``, Range: ``peerid``
     - Composite key: ``(id, peerid)``
   * - peertrustees
     - ``(id, peerid)``
     - Hash key: ``id``, Range: ``peerid``
     - Composite key: ``(id, peerid)``
   * - subscriptions
     - ``(id, peer_sub_id)``
     - Hash key: ``id``, Range: ``peer_sub_id``
     - Composite key: ``(id, peer_sub_id)``
   * - subscription_diffs
     - ``(id, subid_seqnr)``
     - Hash key: ``id``, Range: ``subid_seqnr``
     - Composite key: ``(id, subid_seqnr)``

Index Strategy
~~~~~~~~~~~~~~

**DynamoDB:**

- Global Secondary Indexes (GSI) for non-key lookups:
  - ``actors``: GSI on ``creator`` field
  - ``properties``: GSI on ``value`` field (reverse lookups)
  - ``trusts``: GSI on ``secret`` field (token lookups)

**PostgreSQL:**

- B-tree indexes on frequently queried columns:
  - ``CREATE INDEX idx_actors_creator ON actors(creator)``
  - ``CREATE INDEX idx_properties_value ON properties(value)``
  - ``CREATE INDEX idx_trusts_secret ON trusts(secret)``
  - ``CREATE INDEX idx_attributes_ttl ON attributes(ttl_timestamp)`` (for cleanup)

Connection Management
~~~~~~~~~~~~~~~~~~~~~

**DynamoDB:**

- Stateless HTTP API (no connections to manage)
- PynamoDB handles retries and exponential backoff
- Works well with AWS Lambda (cold starts not affected)

**PostgreSQL:**

- Connection pooling via psycopg3 ``ConnectionPool``
- Default pool: min=2, max=10 connections
- Configure via environment variables:
  - ``PG_POOL_MIN_SIZE``
  - ``PG_POOL_MAX_SIZE``
  - ``PG_POOL_TIMEOUT``
- For AWS Lambda: Consider RDS Proxy for connection management

Data Types
~~~~~~~~~~

**JSON Storage:**

- DynamoDB: Native map/list types
- PostgreSQL: JSONB column type (efficient binary storage)

**Timestamps:**

- Both: Unix epoch as BIGINT for consistency
- PostgreSQL: Could use native TIMESTAMP but uses BIGINT for compatibility

**Composite Keys:**

- DynamoDB: Separate hash and range key fields
- PostgreSQL: Concatenated with ``:`` separator (e.g., ``peerid:subid``)

Recommendations by Scenario
----------------------------

Serverless/Lambda Deployment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Recommend: DynamoDB**

- Zero cold start impact (HTTP API)
- Automatic scaling with Lambda concurrency
- No connection management needed
- Pay-per-use aligns with Lambda pricing model

Traditional Server Deployment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Recommend: PostgreSQL**

- Better cost efficiency for steady load
- Simpler connection management with long-lived processes
- Lower latency with persistent connections
- Easier debugging with SQL query logs

Multi-Region Deployment
~~~~~~~~~~~~~~~~~~~~~~~

**Recommend: DynamoDB Global Tables**

- Built-in multi-region replication
- Automatic conflict resolution
- <100ms cross-region latency
- PostgreSQL multi-region requires manual setup (streaming replication, logical replication)

High-Traffic Application (>1M requests/day)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Recommend: PostgreSQL** (if predictable traffic)

- Fixed monthly cost
- Better cost efficiency at scale
- Lower per-request latency
- Connection pooling handles high concurrency

**Recommend: DynamoDB** (if variable/spiky traffic)

- Automatic scaling for burst traffic
- No capacity planning needed
- Pay only for actual usage

Development/Testing
~~~~~~~~~~~~~~~~~~~

**Either backend works well:**

- DynamoDB Local: ``docker run -p 8000:8000 amazon/dynamodb-local``
- PostgreSQL: ``docker run -p 5432:5432 postgres:16-alpine``
- Both support rapid iteration and testing

See Also
--------

- :doc:`../quickstart/configuration` - Configuration reference for both backends
- :doc:`../guides/postgresql-migration` - DynamoDB to PostgreSQL migration guide
- :doc:`../guides/database-maintenance` - TTL and cleanup configuration
- :doc:`../quickstart/local-dev-setup` - Local development setup
- :doc:`../contributing/backend-testing` - Testing strategy for dual backends
