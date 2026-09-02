# `_matches_pattern()`'s `://` prefix branch is an unnormalised `startswith`

Found by the 3.14.4 security review
(`thoughts/plans/2026-09-02-identifier-matching-and-metadata-fidelity.md`).
Verified at the 3.14.4 tree.

`actingweb/permission_evaluator.py:645`:

```python
if pattern.endswith("://") and target.startswith(pattern):
    return True
```

A rule written as `notes://` matches `notes://../../security/key` and
`notes://\nx` alike — the control-character guard in `_evaluate_rules` catches
the second, nothing normalises the first. Only custom configurations are
exposed: every shipped trust type writes resource rules as `notes://*`, which
takes the (now whole-string, DOTALL) regex path. Fix is either to drop the
branch (a `://` pattern becomes `://*` in the docs) or to normalise the URI
before comparing. Decide with the `uri_pattern` metadata question, since both
are "what does a resource rule match against".

## Related: the MCP `*/list` filters stay fail-open

3.14.4 made the six single-item MCP permission checks fail closed. The three
listing filters (`tools/list`, `resources/list`, `prompts/list`;
`actingweb/handlers/mcp.py:1008`, `:1254`, `:1329`) still treat an evaluator
that raises as "no evaluator" and return the unfiltered list. That discloses
names, not access — a listed tool still fails its `tools/call` check — but it
is the last place the two policies differ, and a client that sees a tool it
cannot call reads that as a bug. Return an empty list on evaluator error, the
way the no-trust path already does.
