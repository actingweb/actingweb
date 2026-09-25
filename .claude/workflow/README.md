# .claude/workflow/ — per-command addenda

Each file here is named after a workflow command and is read by that command
before its first step, after the `## Workflow` section of `CLAUDE.md`. Use it
for project rules that belong to one command only and would clutter
`CLAUDE.md`:

```
.claude/workflow/release.md         # "after a follow-up push, stop; the user re-triggers CI"
.claude/workflow/changelog.md       # "also add user-visible entries to frontend/src/data/whatsNew.ts"
.claude/workflow/verify_implementation.md
```

The two adapter agents read addenda too, under their own names:
`.claude/workflow/browser-qa.md` and `.claude/workflow/outside-voice.md`.

An addendum adds to or overrides the command's defaults; it cannot remove a
safety rule (never type credentials the contract does not name, never
force-push the default branch, never commit secrets). Keep each file short and
imperative. The shared commands live at `~/.claude/commands/` and cannot be
shadowed by a project command of the same name (the user-level one wins), so
this is the way to customize them.
