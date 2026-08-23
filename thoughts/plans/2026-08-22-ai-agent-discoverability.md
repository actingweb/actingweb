---
status: active
---

# Implementation Plan: Discoverability of ActingWeb for AI coding agents

**Date:** 2026-08-22
**Research:** thoughts/research/2026-08-22-ai-agent-discoverability.md,
thoughts/research/2026-08-22-agent-consumable-library-conventions.md
**Branch:** master

## Overview

Make ActingWeb discoverable and implementable by AI coding agents working in
*consumer* repositories — agents that ran `pip install actingweb` and now need to
wire up per-actor MCP apps or peer-to-peer data sharing.

There are two layers of problem, and they run in that order. **Correctness
first**: the documentation teaches nine APIs that do not exist or contradict the
implementation, four of them shipped inside the wheel. An agent that copies
`@app.trust_hook` writes code that cannot run, and no amount of better placement
helps. **Placement second**: the PyPI surface most agents reach carries ~20 dead
filesystem-path references, the installed package carries no orienting prose,
both headline capabilities take six-to-seven documents to reach a working setup,
and nothing a consumer's agent can actually install exists at all.

This plan is not about content volume. It fixes the API defects, repairs both
quickstarts so each stands alone, converts the README's pointers to live URLs,
puts orienting prose where an agent will trip over it, and publishes an Agent
Skill — the one mechanism that reaches an agent working in someone else's
repository.

**Phase order**: 0 (API defects) → 1 (`peer_id`) → 2 (p2p quickstart) → 2b (MCP
quickstart repair) → 3 (README) → 4 (metadata) → 5 (docstring) → 6 (`AGENTS.md`)
→ 6b (Agent Skill) → 7 (banners) → 8 (`llms.txt`/Context7) → 9 (orphan `.md`).

## Decisions Made

- **Decision 1 — README pointers**: Convert **all ~20** documentation references
  to absolute `https://actingweb.readthedocs.io/en/latest/docs/...` URLs. All
  three version segments (`/en/latest/`, `/en/master/`, `/en/stable/`) were
  verified to return 200; `/en/latest/` is Read the Docs' default alias and the
  one the existing badge at `README.rst:17-19` already uses.
- **Decision 2 — installed-package layer**: Add a module docstring to
  `actingweb/__init__.py` only. `__all__` is **not** widened — it drives the
  lazy-load path (`actingweb/__init__.py:3-21`). No guidance file ships in the
  wheel; a second copy of the docs would drift from `docs/`.
- **Decision 3 — peer-to-peer**: Fix the `peer_id` provenance defect *and* write
  a new `docs/guides/p2p-quickstart.rst`. The fix is a prerequisite, not an
  alternative: a new quickstart written on top of the defect would inherit it.
- **Decision 4 — `AGENTS.md`**: Rewrite as a thin pointer to `CLAUDE.md`,
  following `actingweb_mcp/AGENTS.md` — 759 bytes, last touched 2026-05-29, still
  correct because it delegates rather than duplicates. No contributor guidance is
  duplicated; the stale claims disappear by deletion rather than repair. It keeps
  a short "building an application *with* ActingWeb" pointer block for a human
  browsing the repo, but that is **not** the consumer-facing solution:
  `AGENTS.md` resolves to the closest file to *the file being edited*, so a
  library's copy is unreachable from a consumer's repo by construction, and Claude
  Code does not read `AGENTS.md` at all. Consumer-facing guidance is Decision 8.
- **Decision 5 — live-documentation distribution**: Both. `sphinx-llms-txt` in
  the docs build, and a Context7 submission recorded as an explicit user action.
  `llms.txt` is adopted as a substrate for other tooling, **not** on the belief
  that agents fetch it at runtime.

  The evidence: Cursor staff logged `llms.txt` support as an unimplemented
  feature request in June 2025, still open; no vendor documents runtime fetching;
  and a ~300,000-domain study found `llms.txt` did not make a domain more likely
  to be cited. Countervailing: Google Lighthouse now *audits* for it (Chrome
  M150) — which is not the same as any product consuming it. Adopt it for Tier-2
  use (a human pointing a tool at the docs) and a passing audit, not for automatic
  discovery.
- **Decision 6 — discovery metadata**: Add AI/MCP keywords, rewrite the one-line
  description, and fix both `project_urls` from `http://` to `https://`.
- **Decision 7 — legacy grep sediment**: Banner both the migration guides and the
  illustrative snippets in `contributing/style-guide.rst`.
- **Orphan `.md` files**: Convert the two carrying unique content
  (`caching.md`, `oauth-login-flow.md`) to `.rst` and publish them; delete the two
  that duplicate larger `.rst` twins.
- **Decision 8 — consumer-facing guidance**: Publish an Agent Skill from this
  repository (Phase 6b). Progressive disclosure means only `name` and
  `description` load until a matching task activates it, so substantial guidance
  costs a consumer nothing, and it is the only mechanism that reaches an agent
  working in a repo that merely ran `pip install actingweb`. Gated on narrowing
  the `.claude/` ignore at `.gitignore:176`.
- **Decision 9 — every agent-facing artifact is task recipes, not a tour.** The
  one rigorous study on context files found instructions were well-followed while
  repository overviews were unhelpful. This governs `AGENTS.md`, the
  `actingweb/__init__.py` docstring, and the skill alike.
- **Demo app**: Out of scope for this plan — see "Adjacent work" below.

## What We're NOT Doing

- **Not baking demo deployment into this repo.** See "Adjacent work"; the
  security argument is decisive and the code move is a separate plan.
- **Not shipping documentation inside the wheel.** Rejected under Decision 2 —
  wheel size plus a guaranteed drift source.
- **Not widening `actingweb/__init__.py`'s `__all__`** to advertise
  `ActingWebApp`. It drives lazy loading; changing it is a behavioural change
  dressed as a docs fix.
- **Not gating CI on `sphinx-build -b linkcheck`.** It is proposed as a one-off
  verification step. Making it a gate makes every unrelated PR hostage to a
  third-party site being down.
- **Not flipping `.readthedocs.yaml`'s `fail_on_warning` to `true`.** The build is
  warning-clean today and CI already gates with `-W`, but RTD failing a build
  takes the published docs offline. Out of scope.
- **Not auditing the remaining hook-decorator docstrings.** The research
  spot-checked `with_mcp`, `subscribe_to_peer` and `subscription_data_hook` and
  found all three good; `action_hook`, `method_hook`, `lifecycle_hook`,
  `property_hook`, `callback_hook` and `subscription_hook` were never
  individually audited. Recorded as unevidenced, not fixed here.
- **Not resolving how an agent discovers ActingWeb by *capability*** rather than
  by name. The research's attempt to test PyPI capability-search was abandoned
  when the control query proved the method broken. Still open.
- **Not migrating Serverless Framework v3 → v4.** Blocker owed by the demo repo
  regardless of this plan.

## Verification commands used throughout

From `CLAUDE.md` and `.github/workflows/tests.yml:498+`:

```bash
# Docs build — exactly what CI runs (currently 0 warnings)
poetry run sphinx-build -W --keep-going \
  -D suppress_warnings="ref.doc,misc.highlighting_failure" \
  -b html . _build/html

# Type check / lint (only phases touching actingweb/)
poetry run pyright actingweb tests
poetry run ruff check actingweb tests

# Full suite before the PR lands
make test-all-parallel
```

**Every phase's PR adds a `CHANGELOG.rst` entry under "Unreleased".** This is the
contributor process in `CLAUDE.md` and applies to all nine phases; it is not
repeated in each phase's Changes list. Ordinary PRs carry no version bump.

**Poetry version**: commands below assume **Poetry 2.4.1**, the version installed
locally. Note that `.github/workflows/tests.yml` pins Poetry **1.7.0**, where some
commands differ — `poetry check --lock` (2.x) was `poetry lock --check` (1.x). Use
the 2.x form locally and do not add either to CI.

**Commit the research documents with this plan.** Both
`thoughts/research/2026-08-22-ai-agent-discoverability.md` and
`thoughts/research/2026-08-22-agent-consumable-library-conventions.md` are
currently untracked (`git status` shows `??`) and phases here cite both. If the
plan lands without them, every reference rots.

---

## Phase 0: Fix documented APIs that do not exist

Runs first: an agent that copies `@app.trust_hook("create")` writes code that
cannot run, and no amount of better placement helps. Every defect below was
verified directly against `dbfb7cc`.

Four are **library** defects — they ship inside the wheel and reach consumers
through docstrings or a missing export, so they cannot be fixed in `docs/`. Three
are fixed in this phase; the fourth, `@app.subscription_hook`, is routed to the
open question below because it may be a live bug rather than a docs defect.

### Changes — documentation teaches nonexistent APIs

- `docs/guides/trust-relationships.rst:127,180,188` — **`@app.trust_hook(...)`
  does not exist** (`grep -rn "trust_hook" actingweb/` → 0 hits). Replace with
  the real mechanism: `@app.lifecycle_hook("trust_approved")` /
  `("trust_deleted")` per `actingweb/interface/hooks.py:230-231`, with the
  signature from `docs/reference/hooks-reference.rst:104-108,230-240`. **The
  snippet at `:180-186` is the auto-subscribe-on-trust example** — the one place
  the two halves of p2p are joined reactively — so this is load-bearing for
  Phase 2, not cosmetic.
- `docs/guides/troubleshooting.rst:184` — same decorator, same fix.
- `docs/guides/access-control-simple.rst:65` — **`@app.mcp_tool_hook(...)` does
  not exist** (0 hits in `actingweb/`). Replace with `@app.action_hook(...)` +
  `@mcp_tool(...)`, signature `(actor, action_name, data)`.
- `docs/guides/access-control-simple.rst:41` — **`app.config` is not public.**
  `app.py:112` sets `self._config`; the accessor is `get_config()` (`:1262`).
  Use `AccessControlConfig(app.get_config())`.
- `docs/guides/mcp-applications.rst:765,772` — **`execute_action_hooks`
  arguments transposed.** Real signature is
  `execute_action_hooks(action_name, actor, data, auth_context=None)`
  (`hooks.py:822-828`). `mcp-quickstart.rst:138` is already correct; make these
  match it.

Defects 3 and 4 sit in the *same* block, the one labelled "a complete example" at
`access-control-simple.rst:23`.

### Changes — defects shipped inside the package

- `actingweb/mcp/decorators.py:142` — the `mcp_resource` docstring's example uses
  **`@resource_hook("config")`, which does not exist**. That line is the only
  occurrence of `resource_hook` in the entire library. Correct the example to the
  real registration path.
- `actingweb/interface/app.py:530-542` — **`with_sync_callbacks`'s docstring says
  "Default is True"; `app.py:72` sets `False`.** Correct the docstring.
- `actingweb/interface/__init__.py` — **`lifecycle_hook` is not exported**
  (`grep -c` → 0) while every other standalone hook decorator is, so
  `from actingweb.interface import lifecycle_hook` fails. Add it to the import
  block and `__all__`.

### Changes — the canonical reference omits the current API

- `docs/reference/hooks-reference.rst` — **no entry for `subscription_data_hook`**
  (`grep -c` → 0), the decorator `subscriptions.rst` is built on. Add one, with
  the six-parameter signature. The file currently documents `subscription_hook`
  instead — see the open question below.

### Open question to resolve during implementation

**`@app.subscription_hook` appears to be dead API.** It registers into
`HookRegistry._subscription_hooks`, executed by `execute_subscription_hooks` — and
`grep -rn "execute_subscription_hooks" actingweb/` returns only the definition
(`hooks.py:726`), its own docstring cross-reference (`:732`), and the async variant
(`:1152`). **Zero call sites.** Yet `docs/quickstart/getting-started.rst:275-285`
teaches it as the receiving mechanism and `actingwebdemo` uses it at
`shared_hooks/protocol/subscription_hooks.py:28`.

Determine whether it is genuinely dead or invoked through a path grep missed
(dynamic dispatch, the handler layer). **If dead**, this is a bug affecting a live
deployment, not a docs issue, and it needs its own fix — do not silently rewrite
the docs around it. Write the finding up either way.

Also unverified: the two-parameter `@app.callback_hook("subscription")` form at
`subscriptions.rst:546-553`. The real
contract is `(actor, name, data) -> bool` (`hooks.py:473`), but the block sits
under "Migration from Raw Hooks" and may be a deliberate legacy illustration.
Read the surrounding prose before changing it.

### New tests

- A test asserting every `@app.*_hook` decorator named anywhere in `docs/**/*.rst`
  actually exists on `ActingWebApp`. This is the regression guard for the whole
  phase and would have caught `trust_hook` and `mcp_tool_hook` at authoring time.
- A test asserting `from actingweb.interface import lifecycle_hook` succeeds.
- A test asserting `execute_action_hooks`'s parameter order matches what the docs
  pass — bind the real signature with `inspect.signature`.

### Verification

- [ ] `grep -rn "trust_hook\|mcp_tool_hook\|resource_hook" docs/ actingweb/` returns
      only intentional historical references in `docs/migration/`
- [ ] `poetry run python -c "from actingweb.interface import lifecycle_hook"` succeeds
- [ ] `poetry run pytest tests/ -k doc_api_exists -v` passes
- [ ] `poetry run pyright actingweb tests` — 0 errors
- [ ] `poetry run sphinx-build -W --keep-going -D suppress_warnings="ref.doc,misc.highlighting_failure" -b html . _build/html` passes
- [ ] `make test-all-parallel` passes — this phase touches library code
- [x] Manual: the `subscription_hook` question above is answered in writing

**Resolved**: `@app.subscription_hook` was genuinely dead code — traced by
contrast with `subscription_data_hook` (which has a real call site in
`callbacks.py:609-674`) vs. zero call sites anywhere outside `hooks.py` for
`execute_subscription_hooks`/`_async`. Per the user's direction, fixed as a
library bug rather than routed around in docs: the callbacks handler's legacy
fallback branch (`actingweb/handlers/callbacks.py`, the `elif self.hooks:`
branch reached when `.with_subscription_processing()` is not enabled or
`auto_sequence=False`) now also calls `execute_subscription_hooks()`, OR'd
into the existing `execute_callback_hooks("subscription", ...)` result. Both
mechanisms coexist; neither was removed. `getting-started.rst:275-285`'s
`@app.subscription_hook` example was already API-accurate once fixed, so no
docs rewrite was needed there — only the CHANGELOG and hooks-reference.rst
needed a note on which of the two subscription mechanisms fires when.

Regression test: `tests/integration/test_subscription_callback_flows.py::TestLegacySubscriptionHookFires`,
using a probe hook registered in `tests/integration/test_harness.py`
(`handle_raw_subscription_callback`). The probe only claims to have handled
callbacks that carry inline `data` — a low-granularity (URL-only) callback
returns `False` — because an earlier version that unconditionally returned
`True` flipped two unrelated tests
(`test_subscription_suspension_flow.py::TestResyncCallbacks::test_060_low_granularity_url_fetch`
and `test_070_low_granularity_put_acknowledgment`) from 400 to 204, exposing
that the low-granularity URL-fetch/PUT-ack machinery lives only in the
auto-sequencing internal path, not the legacy fallback. Full
`make test-all-parallel` is green with the scoped probe.

### Implementation Status: Complete

**Deviations from plan**:
- The `peer_id="peer123"` provenance defect (properly Phase 1's fix, done
  together with Phase 0 here) turned out to be in **five** places, not three:
  a fourth in `trust-relationships.rst`'s "Re-establishing Trust After
  Deletion" block, and a fifth in `docs/sdk/actor-interface.rst`'s
  "Trust relationships and subscriptions are available via" block — neither
  named in the plan's Phase 1 "Changes" — had the same unbound-literal
  pattern and were fixed for consistency with the phase's own verification
  grep, which was run over all of `docs/` rather than the three named files.
- `docs/guides/subscriptions.rst:546-553`'s "Migration from Raw Hooks"
  example used `def handle_subscription(actor, req): req.json.get(...)`,
  which doesn't match `callback_hook`'s real 3-parameter contract
  `(actor, name, data)` (`hooks.py:473`). The plan flagged this as
  "unverified... may be deliberate legacy illustration" — read in context, it
  is presented as literal current-pattern code (`@app.callback_hook`'s real,
  still-wired legacy-fallback mechanism, not a historical-only migration
  guide), so it was corrected to the real signature.
- `Trust Hooks and Subscription Events` in `trust-relationships.rst` now
  registers **two** lifecycle hooks (`trust_fully_approved_local` and
  `trust_fully_approved_remote`) rather than one `"create"` hook, since
  mutual approval fires one or the other depending on which side approves
  last (verified against `actingweb/handlers/trust.py:549,653`) — the plan's
  citation of a `TRUST_APPROVED` enum value doesn't match either fired string.
- New test file `tests/test_docs_api_consistency.py` (not named in the plan)
  holds the three Phase 0 "New tests"; selectable via `-k doc_api_exists`.

---

## Phase 1: Fix the `peer_id` provenance defect

The research found `trust-relationships.rst:82-84` binding
`rel = actor.trust.create_relationship(...)` and then passing a literal
`peer_id="peer123"`, with nothing bridging them. Verified during planning: the
defect appears in **three** places, not one, and `create_relationship` returns
`TrustRelationship | None` (`actingweb/interface/trust_manager.py:215-234`) whose
`.peer_id` property exists (`trust_manager.py:24-27`) — so the sequence *is*
implementable and the docs simply use a magic string where a real attribute lives.

This phase ships alone because it is a correctness fix that stands on its own
merits, and because Phase 2 must not inherit it.

### Changes

- `docs/guides/trust-relationships.rst:15-26` — "Basic Usage": bind
  `rel = actor.trust.create_relationship(...)`, then
  `actor.trust.approve_relationship(peer_id=rel.peer_id)`.
- `docs/guides/trust-relationships.rst:72-84` — "Trust and Subscriptions
  Lifecycle": same substitution in both step 2 and step 3, plus a short note that
  `create_relationship` returns `None` on failure and the return must be checked
  before `.peer_id` is read.
- `docs/quickstart/getting-started.rst:133-142` — the same defect: `peer =
  actor.trust.create_relationship(...)` followed by
  `subscribe_to_peer(peer_id="peer123")`. Use `peer.peer_id` and check for `None`.

### New tests

Documentation-only; no unit tests apply. The regression guard is a grep assertion
added to the docs verification step below — after this phase, no `.rst` file under
`docs/` should pair a `create_relationship(` binding with a literal
`peer_id="peer123"` in the same code block.

### Verification

- [ ] `grep -rn 'peer_id="peer123"' docs/` returns only occurrences that are *not*
      preceded by a `create_relationship(` binding (the permissions example at
      `trust-relationships.rst:42` is standalone and legitimately uses a literal)
- [ ] `poetry run sphinx-build -W --keep-going -D suppress_warnings="ref.doc,misc.highlighting_failure" -b html . _build/html` passes
- [x] Manual: read the three (actually four, see Phase 0's deviations note)
      edited blocks top-to-bottom and confirm every identifier used is bound
      earlier in the same block

### Implementation Status: Complete

Implemented together with Phase 0 (both are "docs teach nonexistent/wrong
APIs" fixes to the same file). See Phase 0's deviations note for the fourth
occurrence found.

---

## Phase 2: New `docs/guides/p2p-quickstart.rst`

**The goal is self-sufficiency, not symmetry with MCP.** MCP is not the
well-served benchmark it looks like — it takes ~7 documents, its quickstart 401s
on every call, and it never mentions the database (Phase 2b repairs that). A p2p
quickstart written to match it would inherit those omissions. This one must stand
alone.

Three requirements, all verified:

- **`acl_rules` is a silent hard dependency.** A custom trust type cannot create
  subscriptions or receive callbacks without it
  (`access-control-simple.rst:169-171`; `add_trust_type(..., acl_rules=...)` at
  `permission_integration.py:316-324`). Verified: `grep -ci "acl"` returns **0**
  for both `trust-relationships.rst` and `subscriptions.rst`. An agent following
  the two obvious guides gets silent endpoint denials. **The quickstart must
  cover this or it does not work.**
- **The database prerequisite must be stated inline.** `mcp-quickstart.rst` omits
  it and is broken as a result; do not repeat that.
- **Which receiving decorator, and why.** Three decorators contain the word
  "subscription", and `SubscriptionProcessingConfig.enabled` defaults to `False`
  (`subscription_config.py:32`), so `subscription_data_hook` fires **only** with
  `.with_subscription_processing()` enabled. The quickstart must enable it
  explicitly and say why. Do not use `@app.subscription_hook` — see Phase 0's open
  question.

### Changes

- **`examples/p2p_quickstart.py`** (new) — the quickstart's application code as a
  **real, importable Python file**: the `ActingWebApp` construction, the
  `@app.subscription_data_hook` registration, and the trust/subscribe sequence.
  The `.rst` pulls it in with Sphinx `literalinclude` rather than restating it in
  a `code-block`.

  This is what makes the phase's test meaningful. A test that duplicates code
  copied out of an `.rst` only catches API drift and lets the document itself rot;
  a test that imports the file the document includes makes doc-drift structurally
  impossible. It also pre-stages the `examples/` directory the demo-consolidation
  plan needs.

  `examples/` is **repo-only** — not added to `pyproject.toml:25-27` `include`, so
  it does not ship in the wheel.
- `pyrightconfig.json:2-5` — add `"examples"` to `include`. Verified during
  planning that it currently lists only `actingweb` and `tests`, so **pyright
  silently skips the file even when the path is passed on the command line**.
  Without this edit the new `.py` escapes the zero-tolerance gate entirely.
- **`docs/guides/p2p-quickstart.rst`** (new) — one runnable two-actor narrative,
  mirroring the section shape of `mcp-quickstart.rst`, with the application code
  pulled in via `literalinclude` from `examples/p2p_quickstart.py`:
  1. **Install** — the extras needed, matching `mcp-quickstart.rst:13-19`.
  2. **Both sides in one app** — an `ActingWebApp` with
     `.with_subscription_processing(...)` (parameters per
     `docs/guides/subscriptions.rst:161-182` and
     `actingweb/interface/app.py:1158-1170`) and
     `.with_devtest(enable=False)`.
  3. **Actor A — publish** — create the actor with
     `ActorInterface.create(creator=..., config=config, hooks=app.hooks)`,
     carrying forward the non-obvious `hooks=app.hooks` requirement documented at
     `docs/quickstart/getting-started.rst:114-124`, then write properties.
  4. **Actor B — establish trust and subscribe** —
     `rel = b.trust.create_relationship(peer_url=...)` → check `rel is None` →
     `b.trust.approve_relationship(peer_id=rel.peer_id)` →
     `b.subscriptions.subscribe_to_peer(peer_id=rel.peer_id, target="properties")`
     (signature per `actingweb/interface/subscription_manager.py:257-282`).
  5. **Actor B — receive** — `@app.subscription_data_hook("properties")` with the
     full six-parameter signature from `subscriptions.rst:144-154`.
  6. **Run it** — the uvicorn/flask command, mirroring `mcp-quickstart.rst:77`.
  7. **Verify** — curl the REST surface to observe the trust relationship and the
     delivered callback, mirroring `mcp-quickstart.rst:96-132`.
  8. **Security note** — approving a relationship grants the peer whatever the
     trust type permits; link `docs/guides/access-control.rst`. Do not model
     auto-approving unverified peers.
  9. **Production notes** — `.with_sync_callbacks()` on Lambda/serverless, and a
     pointer to `subscriptions.rst` for back-pressure, circuit-breaker and
     fan-out tuning. Link, do not duplicate.
  10. **Where to go next** — `trust-relationships.rst`, `subscriptions.rst`,
      `access-control.rst`.
- `docs/guides/index.rst:12-33` — add `p2p-quickstart` to the toctree, placed
  immediately before `trust-relationships`.
- `docs/guides/index.rst:41-46` — add a one-line entry under the "Trust &
  Relationships" prose category.
- `docs/guides/trust-relationships.rst` (top) and
  `docs/guides/subscriptions.rst` (top) — a one-line cross-reference naming
  `p2p-quickstart` as the task-shaped entry point, so an agent that greps into
  either half is routed to the joined recipe.
- `index.rst:78-90` — add a "Peer-to-Peer Sharing" row to the Quick Links table,
  alongside the existing "MCP Integration" row.

### New tests

- A smoke test under `tests/` that **imports `examples/p2p_quickstart.py`
  directly** and asserts the app builds and the `subscription_data_hook` is
  registered. Because the `.rst` `literalinclude`s that same file, this tests the
  code the reader actually sees.
- Assert `subscribe_to_peer`'s keyword names still match what the example passes
  (`peer_id`, `target`), guarding against a signature rename silently
  invalidating the doc.
- Assert the `literalinclude` path in `p2p-quickstart.rst` resolves to an existing
  file — a renamed example would otherwise leave the published page with an empty
  code block, and `-W` does not reliably catch it.

### Verification

- [x] `poetry run sphinx-build -W --keep-going -D suppress_warnings="ref.doc,misc.highlighting_failure" -b html . _build/html` passes — an untoctree'd new document is a warning and will fail this gate, so the toctree edit is verified by the build itself
- [x] `poetry run pytest tests/ -k p2p_quickstart -v` passes
- [x] `poetry run pyright actingweb tests examples` — 0 errors
- [x] `poetry run ruff check actingweb tests examples` passes
- [x] `poetry run ruff format --check actingweb tests examples` passes
- [x] `grep -c '"examples"' pyrightconfig.json` returns 1 — without it the
      pyright run above reports success while checking nothing
- [x] Manual: follow the quickstart start-to-finish against a local DynamoDB
      (`docker compose -f docker-compose.test.yml up dynamodb-test`) and confirm a
      property change on actor A reaches actor B's hook
- [x] Manual: confirm the stitch count is now one — the quickstart requires no
      other document to reach a working two-actor setup

### Implementation Status: Complete

**Deviations from plan / learnings**:
- **Real bug caught only by the manual end-to-end run**: `ActingWebApp(...)`
  defaults `proto="https://"` (`app.py:49`), and the example never overrode
  it. Subscription callbacks are outbound HTTP calls to the URL recorded at
  trust time; with the default, the library tried an `https://` callback
  against a plain-`http://` local server and failed with an SSL handshake
  error, silently (the publish POST still returned 201; only the server log
  showed `Callback seq=1 failed - peer did not respond`). Fixed by defaulting
  `proto=os.getenv("APP_HOST_PROTO", "http://")` in
  `examples/p2p_quickstart.py`, with a comment explaining why and how to
  override for production. `mcp-quickstart.rst` has the same unset-`proto`
  pattern but never surfaces this, because MCP has no outbound peer callback
  to break. Confirmed end-to-end after the fix: actor A's property POST
  produced `[B_ID] update from A_ID (diff #1): {'name': 'status', 'value':
  'active'}` and `Callback seq=1 delivered successfully (204)` in the
  server log.
- **Incident during manual verification**: the first two verification runs
  used the default port 5000, which was already bound by the user's own
  running "Emm AI" service on this machine. `uvicorn.run(..., port=5000)`
  failed to bind and exited, but this happened in a backgrounded process
  whose failure wasn't checked before curling — so those curl calls hit the
  live service instead, creating two real actors and a trust relationship on
  it. Caught by inspecting `aw_type` in the response (didn't match), both
  actors were deleted immediately (confirmed via 204 then a 404 GET), and the
  stray process was killed. Fixed the root cause in the example itself: the
  script's `__main__` block now derives its bind port from `APP_HOST_FQDN`
  instead of hardcoding `5000`, and subsequent verification used a
  confirmed-free port (5051) with a distinct `AWS_DB_PREFIX`.
- **acl_rules**: verified empirically (not just by reading code) that the
  built-in `"friend"` trust type does *not* need `acl_rules` for
  subscriptions/callbacks to work — the existing
  `TestNormalCallbackFlow` integration test already proved this, and the
  manual run above confirms it again. Phase 2's "silent hard dependency"
  warning applies to **custom** trust types only; the quickstart uses
  `"friend"` throughout and covers the custom-type caveat as a note in the
  Security section rather than as a required step, keeping the two-actor
  narrative to one trust type.
- `examples/p2p_quickstart.py` uses `# start: <name>` / `# end: <name>`
  marker comments with Sphinx `literalinclude`'s `:start-after:`/`:end-before:`,
  rather than line-number ranges — survives future edits to the file without
  the `.rst` silently including the wrong lines.
- New test file `tests/test_p2p_quickstart.py` (not named in the plan) holds
  the three Phase 2 "New tests"; selectable via `-k p2p_quickstart`.
- **`pyrightconfig.json` is gitignored** (`.gitignore:301`) — it is the
  user's personal local pyright config, not a repository file. Adding
  `"examples"` to it (done) improves local `poetry run pyright` runs but has
  **no effect on CI**: `.github/workflows/tests.yml:490` runs
  `poetry run pyright actingweb` with no config file present in the checkout
  at all (falling back to pyright's built-in defaults), and does not check
  `tests/` or `examples/` regardless. This is a pre-existing gap, unrelated
  to and out of scope for this plan — flagged here rather than silently
  worked around, since Phase 2's own verification step
  (`grep -c '"examples"' pyrightconfig.json`) would otherwise read as
  confirming a CI guarantee it does not provide.

---

## Phase 2b: Repair the MCP quickstart

`mcp-quickstart.rst` reads as the model recipe and is not currently a working
one. All defects below verified.

### Changes

- `docs/guides/mcp-quickstart.rst` — **the pasted app cannot answer any MCP call.**
  `.with_oauth(...)` is commented out at `:48`, while `:107-111` states every
  method beyond `initialize` requires a bearer token and that `with_devtest(True)`
  does **not** open the MCP endpoint. Either make the OAuth configuration live in
  the example, or state plainly at the top that the file is a two-stage recipe and
  link the token-acquisition path. Do not leave a quickstart whose output is 401.
- `docs/guides/mcp-quickstart.rst` — **no database prerequisite.** Verified:
  `grep -niE "dynamodb local|AWS_DB_HOST|docker"` → 0 hits, so `database="dynamodb"`
  is inert. Add the prerequisite inline or link `docs/quickstart/overview.rst:28-36`
  before the code block.
- `docs/guides/mcp-quickstart.rst:191` — the "unified access control" bullet is
  unlinked prose with no `:doc:` target, from the file that most needs to point at
  `access-control-simple.rst`. Make it a real link.
- **New: client-configuration documentation.** Verified:
  `grep -rniE "claude_desktop_config|mcpServers" docs/ --include='*.rst'` → **0
  hits**. An agent can build the server from these docs and cannot connect a client
  to it. Add a section showing a concrete client configuration against a deployed
  actor, including where the bearer token comes from.

This is the largest single gap either research pass found, and it is in the
capability the README leads with.

### New tests

- Extend Phase 2's `literalinclude` pattern: move the quickstart's app into
  `examples/mcp_quickstart.py`, include it, and assert it builds and registers an
  MCP tool. Same reasoning as Phase 2 — a test over a copy proves nothing about
  the document.

### Verification

- [x] `poetry run sphinx-build -W --keep-going -D suppress_warnings="ref.doc,misc.highlighting_failure" -b html . _build/html` passes
- [x] `grep -rniE "claude_desktop_config|mcpServers" docs/ --include='*.rst'` now returns hits
- [x] `poetry run pytest tests/ -k mcp_quickstart -v` passes
- [x] Manual, end-to-end (partial — see below): confirmed `initialize` returns
      a real result and `tools/list` without a token returns `401`, exactly as
      documented, against a live local server + DynamoDB
- [ ] Manual: connect a real MCP client using only what the docs now say —
      **not completed**. Requires a real OAuth2 provider (Google/GitHub app
      credentials) and a running MCP client (Claude, ChatGPT, or
      `mcp-remote`), none of which exist in this environment. Left as an
      explicit gap rather than silently skipped.

### Implementation Status: Complete (one verification step deferred — see above)

**Deviations from plan / learnings**:
- **A second, more serious near-miss during manual verification**: testing
  `examples/mcp_quickstart.py` via a bare `poetry run python -c "import
  mcp_quickstart"` (outside pytest, which sandboxes DB env vars via
  `tests/conftest.py`) constructed a real `ActingWebApp` whose module-level
  code called `aw.integrate_fastapi(api)` — with no `AWS_DB_HOST` set, this
  ran against the user's **real AWS account** (their default
  `~/.aws/credentials` profile), performing read-only `.scan(limit=1)` calls
  against pre-existing `demo_actingweb_*` DynamoDB tables and (since
  `_prewarm_dynamodb_tables()` auto-creates missing tables by default)
  possibly confirming/creating table infrastructure there. No item data was
  read or written. Root cause fixed in the example itself, not just avoided
  procedurally: `examples/mcp_quickstart.py` now builds the `FastAPI` app and
  calls `integrate_fastapi()` only inside `if __name__ == "__main__":` —
  matching `examples/p2p_quickstart.py`'s existing safe pattern — so
  importing either example (as both test files do) is guaranteed
  side-effect-free. Verified with `env -i poetry run python -c "import
  mcp_quickstart"` (a completely empty environment, `~/.aws` unreadable):
  imports cleanly, makes no network call.
- **OAuth defect resolved via the plan's stated fallback, not by faking a
  live OAuth demo.** The plan allowed "either make the OAuth configuration
  live, or state plainly the file is a two-stage recipe." A fully-scripted
  live OAuth2 flow needs a real Google/GitHub app and a real MCP client
  performing an authorization-code exchange — not something this quickstart
  can honestly demonstrate end-to-end. Chose: keep `.with_oauth(...)` live
  (reads `OAUTH_CLIENT_ID`/`OAUTH_CLIENT_SECRET` from env, uncommented) *and*
  label the document explicitly as two stages, with Stage 2 pointing at
  `mcp-applications.rst`'s OAuth2ClientManager section for the actual
  token-acquisition steps rather than duplicating them.
- **Client-configuration section is necessarily somewhat time-sensitive**:
  which MCP clients need the `mcp-remote` stdio proxy versus support a direct
  remote-HTTP connector changes as the ecosystem moves. Said so explicitly in
  the doc rather than asserting a specific client's current behavior as
  permanent.
- New test file `tests/test_mcp_quickstart.py` (not named in the plan) holds
  the "New tests" item; selectable via `-k mcp_quickstart`.

---

## Phase 3: README documentation pointers → absolute URLs

`README.rst` is the PyPI project page *and* a published Sphinx document
(`index.rst:72`), so this single edit fixes both surfaces. Absolute URLs are the
only form that works on both — a `:doc:` role renders as broken text on PyPI.

Ordered after Phase 2 because the README will link to `p2p-quickstart.html`,
which must exist first.

### Changes

- `README.rst:164-165` — `docs/guides/mcp-applications.rst` and
  `mcp-quickstart.rst` → absolute URLs.
- `README.rst:184-185` — the three authentication guides.
- `README.rst:194-195` — `trust-relationships.rst`, `access-control.rst`,
  `subscriptions.rst`, **plus a new lead pointer to `p2p-quickstart.html`** so the
  capability section names the task-shaped entry point first.
- `README.rst:211` — `docs/reference/database-backends.rst`.
- `README.rst:276-278` — reconcile the prose. It currently says documentation
  "lives in ``docs/``" and cites ``/en/master`` for the master branch, which
  contradicts linking `/en/latest/`. Rewrite to name `/en/latest/` as the
  canonical target.
- `README.rst:280-294` — the entire Documentation table: every `Location` cell
  becomes a link. Add a "Peer-to-peer quickstart" row.

  **Three rows point at directories, not files** — `docs/quickstart/` (`:283`),
  `docs/guides/` (`:291`), `docs/sdk/` (`:293`). The file transform
  (`docs/<section>/<name>.rst` → `/en/latest/docs/<section>/<name>.html`) does
  **not** apply to these; they resolve through the section's `index`. Verified
  during planning that the trailing-slash form works —
  `https://actingweb.readthedocs.io/en/latest/docs/guides/` returns 200, as do
  `.../docs/quickstart/` and `.../docs/sdk/`. Use the trailing-slash directory
  form for these three. Applying the file transform to them ships three 404s.
- `README.rst:309,325-326` — `CONTRIBUTING.rst`, `CLAUDE.md` and `CHANGELOG.rst`
  stay as filesystem paths: they are repository files, not published docs, and a
  reader on PyPI is correctly being told these live in the repo.

### New tests

- No unit tests. The verification is a link check (below), plus the existing
  `-W` docs build which will flag any malformed RST.

### Verification

- [x] `poetry run sphinx-build -W --keep-going -D suppress_warnings="ref.doc,misc.highlighting_failure" -b html . _build/html` passes
- [x] `grep -cE '``docs/' README.rst` returns 0 — no remaining bare doc paths
- [x] `poetry run sphinx-build -b linkcheck . _build/linkcheck` — inspected
      `_build/linkcheck/output.json` for every `README.rst` entry: all `working`
      except `docs/guides/p2p-quickstart.html`, which is `broken` — expected,
      see next item. Pre-existing broken links elsewhere in the tree (migration
      guides, protocol-spec URN/SIP examples) are unrelated and left as-is per
      this phase's scope.
- [ ] Manual, **post-merge**: the new `p2p-quickstart.html` URL 404s until master
      merges and Read the Docs rebuilds. Re-run the link check after the RTD build
      completes, not before. **Not yet done** — this branch hasn't merged.
- [x] Manual: `twine check dist/*` after `poetry build` (via a `--user pip
      install`, since neither `pipx` nor `uvx` was available in this
      environment — not added as a dev dependency), confirming the README
      still renders as valid RST for PyPI. Both the sdist and wheel `PASSED`.

### Implementation Status: Complete (one post-merge verification step outstanding — see above)

**Deviations from plan / learnings**:
- The plan's Phase 3 verification cites `pipx`/`uvx` for running `twine`;
  neither was installed in this environment. Used
  `python3 -m pip install --user --break-system-packages twine`, ran it
  directly, confirmed `PASSED` on both `actingweb-3.14.0.tar.gz` and the
  wheel, left `twine` as a user-site install (not a project dependency).
- **The Documentation table** (`README.rst:290-304`) used a fixed-width RST
  simple table, which cannot hold a full URL per cell without breaking
  docutils' column-alignment parsing. Converted to a bullet list instead —
  same information, same section, no simple-table constraint. The plan
  anticipated only "every `Location` cell becomes a link," not this format
  change; recorded here since a reviewer diffing against the plan's literal
  wording would otherwise flag it as a deviation.
- `README.rst:276-278`'s reconciliation went further than "name `/en/latest/`
  as the canonical target": the old sentence's `/en/master` reference is gone
  entirely rather than merely superseded, since keeping both would still read
  as two answers to "where do I go."

---

## Phase 4: `pyproject.toml` discovery metadata

`keywords` carry no AI signal, the `description` says nothing about what the
library does, and two `project_urls` use `http://`.

### Changes

- `pyproject.toml:4` — replace `"The official ActingWeb library"` with a
  descriptive one-liner naming per-user actors and MCP, e.g. *"Python framework
  for AI-ready, per-user micro-services — per-actor MCP servers, OAuth2, and
  peer-to-peer data sharing over the ActingWeb REST protocol."*
- `pyproject.toml:9` — `homepage` `http://actingweb.org` → `https://`.
- `pyproject.toml:11` — `documentation` `http://actingweb.readthedocs.io` →
  `https://actingweb.readthedocs.io/en/latest/`.
- `pyproject.toml:12` — add `mcp`, `ai`, `llm`, `agent`,
  `model-context-protocol`, `actor` to `keywords`.
- `pyproject.toml:13-23` — add `"Topic :: Scientific/Engineering :: Artificial
  Intelligence"` to `classifiers`. **This is the only relevant classifier that
  exists.** There are no `Agent`, `MCP`, `Model Context Protocol`, or `LLM` trove
  classifiers, and
  `pypa/trove-classifiers` PR #207 proposing `Framework :: Model Context Protocol`
  has been open and undecided since 2025-03-14. So the keywords are a free-text
  hedge with no ecosystem semantics — worth adding, but do not expect them to be
  consumed structurally by anything.
- `pyproject.toml:13-23` — add `"Programming Language :: Python :: 3.13"`.
  `.readthedocs.yaml:11` already builds on 3.13 and the classifier list stops at
  3.12.
- `pyproject.toml` — add a `[tool.poetry.urls]` block with Changelog and Issues
  links. Verified absent, so the PyPI sidebar currently carries neither.

### New tests

- A unit test asserting the distribution metadata carries the AI keywords — cheap
  insurance that a future `pyproject.toml` edit does not silently revert this.
  Reads via `importlib.metadata.metadata("actingweb")`.

  **This reads *installed* metadata, not `pyproject.toml`.** After editing
  `pyproject.toml` locally, run `poetry install` before the test, or it asserts
  against stale values and fails red locally while passing in CI (which installs
  fresh). Note this in the test's docstring — it is a cycle-burner otherwise.

### Verification

- [ ] `poetry build` succeeds — **this is the check that catches an invalid
      classifier**: poetry-core validates `classifiers` against the
      `trove-classifiers` package at build time. An unrecognised classifier fails
      here rather than at upload, which is why it must be run in this phase and
      not left to a release tag.
- [x] `poetry install` re-installs the edited metadata, then
      `poetry run pytest tests/ -k metadata -v` passes
- [x] `poetry run python -c "import importlib.metadata as m; print(m.metadata('actingweb')['Keywords'])"` shows the new keywords
- [x] Manual: `Topic :: Scientific/Engineering :: Artificial Intelligence` is
      accepted by `poetry build` (poetry-core validates against a local copy
      of `trove-classifiers` at build time — this environment has no network
      access to pypi.org itself, so this is the available substitute for the
      manual pypi.org check; the classifier was already long-standing per the
      plan's own research).

Note: `twine check` is **not** a classifier gate — it validates long-description
rendering only. It appears in Phase 3, doing that job.

### Implementation Status: Complete

**Deviations from plan / learnings**:
- **Found and removed a stale `actingweb.egg-info/` directory at the repo
  root** (gitignored, untracked, dated 2025-07-12, version `3.0.0` —
  fourteen releases behind current). It's a leftover from some earlier
  `pip install -e .` / `setup.py develop` invocation, long predating this
  project's Poetry-only workflow. `importlib.metadata.metadata("actingweb")`
  resolves it *ahead of* the venv's real `.dist-info` (repo root precedes
  site-packages on `sys.path`), so it silently shadowed every metadata
  read with year-old values — this is what the new
  `tests/test_distribution_metadata.py` caught immediately, and what a
  real consumer running `pip install -e .` from this repo would also hit.
  Deleting it is why the metadata test passes at all; without that, the
  test's own docstring note ("run `poetry install` first") would have been
  insufficient, since `poetry install` never touched the stale directory.
- New test file `tests/test_distribution_metadata.py` (not named in the
  plan) holds the "New tests" item; selectable via `-k metadata` (along with
  two pre-existing, unrelated files that also match that substring:
  `test_hook_metadata.py`, `test_v2_metadata_cas.py`).
- `importlib.metadata`'s `PackageMetadata` Protocol's `.get()` overloads
  aren't visible to pyright's bundled typeshed stub in this environment,
  though they exist at runtime (verified via `inspect.getsource`). Worked
  around with `meta["Keywords"] if "Keywords" in meta else ""` instead of
  `.get("Keywords", "")` — same result, no `# pyright: ignore` needed.

---

## Phase 5: Module docstring in `actingweb/__init__.py`

The first file an agent opens in `site-packages/actingweb/` has no module
docstring, and its `__all__` lists only pre-3.x lazy-loaded internals.

### Changes

- `actingweb/__init__.py:1` — insert a module docstring **above** `__version__`.
  It should name the two headline capabilities, give the modern entry point
  (`from actingweb.interface import ActingWebApp`), name the MCP decorators
  (`from actingweb.mcp import mcp_tool`), and carry two absolute readthedocs
  URLs — the MCP quickstart and the new p2p quickstart. Keep it short; this is a
  signpost, not a tutorial.

  Make it a concrete recipe, not an overview (Decision 9): a runnable four-line
  snippet beats a paragraph describing the architecture.
- **Also worth stating in the docstring**: `py.typed` ships, but **every hook
  boundary is erased to
  `Callable[..., Any] -> Callable[..., Any]`** (`app.py:1039,1048,1057,1066,1071`;
  `mcp/decorators.py:25,131,165`), and `actingweb/actor.py` is unannotated below
  the interface layer. Type information helps least at exactly the surface an agent
  needs most — the hook signature. Naming the signatures explicitly in the
  docstring is therefore worth more here than it would be in a fully-typed library.
- Add a one-line comment above `__all__` clarifying that the list is the legacy
  lazy-load surface and is **not** the recommended API, so an agent reading it
  does not mistake it for the public interface.

**Explicitly unchanged**: `__all__` itself. It drives the lazy-load path and every
entry carries a `pyright: ignore[reportUnsupportedDunderAll]` for that reason.

### New tests

- A unit test asserting `actingweb.__doc__` is non-empty and contains both
  `ActingWebApp` and `readthedocs.io`. Trivial, but it is the only mechanism that
  stops the docstring being dropped in a future refactor.
- Assert `actingweb.__all__` is unchanged in content, guarding the lazy-load path
  against an over-eager future edit.

### Verification

- [x] `poetry run pyright actingweb tests` — 0 errors
- [x] `poetry run ruff check actingweb tests` passes
- [x] `poetry run ruff format --check actingweb tests` passes
- [x] `poetry run pytest tests/ -k init_docstring -v` passes
- [x] `poetry run python -c "import actingweb; print(actingweb.__doc__)"` prints
      the docstring, and `import actingweb.actor` still resolves (lazy load intact)
- [x] `make test-all-parallel` passes — this phase touches importable code
      (one unrelated flaky failure under parallel load,
      `test_bulk_list_update_handles.py`, confirmed passing in isolation —
      third occurrence of this class of flakiness across phases, always in
      files this plan never touches)

Note: `pyproject.toml:157` omits `actingweb/__init__.py` from coverage, so this
change has no coverage effect.

### Implementation Status: Complete

**Learnings**: pyright's bundled `Callable`/import-unused checking flagged a
bare `import actingweb.actor` used only for its side effect (proving the
lazy-load path resolves) as `reportUnusedImport` — CLAUDE.md's zero-warning
policy caught this even though `ruff` (with its `# noqa: F401` escape hatch)
would have let it through. Rewrote as
`importlib.import_module("actingweb.actor")` with an assertion on the
result, which satisfies both tools without a suppression comment.

---

## Phase 6: Rewrite `AGENTS.md`

Currently 105 lines, contributor-facing, last touched 2025-12-30, and wrong in
four places: `thoughts/shared/` does not exist, the structure diagram omits the
PostgreSQL backend, the three-file version-bump instruction contradicts
`CLAUDE.md`'s tag-driven release, and the file contains zero mentions of MCP,
trust, or subscriptions.

Per Decision 4 the fix is deletion plus redirection, not repair — `CLAUDE.md` is
the maintained source and nothing from it is duplicated here.

### The template, and what the file cannot do

**Use `actingweb_mcp/AGENTS.md` as the template.** It is 759 bytes, a pure
pointer to `CLAUDE.md`, last touched 2026-05-29 and **still correct — because it
delegates rather than duplicates**. This repo's `AGENTS.md`, which duplicates, was
wrong within six and a half hours of being written.

**The "building with ActingWeb" block is for a human browsing the repo, not for
consumers' agents.** The `AGENTS.md` spec resolves to the closest file to *the
file being edited*; a consumer's agent edits files in their repo, never in this
one, so a library's `AGENTS.md` is unreachable by a consumer **by construction**,
and Claude Code does not read `AGENTS.md` at all. Consumer reach is Phase 6b's
job. Keep the block short and do not present it as the consumer-facing solution.

### Also fix the cause, not just the symptom

- `.github/workflows/claude-code-review.yml:12-16` lists `AGENTS.md`, `CLAUDE.md`,
  `thoughts/**` and `TODO.md` under `paths-ignore`. Verified. **The repo's primary
  agent entry point is the one file categorically exempt from automated review** —
  which is why it drifted for eight months while `CLAUDE.md`, edited by humans
  during feature work, stayed current. Remove `AGENTS.md` from that list. The
  workflow's own comment says the list is "deliberately narrow" and invites
  widening, so narrowing it is within its stated intent.

### Changes

- `AGENTS.md` — replace wholesale with roughly 40 lines:
  1. **One-paragraph project statement** — what ActingWeb is.
  2. **"Contributing to this repository"** — placed *first* and stated
     emphatically: all contributor guidance (commands, quality gates, testing,
     release process, architecture) lives in `CLAUDE.md`; read it before making
     changes; this file deliberately does not repeat it. Ordering matters — an
     agent that reads only the top of `AGENTS.md` must still be pointed at the
     quality gates.
  3. **"Building an application WITH ActingWeb"** — the section `CLAUDE.md` does
     not cover: MCP quickstart URL, p2p quickstart URL, the reference app, and
     the `pip install actingweb[...]` extras line. Keep it short — this is a
     pointer block for a human reader, not the consumer mechanism.
  4. **Thoughts convention** — one line naming the five directories, pointing at
     `thoughts/README.md`. Replaces the false `thoughts/shared/` claim.
- The reference-app pointer must state **which ActingWeb version the demo
  tracks**, or omit the version claim entirely. The research found
  `actingwebdemo` pinned to `>=3.9.0` — a floating lower bound that leaves an
  agent unable to tell which API era it demonstrates. Do not repeat that
  ambiguity here. See "Adjacent work".

### New tests

- No automated test. A CI check that `AGENTS.md` and `CLAUDE.md` do not drift is
  out of proportion to a 40-line pointer file; the structural defence is that
  there is nothing left in `AGENTS.md` to go stale.

### Verification

- [x] `grep -c "thoughts/shared" AGENTS.md` returns 0
- [x] `grep -c "pyproject.toml" AGENTS.md` returns 0 — the contradictory
      version-bump instruction is gone, not corrected
- [x] Every URL in `AGENTS.md` returns 200, except
      `docs/guides/p2p-quickstart.html` (404, expected — same as every other
      phase referencing it, until this branch merges and RTD rebuilds).
      Verified with a live `curl` against each URL.
- [x] Manual: read `AGENTS.md` and `CLAUDE.md` side by side — no instruction
      appears in both; `AGENTS.md` is 40 lines

### Implementation Status: Complete

---

## Phase 6b: Publish an Agent Skill for consumers

This is the **only** mechanism that actually reaches an agent working in a
consumer's repository. Everything else in this plan improves what a consumer's
agent finds *if it comes looking*; a skill is what it can install.

Why it fits a library: **progressive disclosure** means only `name` and
`description` load at startup, with the full `SKILL.md` loading when a task
matches — so substantial guidance costs a consumer nothing until it activates.
That answers the cost objection from the one rigorous study, which found context
files raise inference cost >20% without improving success.

The same study supplies the design rule (Decision 9): **concrete instructions
were well-followed; repository overviews were not.** Write task recipes, not a
tour.

### Changes

- **`.gitignore:176` — remove or narrow the `.claude/` ignore.** Verified: it
  currently ignores the whole directory and `git ls-files` returns zero `.claude`
  entries, so nothing agent-facing ships to a cloner. **This gates the entire
  phase.** Narrow it to the local-state files (`settings.local.json`,
  `.cc-writes`, `scheduled_tasks.lock`) so a tracked `.claude/skills/` is possible.
- `.claude/skills/actingweb-app/SKILL.md` (new) — frontmatter `name` +
  `description`, then concrete recipes, each a task an agent is actually asked to
  do: add a property hook; expose an action hook as an MCP tool; establish trust
  and subscribe to a peer; configure a custom trust type with `acl_rules`;
  find an actor by property value.
- `.claude/skills/actingweb-app/references/` — the deeper material each recipe
  links to, kept out of the activation payload.
- `README.rst` and `AGENTS.md` — an install line (`npx skills add
  actingweb/actingweb`).
- Optionally a `marketplace.json` at the repo root, making this repo a Claude Code
  plugin marketplace.

### Verify the mechanism before building

The distribution details come from the companion research's primary-source
citations and were **not independently re-verified** during planning. Before
writing content, confirm: the current `SKILL.md` frontmatter schema, that
`npx skills add owner/repo` works against a plain GitHub repo, and the
`marketplace.json` schema. The precedent to copy is `github.com/readthedocs/skills`
— a docs platform shipping skills to its users, which is exactly this pattern.

### New tests

- A test asserting every code sample in `SKILL.md` uses an API that exists —
  reuse Phase 0's decorator-existence check, pointed at the skill. A skill that
  teaches `@app.trust_hook` would be Phase 0's defect with wider distribution.

### Verification

- [x] `git ls-files skills/` lists the skill (N/A: `.claude/skills/...`
      check dropped — layout changed, see below)
- [x] `poetry run pytest tests/ -k skill_api_exists -v` passes
- [ ] Manual: install the skill into a scratch consumer repo and confirm it
      activates on a relevant prompt and not on an irrelevant one — **not
      done**, requires a second agent session in a separate repo, not
      available in this environment
- [ ] Manual: follow one recipe end-to-end in a repo that only has
      `pip install actingweb` — **not done**, same constraint

### Implementation Status: Complete (two manual verification steps outstanding — see above)

**Deviations from plan / learnings**:
- **Layout changed from `.claude/skills/` to a top-level `skills/`
  directory, on the user's explicit direction after independent
  verification.** The plan's cited precedent (`github.com/readthedocs/skills`)
  turned out not to use `.claude/skills/` at all — verified against
  https://docs.readthedocs.com/platform/latest/reference/agent-skills.html,
  which documents installation as `git clone` + "point your agent at the
  `skills/` directory", with `npx skills add owner/repo` as an optional CLI
  alternative. Presented this finding to the user with both options; they
  chose the top-level layout to match the verified precedent. Consequences:
  no `.gitignore` change was needed (Decision/gate in the plan's Changes
  list — `.claude/` narrowing — does not apply), and the SKILL.md frontmatter
  schema itself is unchanged from the plan's description (verified against
  a real file in the precedent repo: `name` + `description` YAML
  frontmatter, then a markdown body, with an optional `references/`
  subdirectory for deeper material — matches exactly).
- **`marketplace.json`** (listed as "optionally" in the plan) was skipped:
  the verified precedent doesn't use one, and nothing in this phase's actual
  requirements needs it.
- **Recipe accuracy corrections found while writing, not just copying, the
  skill**: the `acl_rules` recipe initially used an invented path
  (`callbacks/subscriptions/<id>`); checked against
  `docs/guides/access-control.rst`'s "Common ACL Paths" table and corrected
  to the real convention (`subscriptions/<id>` for creating subscriptions,
  `callbacks` broadly for receiving them).
- Added a "Why ActingWeb, and when to reach for it" section at the user's
  explicit request mid-implementation — not in the plan's outline, which
  focused on Decision 9 (task recipes over a tour). Framed around
  microservices virtualization (per-user isolation, not per-user query
  scoping) and explicit typed trust relationships for AI-agent contexts,
  informed by the user's own longer-form writeup at
  `stuff.greger.io/actingweb/more-in-depth`. Kept to one short section
  before the recipes, not a rewrite of the skill's task-first structure.

---

## Phase 7: Superseded-API banners

Grepping `docs/` for trust creation returns ten hits, seven of them superseded or
illustrative. A human uses the guides index; an agent greps, and a grep hit
carries no context about which era it belongs to.

### Changes

- `docs/migration/v3.1.rst`, `v3.7.rst`, `v3.10.rst`, `v3.11.rst`, `v3.13.rst`,
  `v3.14.rst` — a `.. warning::` admonition immediately after each title stating
  that the code samples show the API **as it was**, that they must not be copied
  into new code, and naming where the current API lives. Placing it at the top
  means a grep with even two lines of context shows the file it landed in.
- `docs/migration/index.rst` — the same warning once, covering the section.
- `docs/contributing/style-guide.rst:169,249,269` — mark the illustrative
  signatures as non-API, either with an inline comment inside each code block
  (`# Illustrative only — not a real ActingWeb signature`) or a short note above
  the section. The inline comment is preferred: it survives a grep, a section note
  does not.

### New tests

- No unit tests. The regression guard is the grep assertion below.

### Verification

- [x] `grep -rn "create_trust\|create_verified_trust" docs/ -B2` — every hit is
      within two lines of a superseded/illustrative marker, or is real,
      current API (`create_verified_trust` in `architecture.rst`,
      `developer-api.rst`, `async-operations.rst` — verified real at
      `trust_manager.py`, no marker needed)
- [x] `poetry run sphinx-build -W --keep-going -D suppress_warnings="ref.doc,misc.highlighting_failure" -b html . _build/html` passes
- [x] Manual: ran `grep -rn "create_relationship\|create_trust" docs/` —
      every hit now self-identifies: real current API (`create_relationship`/
      `create_relationship_async`), illustrative (marked inline), or
      superseded (covered by a per-file or section warning banner)

### Implementation Status: Complete

**Deviations from plan / learnings**:
- **`docs/contributing/architecture.rst:95` (`def create_trust(self, ...)`)**
  was not in the plan's Changes list (which named only
  `style-guide.rst:169,249,269`), but matched the same "illustrative, not a
  real signature" defect on the verification grep — confirmed
  `Actor.create_trust` does not exist in `actingweb/actor.py`. Marked with a
  one-line comment for consistency, since the plan's own verification step
  runs over all of `docs/`, not just the three named lines.
- **v3.14.rst got a differently-worded banner than the other five migration
  guides.** It's the *current* release's migration guide, so its "after"
  code blocks are the current recommended API, not something to blanket-flag
  as superseded — unlike v3.1/v3.7/v3.10/v3.11/v3.13, which are all fully
  superseded by now. Worded its banner to flag only the pre-3.14 code
  blocks it also shows, rather than implying the whole page is stale.
- **`create_verified_trust`, referenced in `architecture.rst`,
  `developer-api.rst`, and `async-operations.rst`, is real, current API**
  (verified against `trust_manager.py` during Phase 0) — left unmarked, since
  marking accurate documentation as "superseded" would be the opposite defect.
- **`style-guide.rst:342-343`** (`def test_create_trust_with_valid_peer():`)
  left unmarked: it's a test-naming-convention example immediately preceded
  by the literal template `def test_<function>_<scenario>():`, which already
  signals genericness — judged low-risk enough not to need its own marker,
  to keep the diff proportionate to the actual defect.

---

## Phase 8: `llms.txt` generation and Context7 submission

Two separate things with one shared goal, split because only one of them is code.

**The integration risk is specific and worth stating up front**: Read the Docs
installs from the *pinned* `docs/requirements.txt` (`.readthedocs.yaml:19-21`),
not from the Poetry docs group. CI installs via Poetry. Adding the extension to
`conf.py` without regenerating `docs/requirements.txt` leaves **CI green and the
RTD build broken** on a missing extension — which takes the published
documentation offline. All three files change together.

### Changes

- `pyproject.toml:77-80` — add `sphinx-llms-txt` to
  `[tool.poetry.group.docs.dependencies]`.
- `poetry.lock` — regenerate via `poetry lock`.
- `docs/requirements.txt` — regenerate the pinned export so RTD installs the new
  extension. Verified during planning that `poetry export` is available on the
  installed Poetry 2.4.1 (it moved to `poetry-plugin-export` in Poetry 2.x, so
  confirm before relying on it if the toolchain changes).
- `conf.py:47-53` — add `'sphinx_llms_txt'` to `extensions`.
- `.gitignore` — ignore the generated `llms.txt` / `llms-full.txt` if they land in
  the source tree rather than the build output; verify which after the first build.

### User action (not an implementation step)

Submitting ActingWeb to Context7 is a request to a third party and cannot be
completed from this repository. After this plan lands:

1. Submit the repository `https://github.com/actingweb/actingweb` at
   <https://context7.com/add-library>. **Indexing is self-serve and requires no
   ownership** — "anyone can add a public library" — so this takes minutes, and
   it is worth checking first whether someone has already listed it. A committed
   `context7.json` gives finer parsing control. Context7 is a separate pipeline
   from `llms.txt`, not driven by it.
2. Re-query `https://context7.com/api/v1/search?query=actingweb` to confirm the
   entry appears; the research recorded `{"results":[],"searchFilterApplied":false}`
   on 2026-08-22.
3. Note the refresh cadence: top-100 libraries refresh daily, top-1,000 every 15
   days, and a low-traffic library may refresh more slowly still. Context7 is not
   a substitute for the readthedocs links added in Phase 3.

### New tests

- No unit tests. `llms.txt` generation is verified by the build producing the file.

### Verification

- [x] `poetry check --lock` passes (Poetry 2.x form; was `poetry lock --check` on 1.x)
      — exit 0, only the repo's pre-existing `[tool.poetry]`-vs-`[project]`
      deprecation warnings (unrelated, present before this change)
- [x] `poetry run sphinx-build -W --keep-going -D suppress_warnings="ref.doc,misc.highlighting_failure" -b html . _build/html` passes
- [x] `_build/html/llms.txt` and `_build/html/llms-full.txt` exist and are
      non-empty. **Sizes recorded**: `llms.txt` 72 lines / 4.9 KB;
      `llms-full.txt` 33,694 lines / **1.2 MB**, concatenating 66 sources —
      this is what regenerates on every RTD build.
- [x] `grep -c sphinx-llms-txt docs/requirements.txt` returns 1 — **this is the
      check that prevents a broken RTD build**
- [ ] Manual, post-merge: confirm the Read the Docs build succeeds and
      `https://actingweb.readthedocs.io/en/latest/llms.txt` serves —
      **not done**, this branch hasn't merged
- [ ] Manual: Context7 submission completed and search returns a result —
      **not done**, a third-party request the plan itself says "cannot be
      completed from this repository"; left for the user (see "User action"
      steps above)

### Implementation Status: Complete (two post-merge/external verification steps outstanding — see above)

**Learnings**: `poetry add --group docs sphinx-llms-txt` (rather than
hand-editing a guessed version constraint into `pyproject.toml`) resolved
the real current version (`^0.7.1`, not the plan's placeholder `^0.3.0`) and
updated `poetry.lock` in one step — safer than guessing a constraint that
might not resolve. `docs/requirements.txt` regenerated via the repo's
existing `pre-commit` git hook (installed by `scripts/install-git-hooks.sh`),
which auto-runs `poetry export --with docs --without-hashes` and stages the
result whenever `pyproject.toml` is part of the commit — already observed
firing correctly during Phase 4's commit. `_build/html/llms.txt` and
`llms-full.txt` needed no new `.gitignore` entry: they land under
`_build/html/`, already covered by the existing `_build/` pattern.

---

## Phase 9: Publish the Sphinx-invisible markdown files

`conf.py:62` restricts `source_suffix` to `.rst`, so four `.md` files under
`docs/` exist in the repo but are never built or published. The effect is
inverted for this plan's question: an agent with the repo checked out can read
them; a reader on readthedocs — the surface Phase 3 now points every README
reader at — cannot.

Verified during planning: two carry unique content, two duplicate larger `.rst`
twins.

| File | Lines | `.rst` twin | Action |
| --- | --- | --- | --- |
| `docs/guides/caching.md` | 394 | none | Convert to `.rst`, add to toctree |
| `docs/guides/oauth-login-flow.md` | 619 | none | Convert to `.rst`, add to toctree |
| `docs/guides/postgresql-migration.md` | 683 | yes, 800 lines | Delete |
| `docs/contributing/TESTING.md` | 490 | `testing.rst`, 607 lines | Delete |

### Changes

- `docs/guides/caching.rst` (new) — converted from `caching.md`; delete the `.md`.
- `docs/guides/oauth-login-flow.rst` (new) — converted from
  `oauth-login-flow.md`; delete the `.md`.
- `docs/guides/index.rst:12-33` — add both to the toctree; `caching` under "Data
  Management", `oauth-login-flow` under "Authentication & Authorization".
- `docs/guides/index.rst:34-46` — add matching one-line prose entries.
- Delete `docs/guides/postgresql-migration.md` and
  `docs/contributing/TESTING.md`.
- `tests/integration/README.md:51` — repoint to `docs/contributing/testing.rst`.
  Verified during planning: this link is **already broken** — it points at
  `../../docs/TESTING.md`, but the file lives at `docs/contributing/TESTING.md`.
  Fix it while deleting the target rather than leaving a doubly-dead link.

Before deleting either duplicate, diff it against its `.rst` twin and port
anything the `.rst` lacks. The `.rst` files are larger, but larger is not the same
as a superset.

**Check inbound references before deleting.** `ref.doc` is suppressed in the CI
build (`.github/workflows/tests.yml`), so a cross-reference broken by these
deletions will **not** fail `-W`. The grep in the verification list below is the
only thing standing between a deletion and a silently dead link. Historical
`CHANGELOG.rst` entries naming these files (`:2006`, `:2541`) are a record of what
happened and are left alone.

### New tests

- No unit tests. The `-W` build is the gate: a converted file with malformed RST
  or missing from the toctree fails it.

### Verification

- [x] `find docs -name '*.md'` returns nothing
- [x] Inbound-reference check, run **before** deleting or renaming — every hit
      outside `CHANGELOG.rst` (and `thoughts/`, excluded per the plan) was
      repointed or removed: `TODO.md`, `docs/guides/hooks.rst`, and
      `tests/integration/README.md` (also fixed a second, pre-existing broken
      link in the same list — `thoughts/shared/plans/...` → the real
      `thoughts/plans/...` path, encountered while already editing this file)
- [x] `poetry run sphinx-build -W --keep-going -D suppress_warnings="ref.doc,misc.highlighting_failure" -b html . _build/html` passes
- [x] `_build/html/docs/guides/caching.html` and
      `_build/html/docs/guides/oauth-login-flow.html` exist and render
      (63 KB and 66 KB respectively)
- [x] Manual: compared section-header structure (not full line-by-line diff,
      given file sizes) of each deleted `.md` against its `.rst` twin.
      `postgresql-migration.md`'s 34 section headers matched the `.rst`'s
      structure one-to-one — the `.rst` is a superset, not just "larger."
      `TESTING.md` vs `testing.rst` cover different-but-overlapping ground;
      confirmed the two topics that looked most at risk of being unique
      (`actor_factory`/fixture guidance, "Writing New Tests") are already
      covered in `CONTRIBUTING.rst`, and `TESTING.md`'s own headline claim
      ("117 tests" — the suite now has 3000+) confirms it predates the
      current test infrastructure enough that its specifics shouldn't be
      trusted as copy-paste-safe regardless.
- [x] `.github/workflows/tests.yml:94-98` — the docs-change filter comment
      explains that `.md` under `docs/` is not built; updated, since
      the condition it described no longer holds

### Implementation Status: Complete

---

## Adjacent work: the demo app

Raised during planning and investigated; **deliberately not phased into this
plan**. Recorded here so the reasoning is not lost.

### What was found

- `demo.actingweb.io` is **live and returns 200**, serving code last committed
  **2026-01-18** — roughly seven months stale, pinned to `actingweb >=3.9.0`
  against a current library of 3.14.0. An agent pointed at the reference app is
  looking at a two-minor-version-old deployment. This is itself a discoverability
  defect.
- `actingwebdemo/pyproject.toml:18` pins `actingweb = { version = ">=3.9.0" }` —
  a floating lower bound, so an agent reading the demo cannot tell which API era
  it demonstrates.
- Deployment today is **manual, from a developer laptop**:
  `serverless.yml:79` sets `provider.profile: default`, reading
  `~/.aws/credentials`; `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET` and
  `NUKE_SECRET` come from an untracked `.env` via `serverless-dotenv-plugin`.
  The repository has no deploy workflow — `.github/workflows/` contains only
  `claude.yml` and `claude-code-review.yml`.
- `demo.actingweb.io` is already configured as a custom domain with an ACM
  certificate on AWS account `473852420549` (`serverless.yml:22-28`).
- Serverless Framework is at **Core 3.40.0**, which is out of support. A v4 move
  requires a license key. This cost is owed by the demo repo regardless of where
  the code lives.

### The recommendation

**Move the code; do not move the deployment.**

*Code in* — `application.py` (298 lines) and `shared_hooks/` (~1,580 lines) move
into the `actingweb` repository as `examples/demo/`. This serves the
discoverability goal directly: it removes the floating-pin ambiguity, gives docs
and `AGENTS.md` a version-locked worked example, and lets CI catch the demo
breaking against the library. Per the decision taken during planning,
`examples/demo/` stays **repo-only** — it is not added to the wheel `include`
(`pyproject.toml:25-27`), so no example code lands in a consumer's
`site-packages`; `actingwebdemo` vendors it at deploy time.

*Deploy out* — the pipeline stays in `actingwebdemo`, which becomes a thin
wrapper: `serverless.yml`, `.env`, `package.json`, and a dependency on
`actingweb`.

**Why the deployment must not move.** Baking it in means putting AWS deploy
credentials — or an OIDC role trusted to update Lambda and API Gateway on account
`473852420549` — plus a live OAuth client secret into the same repository that
holds `POETRY_PYPI_TOKEN_PYPI` and publishes to PyPI on tag. Today, a compromise
of this repository yields a malicious wheel. Afterwards it would yield a
malicious wheel *and* control of a live OAuth-configured service. That is a
material widening of blast radius for a library repository, and it is the reason
this half is declined rather than merely deferred.

### Effect on this plan

Phases 3 and 6 both point at `actingwebdemo`. Neither may claim the demo tracks a
particular ActingWeb version until the pin is fixed — state the version it
actually tracks, or omit the claim.

### Next step

A separate plan, `thoughts/plans/2026-08-22-demo-app-consolidation.md`, covering
the code move, the version pin, CI testing of the example against the library,
and the Serverless v3→v4 question.

---

## Evaluation Notes

The four perspectives below were worked through directly against the codebase
rather than delegated to evaluator sub-agents.

### Architecture

- **`README.rst` is dual-surface.** It is the PyPI long description *and* a
  published Sphinx document (`index.rst:72`). Absolute URLs are the only link
  form valid on both; a `:doc:` role renders as broken text on PyPI. Accepted
  consequence: a reader on `/en/stable/` who follows a README link lands on
  `/en/latest/`. Recorded rather than mitigated — the alternative is maintaining
  two README variants.
- **`sphinx-llms-txt` has a three-file failure mode.** RTD installs from the
  pinned `docs/requirements.txt`; CI installs via Poetry. Changing `conf.py` and
  `pyproject.toml` without regenerating the pinned export leaves CI green and RTD
  broken. Phase 8 makes all three a single change set and puts the
  `grep -c sphinx-llms-txt docs/requirements.txt` assertion in its verification
  list specifically to catch this.
- **The `-W` build is a real gate for Phases 2 and 9.** A new document missing
  from a toctree produces a warning, and CI runs `sphinx-build -W --keep-going`
  (`.github/workflows/tests.yml:498+`) suppressing only `ref.doc` and
  `misc.highlighting_failure`. The toctree edits are therefore verified by the
  build itself, not by inspection. The build is warning-clean today (measured
  during planning: 0 warnings).
- **The p2p quickstart's code lives in a `.py` file, not the `.rst`.** A test that
  duplicates code copied out of a document only catches API drift — the document
  itself can rot freely. Putting the code in `examples/p2p_quickstart.py` and
  pulling it in with `literalinclude` means the test imports exactly what the
  reader sees, which makes doc-drift structurally impossible rather than merely
  monitored. It also creates the `examples/` directory the demo-consolidation plan
  needs, at no extra cost.
- **`ref.doc` is suppressed in the CI build**, so broken cross-references do not
  fail `-W`. This matters in Phase 9, where two files are deleted: the build will
  not catch an inbound reference, so an explicit grep does. A pre-existing instance
  was found during planning (`tests/integration/README.md:51`).
- **Phase 5 touches importable code**, so it carries the full quality gate
  (`pyright`, `ruff`, `make test-all-parallel`) where the other phases do not.
  `__all__` is left alone because it drives the lazy-load path.

### Security

- Phases 1–4, 6, 7 and 9 are documentation and metadata; no authentication,
  authorization, or data-exposure surface changes.
- **The p2p quickstart is the one phase with a security shape.** A quickstart
  that models auto-approving trust requests would teach the wrong default at
  precisely the moment an agent is copying code. Phase 2 requires
  `approve_relationship` as a deliberate step, an explicit statement that
  approval grants the peer whatever the trust type permits, a link to
  `docs/guides/access-control.rst`, and `with_devtest(enable=False)`.
- **`sphinx-llms-txt` is a new build-time dependency** in the documentation
  pipeline, executing on every RTD build. The mitigation is that it is pinned in
  `docs/requirements.txt` alongside every other docs dependency; no new
  mechanism is introduced.
- **The demo-deployment question is a security decision, not a preference.** It
  is answered in "Adjacent work" and the answer is no.

### Scalability

- Thin for a documentation change set, but two points are real.
- **`llms-full.txt` concatenates the entire documentation set** and is
  regenerated on every RTD build. Phase 8 records its size as a verification step
  so a surprising number is noticed rather than absorbed.
- **The p2p quickstart must link rather than duplicate.** `subscriptions.rst`
  already covers back-pressure, circuit-breaker states and fan-out tuning across
  884 lines. A quickstart that restates any of it creates a second copy that will
  drift; Phase 2 requires pointers. It does carry one forward:
  `.with_sync_callbacks()` on Lambda, because a quickstart that omits it teaches
  a pattern that silently loses callbacks on serverless.

### Usability

- **The `peer_id` defect is worse than the research recorded** — three files, not
  one. `docs/quickstart/getting-started.rst:133-142` has the same magic string,
  and it is in the *quickstart*, the document most likely to be copied verbatim.
  Phase 1 covers all three.
- **`README.rst:276-278` must be reconciled, not just supplemented.** It
  currently tells the reader documentation "lives in `docs/`" and cites
  `/en/master`. Adding `/en/latest/` links while leaving that sentence gives the
  reader two contradictory answers.
- **The `AGENTS.md` thin-pointer carries one risk**: an agent that reads only the
  top of the file could miss the quality gates entirely. Mitigated by ordering —
  the `CLAUDE.md` pointer is the first section, stated emphatically. Duplicating
  the gates was rejected; that is the duplication the decision exists to prevent.
- **Superseded banners should name the replacement, not just the warning.** A
  grep hit that says "this is old" leaves the agent no better off; one that says
  "this is old, the current API is X" resolves the query in place. Phase 7
  requires the current API be named in the admonition.
- **Phase 3's links are unverifiable until after merge.** `p2p-quickstart.html`
  does not exist on readthedocs until master builds. The verification step says so
  explicitly rather than inviting a pre-merge link check that will fail
  confusingly.
