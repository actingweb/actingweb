# `_glob_to_regex()` anchors with `$`, and `*`/`?` use `.`

`PermissionEvaluator._glob_to_regex()`
(`actingweb/permission_evaluator.py`, near the bottom of the class) builds
`f"^{escaped}$"` from a glob, with `\*` → `.*` and `\?` → `.`. Two gaps, both
about newlines:

- **`$` is not `\Z`.** In Python, `$` also matches immediately *before* a
  trailing newline. So pattern `notes` matches target `"notes\n"`, and pattern
  `secret*` matches `"secret\n"` — an anchor that does not anchor.
- **`.` excludes newline unless `re.DOTALL`.** So `*` does NOT match a name
  containing `\n`: pattern `memory_*` fails to match `"memory_a\nb"`. A rule
  the owner wrote intending to cover a namespace silently does not cover part
  of it.

Both are equally broken today in the single-list path
(`evaluate_property_access` → `_matches_pattern`), where the target name comes
from the CALLER. What changed is reachability: since
`thoughts/plans/2026-08-29-bulk-list-reads-from-a-consumer.md` Phase 5, the
authenticated bulk readers pass names that came from **storage**, so a list
whose name contains a newline is now matched against these patterns without
any caller having typed it. Nothing in the library forbids such a name.

The fix is two characters and a flag:

```python
return f"^{escaped}\\Z"          # instead of f"^{escaped}$"
re.compile(regex_pattern, re.DOTALL)
```

Deliberately not done in that plan: it changes matching semantics for every
permission rule in every deployment, which is a bigger blast radius than the
release it would have ridden in, and it wants its own tests (a `\n`-containing
target against exact, `*` and `?` patterns, both directions) plus a changelog
note. Filed rather than smuggled.

Note also `self._pattern_cache` is keyed on the pattern string alone, so if
the flags ever become conditional the cache key must include them.
