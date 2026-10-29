# PostgreSQL unit tests depend on the integration suite's schema setup

**Filed:** 2026-10-18, from the OSS Scanner `tools/check` run behind PR #157
(raised again in that PR's review).

A serial PostgreSQL run of the unit tests on its own fails. In the scanner
image (`--network none`, a fresh cluster on :5433), this command:

```sh
DATABASE_BACKEND=postgresql poetry run pytest tests/ --ignore=tests/integration \
  --ignore=tests/performance -m "not benchmark" --no-cov
```

reports `44 failed, 2741 passed, 124 skipped, 15 errors`, mostly
`relation "actors" does not exist`. The result is the same on `master`
(6d74cb5) and on PR #157. A serial run of the whole `tests/` tree on
PostgreSQL also fails (43 failed, 9 errors).

**Cause (from the code, not instrumented):** the only `alembic upgrade head`
lives in a session fixture in `tests/integration/conftest.py`. Unit tests that
touch PostgreSQL do not run migrations themselves. They pass in CI only
because the `-n 4 --dist loadgroup` run puts integration and unit tests in
the same worker sessions, so the schema already exists when they run.

**What doing it buys:** the PostgreSQL unit tests can run on their own, and
the documented PostgreSQL check (`tests/integration` only) stops being the
only one that works on a fresh database.

**Shape:** a root-level session fixture (or a shared helper the integration
conftest also uses) that runs the migrations once when
`DATABASE_BACKEND=postgresql`. Check the interaction with the per-worker
schema prefix (`test_w0_`) and the per-worker alembic cost noted in
[ci-postgres-parallel-flakiness.md](ci-postgres-parallel-flakiness.md).
