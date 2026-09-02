# `_glob_to_regex()` cannot express a literal `*` or `?`, and NFC/NFD names are distinct

Found by the 3.14.4 architecture review
(`thoughts/plans/2026-09-02-identifier-matching-and-metadata-fidelity.md`).
Verified at the 3.14.4 tree.

## Backslash escapes

`actingweb/permission_evaluator.py` `_glob_to_regex()` is `re.escape()`
followed by `.replace(r"\*", ".*")` and `.replace(r"\?", ".")`. A glob that
tries to escape a wildcard, `a\*b`, is escaped to `a\\\*b` and then the
`\*` inside it is rewritten, so the pattern still matches `aXYZb`. There is no
way to write a rule for an identifier that contains a literal `*` or `?`.
Nothing shipped needs one; a consumer with such names would. The fix is a
character-by-character scanner (handle `\`, `*`, `?`, escape everything else)
— not a patch-release change because it changes what an existing pattern
containing a backslash matches.

## Unicode normalisation

NFC and NFD spellings of one visible name are different keys, different
permission targets and different storage rows. Same failure shape as the
newline bypass 3.14.4 closed (a rule that visibly covers a namespace does not
cover a byte-different spelling of it), not closed by it. If it is ever
addressed it is a normalisation at the same two choke points 3.14.4 used —
`_evaluate_rules` and the property/list name write path — and a migration
question for stored names.
