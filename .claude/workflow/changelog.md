# /changelog addendum

- `CHANGELOG.rst` is RST, not Markdown: section titles are underlined
  (`Unreleased` with dashes, categories with tildes), inline code is
  double-backticked, and bullets are `- ` with continuation lines indented
  two spaces.
- Match the existing entries: multi-line prose for a consumer of the library.
  A bold first sentence names the symptom or the change, then the cause,
  then the new behaviour and what a consumer should check or do. File paths
  and symbol names are allowed when a consumer needs them to act (a module
  they import, a config option, a route); never as a substitute for saying
  what changed.
- Every consumer-visible shift gets a bold **Behavior change:** sentence
  inside its entry. A wire-shape, response-field or public-signature change
  gets a **Breaking:** lead under `CHANGED`, even when it also has a
  `SECURITY` entry explaining why.
- Guarantee wording must be exactly true. When a shorter sentence would
  over-claim, keep the longer one.
- Security fixes go under `SECURITY` with the exposure, the affected
  versions where known, and what to check in a deployment.
- Dependency floors raised for a CVE go under `SECURITY` with the CVE or
  advisory id and whether any library code path was exploitable.
- A patch release never adds or edits `docs/migration/`; the changelog
  carries its behaviour notes. A minor adds `docs/migration/vX.Y.rst`.
