# CI "Tests (postgresql)" 20-minute hang — root cause and mitigation

Date: 2026-06-15
Branch: fix/github-displayname-normalization

## Symptom

The `Tests (Python 3.11, postgresql)` matrix job intermittently reached ~99% of
the suite in ~2.5 min, then went completely silent and was cancelled at the
20-minute `timeout-minutes` wall with no diagnostics. The dynamodb matrix
usually passed (~15.5 min).

## What it is NOT

Not a database deadlock. While a wedged run was live, `pg_stat_activity` showed
**zero lock waiters**; every connection was `idle` in `ClientRead` after a
`COMMIT`. The database was idle — the wedge is entirely on the Python/pytest
side.

## Root cause

An **xdist controller wedge at the suite tail**. Captured via a `faulthandler`
watchdog stack dump of a reproduced hang:

- Controller main thread: `xdist/dsession.py:154 loop_once` → `queue.get()` —
  blocked waiting for a worker event that never arrives. All workers were alive
  but idle (DB connections parked).
- pytest-rerunfailures runs a controller-side socket server (`ServerStatusDB`)
  with one `run_connection`/`_sock_recv` thread per worker, plus an
  `XDistHooks` / `pytest_handlecrashitem` crashed-worker handler. This machinery
  is created on **every** parallel run whenever xdist is active
  (`pytest_rerunfailures.py:384`), **independent of `--reruns`** — so dropping
  `--reruns` does not disable it.

### Trigger

The wedge consistently appears around
`tests/integration/test_oauth2_client_manager.py::TestOAuth2ClientCreation`.
Those tests pass in isolation but are slow and flaky under `-n 4`:

- Their per-worker session fixtures (`setup_database` runs `poetry run alembic
  upgrade head` as a subprocess; `test_app` starts uvicorn) take ~2 min and are
  charged to whichever test first triggers them.
- Under parallel load a worker becomes unresponsive at the tail; xdist's
  crashed/slow-worker handling (entangled with rerunfailures + `--dist
  loadgroup`) leaves the controller blocked in `queue.get()`.

### Why earlier attempts didn't help

- **Per-test `--timeout` (thread method):** when the wedge happens no test is
  "running", so it never fires. Worse, with the default `timeout_func_only=false`
  it charged the ~2 min fixture setup to the first test and `os._exit`'d the
  worker (`node down: Not properly terminated`) — which on dynamodb produced a
  fresh failure and on postgres fed the hang.
- **`--session-timeout`:** cooperative — only checked when the controller event
  loop regains control, which the `queue.get()`/recv wedge prevents. Observed to
  fire only after 38 minutes. Not a reliable guard.
- **`--dist loadgroup` + worker restart:** restarting a crashed worker trips a
  known xdist bug (`KeyError: <WorkerController gwN>` in
  `loadscope._assign_work_unit`) that itself wedges the controller.

## Mitigation (shipped)

The reliable, library-agnostic guard is a **non-cooperative watchdog**:

- `tests/conftest.py`: `faulthandler.dump_traceback_later(N, exit=True)` armed
  from `PYTEST_WATCHDOG_SECONDS` (CI sets 1500). A C-level timer thread in every
  process dumps all thread stacks and hard-exits if still alive after N seconds.
  **Validated**: on a reproduced wedge it fired at exactly 5:00, dumped the
  stacks (which is how the rerunfailures threads were identified), and exited 1.
- `.github/workflows/tests.yml`:
  - `PYTEST_WATCHDOG_SECONDS: 1500` (above the legit full-run wall, below
    `timeout-minutes`).
  - `timeout-minutes: 30` (was 20; dynamodb alone is ~15.5 min).
  - `--max-worker-restart=0` (avoid the loadgroup-reschedule `KeyError`).
  - `--timeout=300 --timeout-method=thread` retained as a single-test backstop.
- `pyproject.toml`: `timeout_func_only = true` so `--timeout` measures the test
  body only, never the slow session-fixture setup.

This turns a silent 20-minute hang into a fast, self-diagnosing failure.

## Follow-up (not done here)

The watchdog bounds the symptom; the underlying flakiness remains:

1. Stabilise `test_oauth2_client_manager.py::TestOAuth2ClientCreation` under
   parallel execution (fixed `creator="user@example.com"` + process-global
   singletons: the psycopg pool and `trust_type_registry._registry`).
2. Speed up the per-worker `alembic upgrade head` session fixture (subprocess +
   full migration chain per worker).
3. Evaluate whether `--dist loadgroup` is required, or whether disabling
   rerunfailures' xdist socket machinery under parallel runs is viable.
