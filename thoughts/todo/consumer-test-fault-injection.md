# A public fault-injection helper for consumers' tests (`actingweb.testing`)

**Filed:** 2026-11-19, by `thoughts/plans/2026-11-19-emm-4-0-adoption-findings.md` (the consumer's A13).

A consumer's tests inject backend faults by patching library internals,
which is fragile across releases. This repository's tests have no shared
helper either (`tests/_adoption_helpers.py` has `seam_fault` and
`backend_fault`, per backend, patching private seams). A public
`actingweb.testing` would be new API: which seams it promises (actor,
attribute, property, trust reads and writes), how a fault is shaped
(`DbError` with a transient or permanent cause), and how it stays valid
across backend changes. Nothing the consumer patches is planned to move
between 4.0.0rc1 and 4.0.0 final, so this waits for its own design.
