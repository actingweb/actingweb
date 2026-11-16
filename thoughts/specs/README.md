# Specs

How each capability of the library behaves today, for this repository's
developers and maintainers. Format and rules:
`~/.claude/shared/conventions.md` ("Living specs"). This repository's
sources: `.claude/workflow/create_specs.md`.

No capability has a spec yet, and the capability map has not been proposed.
`/create_specs` with no argument proposes the map and fills the table below;
`/create_specs <capability>` then writes one spec at a time. `/create_plan`
offers it when a plan touches a capability with no spec.

| Capability | File | Prefix | Status | Reviewed |
| --- | --- | --- | --- | --- |

Until a capability has a spec, its behaviour is recorded where it was before:
`docs/` (what a consumer is told), `docs/protocol/actingweb-spec.rst` (the
protocol), the wire recordings under `tests/integration/wire/` (what two
applications exchange), and the plans and verifications that changed it.
Plans written up to and including `2026-11-16-3-16-pre-validation-fixes`
carry no mergeable Spec Delta.
