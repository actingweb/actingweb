# /verify_implementation addendum

- The Full tier includes both backends. Record the DynamoDB and the
  PostgreSQL run separately in the verification, with counts; "tests pass"
  without a backend named is not evidence.
- A parallel failure is re-run sequentially before it is reported; say which
  run the number comes from.
- Run one test run at a time (port `5555`, `test_w0_` prefix); inside the
  Claude Code sandbox add `-p no:rerunfailures`.
- Benchmarks (`-m benchmark`) are not part of CI; run them alone when the
  plan touched list storage or the attribute layer, and record the numbers.
- Verify the docs build (`sphinx-build -W ...` from the Full tier) whenever a
  phase touched `docs/` or a docstring autodoc pulls in.
- A plan that claims a security property (a strip, a binding, a revocation)
  gets that property demonstrated in the verification, not inferred from
  green tests: the test that pins it is named with its assertion.
- Check `thoughts/todo/` against the plan: every todo the plan said it would
  close is deleted with its `INDEX.md` row; every deferral the plan named
  has a todo file. Then set the plan's `verified:` link.
- If the plan has a consumer message (Phase 3 in most plans here), confirm it
  is still accurate after implementation and quote it in the verification.
