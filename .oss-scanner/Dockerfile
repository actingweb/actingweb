# Build image for Anthropic's OSS Scanner (https://github.com/anthropics/oss-scanner).
# The scanner builds this with the repository as the build context and then runs the
# audit with no network, so everything the test suite needs is fetched here:
# Python deps, DynamoDB Local (JRE + jar) and a PostgreSQL server.
#
# TEST-ONLY IMAGE: the PostgreSQL superuser role and the `testpassword` credentials
# below mirror docker-compose.test.yml. Never deploy this image.
#
# In the finished image, start both test databases and run the suite with:
#   aw-test-services
#   poetry run pytest tests/ --ignore=tests/performance -m "not benchmark" --no-cov
#   DATABASE_BACKEND=postgresql poetry run pytest tests/integration --no-cov

# DynamoDB Local, pinned by version and digest (the CloudFront tarball has no
# versioned URL).
FROM amazon/dynamodb-local:3.3.2@sha256:6ada631ec7aa5fc83446855eb17233e3dad184fec47477e8140c6c569cfe0c86 AS dynamodb

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

COPY --from=dynamodb /home/dynamodblocal /opt/dynamodb-local

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

COPY .oss-scanner/aw-test-services.sh /usr/local/bin/aw-test-services
RUN chmod +x /usr/local/bin/aw-test-services

# Poetry version that generated poetry.lock.
RUN pip install "poetry==2.4.1"

# Dependencies first so a source change does not rebuild this layer.
# Same install as CI: every extra (Flask, FastAPI, PostgreSQL) plus the dev group.
WORKDIR /src
COPY pyproject.toml poetry.lock /src/
RUN poetry install --with dev --extras "all" --no-root

# scanner contract: the checkout lives inside the image, at /src
COPY . /src
RUN poetry install --with dev --extras "all"

# Smoke-test the image: unit tests against DynamoDB Local. A failing test does not
# fail the build.
RUN aw-test-services \
    && (poetry run pytest tests/ --ignore=tests/integration --ignore=tests/performance \
          -m "not benchmark" --no-cov -q -p no:cacheprovider \
        || echo "WARNING: unit tests reported failures")
