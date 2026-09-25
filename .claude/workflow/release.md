# /release addendum

- The bump rides in the release PR: `pyproject.toml` and
  `actingweb/__init__.py` must agree with each other and with the tag before
  the PR is opened. Never bump on `master` after merging.
- Tag only the merge commit on `master`, after `git pull`. Push the tag by
  name (`git push origin vX.Y.Z`); never `git push --tags`.
- A pre-release version (`aN`, `bN`, `rcN`, `.devN`) publishes to TestPyPI and
  a GitHub Release marked pre-release. When a plan calls for an `rcN` pass
  against real clients, the stable release is a second, version-only PR that
  folds the rc changelog heading into the final `vX.Y.Z` heading.
- Never run `poetry publish` by hand or `gh workflow run` the release
  workflow; the tag is the publish. Only the user dispatches it manually.
- Before tagging: CI green on **both** database backends, the Documentation
  Build green, and `CHANGELOG.rst` renamed with a new empty `Unreleased`
  above the release.
- A minor's changelog entry opens with a `.. note::` pointing at
  `docs/migration/vX.Y.rst`; confirm that file and its `index.rst` row exist.
  A patch has no migration file.
- After the tag: delete every `thoughts/todo/` file the release closed (and
  its `INDEX.md` row) and set the plan's `status: done` with its
  `verified:` link.
