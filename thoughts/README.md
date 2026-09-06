# thoughts/ — what goes where

One rule underpins everything here:

> **A directory is a *kind* of document. It is never a *status*.**

Kind never changes — a plan is a plan forever. Status changes constantly. Encoding
status as a location means every state change is a file move, and every file move
breaks the links pointing at it.

## The six directories

| Directory | Holds | Dated? | Written by |
| --- | --- | --- | --- |
| `research/` | What we found out — investigation, measurement, analysis | yes | `/research_codebase` |
| `plans/` | What we intend to do — phased implementation plans | yes | `/create_plan` |
| `verifications/` | Evidence a plan actually landed | yes | `/verify_implementation` |
| `reference/` | Durable knowledge — patterns, architecture, protocol flows | no | by hand |
| `todo/` | Known work not yet scheduled | no | by hand |
| `inbound/` | Reports from outside this repo, not yet triaged | no | whoever files one |

Nothing else. If a document doesn't fit one of these six, it is probably a
`research/` note.

### Dated vs undated is not cosmetic

- **Dated** (`YYYY-MM-DD-slug.md`) means *snapshot*: true as of that date, never
  edited afterwards except to correct an error. The date is when it was written.
- **Undated** (`slug.md`) means *living*: kept current, edited in place, deleted
  when it stops being true. A date in the filename would become a lie the first
  time you update it.

`research/`, `plans/` and `verifications/` are snapshots. `reference/`,
`todo/` and `inbound/` are living.

### Same slug = same thread of work

`research/2026-07-23-dynamodb-scaling-defects.md` →
`plans/2026-07-23-dynamodb-scalability.md` → `verifications/...`. Reusing the
slug across directories is how you follow a piece of work end to end. Dates may
differ (research precedes the plan); the slug should not drift.

### `inbound/` is an inbox, and an inbox is meant to be empty

`inbound/` holds reports written **outside this repository** — a consumer
project, a downstream deployment, a security evaluation elsewhere — that nobody
here has evaluated yet. It exists so a report has somewhere to land without its
author having to guess whether it is a bug, a todo, or a plan. That judgement is
ours, not theirs.

Undated filenames: a report carries its own filed-by date in the body, and the
date that matters afterwards is the date *we* triaged it, which lands in what
the triage produces.

It is the one directory with a lifecycle that ends in deletion:

```
someone drops a report in inbound/
        ↓ triage: verify the claims against the tree
    the finding is real  → todo/ (or research/, or a plan) + INDEX.md row
    the finding is wrong → say so in the reply, or write it up in research/
        ↓
delete the inbound file — the todo/research/plan is the record
```

Triage means *verify*, not *transcribe*. An external reporter reads the code
from outside and can be right about the symptom and wrong about the cause, the
blast radius, or which fix the codebase already supports. Check every claim
against the tree before filing anything, and write down what the check changed —
that delta is most of the value of doing this at all.

Carry the attribution across (who filed it, when, out of what) — the report is
deleted, so what you write is the only surviving record of where it came from.

**The normal state of this directory is empty.** A file sitting here is a
report nobody has looked at, which is exactly what the directory is for and
exactly what it should not accumulate. `inbound/README.md` stays regardless: it
is the signpost, not an item in the queue.

### `todo/` holds only what is *not* done

A todo says what is wrong, where, what it would buy, and what has to be decided
or unblocked first. It does not say what shipped, when, or in which release.
When the work lands the file is **deleted** — the plan and the verification are
the record, and they are dated, linked and immutable in a way a living file
cannot be.

The three things that creep in and should be cut on sight:

- **Closed sub-items kept for the tally** ("§1 — DONE in #130"). Delete the
  section; if it established a constraint the remaining work inherits, keep the
  *constraint*, not the announcement.
- **Decision ceremony** ("Decided 2026-08-14, owner walkthrough"). The decision
  survives as a present-tense statement of the approach; the date and the
  meeting do not.
- **Release archaeology in the index** — sections recording what each release
  closed, ledger rows for deleted files, a running log of when the list was
  reviewed. All of it is a worse copy of `plans/` and `verifications/`.

What is *not* history and should stay: provenance (which review found this,
which tree the line numbers were checked against), constraints established by
work that already landed, and the reason an item is blocked.

**Todos are identified by filename, never by a number.** Numbering a living
queue forces a choice between renumbering — which silently changes what an
older reference means — and freezing the numbers, which turns the index into a
record of what used to be there. A stale filename reference is visibly stale,
which is the failure mode you want.

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

The workflow commands maintain this themselves: `/create_plan` opens a plan at
`proposed`, `/implement_plan` moves it to `active` when work actually starts and
to `done` when the phases finish, `/verify_implementation` adds the `verified:`
back-link.

**Never leave a stalled plan `active`.** A plan whose remaining phases were never
picked up is `done` — write the unfinished remainder to `todo/` and let the plan
close. Agreed-but-blocked is `proposed`, not `active`. Otherwise the grep above
stops meaning anything, which is the only reason status lives in frontmatter.

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
        ↓ implementation starts                          (status: active)
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
- A report arrived from outside the repo → it lands in `inbound/`; triage it,
  file what survives verification, then delete the file.

**Rule of thumb:** if you'd want to read it in a year, it's `reference/`. If it
only makes sense next to a date, it's `research/`. If it's a promise, it's
`plans/` or `todo/`.
