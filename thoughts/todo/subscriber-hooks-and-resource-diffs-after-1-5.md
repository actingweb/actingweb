# Subscribers after specification 1.5: the previous value is read apart from the write

Filed 2026-11-15 by the codex review of `spec-1-5` Phase 3. Two other items
of this file (a rebuild the poll runs told no data hook; the SDK's resource
notification sent a partial value) closed with
`thoughts/plans/2026-11-16-3-16-pre-validation-fixes.md`, Phase 2.

## What is still weak

- **The previous value is read apart from the write.** A concurrent writer
  between the read and the write can make it stale (a key added by the other
  writer and removed by this one is not reported as gone). The same race
  exists for ordinary diffs; reading the old value from the write itself
  needs a backend that returns it.
- **`notify_subscribers(resource=...)` reads the stored value apart from
  the application's write** (since the pre-validation plan): a second write
  between the application's write and its notification is sent under the
  first one's sequence, and again under its own. A subscriber ends with the
  right value; a data hook sees it twice.
