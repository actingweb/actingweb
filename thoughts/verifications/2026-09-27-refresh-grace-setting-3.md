# Verification: a configurable refresh-token grace period, and client guidance for lost responses (third run, after Iterations 8–12)

**Date:** 2026-09-27
**Plan:** thoughts/plans/2026-09-27-refresh-grace-setting.md
**Research:** thoughts/research/2026-09-26-spa-refresh-reuse-after-dropped-rotation.md
**Branch:** release/3.15.0-refresh-grace
**Commit:** a25b64a, plus the uncommitted working tree: both phases and
Iterations 1–12. Nothing is committed yet.

This is the third verification today (`-3`). The first two are
`2026-09-27-refresh-grace-setting.md` and `-2.md`.

## Automated Check Results

All checks ran sequentially, one run at a time, unsandboxed, on the
working tree as it stands after Iterations 8–12.

- **Browser QA:** N/A. No phase touches anything a user sees.
- **Second opinion:**
  - Outside-voice agent, with providers codex (`codex exec -s read-only`,
    unsandboxed) and a fresh-context Claude: one medium finding (P1) and
    four low ones. It refuted two codex claims about pickling and
    `__dict__`, because the attribute did not exist before this branch.
  - Built-in `/code-review high`: findings folded in below.
  - Built-in security review, since the diff touches auth: no
    vulnerability at confidence 8 or above. At the default grace every
    branch of both ladders behaves as it does at HEAD. No request data
    reaches the grace, and no path bypasses the validating property.
- `poetry run ruff check actingweb tests`: pass.
- `poetry run ruff format --check actingweb tests`: pass (398 files).
- `poetry run pyright actingweb tests`: pass, 0 errors, 0 warnings.
- `make test-all-parallel`, DynamoDB: 3742 passed, 31 skipped, and
  **1 error**. 962 integration tests passed.
  - The error is a teardown `ReadTimeoutError` against DynamoDB Local
    (`localhost:8001`, read timeout 30 s) in
    `tests/test_hot_path_n_plus_one.py::TestPropertyStoreBulkReads::test_to_dict_is_single_bulk_read`.
    That is property storage, untouched here.
  - Re-run alone, the file gives 11 passed: a parallel isolation flake, per
    the contract.
  - Three of the day's four DynamoDB full runs had one such teardown
    timeout, each in a different test of list or property storage; see the
    Note under Issues Found.
- `make test-all-parallel`, PostgreSQL: pass. 3633 passed, 140 skipped
  (backend-specific), including 954 integration tests.
- `sphinx-build -W --keep-going ...`: build succeeded.

## Phase Verification

### Phase 1: The grace setting - VERIFIED

**Changes verified:**
- `actingweb/config.py:402-413`: `refresh_token_grace_period` is a
  property whose setter calls `validate_refresh_token_grace`.
  - `:158` sets the default through it before the kwargs loop at `:288`,
    so every write is checked: the default, the kwargs, a later
    assignment, and the builder.
  - No code in `actingweb/`, `tests/`, `examples/`, `../actingweb_mcp` or
    `../actingwebdemo` subclasses, copies, pickles or inspects `vars()` of
    `Config`, or writes the backing `_refresh_token_grace_period`. Checked
    by the outside-voice agent, and by grep here.
- `actingweb/single_use.py`:
  - `validate_refresh_token_grace` is at `:26`.
  - `refresh_token_grace` (`:46`) is documented as defence in depth for
    objects that are not a `Config`.
  - `classify_reuse` at `:65-83` treats grace as `grace > 0 and age <= grace`.
- `actingweb/constants.py`:
  - The old names are commented as defaults that the ladders do not read.
  - The redundant assert is gone.
  - `REFRESH_TOKEN_GRACE_MAX < min(both windows)` remains.
- `actingweb/interface/app.py:211-215` and `:1355-1357` write the grace to
  the Config only after a builder call, and the comment states that the
  builder wins.
- Both ladders use `classify_reuse`. The security review compared them
  branch by branch with HEAD.

**Tests verified:**
- `tests/test_refresh_grace_setting.py` covers:
  - the builder bounds and types;
  - `test_config_refuses_a_bad_value_at_construction`;
  - `test_assigning_a_bad_value_raises` (eight values, including `0.0`,
    `"0"`, `False` and `True`; it failed before Iteration 8);
  - `test_assigning_a_value_in_range_works`;
  - `test_the_ladders_clamp_a_config_that_bypasses_the_property`
    (`SimpleNamespace`);
  - `test_classify_reuse`.
  - All pass.
- `test_the_configured_grace_decides_rotation_or_theft`, in both ladder
  files, has six cases, including `grace0-same-second`. All pass.
- The older SPA tests and the MCP cleanup test seed ages from
  `config.refresh_token_grace_period`.

**Failure scenarios:** all three are now pinned:
- a bad value fails where it is set (builder, kwargs, assignment);
- a same-second reuse under grace 0 is answered as theft;
- the default path is unchanged.

The grace-0 concurrent-mint race is documented, not pinned by a test, as
the owner decided.

**Deviations from plan:** Iterations 1–12 are recorded in the plan. All
are acceptable.

### Phase 2: Docs, changelog and client guidance - ISSUES FOUND

**Changes verified:**
- The grace-0 cost (signs out a concurrent duplicate and a retry after a
  storage fault) is stated in six places.
- "Never flags" is replaced in `CHANGELOG.rst` and `security.rst`.
- `configuration.rst` states that the builder's value wins.
- The docs build passes.

**Still inexact:** P1–P6 below. All are doc wording; none is a code
defect.

**Consumer message:** unchanged, and still accurate. The consumer keeps the
default grace.

## Todo check

- The benchmark todo and its `INDEX.md` row hold only the open DynamoDB
  question.
- `token-store-fault-contract-gaps.md` is present.
- The plan closes no other todo.

## Previous Verification

**Previous:** thoughts/verifications/2026-09-27-refresh-grace-setting-2.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| N1. Grace-0 revocation races the winner's mint | Accepted by the owner (docs, not code). Wording still inexact: P1 | Iteration 9; `spa-authentication.rst:747-753` |
| N2. Grace 0 removes the store-fault retry | Fixed | the storage-fault retry is named in `app.py`, `CHANGELOG.rst`, `spa-authentication.rst`, `security.rst`, `configuration.rst`, `mcp-applications.rst` |
| N3. A non-integer falls back to the widest grace | Fixed | `config.py:402-413`; `test_assigning_a_bad_value_raises` |
| N4. The comment overstates what survives | Fixed | `app.py:211-213`; `configuration.rst:47` |
| N5. "Never flagged" contradicts the SPA guide | Partly fixed. `oauth2-setup.rst:340` missed: P2 | `CHANGELOG.rst`, `security.rst:56` |
| N6. Old constant names control nothing | Fixed (commented) | `constants.py:214-216`; `oauth2_spa.py:50-57` |
| N7. Redundant assert | Fixed | `constants.py` |
| N8. Tests seed from the old constants | Fixed | `tests/test_oauth2_spa_refresh_rotation.py`, `tests/test_mcp_refresh_rotation.py:363` |
| N9. The todo records what landed | Fixed | the todo file and `INDEX.md:50` |
| N10. The expiry-first order does not trip theft | Accepted as designed | Iteration 12 note; SPA guide "A token's own expiry comes first" |

## Remaining Tasks

- [ ] Doc wording P1–P6. These are small edits for one more
      `/iterate_plan` before the commit.
- [ ] Optional: decide P7 (clock-skew bound on the grace) and P8 (clamp
      logging). Both predate this change or are hygiene. If they are not
      picked up with P1–P6, file P7 as a todo.

## Issues Found

### P1. The grace-0 qualifier says the in-flight request "keeps" its tokens; it only may

**Severity:** Medium (security-property wording)

**Description:**
- Chain revocation deletes every refresh token with the chain id
  (`oauth_session.py:876`), and the winner mints with that same chain
  (`oauth2_spa.py:739`).
- So if the winner mints before the loser revokes, its successor is
  deleted too, and both are signed out. If it mints after, it survives.
- The docs state one outcome as certain:
  - `spa-authentication.rst:750-751` "the one that consumed it keeps the
    new tokens it is issued";
  - `CHANGELOG.rst:228`, `security.rst:56` and `app.py:584` "a request
    still being answered when the chain is revoked keeps the tokens it is
    issued".
- `mcp-applications.rst:600-603` and `configuration.rst:47` describe `0`
  with no concurrency caveat at all, although Iteration 9 says every place
  now says the same three things.
- Found by the outside-voice agent (Claude) and the code review
  independently. The previous verification's suggested wording was "may
  keep".

**Location:** as listed.

**Recommendation:**
- Say "may keep the tokens it is issued (whether it does depends on
  timing)".
- Add the caveat to `mcp-applications.rst` and `configuration.rst`.

### P2. `oauth2-setup.rst` still says a grace branch is never flagged

**Severity:** Low

**Description:** `docs/guides/oauth2-setup.rst:339-340` says "a thief
replaying inside the grace period also gets a working branch, and neither
branch is flagged afterwards". That contradicts `security.rst:56` and the
SPA guide. N5 missed this paragraph, although this diff edited it.

**Location:** `docs/guides/oauth2-setup.rst:339-340`

**Recommendation:** use the `security.rst` wording.

### P3. The SPA guide's cost sentence is circular

**Severity:** Low

**Description:** `spa-authentication.rst:738-742` reads "Reuse detection
only notices a branch that later replays one of its *own* consumed tokens,
so a copied token ... yields a branch that is flagged only if it replays
one of its own consumed tokens later". The second clause restates the
first, and the reader is not told the practical cost: both branches can
live on undetected.

**Location:** `docs/guides/spa-authentication.rst:738-742`

**Recommendation:** "..., so a copied token presented inside the grace
window and the legitimate client can both keep working branches, and
neither is flagged unless one of them later replays its own consumed
token."

### P4. The builder's `Raises:` is narrower than the check

**Severity:** Low

**Description:** `app.py:595` reads "If ``seconds`` is outside the range 0
to 60". The check also refuses `bool` and non-`int` values inside the
range.

**Location:** `actingweb/interface/app.py:595`

**Recommendation:** "If ``seconds`` is not an integer from 0 to 60 (a
``bool`` is refused)."

### P5. "Every reuse ... is answered as theft" is broader than the ladder

**Severity:** Low

**Description:**
- Under grace 0, a reuse past the token's own `expires_at`, or past the
  two-day window, is answered as expired, not theft.
- A legacy chain-less SPA token revokes only itself.
- Affected lines: `app.py:580`, `CHANGELOG.rst:223`, `security.rst:56`.

**Location:** as listed.

**Recommendation:** "every reuse inside the reuse window".

### P6. The migration guide still says "60 seconds" twice above the paragraph that makes it a default

**Severity:** Low

**Description:** `docs/migration/v3.15.rst:70` "**within 60 seconds**
rotates again" and `:83` "inside the 60 seconds". The paragraph at `:95`
qualifies 60 as the default, but these two lines read as fixed.

**Location:** `docs/migration/v3.15.rst:70,83`

**Recommendation:** add "(the default grace period)".

### P7. A negative age from clock skew counts as grace, whatever its size

**Severity:** Low (predates this change)

**Description:**
- `single_use.classify_reuse`: `if grace > 0 and age <= grace:`.
- A worker whose clock ran ahead stamps `used_at` in the future. A replay
  on another worker then has a negative age and rotates, for as long as
  the skew lasts, which may be longer than the documented 60 s ceiling.
- HEAD did the same: `time_since_use <= GRACE_PERIOD_IMMEDIATE` in the
  SPA ladder, `age <= MCP_REFRESH_TOKEN_GRACE_PERIOD` in the MCP ladder.
- Grace 0 now treats negative ages as theft.

**Location:** `actingweb/single_use.py` `classify_reuse`

**Recommendation:**
- Bound it: `-SKEW_TOLERANCE <= age <= grace`, with a tolerance of a few
  seconds.
- Or document that the ceiling assumes synchronised clocks.
- If not done now, file as a todo.

### P8. The defensive clamp logs a non-integer but clamps an out-of-range integer silently

**Severity:** Low (hygiene)

**Description:** `single_use.py:46-62` logs a WARNING for a non-integer
but clamps, say, 3600 with no log. It only runs for objects that are not
a `Config`.

**Location:** `actingweb/single_use.py:46-62`

**Recommendation:** log both, or neither.

### Note: DynamoDB Local teardown timeouts in parallel full runs

- Three of the day's four DynamoDB full runs had one teardown timeout each:
  - `test_bulk_list_update_handles.py` (lock or read timeout);
  - `test_hot_path_n_plus_one.py`, twice, in different tests.
- Each file passed alone. This is not a finding against this plan: that
  code is untouched, and the contract names parallel isolation flakes.
- It is recurring enough that the owner may want a todo; not filed here.

### Carried, accepted

- The old constant names remain importable (N6, commented).
- The builder's value wins over a later direct assignment (N4, intended
  precedence).
- The builder stamps appear in both `get_config()` and
  `_apply_runtime_changes_to_config()`. This follows the existing
  indexed-property pattern and predates this change.

## Overall Assessment

The implementation is complete and correct in code. Both phases and
Iterations 1–12 are in place:
- every write of the grace is validated;
- grace 0 treats a same-second reuse as theft;
- one classifier serves both ladders;
- the default path is identical to HEAD, as the security review confirmed
  branch by branch.

The full tier is green on PostgreSQL, and green on DynamoDB apart from one
parallel teardown timeout that passes alone.

What remains is wording. The grace-0 caveat overstates one outcome ("keeps"
where it should be "may keep") and is missing from two pages (P1, medium,
because it describes a security property). Five more doc sentences are
imprecise (P2–P6). P7 and P8 are low and optional. None blocks the
default path or the consumer, but the project's changelog rule asks for
exactly-true guarantee wording. One short `/iterate_plan` on P1–P6 should
close it; then `/commit`.
