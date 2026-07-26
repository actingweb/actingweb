# thoughts/ — what goes where

One rule underpins everything here:

> **A directory is a *kind* of document. It is never a *status*.**

Kind never changes — a plan is a plan forever. Status changes constantly. Encoding
status as a location means every state change is a file move, and every file move
breaks the links pointing at it.

## The five directories

| Directory | Holds | Dated? | Written by |
| --- | --- | --- | --- |
| `research/` | What we found out — investigation, measurement, analysis | yes | `/research_codebase` |
| `plans/` | What we intend to do — phased implementation plans | yes | `/create_plan` |
| `verifications/` | Evidence a plan actually landed | yes | `/verify_implementation` |
| `reference/` | Durable knowledge — patterns, architecture, protocol flows | no | by hand |
| `todo/` | Known work not yet scheduled | no | by hand |

Nothing else. If a document doesn't fit one of these five, it is probably a
`research/` note.

### Dated vs undated is not cosmetic

- **Dated** (`YYYY-MM-DD-slug.md`) means *snapshot*: true as of that date, never
  edited afterwards except to correct an error. The date is when it was written.
- **Undated** (`slug.md`) means *living*: kept current, edited in place, deleted
  when it stops being true. A date in the filename would become a lie the first
  time you update it.

`research/`, `plans/` and `verifications/` are snapshots. `reference/` and
`todo/` are living.

### Same slug = same thread of work

`research/2026-07-23-dynamodb-scaling-defects.md` →
`plans/2026-07-23-dynamodb-scalability.md` → `verifications/...`. Reusing the
slug across directories is how you follow a piece of work end to end. Dates may
differ (research precedes the plan); the slug should not drift.

## Status lives in the plan, not in the path

Every plan carries frontmatter:

```yaml
---
status: proposed | active | done | superseded
verified: thoughts/verifications/YYYY-MM-DD-slug.md   # when status: done
superseded_by: thoughts/plans/YYYY-MM-DD-slug.md      # when status: superseded
---
```

Other keys are fine — some older plans carry `date`, `git_commit`, `tags` from an
earlier `/create_plan`. Only `status` is required, and it must be one of the four
below.

Closed vocabulary, four values:

- **proposed** — written, not agreed. Nobody is working on it.
- **active** — being implemented right now.
- **done** — implemented. Link the verification.
- **superseded** — overtaken. Link the replacement. (Kept, not deleted: knowing
  what we decided *not* to do is worth as much as knowing what we did.)

Find work in flight with `grep -l "^status: active" thoughts/plans/*.md`.

### Don't add a `completed/` directory

It is the obvious idea and it fails four ways:

1. **It breaks links.** `/verify_implementation` writes `**Plan:**
   thoughts/plans/<slug>.md` into every verification. Move the plan and that
   link rots — silently, because nothing checks.
2. **It obscures history.** `git log thoughts/plans/x.md` stops at the move
   unless you remember `--follow`.
3. **It invites duplication.** Copying is easier than moving, so the same work
   ends up in both places and the two versions drift.
4. **"Completed" is not a kind.** Finished plans, completion reports and
   architecture docs are three different things that all feel "done", so they
   get swept into one box and stop being findable.

A plan that is finished is a plan with `status: done`. It stays where the links
point.

## Workflow

**Tool-driven loop** — the `/` commands already implement this:

```
/research_codebase      → research/YYYY-MM-DD-slug.md
/create_plan            → plans/YYYY-MM-DD-slug.md      (status: proposed)
        ↓ agreed                                         (status: active)
/implement_plan         → code
/verify_implementation  → verifications/YYYY-MM-DD-slug.md
        ↓                                                (status: done + verified:)
/iterate_plan           → amends the plan in place
```

**By hand:**

- Found something real but not doing it now → `todo/slug.md`. Delete the file
  when the work lands; don't move it, the plan and verification are the record.
- A todo grows big enough to need phases → `/create_plan` from it, and leave the
  todo as a stub pointing at the plan (or delete it — the plan supersedes it).
- Learned something durable about how the system works → `reference/slug.md`,
  updated in place forever.
- Investigated something and wrote it up → `research/`, even if no plan follows.

**Rule of thumb:** if you'd want to read it in a year, it's `reference/`. If it
only makes sense next to a date, it's `research/`. If it's a promise, it's
`plans/` or `todo/`.
