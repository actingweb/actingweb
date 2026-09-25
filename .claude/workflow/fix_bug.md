# /fix_bug addendum

- Scope lock is self-check. State the boundary as the set of paths the fix
  needs: the module under `actingweb/`, its backend twin under
  `actingweb/db/<backend>/` when storage is involved, `tests/`,
  `CHANGELOG.rst`, and `docs/` when documented behaviour changes.
- A bug reported from a consumer (`thoughts/inbound/`, or a consumer's plan
  or todo) is verified against this tree before it is accepted: the reporter
  reads the code from outside and can be right about the symptom and wrong
  about the cause or the blast radius. Write down what the check changed.
- Reproduce on both backends. A fix that only the DynamoDB path needs still
  gets a PostgreSQL run to show the other path is unaffected.
- Every fix gets a regression test that fails before and passes after; name
  the assertion in the research note.
- Prefer the primitive the codebase already has (`conditional_update_attr`,
  `delete_attr_conditional`, `delete_by_chain`, the redaction helpers) over
  a new one; the research note names the reuse.
- Decide the release with the fix: patch when no route, hook name, kwarg,
  response field, public signature or config option changes; minor
  otherwise. Record it in the research note's decisions.
- Never patch a bug in `examples/demo/` around a library defect; fix the
  library and let the demo inherit it.
