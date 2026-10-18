#!/bin/sh
# Start the test databases inside the OSS Scanner image (see Dockerfile):
# DynamoDB Local on :8001 and PostgreSQL on :5433. Safe to run more than once;
# exits non-zero if either does not come up.
set -eu

PG_OPTS="-p 5433 -k /var/run/postgresql"

if ! curl -s -o /dev/null http://localhost:8001/; then
  (cd /opt/dynamodb-local \
    && nohup java -Djava.library.path=./DynamoDBLocal_lib -jar DynamoDBLocal.jar \
         -sharedDb -inMemory -port 8001 >/tmp/dynamodb.log 2>&1 &)
fi

if ! /opt/pgbin/pg_isready -q -h localhost -p 5433; then
  su postgres -c "/opt/pgbin/pg_ctl -D /var/lib/aw-pg -o '$PG_OPTS' -l /tmp/postgres.log -w start"
fi
if ! /opt/pgbin/pg_isready -q -h localhost -p 5433; then
  echo "PostgreSQL did not start; see /tmp/postgres.log" >&2
  exit 1
fi

for _ in $(seq 1 30); do
  curl -s -o /dev/null http://localhost:8001/ && exit 0
  sleep 1
done
echo "DynamoDB Local did not start; see /tmp/dynamodb.log" >&2
exit 1
