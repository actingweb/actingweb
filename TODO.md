# TODO

A living checklist for near‑term tasks, quality gates, and release prep. Keep items small and actionable. Use commands from the repo guidelines.

## Typing & Linting

- [ ] Run mypy and address warnings (`poetry run mypy actingweb`).
- [ ] Format codebase with Black (`poetry run black .`).

## Packaging & Release

- [ ] Document release steps: version bump, `CHANGELOG.rst`, tag, and publish.

## Developer Experience

- [ ] Add a concise CONTRIBUTING guide (dev install, common commands, testing).

## Performance & Caching

- [ ] Review and finalize caching strategy documented in `cache.md`.
- [ ] Implement a shared cache across other high‑volume endpoints; define keys/TTLs and invalidation rules.
