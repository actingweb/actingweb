==========================
PostgreSQL Migration Guide
==========================

This guide explains how to migrate from DynamoDB to PostgreSQL for existing ActingWeb deployments.

Prerequisites
=============

- PostgreSQL 12 or higher
- Python 3.11+
- ActingWeb with PostgreSQL extras installed: ``poetry install --extras postgresql``
- Access to both DynamoDB and PostgreSQL databases during migration

Migration Overview
==================

The migration process involves:

1. **Setup**: Install PostgreSQL backend and run migrations
2. **Export**: Extract data from DynamoDB
3. **Import**: Load data into PostgreSQL
4. **Validate**: Verify data integrity
5. **Switchover**: Update configuration to use PostgreSQL
6. **Cleanup**: (Optional) Archive or delete DynamoDB data

**Estimated time**: 2-6 hours depending on data volume

Step 1: PostgreSQL Setup
========================

1.1 Install PostgreSQL
----------------------

**macOS (Homebrew)**:

.. code-block:: bash

   brew install postgresql@16
   brew services start postgresql@16

**Ubuntu/Debian**:

.. code-block:: bash

   sudo apt update
   sudo apt install postgresql-16 postgresql-contrib
   sudo systemctl start postgresql

**Docker (Development)**:

.. code-block:: bash

   docker run -d \
     --name actingweb-postgres \
     -e POSTGRES_USER=actingweb \
     -e POSTGRES_PASSWORD=secretpassword \
     -e POSTGRES_DB=actingweb \
     -p 5432:5432 \
     postgres:16-alpine

1.2 Create Database and User
----------------------------

.. code-block:: text

   -- Connect as postgres superuser
   psql -U postgres

   -- Create user and database
   CREATE USER actingweb WITH PASSWORD 'secretpassword';
   CREATE DATABASE actingweb OWNER actingweb;
   GRANT ALL PRIVILEGES ON DATABASE actingweb TO actingweb;

   -- Exit psql
   \q

1.3 Install Python Dependencies
-------------------------------

.. code-block:: bash

   # Install PostgreSQL extras
   poetry install --extras postgresql

   # Verify installation
   poetry run python -c "import psycopg; import alembic; print('PostgreSQL dependencies installed')"

1.4 Configure Environment
-------------------------

**Development (.env)**:

.. code-block:: bash

   # Backend selection
   DATABASE_BACKEND=postgresql

   # PostgreSQL connection
   PG_DB_HOST=localhost
   PG_DB_PORT=5432
   PG_DB_NAME=actingweb
   PG_DB_USER=actingweb
   PG_DB_PASSWORD=secretpassword

   # Optional: Schema prefix for testing
   PG_DB_PREFIX=

**Production (systemd/Docker)**:

.. code-block:: bash

   export DATABASE_BACKEND=postgresql
   export PG_DB_HOST=postgres.example.com
   export PG_DB_PORT=5432
   export PG_DB_NAME=actingweb_prod
   export PG_DB_USER=actingweb
   export PG_DB_PASSWORD=<secure-password>

1.5 Run Alembic Migrations
--------------------------

.. code-block:: bash

   cd actingweb/db/postgresql/
   alembic upgrade head

**Verify tables created**:

.. code-block:: bash

   psql -U actingweb -d actingweb -c "\dt"

Expected output::

                 List of relations
    Schema |        Name         | Type  |   Owner
   --------+---------------------+-------+-----------
    public | actors              | table | actingweb
    public | alembic_version     | table | actingweb
    public | attributes          | table | actingweb
    public | peertrustees        | table | actingweb
    public | properties          | table | actingweb
    public | subscription_diffs  | table | actingweb
    public | subscriptions       | table | actingweb
    public | trusts              | table | actingweb

Step 2: Export DynamoDB Data
============================

2.1 Use Migration Script (Recommended)
--------------------------------------

.. code-block:: bash

   # Export all data to JSON
   poetry run python scripts/migrate_dynamodb_to_postgresql.py export \
     --output-dir /tmp/actingweb_export \
     --aws-profile production \
     --table-prefix prod_

   # Verify export
   ls -lh /tmp/actingweb_export/

Expected files:

- ``actors.json``
- ``properties.json``
- ``attributes.json``
- ``trusts.json``
- ``peertrustees.json``
- ``subscriptions.json``
- ``subscription_diffs.json``

2.2 Manual Export (Advanced)
----------------------------

**Export single table**:

.. code-block:: python

   import json
   from pynamodb.models import Model

   # Export actors
   actors = []
   for actor in ActorModel.scan():
       actors.append(actor.to_dict())

   with open('actors.json', 'w') as f:
       json.dump(actors, f, indent=2)

Step 3: Import to PostgreSQL
============================

3.1 Use Migration Script (Recommended)
--------------------------------------

.. code-block:: bash

   # Import data from JSON
   poetry run python scripts/migrate_dynamodb_to_postgresql.py import \
     --input-dir /tmp/actingweb_export \
     --pg-host localhost \
     --pg-port 5432 \
     --pg-database actingweb \
     --pg-user actingweb \
     --pg-password secretpassword

   # Verify import
   poetry run python scripts/migrate_dynamodb_to_postgresql.py validate \
     --input-dir /tmp/actingweb_export \
     --pg-host localhost \
     --pg-port 5432 \
     --pg-database actingweb \
     --pg-user actingweb \
     --pg-password secretpassword

3.2 Verify Row Counts
---------------------

.. code-block:: sql

   -- Check row counts
   SELECT 'actors' AS table_name, COUNT(*) FROM actors
   UNION ALL
   SELECT 'properties', COUNT(*) FROM properties
   UNION ALL
   SELECT 'attributes', COUNT(*) FROM attributes
   UNION ALL
   SELECT 'trusts', COUNT(*) FROM trusts
   UNION ALL
   SELECT 'peertrustees', COUNT(*) FROM peertrustees
   UNION ALL
   SELECT 'subscriptions', COUNT(*) FROM subscriptions
   UNION ALL
   SELECT 'subscription_diffs', COUNT(*) FROM subscription_diffs;

Compare with DynamoDB counts.

Step 4: Validation
==================

4.1 Automated Validation
------------------------

The migration script includes validation:

.. code-block:: bash

   poetry run python scripts/migrate_dynamodb_to_postgresql.py validate \
     --input-dir /tmp/actingweb_export \
     --pg-host localhost \
     --pg-database actingweb

**Checks performed**:

- Row count matches
- Primary key uniqueness
- Foreign key integrity (actor references)
- Data type conversions (JSON, timestamps)
- Sample record comparison

4.2 Manual Verification
-----------------------

**Check specific actor**:

.. code-block:: sql

   -- Get actor by ID
   SELECT * FROM actors WHERE id = 'test-actor-123';

   -- Get actor's properties
   SELECT * FROM properties WHERE id = 'test-actor-123';

   -- Get actor's trusts
   SELECT * FROM trusts WHERE id = 'test-actor-123';

**Compare with DynamoDB**:

.. code-block:: python

   from actingweb.db.dynamodb.actor import DbActor

   db_actor = DbActor()
   db_actor.get('test-actor-123')
   print(db_actor.handle)

4.3 Integration Test
--------------------

Run integration tests against PostgreSQL:

.. code-block:: bash

   # Set PostgreSQL as backend
   export DATABASE_BACKEND=postgresql
   export PG_DB_HOST=localhost
   export PG_DB_PORT=5432
   export PG_DB_NAME=actingweb_test
   export PG_DB_USER=actingweb
   export PG_DB_PASSWORD=testpassword

   # Run tests
   poetry run pytest tests/integration/ -v

All tests should pass.

Step 5: Switchover
==================

5.1 Low-Traffic Switchover (Recommended)
----------------------------------------

**Best for**: Development, staging, low-traffic production

1. **Schedule maintenance window** (low traffic period)
2. **Stop application** to prevent writes to DynamoDB
3. **Export latest DynamoDB data** (capture any final changes)
4. **Import to PostgreSQL**
5. **Update configuration** to ``DATABASE_BACKEND=postgresql``
6. **Restart application**
7. **Verify** application functionality
8. **Monitor** for errors

5.2 Blue-Green Deployment
-------------------------

**Best for**: High-availability production

1. **Deploy new PostgreSQL-backed instances** (green environment)
2. **Import data** to PostgreSQL
3. **Route subset of traffic** to green environment (e.g., 10%)
4. **Monitor** for issues
5. **Gradually increase traffic** to green environment
6. **Switch DNS/load balancer** to green environment
7. **Decommission** old DynamoDB instances (blue environment)

5.3 Configuration Updates
-------------------------

**Update systemd service**:

.. code-block:: ini

   [Service]
   Environment="DATABASE_BACKEND=postgresql"
   Environment="PG_DB_HOST=postgres.example.com"
   Environment="PG_DB_PORT=5432"
   Environment="PG_DB_NAME=actingweb_prod"
   Environment="PG_DB_USER=actingweb"
   Environment="PG_DB_PASSWORD=<secure-password>"

**Update Docker Compose**:

.. code-block:: yaml

   services:
     app:
       environment:
         - DATABASE_BACKEND=postgresql
         - PG_DB_HOST=postgres
         - PG_DB_PORT=5432
         - PG_DB_NAME=actingweb
         - PG_DB_USER=actingweb
         - PG_DB_PASSWORD=secretpassword
       depends_on:
         postgres:
           condition: service_healthy

     postgres:
       image: postgres:16-alpine
       environment:
         POSTGRES_USER: actingweb
         POSTGRES_PASSWORD: secretpassword
         POSTGRES_DB: actingweb
       volumes:
         - postgres_data:/var/lib/postgresql/data
       healthcheck:
         test: ["CMD-SHELL", "pg_isready -U actingweb"]
         interval: 10s
         timeout: 5s
         retries: 5

   volumes:
     postgres_data:

**Update Kubernetes**:

.. code-block:: yaml

   apiVersion: v1
   kind: ConfigMap
   metadata:
     name: actingweb-config
   data:
     DATABASE_BACKEND: "postgresql"
     PG_DB_HOST: "postgres-service"
     PG_DB_PORT: "5432"
     PG_DB_NAME: "actingweb"
   ---
   apiVersion: v1
   kind: Secret
   metadata:
     name: actingweb-secrets
   type: Opaque
   stringData:
     PG_DB_USER: "actingweb"
     PG_DB_PASSWORD: "<secure-password>"

Step 6: Post-Migration
======================

6.1 Monitoring
--------------

**PostgreSQL connection pooling**:

.. code-block:: sql

   -- Check active connections
   SELECT count(*) FROM pg_stat_activity WHERE datname = 'actingweb';

**Query performance**:

.. code-block:: sql

   -- Enable query logging (postgresql.conf)
   log_statement = 'all'
   log_duration = on

   -- Or use pg_stat_statements extension
   CREATE EXTENSION pg_stat_statements;
   SELECT query, calls, total_time, mean_time
   FROM pg_stat_statements
   ORDER BY total_time DESC
   LIMIT 10;

6.2 Backup Setup
----------------

**pg_dump (simple)**:

.. code-block:: bash

   # Daily backup
   pg_dump -U actingweb actingweb | gzip > actingweb_$(date +%Y%m%d).sql.gz

   # Cron job
   0 2 * * * pg_dump -U actingweb actingweb | gzip > /backups/actingweb_$(date +\%Y\%m\%d).sql.gz

**Continuous archiving (production)**:

.. code-block:: bash

   # Enable WAL archiving in postgresql.conf
   wal_level = replica
   archive_mode = on
   archive_command = 'test ! -f /archive/%f && cp %p /archive/%f'

   # Use pgBackRest or Barman for point-in-time recovery

6.3 Performance Tuning
----------------------

**Connection pooling** (already configured in connection.py):

.. code-block:: bash

   export PG_POOL_MIN_SIZE=2
   export PG_POOL_MAX_SIZE=20
   export PG_POOL_TIMEOUT=30

**PostgreSQL tuning** (postgresql.conf):

.. code-block:: ini

   # Memory
   shared_buffers = 256MB           # 25% of RAM
   effective_cache_size = 1GB       # 50-75% of RAM
   work_mem = 16MB                  # Per connection sort memory

   # Connections
   max_connections = 100

   # Query planner
   random_page_cost = 1.1           # For SSD storage
   effective_io_concurrency = 200   # For SSD storage

6.4 Cleanup (Optional)
----------------------

After confirming PostgreSQL is working correctly:

**Archive DynamoDB data**:

.. code-block:: bash

   # Export to S3 for archival
   aws dynamodb scan --table-name prod_actors \
     | gzip > s3://backups/dynamodb/actors_$(date +%Y%m%d).json.gz

**Delete DynamoDB tables**:

.. code-block:: bash

   # WARNING: Irreversible!
   aws dynamodb delete-table --table-name prod_actors
   aws dynamodb delete-table --table-name prod_properties
   # ... etc

Rollback Procedures
===================

Quick Rollback (if issues detected early)
-----------------------------------------

.. code-block:: bash

   # 1. Stop application
   systemctl stop actingweb

   # 2. Revert configuration
   export DATABASE_BACKEND=dynamodb
   export AWS_DB_HOST=http://dynamodb.us-west-2.amazonaws.com
   export AWS_DB_PREFIX=prod_

   # 3. Restart application
   systemctl start actingweb

   # 4. Verify DynamoDB is still accessible

Data Recovery (if PostgreSQL data corrupted)
--------------------------------------------

.. code-block:: bash

   # 1. Drop PostgreSQL database
   psql -U postgres -c "DROP DATABASE actingweb;"
   psql -U postgres -c "CREATE DATABASE actingweb OWNER actingweb;"

   # 2. Re-run migrations
   cd actingweb/db/postgresql/
   alembic upgrade head

   # 3. Re-import from exported JSON
   poetry run python scripts/migrate_dynamodb_to_postgresql.py import \
     --input-dir /tmp/actingweb_export

   # 4. Validate
   poetry run python scripts/migrate_dynamodb_to_postgresql.py validate \
     --input-dir /tmp/actingweb_export

Common Issues
=============

Issue: Connection refused
-------------------------

**Symptom**::

   psycopg.OperationalError: connection to server at "localhost" (::1), port 5432 failed: Connection refused

**Solution**:

.. code-block:: bash

   # Check PostgreSQL is running
   pg_isready -h localhost -p 5432

   # Start PostgreSQL
   sudo systemctl start postgresql   # Linux
   brew services start postgresql@16 # macOS

   # Check pg_hba.conf allows connections
   sudo vi /etc/postgresql/16/main/pg_hba.conf
   # Add: host  all  actingweb  127.0.0.1/32  md5
   sudo systemctl reload postgresql

Issue: Authentication failed
----------------------------

**Symptom**::

   psycopg.OperationalError: FATAL: password authentication failed for user "actingweb"

**Solution**:

.. code-block:: bash

   # Reset password
   psql -U postgres -c "ALTER USER actingweb WITH PASSWORD 'newsecretpassword';"

   # Update environment variable
   export PG_DB_PASSWORD=newsecretpassword

Issue: Schema already exists
----------------------------

**Symptom**::

   alembic.util.exc.CommandError: Target database is not up to date.

**Solution**:

.. code-block:: bash

   # Check current version
   cd actingweb/db/postgresql/
   alembic current

   # Stamp database with current version
   alembic stamp head

   # Or drop and recreate
   psql -U actingweb -d actingweb -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
   alembic upgrade head

Issue: Migration script fails
-----------------------------

**Symptom**::

   ERROR: Failed to import properties: duplicate key value violates unique constraint

**Solution**:

.. code-block:: bash

   # Check for duplicate data in export
   jq '.[] | .id + ":" + .name' /tmp/actingweb_export/properties.json | sort | uniq -d

   # Clean duplicates before import
   poetry run python scripts/migrate_dynamodb_to_postgresql.py import \
     --input-dir /tmp/actingweb_export \
     --skip-duplicates \
     --log-level DEBUG

Issue: Performance degradation
------------------------------

**Symptom**: Queries slower than DynamoDB

**Solution**:

.. code-block:: sql

   -- Check missing indexes
   SELECT schemaname, tablename, indexname
   FROM pg_indexes
   WHERE schemaname = 'public';

   -- Add missing indexes (already in Alembic migrations)
   -- Analyze query plans
   EXPLAIN ANALYZE SELECT * FROM trusts WHERE id = 'actor-123';

   -- Update table statistics
   ANALYZE actors;
   ANALYZE properties;
   -- ... etc

   -- Vacuum tables
   VACUUM ANALYZE;

Performance Comparison
======================

Typical performance characteristics:

.. list-table::
   :header-rows: 1
   :widths: 25 15 15 45

   * - Operation
     - DynamoDB
     - PostgreSQL
     - Notes
   * - Single actor read
     - 5-10ms
     - 1-3ms
     - PostgreSQL faster (local)
   * - Property read
     - 5-10ms
     - 1-2ms
     - PostgreSQL faster
   * - Trust query
     - 10-20ms
     - 2-5ms
     - PostgreSQL faster (JOIN support)
   * - Batch operations
     - Good
     - Excellent
     - PostgreSQL supports transactions
   * - Full table scan
     - Poor
     - Good
     - PostgreSQL has better filtering
   * - Concurrent writes
     - Excellent
     - Good
     - DynamoDB has better write scaling

**PostgreSQL advantages**:

- Lower latency for single reads (no network overhead)
- Complex queries with JOINs
- Transaction support (ACID guarantees)
- Lower cost for read-heavy workloads
- Mature backup/restore tools

**DynamoDB advantages**:

- Automatic scaling
- Multi-region replication
- Better for extremely high write throughput (>10k writes/sec)
- Managed service (no server maintenance)

Support
=======

For migration assistance:

- GitHub Issues: https://github.com/actingweb/actingweb/issues
- Documentation: https://actingweb.readthedocs.io

Appendix: Schema Reference
==========================

PostgreSQL Schema
-----------------

**actors table**:

.. code-block:: sql

   CREATE TABLE actors (
       id VARCHAR(255) PRIMARY KEY,
       creator VARCHAR(255),
       passphrase TEXT
   );
   CREATE INDEX idx_actors_creator ON actors(creator);

**properties table**:

.. code-block:: sql

   CREATE TABLE properties (
       id VARCHAR(255),
       name VARCHAR(255),
       value TEXT,
       PRIMARY KEY (id, name),
       FOREIGN KEY (id) REFERENCES actors(id) ON DELETE CASCADE
   );
   CREATE INDEX idx_properties_value ON properties(value);

**trusts table**:

.. code-block:: sql

   CREATE TABLE trusts (
       id VARCHAR(255),
       peerid VARCHAR(255),
       baseuri VARCHAR(255),
       type VARCHAR(50),
       relationship VARCHAR(50),
       secret VARCHAR(255),
       -- ... additional fields
       PRIMARY KEY (id, peerid),
       FOREIGN KEY (id) REFERENCES actors(id) ON DELETE CASCADE
   );
   CREATE INDEX idx_trusts_secret ON trusts(secret);

See ``actingweb/db/postgresql/schema.py`` for complete schema definitions.
