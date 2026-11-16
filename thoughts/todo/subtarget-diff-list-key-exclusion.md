# A `list:`-named key inside a property passes a subtarget subscriber unfiltered

Found 2026-11-16 by the fresh-context review of
`thoughts/plans/2026-11-16-3-16-pre-validation-fixes.md`, Phase 2 (its
finding 1, rated Medium by the reviewer). Predates that plan: the property
handlers have sent a subtarget subscriber the whole stored value since
`spec-1-5`; the plan's `notify_subscribers(resource=...)` now does too.

## What is wrong

`Actor._filter` (the delivery filter, `actingweb/actor.py`, the branch for a
subtarget-level subscription without a resource) keeps every key that starts
with `list:` whole when the bare name may be read
(`if k.startswith("list:") and self._may_read(snapshot, k[5:])`), and
filters the other keys at their paths. The carve-out is for a list diff
keyed by `list:<name>`. A stored property that itself has a key named
`list:<x>` (say `settings = {"theme": "x", "list:notes": {"private": 1}}`)
with a grant that excludes a path beneath it (`settings/list:notes/private`)
is sent to a subscriber of `properties/settings` with `private` in it. A
target-level subscriber and a direct `GET` filter it.

## Why it waits

It needs an owner-stored key that starts with `list:` inside an object
property, and an exclusion beneath that key; neither consumer stores such a
key. The fix must tell a list diff from a stored value at that branch
(`whole` is a stored value, never a list diff), which the filter cannot see
today.

## What to do

Pass the filter whether the blob is a stored value, and apply the `list:`
carve-out to diffs only; a test with the shape above at subtarget level.
