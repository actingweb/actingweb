# Drop Python 3.11 once it reaches end of life

**Provenance:** the owner decided on 2026-11-04, while fixing a CI type-check
failure on PR #169 that the local 3.14 environment did not report: keep 3.11
until its upstream end of life, then drop it. The policy is to support every
Python version CPython still maintains, not SPEC 0.

## What is open

`pyproject.toml` claims `python = "^3.11"` with classifiers 3.11 to 3.14.
CI tests 3.11 and 3.14, the oldest and newest claimed versions
(`.github/workflows/tests.yml`, `python-version`), and type-check, docs and
the publish workflow run on 3.11. CPython 3.11 gets security fixes only, and
its end of life is **October 2027** (PEP 664).

## What doing it buys

The library stops promising a Python version that upstream no longer patches,
and CI stops spending a matrix leg on it.

## When and how

**Trigger:** the first minor release after October 2027. Raising the minimum
is breaking for consumers still on 3.11, so it never goes in a patch.

- `pyproject.toml`: `python = "^3.12"`, drop the 3.11 classifier, then
  `poetry lock` and regenerate `docs/requirements.txt`.
- `pyrightconfig.json` `pythonVersion` and `[tool.mypy] python_version`: 3.12.
- `.github/workflows/tests.yml`: the matrix's oldest entry becomes 3.12, and
  the type-check and docs jobs move to it. `publish-to-pypi.yml` too.
- **Branch protection:** the required contexts are named
  `Tests (Python 3.11, dynamodb|postgresql)`, so they must be renamed in the
  repository settings in the same change, or every PR waits on checks that
  never report. The "CI policy" section of `CLAUDE.md` names them too.
- Docs: `README.rst` and `CONTRIBUTING.rst` ("Python 3.11+"), and the
  `python:3.11-slim` and `runtime: python3.11` examples in
  `docs/quickstart/deployment.rst` and `docs/quickstart/getting-started.rst`.
- A changelog entry with a **Breaking:** lead under `CHANGED`, and a row in
  that minor's migration guide.

`demo.actingweb.io` moves to Python 3.14 with the 3.16 pin (actingwebdemo
branch `deps/actingweb-3.16-python-3.14`), so the demo does not block this.
