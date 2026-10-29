# Verification: vouched actors, clean-slate adoption on OAuth login, a closable factory, and SPA `prompt` (re-run after iteration 1)

**Date:** 2026-10-27
**Plan:** thoughts/plans/2026-10-26-oauth-adoption-vouching-and-open-factory.md
**Research:** thoughts/research/2026-10-26-v3.16-scope-oauth-adoption-vouching-and-spanned-list-items.md; thoughts/research/2026-10-27-adoption-reads-postgresql-fault-as-empty.md
**Branch:** release/3.16.0-oauth-adoption-vouching
**Commit:** 52abce6 (base; the whole plan and its iteration are uncommitted in the working tree)

This run covers the whole plan, plus the batch "2026-10-27, after
verification" in its Iterations section (entries 1-7). The owner also asked
for a check that the relevant docs are updated. That check is under
"Documentation".

## Automated Check Results

- **Browser QA:** not re-run. The iteration changed no rendered page: every
  visible change is a JSON response (the closed-factory 403, `GET /` JSON
  config). Those are covered by `tests/test_flask_factory_fallback.py` and
  `TestFactoryJsonConfig` in `tests/test_fastapi_template_response.py`. The
  previous run's gstack browse walk of the demo still stands for the HTML
  pages.
- **Second opinion:**
  - **outside-voice:** Codex (`codex exec -s read-only`, unsandboxed) plus a
    fresh-context Claude. Fifteen findings; all are folded into Issues Found
    below. The successor race was dropped as already listed.
  - **`/code-review high`:** ten findings, folded in.
  - **Security review (built-in):** no findings above the confidence bar. It
    noted one older weakness, out of scope: the email claim is trusted
    without the provider's `email_verified`.
  - **Docs audit:** a fresh-context agent, which the owner asked for.
- `ruff check actingweb tests`: pass, "All checks passed!"
- `ruff format --check actingweb tests`: pass, 417 files already formatted.
- `pyright actingweb tests`: pass, 0 errors, 0 warnings.
- `tests/integration/verify_groups.py`: pass, all 50 groups documented.
- **DynamoDB suite:** pass, 3995 passed, 31 skipped (parallel, `-n auto --dist loadgroup`).
  - `make test-all-parallel` could not start its containers: the sibling
    worktree `.claude/worktrees/actingweb-oss-scanner-b30766` owns the
    `actingweb-test-dynamodb` container on the same port.
  - So the target's pytest line ran directly against the running containers.
    Its `down -v` was skipped, which would have removed the other worktree's
    container.
- **PostgreSQL suite:** pass, 3886 passed, 140 skipped. Same invocation, with
  the PostgreSQL environment from the Full tier.
- **Docs build** (`sphinx-build -W`, `.claude/**` excluded locally): pass,
  "build succeeded".
- **Benchmarks** (`tests/performance -m benchmark`, run alone, DynamoDB): 17 passed.
  - They ran because the iteration touched the attribute layer.
  - Medians: attribute read 1.12 ms, attribute write 1.78 ms, actor create
    2.96 ms, actor delete 3.16 ms, trust list 4.18 ms, bulk property read
    315 ms.
  - There is no earlier run of this plan to compare against.

## Phase Verification

The phases verified last run and their findings are not repeated here. This
run reads the Iterations batch against the code.

### Iteration 1: fault-as-empty (Issues 1, 2, 3, 8) - ISSUES FOUND

**Changes verified:**
- `actingweb/oauth2.py:1761` `if store is not None and not store.loaded:` returns None before the vouching decision. Matches.
- `actingweb/attribute.py:40-57`: `InternalStore.loaded` and `mark_empty()`. Matches.
- `actingweb/actor.py` `purge_relationships`: strict reads before and after the wipe. Matches.
- `actingweb/oauth_session.py:905-930`: strict mode collects failures. It matches on PostgreSQL only (Issue A).
- `scripts/mark_actors_vouched.py:86-106`: the loaded check and the read-back. Matches, but the actor-list read is not strict (Issue C).

**Tests verified:** the five tests in `tests/test_adoption_backend_faults.py`.
Each injects PostgreSQL's fault shape at the backend seam and asserts the
sign-in returns None with the actor untouched. Meaningful.

**Deviations:**
- The fix assumed DynamoDB raises on every fault. That holds for reads, but
  not for `delete_attr` (Issue A).
- The fix also never asks whether a write to `_internal` was confirmed
  (Issue B).

### Iteration 2: unfinished replacement, concurrent successor, GSI lag (Issues 5, 6) - VERIFIED (minor issues)

**Changes verified:**
- `actor.py:517-559`: `delete -> bool`.
- `oauth2.py:1791-1800`: the tombstone resume.
- `oauth2.py:1822-1827`: fails closed on an unconfirmed delete.
- `oauth2.py:1846-1857`: successor reuse.
- The `None` filter in `Actor.create`.

**Notes:**
- `delete()` reports "no fault", not "row removed". `db/postgresql/actor.py`
  has no rowcount check, and DynamoDB returns True for a missing item. This
  is still enough for the fail-closed check.
- An UNKNOWN tombstone read on a half-wiped actor falls through to a clean in
  place that leaves the tombstone in place (Issue K).

### Iteration 3: OAuth2 clients and provider tokens (Issue 7) - ISSUES FOUND

**Changes verified:**
- `oauth2.py:1656-1685`: `_actor_client_ids` (strict) and `_delete_actor_clients`.
- The clean-path order at `:1871-1888`: rotate, revoke, purge, delete clients.
- Provider tokens cleared at `:1892-1901`.

**Checked:**
- A client whose trust cascade-deletes it during the purge is deleted again
  without error: `single_use.delete_confirmed` returns True for a row that is
  already gone (`single_use.py:216-218`). There is no lockout.
- The tests register clients without their trust row, so this cascade case is
  untested. Low risk.

**Issue:** the replace path makes the client delete non-fatal, on the grounds
that "the client rows went with the buckets". That ground does not hold when
the bucket delete faults (Issue I).

### Iteration 4: hook signature docs (Issue 4) - VERIFIED

- `hooks-reference.rst` and `apple-sign-in.rst` take `**kwargs`.
- Stale passages remain in `actor-deletion.rst`. See Documentation.

### Iteration 5: closed-factory JSON, duplicates (Issues 9, 10) - VERIFIED

- The gate checks `Content-Type` or `_wants_json()` through `get_header`.
- `SPA_PROMPT_VALUES` is imported.
- `relationship_summary` is shared by both paths.

### Iteration 6: creator rename unvouches (Issue 11) - ISSUES FOUND

- `handlers/trust.py:264-276` writes `creator_changed` after a modify that
  really changed the creator. The integration test `TestCreatorRenameUnvouches`
  asserts the marker over HTTP.
- Issues F and B: with `force_email_prop_as_creator` the marker outlives the
  change, the protocol's `trustee` handoff now unvouches, and the marker
  write is not confirmed.

### Iteration 7: `GET /` JSON config (Issue 12) - VERIFIED

- Flask and FastAPI return the handler's JSON when asked. The tests fail with
  the fix disabled, as the iteration recorded.
- The security review and the outside voice both found no leak: provider
  names and public URLs only.

**Security properties demonstrated** (contract addendum; the test that pins
each, and its assertion):
- **A vouched actor is not wiped on a read fault:**
  `TestVouchingReadFault::test_unreadable_marker_fails_closed_and_wipes_nothing`.
  It asserts `lookup_or_create_actor_by_identifier(creator) is None` and
  `row.passphrase == "own-pass"`.
- **No wipe is confirmed on a list fault:**
  `TestWipeConfirmationReadFault` (`[trusts|subscriptions]`). It asserts the
  sign-in is None and `not istore(row).auth_method`.
- **An unreadable SPA bucket fails the adoption:**
  `TestSpaRevokeReadFault`. On DynamoDB a failed delete is still not detected
  (Issue A).
- **A creator rename unvouches:** `TestCreatorRenameUnvouches` asserts the
  marker reads `"creator_changed"` over HTTP
  (`tests/integration/test_factory_squat_adoption.py:159`).

**Consumer message:** the plan has none. Nothing to quote.

**Todos:**
- The plan's own todos (`oauth-adoption-of-unvouched-actors-and-open-factory.md`,
  `spa-authorize-prompt.md`) and this iteration's two
  (`creator-rename-keeps-vouch.md`, `flask-factory-json-config.md`) are
  deleted, along with their `INDEX.md` rows.
- The deferrals are filed: `creator-uniqueness-not-enforced.md`,
  `spanned-list-items.md`, and `db-layer-get-bucket-or-empty.md` (updated).

## Documentation

The owner asked for this check. The docs cover most of the change: the
marker table lists every value the code writes, the `actor_adopted` kwargs
match `oauth2.py:1922-1936`, and `with_open_factory` is documented in seven
pages. The changelog category order is right, and `v3.16` is in the toctree
with its index row.

Gaps that would mislead a consumer, in rank order:

1. **The demo `.env.example` closes the factory** (Issue D).
2. **The backfill script cannot be run as the docs describe.**
   - It is not in the wheel: `pyproject.toml:26` packages only `actingweb`,
     while the other maintenance tools are `actingweb.maintenance` entry
     points.
   - It needs 3.16 installed: it calls `InternalStore.loaded`.
   - Yet `docs/migration/v3.16.rst` and the CHANGELOG say "run it before
     upgrading" (Issue G).
3. **The migration guide doesn't explain the script's output.**
   - `scanned/marked/skipped/pending/errors` and exit 1 are not described.
   - `pending` actors count as marked but stay unvouched.
   - The `--start-after` resume id is logged only at DEBUG
     (`mark_actors_vouched.py:118`).
4. **MCP deployments are under-warned.** `v3.16.rst`'s "Start here" and its
   table omit that a clean in place deletes registered OAuth2 clients: every
   MCP connector of an unmarked actor must reconnect. The CHANGELOG and
   `security.rst:52` do say it.
5. **The verification link now ends the session** (Issue E). Only `v3.16.rst`
   says so. These are stale:
   - `docs/guides/authentication.rst` (the Verification Flow steps, about `:1049-1056`)
   - `docs/guides/oauth-login-flow.rst:346-350`
   - `docs/guides/spa-authentication.rst` (about `:403-430`)
6. **`docs/reference/actor-deletion.rst` is stale.**
   - `:205-209` says only the HTTP path runs lifecycle hooks.
   - The billing example at `:189-200` doesn't check
     `reason == "replaced_at_adoption"`.
   - `:48` ties the tombstone to the HTTP path only.
7. **Rendering bug:** `docs/sdk/actor-interface.rst:51-57`. The new
   `auth_method` paragraph sits inside the code block, so
   `# Load by creator` / `get_by_creator(...)` render as a block quote.
   `-W` does not catch this.
8. **The CHANGELOG's definition of vouched is incomplete.**
   `CHANGELOG.rst:23-25` leaves out `creator_changed`, which `oauth2.py:1575`
   and `security.rst:52` include.

Smaller:
- `docs/guides/hooks.rst:187`: the event list lacks `actor_adopted`.
- `examples/demo/shared_hooks/protocol/lifecycle_hooks.py:10,61` says
  `actor_deleted` fires only via `DELETE`.
- `v3.16.rst:199-201` still says the second concurrent replacement fails
  closed. Since iteration 2 it reuses the successor.
- **Marker table in `authentication.rst`:**
  - the `email_verified == "false"` qualifier is shown on one row, but
    applies to all;
  - `<provider>_oauth2` is also written by a clean in place and by the MCP
    server.
- **`prompt_supported`:**
  - the CHANGELOG ADDED entry implies `GET /?format=json` carries it, which
    it does not;
  - `spa-authentication.rst:1386` names only `/oauth/spa/config`, though
    `/oauth/config` serves the same handler;
  - the example response at `:1361-1372` omits the field.
- "off by default" for `with_open_factory` reads as "the factory is off".
- **Undocumented:**
  - the status codes of a failed adoption: 502 on the callback, 500 on SPA
    authorize/token and on the verify link;
  - a closed factory still renders the `GET /` form.
- The `docs/migration/index.rst` row omits the creator-rename unvouching.
- **CHANGELOG judgment calls for the owner:**
  - two possible **Breaking:** leads: the `actor_deleted` kwargs for
    `func(actor)` hooks, and `fetch(..., strict=)` on the protocol for custom
    backends;
  - missing **Behavior change:** sentences: the factory 403s now carry a
    body, and the Flask `GET /` JSON;
  - `Actor.delete -> bool` sits under ADDED;
  - no FIXED entry for the `unique_creator` `None` filter.
- **Not in the rendered API docs:**
  - `actingweb.oauth2` (`adopt_actor`, `is_vouched_actor`, `prompt=`),
    `actingweb.oauth_session` and `actingweb.db.protocols` have no autodoc
    page;
  - the `:func:` reference at `actor.py:377` renders unlinked.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-27-oauth-adoption-vouching-and-open-factory.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. A PostgreSQL read fault makes a vouched actor look unvouched | Fixed | `oauth2.py:1761`; `TestVouchingReadFault` |
| 2. `confirmed` true when the re-read faults | Fixed | strict reads in `purge_relationships`; `TestWipeConfirmationReadFault` |
| 3. SPA revoke cannot fail | Fixed on PostgreSQL; still open on DynamoDB | `oauth_session.py:908,926`; see Issue A |
| 4. `actor_deleted` hooks to the documented signature skip replacements | Fixed (docs) | `hooks-reference.rst`, CHANGELOG **Check:**; `actor-deletion.rst` still stale |
| 5. Failed replacement cleaned in place with a tombstone | Fixed for a DELETED tombstone; UNKNOWN still falls through | `oauth2.py:1791`; Issue K |
| 6. Two successors / GSI `None` crash | GSI crash fixed; race narrowed, accepted as a known limitation | `oauth2.py:1846-1857`; `creator-uniqueness-not-enforced.md` |
| 7. Registered clients survive a clean | Fixed | `oauth2.py:1805,1888`; `TestIterationOneFindings` |
| 8. Backfill misreads faults | Fixed per actor; the actor-list read is not strict | Issue C |
| 9. Empty 403 for a form post with `Accept` JSON | Fixed | `tests/test_flask_factory_fallback.py` |
| 10. Duplications | Fixed, except the SPA pre-check (declined, reasoned in Iterations entry 5) | `relationship_summary`, `SPA_PROMPT_VALUES` |
| 11. Creator rename keeps the vouch | Fixed, with side effects | `handlers/trust.py:276`; Issue F |
| 12. Flask `GET /?format=json` served HTML | Fixed | `TestFactoryJsonConfig`, Flask fallback tests |
| 13. Error page "Possible Causes" | Accepted as-is (cosmetic, demo template) | Iterations batch note |

The previous run's Remaining Tasks:
- Issues 1-3 and Issues 4-8 were addressed as tabled above.
- The release-PR bump is still open.
- The triage outputs are still uncommitted with this work.

## Remaining Tasks

- [ ] Fix Issues A-C before release. Each one lets a sign-in report a
      completed adoption that did not happen, or lets a backfill report a
      success that did not happen (`/iterate_plan`).
- [ ] Fix Issues D-G, and the ranked Documentation items 2-8, in the same
      iteration, or file todos for them.
- [ ] Owner decisions:
  - Issue F: exempt `creator == "trustee"`? Reset the marker when
    `force_email_prop_as_creator` reverts the creator?
  - The CHANGELOG **Breaking:** leads.
- [ ] Release PR:
  - the version bump in `pyproject.toml` and `actingweb/__init__.py`;
  - the `Unreleased` rename;
  - a `.. note::` pointing at `docs/migration/v3.16.rst`.

  The owner targets "a new major release", while the tree says 3.16.0. The
  number is set in that PR.
- [ ] Commit the triage outputs with this work, as the previous run noted.

## Issues Found

### A. On DynamoDB, the strict SPA revoke cannot detect a failed delete
**Severity:** High
**Description:** `revoke_all_tokens(strict=True)` reads a True from
`delete_attr` as "gone". DynamoDB's delete swallows every exception and
answers True (`db/dynamodb/attribute.py:182-191`). A throttled delete of a
squatter's SPA refresh token therefore leaves `failures` empty, and the
adoption completes with the session alive. Issue 3 is fixed only on
PostgreSQL.
**Location:** `actingweb/oauth_session.py:908` `if not access_bucket.delete_attr(name=token):` and `:926`
**Recommendation:** use `single_use.delete_confirmed` per token, as
`client_registry.py:358-363` does for the same reason. Add a fault test that
patches the DynamoDB delete to raise.

### B. `_internal` writes are never confirmed, so the marker can silently fail to land (PostgreSQL)
**Severity:** High
**Description:** `InternalStore.__setattr__` ignores the result of
`set_attr`, and PostgreSQL answers a write fault with False. Three paths
depend on the marker landing:
- `actor.py:470` `self.store.auth_method = auth_method`: a new OAuth actor
  ends up with no marker, reads as legacy, and is cleaned at its next
  sign-in, with no error at creation.
- `oauth2.py:1902`: the clean path fires `actor_adopted` with the actor
  still unvouched. Every later sign-in purges what the legitimate user built.
- `handlers/trust.py:276`: the rename answers 204 and stays vouched, which
  reopens Issue 11.

The backfill script reads its writes back; the adoption code does not.
**Location:** `actingweb/attribute.py:77` `self.__dict__["_db"].set_attr(name=k, data=v)`
**Recommendation:** add a confirmed setter (write, then a strict read-back,
or raise) and use it for `auth_method` at all three sites. In `trust.py`,
consider writing the marker before `modify(creator=...)`.

### C. The backfill script reports success when the actor list cannot be read
**Severity:** Medium
**Description:** both backends' `DbActorList.fetch` return False on a fault.
`or []` turns that into scanned=0, errors=0, exit 0. An operator upgrades
believing the actors are marked, and every legacy actor is cleaned at its
first sign-in.
**Location:** `scripts/mark_actors_vouched.py:68` `rows = get_actor_list(config).fetch() or []`
**Recommendation:** treat a result that is not a list as fatal (exit 1).
Add a test.

### D. The demo `.env.example` closes the factory, contradicting its own comment
**Severity:** Medium
**Description:** `OPEN_FACTORY=` (empty) becomes `""` through `load_dotenv()`,
so `os.getenv("OPEN_FACTORY", "true").lower() == "true"` is False. Copying the
example, as CLAUDE.md's `### App` instructs, makes the quickstart `POST /`
answer 403.
**Location:** `examples/demo/.env.example:23`; `examples/demo/application.py:81`
**Recommendation:** write `OPEN_FACTORY=true`, or parse
`(os.getenv("OPEN_FACTORY") or "true")`.

### E. Clicking the verification link signs a free-text user out, and the form then refuses them
**Severity:** Medium
**Description:** the link runs a clean in place on the user's own
`email_unverified` actor: passphrase rotated, SPA/MCP tokens revoked,
provider tokens cleared. This is intended. But a provider with no verified
emails sends the user back to the free-text form, which answers 409 for an
existing actor. The 409 predates this change; before it, the user kept their
session after the click, and now they lose it immediately. Apart from
`v3.16.rst`, the guides don't mention it.
**Location:** `actingweb/handlers/oauth_email.py:219-229` (adoption), `:465-470` (409)
**Recommendation:** owner decision. Either let a verified `email_verified`
actor sign in through the form when the address matches the claimed session,
or document the sign-out and the re-entry path. In both cases update the
three stale guides.

### F. `creator_changed` outlives a reverted creator and fires on the protocol's `trustee` handoff
**Severity:** Medium
**Description:**
- **Reverted creator:** with `force_email_prop_as_creator` on (`Config`
  default True; `ActingWebApp` default False), `Actor.get()` sets the
  creator back to `store.email` on the next load (`actor.py:265-277`). The
  marker stays `creator_changed`, so the owner's next sign-in cleans their
  own actor.
- **`trustee` handoff:** setting `creator` to `trustee`, as the spec allows
  (`docs/protocol/actingweb-spec.rst:2289-2290`), also unvouches, and the
  backfill skips the actor.
- **Who can trigger it:** the endpoint authorizes as `POST /trust`, so an
  admin-trusted peer can cause either.

**Location:** `actingweb/handlers/trust.py:264-276`
**Recommendation:** owner decision. Exempt `creator == "trustee"`, skip the
marker when the new creator equals `store.email` under
`force_email_prop_as_creator`, or document both.

### G. The backfill script is not installable from PyPI, and "before upgrading" cannot work
**Severity:** Medium
**Description:** the script is not packaged, and it calls the 3.16-only
`InternalStore.loaded`. Against 3.15 every actor raises and is counted as an
error.
**Location:** `scripts/mark_actors_vouched.py:86`; `pyproject.toml:26`; `docs/migration/v3.16.rst` (Start here, item 1)
**Recommendation:** move it into `actingweb.maintenance` with an entry point,
or document "install 3.16, run the script before serving the first sign-in".
Also document the output (Documentation item 3).

### H. `DELETE /<id>` ignores the new `delete() -> bool`
**Severity:** Low
**Description:** on a PostgreSQL row-delete fault the handler answers 204 and
fires `actor_deleted_complete` for a live, half-wiped actor. This behaviour
predates the change; the new signal goes unused.
**Location:** `actingweb/handlers/root.py:115` `myself.delete()`; `actingweb/interface/actor_interface.py:392`
**Recommendation:** return 500 and skip the completion hook on False, or file
a todo.

### I. On the replace path, the reason for a non-fatal client delete fails when the bucket delete faults
**Severity:** Medium
**Description:** the comment says the client rows went with the buckets. But
`buckets.delete()`'s result is ignored (`actor.py:558`), and
`Buckets.delete` answers True unconditionally (`attribute.py:416-421`). If the
bucket delete and `delete_client` both fail and the row delete succeeds, the
client row and its index row both remain, still able to authenticate. The
only trace is a log line.
**Location:** `actingweb/oauth2.py:1828-1838`
**Recommendation:** confirm the client rows are gone (`delete_confirmed`). If
they are not, leave the tombstone so the next sign-in resumes, and fix the
comment.

### J. Tokens issued between the revoke and the purge survive the clean
**Severity:** Low
**Description:** the passphrase is rotated first, so this needs an MCP client
that refreshes inside the window. Its clients are deleted later, but a token
issued in the window is not revoked.
**Location:** `actingweb/oauth2.py:1874` `tokens_revoked = _revoke_all_actor_tokens(config, actor_id)`
**Recommendation:** revoke again after `_delete_actor_clients`.

### K. An UNKNOWN tombstone read cleans a half-wiped actor in place and leaves it tombstoned
**Severity:** Low
**Description:** a later DELETED read makes applications that follow the
documented guard (`actor_interface.py:202-203`) drop the actor's work.
**Location:** `actingweb/oauth2.py:1791`
**Recommendation:** when the status is UNKNOWN and the marker is absent, fail
closed; or clear the tombstone when a clean succeeds.

### L. Low-severity code findings
- `oauth2.py:1820`: `deletion.mark_actor_deleted` is redundant, because
  `delete()` writes the same tombstone first.
- `oauth2.py:1811-1812`: the replace-path summary reads are not strict. On
  PostgreSQL a fault reports nothing removed in the hook and the log.
- `oauth2.py:1821`: `actor_deleted` fires before an unconfirmed delete. A
  retry fires it again. This is documented in the plan's Learnings and the
  migration guide; accepted.
- `oauth2.py:1855`: if creating the successor raises after the old row is
  gone, `actor_adopted` never fires and the old-to-new id mapping is lost.
- `actor.py` `purge_relationships`: confirmation does not re-read the
  peer-trustee rows. The method issues about 4+N list reads where 2 would do.
- `actor.py:462-470`: `mark_empty()` runs after the `trustee_root` write,
  which drops the cached value. The comment "skip the read" is wrong in that
  case. Move `mark_empty()` up.
- `scripts/mark_actors_vouched.py:100`: `--marker factory` (or any
  unvouched value) counts as marked. Refuse values in
  `UNVOUCHED_AUTH_METHODS`.
- `oauth2.py:1833`: on the replace path, `delete_client` re-runs token and
  trust cleanup against a deleted actor. Only the index row needs removing.
- `delete()` docstring: it says "removed", but the value means "no fault".
  Neither backend checks the row count (`db/postgresql/actor.py:263`).
- Type hints are missing on the changed signatures
  `delete_peer_trustee(..., notify_peers=True)` and
  `delete_reciprocal_trust(..., notify_peers=True)`, and on the DynamoDB
  `fetch(self, actor_id, *, strict=False)`. CLAUDE.md requires hints on all
  functions.

### Note (older than this change, out of scope)
`get_email_from_user_info` and bearer auth (`auth._check_oauth2_token`) trust
the provider's `email` claim without checking `email_verified`. If a provider
ever returns an unverified address, adoption cleanup cannot remove a
squatter's creator access. Consider a todo.

## Overall Assessment

The plan and its first iteration have landed, and every automated gate is
green on both backends: DynamoDB 3995/31, PostgreSQL 3886/140, lint, types,
docs and benchmarks. Eleven of the thirteen earlier issues are fixed or
accepted, and the fault-as-empty fixes are pinned by tests that inject
PostgreSQL's fault shape.

The iteration closed PostgreSQL's "a fault reads as empty" on reads, but it
missed two of the same kind:
- on DynamoDB a failed delete reports success (Issue A);
- on PostgreSQL a failed `_internal` write is never reported (Issue B).

Either one lets a sign-in report a completed adoption that did not happen.
Fix both before merge, along with the backfill script's silent empty scan
(C), which an operator relies on before the upgrade.

The docs describe the core behaviour correctly but are not release-ready:
- the demo `.env.example` closes the factory;
- the backfill script cannot be run the way the migration guide says;
- the verification link's sign-out and the MCP client deletion are missing
  from the guides an upgrader reads;
- one code block in the SDK docs renders broken.

Issues E and F need an owner decision before the fix.

The UI was not re-exercised in a browser this run. The only visible changes
are JSON responses, and they are covered by tests.
