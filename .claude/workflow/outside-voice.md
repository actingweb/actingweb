# outside-voice addendum

- Codex runs only outside the Claude Code sandbox (`codex exec -s read-only`
  fails to initialise inside it). Try Codex first; if it fails, be the
  fresh-context reviewer yourself and say so in the report.
- The plan's "Evaluation Notes" already list what the five evaluators found;
  do not repeat those. The brief is what they missed: storage lifecycle
  (what a fast-path delete leaves behind, what a purge does not cover, which
  backend reaps what), sequencing across changes that share a file, and
  whether the release should be split.
- Verify against both backends' code under `actingweb/db/` when a finding is
  about storage; the two differ in expired-row reads and fault returns.
- Every finding quotes `file:line` or the plan section; a finding without a
  line is a note.
