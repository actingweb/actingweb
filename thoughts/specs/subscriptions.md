# Spec: Subscriptions

**Status:** partial (covers: behaviour changed since 2026-11-17)
**Reviewed:** 2026-11-17 by Greger Wedel (with the plan)
**Last changed:** 2026-11-17 by thoughts/plans/2026-11-17-3-16-pre-rc1-fixes.md
**ID prefix:** SUB

## Summary

A subscriber holds a replica of what a publisher grants it, filled by a
baseline, diffs and permission callbacks. This partial spec covers only the
fetch a permission callback makes when a grant widens.

## Permission callbacks

- **SUB-1** — When a peer grants a property, the subscriber fetches it and
  applies the baseline's rule for the answer: text that is not JSON is
  stored as text when the publisher itself answered with it, an empty body
  or `{}` leaves no value (plain or list), and a non-2xx or redirected
  answer, or one that is not the publisher's, stores nothing. [plan+test]
  `tests/test_permission_callback_fetch.py` (all four tests),
  `tests/integration/test_permission_callback_text.py::test_grant_of_a_text_property` (plans/2026-11-17-3-16-pre-rc1-fixes.md, AC-11, AC-12, AC-17)

## Not supported

- A granted text value that parses as JSON (`[1,2]`, `42`, `true`) is
  stored as what it parses to, on this path and in the baseline
  (`thoughts/todo/subscription-subscriber-fault-hardening.md`).

## Untested

- None of the above.
