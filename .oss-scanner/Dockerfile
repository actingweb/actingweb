# Build image for Anthropic's OSS Scanner (https://github.com/anthropics/oss-scanner).
# The scanner builds this with the repository as the build context and then runs the
# audit with no network, so everything the test suite needs is fetched here:
# Python deps, DynamoDB Local (JRE + jar) and a PostgreSQL server.
#
# In the finished image, start both test databases and run the suite with:
#   aw-test-services
#   poetry run pytest tests/ --ignore=tests/performance -m "not benchmark" --no-cov
#   DATABASE_BACKEND=postgresql poetry run pytest tests/integration --no-cov
FROM python:3.11-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    PG_DB_HOST=localhost \
    PG_DB_PORT=5433 \
    PG_DB_NAME=actingweb_test \
    PG_DB_USER=actingweb \
    PG_DB_PASSWORD=testpassword \
    AWS_DB_HOST=http://localhost:8001 \
    AWS_ACCESS_KEY_ID=local \
    AWS_SECRET_ACCESS_KEY=local \
    AWS_DEFAULT_REGION=us-east-1

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl git default-jre-headless postgresql postgresql-contrib \
    && rm -rf /var/lib/apt/lists/*

# DynamoDB Local, as docker-compose.test.yml runs it (in memory, shared db, :8001).
RUN mkdir -p /opt/dynamodb-local \
    && curl -fsSL https://d1ni2b6xgvw0s0.cloudfront.net/v2.x/dynamodb_local_latest.tar.gz \
       | tar -xz -C /opt/dynamodb-local

# PostgreSQL cluster matching the CI service (:5433, actingweb/testpassword, actingweb_test).
RUN PGBIN="$(ls -d /usr/lib/postgresql/*/bin | head -n1)" \
    && ln -s "$PGBIN" /opt/pgbin \
    && mkdir -p /var/lib/aw-pg /var/run/postgresql \
    && chown postgres:postgres /var/lib/aw-pg /var/run/postgresql \
    && echo postgres > /tmp/pgpw && chown postgres /tmp/pgpw \
    && su postgres -c "/opt/pgbin/initdb -D /var/lib/aw-pg -A md5 -U postgres --pwfile=/tmp/pgpw" \
    && rm /tmp/pgpw
RUN su postgres -c "/opt/pgbin/pg_ctl -D /var/lib/aw-pg -o '-p 5433 -k /var/run/postgresql' -w start" \
    && PGPASSWORD=postgres psql -h localhost -p 5433 -U postgres \
         -c "CREATE ROLE actingweb LOGIN SUPERUSER PASSWORD 'testpassword';" \
         -c "CREATE DATABASE actingweb_test OWNER actingweb;" \
    && su postgres -c "/opt/pgbin/pg_ctl -D /var/lib/aw-pg -w stop"

# Starts both test databases in the background; safe to run more than once.
RUN printf '%s\n' \
      '#!/bin/sh' \
      'if ! curl -s -o /dev/null http://localhost:8001/; then' \
      '  (cd /opt/dynamodb-local && nohup java -Djava.library.path=./DynamoDBLocal_lib -jar DynamoDBLocal.jar -sharedDb -inMemory -port 8001 >/tmp/dynamodb.log 2>&1 &)' \
      'fi' \
      'su postgres -c "/opt/pgbin/pg_ctl -D /var/lib/aw-pg -o \"-p 5433 -k /var/run/postgresql\" -l /tmp/postgres.log -w status" >/dev/null 2>&1 \' \
      '  || su postgres -c "/opt/pgbin/pg_ctl -D /var/lib/aw-pg -o \"-p 5433 -k /var/run/postgresql\" -l /tmp/postgres.log -w start"' \
      'for i in $(seq 1 30); do curl -s -o /dev/null http://localhost:8001/ && exit 0; sleep 1; done' \
      'echo "DynamoDB Local did not start; see /tmp/dynamodb.log" >&2; exit 1' \
      > /usr/local/bin/aw-test-services \
    && chmod +x /usr/local/bin/aw-test-services

RUN pip install "poetry>=2,<3"

# scanner contract: the checkout lives inside the image, at /src
COPY . /src
WORKDIR /src

# Same install as CI: every extra (Flask, FastAPI, PostgreSQL) plus the dev group.
RUN poetry install --with dev --extras "all"

# Smoke-test the image: unit tests against DynamoDB Local. A failing test does not
# fail the build.
RUN aw-test-services \
    && (poetry run pytest tests/ --ignore=tests/integration --ignore=tests/performance \
          -m "not benchmark" --no-cov -q -p no:cacheprovider \
        || echo "WARNING: unit tests reported failures")
