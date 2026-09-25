# /implement_plan addendum

- Every phase is green on **both** backends before it is called complete:
  the Full tier's DynamoDB and PostgreSQL runs. A PostgreSQL-only failure is
  a backend difference, not a flake.
- Run one test run at a time; a second run (in this or another session)
  collides on port `5555` and the `test_w0_` database prefix.
- Inside the Claude Code sandbox, direct `pytest` calls need
  `-p no:rerunfailures`.
- A change to `pyproject.toml` regenerates `docs/requirements.txt` in the same
  commit (`poetry export --with docs --without-hashes -o docs/requirements.txt`).
- A new PostgreSQL column or index needs an Alembic migration under
  `actingweb/db/postgresql/migrations/` in the same phase; the integration
  fixtures run the chain from scratch per worker.
- A change to a DynamoDB model needs the matching change on the PostgreSQL
  backend and in `db/protocols.py`; the two backends share one protocol.
- A new or changed route, hook, kwarg, response field or config option makes
  the release a minor; say so in the phase notes so the changelog phase
  places it right.
- Deferred work found while implementing goes to `thoughts/todo/<slug>.md`
  plus a row in `thoughts/todo/INDEX.md`; a consumer-side follow-up goes in
  the phase notes for the Phase 3 consumer message.
- Do not edit `examples/demo/` casually: it is imported by tests and is the
  code behind `demo.actingweb.io`.
