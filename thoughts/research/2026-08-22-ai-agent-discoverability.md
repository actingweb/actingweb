# Research: Discoverability of ActingWeb for AI coding agents

**Date:** 2026-08-22
**Branch:** master
**Commit:** dbfb7cc
**Companion:** `thoughts/research/2026-08-22-agent-consumable-library-conventions.md`
(external state of play — `llms.txt`, `AGENTS.md`, Agent Skills, Context7, PyPI metadata)

## Research Question

Is ActingWeb and its documentation discoverable for AI coding agents in a good
way? Specifically: can an AI coding agent working in a *consumer* repository pick
up and implement (a) per-actor MCP apps and (b) peer-to-peer data sharing?

The subject is **coding agents writing application code against the library**
(Claude Code, Cursor, Copilot in a downstream repo that ran `pip install
actingweb`). It is *not* about runtime MCP hosts talking to a deployed actor —
MCP and trust/subscriptions appear here as the capabilities such an agent must
discover and wire up.

## Summary

**Correctness comes before placement: the documentation teaches APIs that do not
exist.** Nine defects were verified. `@app.trust_hook`, `@app.mcp_tool_hook` and
`app.config` are used in guides and have zero occurrences in `actingweb/`; the
`mcp_resource` docstring shipped inside the wheel teaches a nonexistent
`@resource_hook`; the canonical hooks reference documents a decorator with no
call sites and omits the one the subscriptions guide is built on. An agent that
copies these writes code that cannot run, and no amount of better placement
helps.

**The library's own prose is strong; its placement is the second problem.**
`README.rst` leads with "AI-ready", names MCP in the first paragraph and puts
`@mcp_tool` in the first code example — an agent that reads the README learns the
value proposition immediately. The gap is not content volume. It is that the two
artifacts written *for* agents in this repo — `AGENTS.md` and `CLAUDE.md` — are
both aimed at agents **contributing to ActingWeb** (test commands, pyright gates,
release process), and nothing anywhere is aimed at an agent **consuming** it.

**The likeliest entry point is PyPI, and its outbound links are dead.** An agent
that runs `pip install actingweb` may never open the git repository. PyPI carries
the full README intact (15,654 chars of RST), so the AI/MCP framing lands — but
all ~20 of the README's documentation pointers are *filesystem paths* like
``docs/guides/mcp-quickstart.rst``, which resolve only for a reader who already
has the repo. The corresponding readthedocs pages exist and their URLs are a pure
transform of those paths, but the README never gives them. So the surface most
agents actually reach names both headline capabilities and then points at files
the reader cannot open.

**Nothing an agent can grep in a consumer repo carries any guidance.** The 3.14.0
wheel has 159 entries and zero `.md`/`.rst` documentation beyond
`entry_points.txt` and `LICENSE.rst`. An agent that greps
`site-packages/actingweb/` finds code and type hints only. Two mitigations do
exist and are real: `py.typed` ships, and `actingweb/interface/__init__.py` and
`actingweb/mcp/__init__.py` both carry orienting module docstrings with clean
`__all__`. Against that, `actingweb/__init__.py` — the first file anyone opens —
has **no module docstring at all**, and its `__all__` lists legacy lazy-loaded
module names (`actor`, `attribute`, `oauth`, `auth`) without ever mentioning
`ActingWebApp` or MCP.

**Both headline capabilities are under-served, and MCP has the worse terminal
gap.** MCP takes roughly seven documents to a working setup, not one: the
quickstart's pasted application returns 401 on every call because `.with_oauth`
is commented out, it never mentions the database prerequisite, and **no
client-configuration example exists anywhere in `docs/`** — an agent can build
the server from these docs and cannot connect a client to it. Peer-to-peer takes
roughly six: both halves are documented — the publisher side at
`docs/guides/trust-relationships.rst:61-99`, the receiver side at
`docs/guides/subscriptions.rst:121-207` — but they live in separate guides, are
never joined into one two-actor example, and the hard `acl_rules` dependency that
makes a custom trust type work at all is mentioned in neither.

**On the external side, the one channel agents demonstrably use is empty, and the
file most often recommended is not consumed by anything.** Context7 — the
live-documentation service Claude Code and Cursor query over MCP — returns no
results for `actingweb`. `llms.txt` has no evidence of runtime fetching by any
coding agent; a zero-config Sphinx generator exists, so the cost is trivial, but
it should be adopted as a substrate for tooling, not on the belief that agents
read it automatically. **`AGENTS.md` cannot reach a library's consumers at all** —
the spec resolves to the closest file to *the file being edited*, so a consumer's
agent never sees it. The one mechanism that does target the consuming case is
**Agent Skills**, which is distributable from this repository today.

## Detailed Findings

### The documentation teaches APIs that do not exist

Nine defects, all verified directly against `dbfb7cc`. Four of them are library
defects — they ship inside the wheel and reach every consumer through docstrings
or a missing export, so they cannot be fixed in `docs/`.

**Documented decorators and attributes with zero implementation:**

| # | Defect | Verification |
| --- | --- | --- |
| 1 | **`@app.trust_hook(...)` does not exist.** Used at `docs/guides/trust-relationships.rst:127,180,188` and `docs/guides/troubleshooting.rst:184`. | `grep -rn "trust_hook" actingweb/` → **0 hits**. `app.py` defines `property_hook:1039`, `callback_hook:1048`, `app_callback_hook:1057`, `subscription_hook:1066`, `lifecycle_hook:1071`, `method_hook:1080`, `action_hook:1119`, `subscription_data_hook:1214` — no `trust_hook`, no `__getattr__`. Trust events are lifecycle events (`hooks.py:230-231`). |
| 2 | **`@app.mcp_tool_hook(...)` does not exist.** Used at `docs/guides/access-control-simple.rst:65`. | `grep -rn "mcp_tool_hook" actingweb/` → **0 hits**. |
| 3 | **`app.config` is not a public attribute.** `AccessControlConfig(app.config)` at `docs/guides/access-control-simple.rst:41`. | `app.py:112` sets `self._config`; the accessor is `get_config()` at `:1262`. No `config` property, no `__getattr__`. |

Defects 2 and 3 are in the **same code block**, the one labelled "a complete
example" at `access-control-simple.rst:23`.

**The documentation contradicts itself:**

| # | Defect | Verification |
| --- | --- | --- |
| 4 | **`execute_action_hooks` argument order.** `docs/guides/mcp-applications.rst:765,772` pass the actor first; `docs/guides/mcp-quickstart.rst:138` passes the name first. | `hooks.py:822-828` — `execute_action_hooks(self, action_name, actor, data, auth_context=None)`. **mcp-quickstart is right; mcp-applications is transposed.** |

**Defects shipped inside the package itself:**

| # | Defect | Verification |
| --- | --- | --- |
| 5 | **`mcp_resource`'s own docstring teaches a nonexistent decorator.** Its example uses `@resource_hook("config")`. | `grep -rn "resource_hook" actingweb/` → exactly **1 hit**: `actingweb/mcp/decorators.py:142`, inside that docstring. The decorator does not exist. |
| 6 | **`@app.subscription_hook` appears to be dead API.** It registers into `HookRegistry._subscription_hooks`, executed by `execute_subscription_hooks`. | `grep -rn "execute_subscription_hooks" actingweb/` → only the definition (`hooks.py:726`), its own docstring cross-reference (`:732`), and the async variant (`:1152`). **Zero call sites.** Yet `docs/quickstart/getting-started.rst:275-285` teaches it as the receiving mechanism, and `actingwebdemo/shared_hooks/protocol/subscription_hooks.py:28` uses it in a live deployment. |
| 7 | **`with_sync_callbacks` docstring states the wrong default.** Docstring says "Default is True". | `app.py:72` — `self._sync_subscription_callbacks = False  # Async by default`. |
| 8 | **`lifecycle_hook` is not exported from `actingweb.interface`.** | `grep -c "lifecycle_hook" actingweb/interface/__init__.py` → **0**. The other standalone hook decorators are exported; this one is not, so `from actingweb.interface import lifecycle_hook` fails. |

**The canonical reference omits the current API:**

| # | Defect | Verification |
| --- | --- | --- |
| 9 | **`docs/reference/hooks-reference.rst` has no entry for `subscription_data_hook`** — the decorator `docs/guides/subscriptions.rst` is built on. | `grep -c "subscription_data_hook" docs/reference/hooks-reference.rst` → **0**. `subscription_hook` (the dead one, defect 6) → **1**. The canonical reference documents the dead decorator and omits the live one. |

**One related claim was not verified**: the `@app.callback_hook("subscription")`
two-parameter `(actor, req)` form at `subscriptions.rst:546-553`. The real
contract is `(actor, name, data) -> bool` (`hooks.py:473`), but the block sits
under a "Migration from Raw Hooks" heading, so it may be a deliberate legacy
illustration rather than a defect. Check the surrounding prose before changing it.

### Layer 0 — PyPI is the likely entry point, and its outbound links are broken

An agent that reaches ActingWeb via `pip install actingweb` may never see the git
repository at all. That makes the PyPI project page — not the repo — the primary
prose surface. Checked against PyPI's JSON API on 2026-08-22:

| Field | Value |
| --- | --- |
| `description` | 15,654 characters — the full README |
| `description_content_type` | `text/x-rst` (renders natively on PyPI) |
| `summary` | "The official ActingWeb library" |
| `keywords` | `actingweb, distributed, microservices, rest, api` |
| `project_urls` | Documentation → `http://actingweb.readthedocs.io`; Homepage → `http://actingweb.org`; Repository → `https://github.com/actingweb/actingweb` |

So the good news is real: the AI-first framing, the MCP positioning and the
`@mcp_tool` example all reach a PyPI reader intact.

**But every documentation pointer in that README is a filesystem path, not a
URL.** There are roughly twenty of them, and on PyPI none is reachable:

- `README.rst:164-165` — "See ``docs/guides/mcp-applications.rst`` and ``docs/guides/mcp-quickstart.rst``"
- `README.rst:184-185` — the three authentication guides
- `README.rst:194-195` — `docs/guides/trust-relationships.rst`, `access-control.rst`, `subscriptions.rst`
- `README.rst:211` — `docs/reference/database-backends.rst`
- `README.rst:280-294` — the entire "Documentation" table, every row a bare path

For a reader with the repo checked out these resolve. For an agent on PyPI they
are dead references: the two capabilities in question are named, and then the
reader is pointed at files it cannot open.

**The destinations exist and the URLs are mechanically derivable.** Verified live:

- `https://actingweb.readthedocs.io/en/latest/docs/guides/mcp-quickstart.html` → 200
- `https://actingweb.readthedocs.io/en/latest/docs/guides/trust-relationships.html` → 200

The mapping is a pure transform of the paths already in the README
(`docs/<section>/<name>.rst` → `/en/latest/docs/<section>/<name>.html`). The
README carries one generic readthedocs link at `:276-278` and no deep links.

Two smaller observations on the same surface: both `Documentation` and `Homepage`
`project_urls` use `http://` rather than `https://`, and `actingweb.org` —
presented as "Protocol & project home" at `README.rst:302` — 200s after
redirecting to `https://stuff.greger.io/actingweb`.

**Not established:** how an agent discovers ActingWeb *by capability* rather than
by name — whether from training data, a user instruction, or search. An attempt to
test PyPI capability-search was abandoned when the control query for the literal
string `actingweb` also returned nothing, proving the scrape method broken rather
than the discovery absent. This remains an open question.

### Layer 1 — Discovery: does an agent learn ActingWeb does this at all?

**README.rst is a strength.** The title is "a Python framework for AI-ready,
per-user micro-services" (`README.rst:1-3`); MCP is the first of three client
types listed (`README.rst:28-30`); the Quick example imports `from actingweb.mcp
import mcp_tool` and defines an MCP tool (`README.rst:74-107`); there is a
dedicated "AI / MCP support" section (`README.rst:158-165`) and a "Trust,
permissions, and subscriptions" section (`README.rst:187-195`).

**PyPI metadata carries none of that signal.** `pyproject.toml:12` sets
`keywords = ["actingweb", "distributed", "microservices", "rest", "api"]` — no
`mcp`, `ai`, `agent`, `llm`, or `assistant`. `pyproject.toml:13-23` classifiers
are `Distributed Computing`, `Libraries :: Python Modules`, `HTTP Servers` —
nothing AI-related, and no `Programming Language :: Python :: 3.13` although
`.readthedocs.yaml:11` builds on 3.13. The `description` is "The official
ActingWeb library" (`pyproject.toml:4`), which says nothing about what the library
does. There is **no `[tool.poetry.urls]` block**, so the PyPI sidebar carries
neither a Changelog nor an Issues link.

Verified against the built artifact: the wheel's `METADATA` carries
`Keywords: actingweb,distributed,microservices,rest,api`, confirming this is what
reaches PyPI.

**There is no PyPI-side metadata channel for AI capability at all.** The only
relevant trove classifier is the long-standing
`Topic :: Scientific/Engineering :: Artificial Intelligence`;
`pypa/trove-classifiers` PR #207, proposing `Framework :: Model Context
Protocol`, has been open and undecided since 2025-03-14. Free-text keywords carry
no ecosystem semantics — worth adding as a hedge, not as a channel anything
consumes structurally.

### Layer 2 — The installed package: what a consumer-repo agent can actually grep

Inspected `dist/actingweb-3.14.0-py3-none-any.whl` directly.

| Fact | Value |
| --- | --- |
| Total wheel entries | 159 |
| `.md`/`.rst`/`.txt` in wheel | `dist-info/entry_points.txt`, `dist-info/licenses/LICENSE.rst` — nothing else |
| Docs shipped under `actingweb/` | none (only `templates/`, per `pyproject.toml:25-27`) |
| sdist extras | adds `README.rst` at the archive root |
| `METADATA` size | 17,968 bytes — carries the full README, and does contain the string `mcp_tool` |

The `METADATA` fact is worth recording but should not be leaned on: reading it
requires `importlib.metadata.metadata("actingweb")` or `pip show -v`, which is not
something coding agents routinely do when orienting in a repo.

**`actingweb/__init__.py` has no module docstring.** The file opens with
`__version__ = "3.14.0"` (`actingweb/__init__.py:1`) followed by an `__all__` of
lazy-loaded legacy module names (`actingweb/__init__.py:4-21`): `actor`,
`attribute`, `attribute_list`, `attribute_list_store`, `oauth`, `auth`,
`aw_proxy`, `peertrustee`, `property`, `subscription`, `trust`, `config`,
`aw_web_request`, plus `interface` and `ListMetadataContentionError`. Neither
`ActingWebApp` nor anything MCP-related appears. An agent opening the package root
to orient itself gets a list that points at the pre-3.x internals.

**The sub-packages are better.** `actingweb/interface/__init__.py:1-6` opens with
"Modern developer interface for ActingWeb library… clean, fluent API" and exports
`ActingWebApp`, `ActorInterface`, `TrustManager`, `SubscriptionManager`, the hook
decorators, and the callback/fan-out/remote-storage types.
`actingweb/mcp/__init__.py:1-20` explains that ActingWeb implements MCP by hand
rather than depending on the official SDK, and exports exactly
`mcp_tool`, `mcp_resource`, `mcp_prompt`.

**`py.typed` ships** (`actingweb/py.typed`), so type checkers and agents in
consumer repos get inline signature information — but it helps least at exactly
the surface an agent needs most. **Every hook boundary is erased to
`Callable[..., Any] -> Callable[..., Any]`** (`app.py:1039,1048,1057,1066,1071`
and `mcp/decorators.py:25,131,165`), and `actingweb/actor.py` is unannotated below
the interface layer. There is also no writing measuring `py.typed` as an agent
affordance at all; treat it as sound engineering, not as an evidenced agent
feature.

**Docstring spot-checks are good where it counts.**
`SubscriptionManager.subscribe_to_peer` (`actingweb/interface/subscription_manager.py:257-282`)
carries a full `Args:`/`Returns:` docstring. `ActingWebApp.with_mcp`
(`actingweb/interface/app.py:499-513`) documents the `server_name` tool-prefix
subtlety. `ActingWebApp.subscription_data_hook` (`app.py:1214-1241`) includes an
inline usage example at `app.py:1225`. The full set of hook decorators
(`action_hook`, `method_hook`, `lifecycle_hook`, `property_hook`, `callback_hook`,
`subscription_hook`) was not individually audited.

### Layer 3 — Repo and readthedocs

#### The MCP path is incomplete, and its terminal gap is client configuration

`docs/guides/mcp-quickstart.rst` (192 lines) *reads* as self-contained: install
extras (`:13-19`), a full `app_mcp.py` with imports, fluent config, a lifecycle
hook, an `@mcp_tool` action hook, an `@mcp_prompt` method hook, and
`aw.integrate_fastapi(api)` (`:24-77`), the uvicorn command (`:77`), curl-based
JSON-RPC tests (`:96-132`), a unit testing tip (`:134-147`), and tool safety
annotations (`:149-185`). `docs/guides/mcp-applications.rst` (1385 lines) adds
"Example: Complete MCP Application" at `:954`, plus per-actor tool visibility
(`:304`), structured output (`:350`), protocol version negotiation (`:420`),
OAuth2 integration (`:557`), deployment patterns (`:603`), and testing (`:734`).

**It does not actually work as pasted**, and reaching a working setup takes
roughly seven documents rather than one:

- **The quickstart's app cannot answer any MCP call.** `.with_oauth(...)` is
  commented out (verified at `mcp-quickstart.rst:48`), while the same file states
  every method beyond `initialize` requires a bearer token and that
  `with_devtest(True)` does **not** open the MCP endpoint. The pasted app returns
  401 for `tools/list`.
- **The quickstart never mentions the database.** Verified:
  `grep -niE "dynamodb local|AWS_DB_HOST|docker" docs/guides/mcp-quickstart.rst`
  → **0 hits**. `database="dynamodb"` in the quickstart is inert without
  `docs/quickstart/overview.rst:28-36`.
- **There is no client-configuration documentation anywhere.** Verified:
  `grep -rniE "claude_desktop_config|mcpServers" docs/ --include='*.rst'` →
  **0 hits**. An agent can build the server from these docs and cannot connect a
  client to it. This is the single largest gap found, and it is in the capability
  the README leads with.
- `mcp-quickstart.rst:191` — the "unified access control" bullet is unlinked prose
  with no `:doc:` target, from the file that most needs to point at
  `access-control-simple.rst`.

#### The peer-to-peer path is reference-shaped, split, and silently gated

Both halves exist:

- **Publisher / initiating side** — `docs/guides/trust-relationships.rst:61-99`,
  "Trust and Subscriptions Lifecycle", gives the only joined three-step recipe:
  `create_relationship` → `approve_relationship` → `subscribe_to_peer`, followed by
  a trust-state/subscription-behaviour table (`:86-99`).
- **Receiver side** — `docs/guides/subscriptions.rst:121-207`, "Subscription
  Processing → Quick Start", shows `.with_subscription_processing(...)` and
  `@app.subscription_data_hook("properties")` with the full handler signature
  (`:144-154`), specific and wildcard handlers (`:191-206`), and a config table
  (`:161-182`).

They are in two different guides and are never joined. There is no worked example
anywhere showing actor A and actor B — two deployments, or two actors in one — as
a single narrative, and no equivalent to the MCP guide's "Example: Complete MCP
Application". Reaching a working two-actor setup takes roughly six documents:
`docs/quickstart/overview.rst` (database), `docs/quickstart/getting-started.rst:114-146`
(actor creation, including the non-obvious requirement to pass `hooks=app.hooks`
to `ActorInterface.create()` or lifecycle hooks silently do not fire, `:117-120`),
`trust-relationships.rst`, `subscriptions.rst`, `access-control-simple.rst`, and
`docs/reference/hooks-reference.rst`.

**`acl_rules` is a silent hard dependency.** A custom trust type cannot create
subscriptions or receive callbacks without it —
`access-control-simple.rst:169-171` states this plainly, and
`add_trust_type(..., acl_rules=...)` exists at `permission_integration.py:316-324`.
Verified: **`grep -ci "acl" docs/guides/trust-relationships.rst` → 0**, and
**`grep -ci "acl" docs/guides/subscriptions.rst` → 0**. An agent reading the two
obvious p2p guides gets silent endpoint denials with nothing pointing at the cause.

**One concrete followability gap, in three files.** In the
`trust-relationships.rst:61-99` recipe, step 1 binds
`rel = actor.trust.create_relationship(peer_url=...)` (`:73-76`) and step 3 passes
a literal `peer_id="peer123"` (`:82-84`). Nothing bridges them. The same defect
appears at `trust-relationships.rst:15-26` and — worse, because it is the document
most likely to be copied verbatim — at `docs/quickstart/getting-started.rst:133-142`.
`TrustManager.create_relationship` returns `TrustRelationship | None`
(`actingweb/interface/trust_manager.py:221`) and `TrustRelationship` exposes
`.peer_id` (`trust_manager.py:24-27`), so `rel.peer_id` is the missing link and
the sequence *is* implementable — the docs simply use a magic string where a real
attribute exists, and never mention that the return can be `None`.

**Which receiving decorator, and why, is unstated.** Three decorators contain the
word "subscription", and `SubscriptionProcessingConfig.enabled` defaults to
`False` (`subscription_config.py:32`), so `subscription_data_hook` fires **only**
with `.with_subscription_processing()` enabled.

`docs/guides/subscriptions.rst` is 884 lines across 30+ sections (Callback Modes,
Peer Capability Discovery, Remote Peer Storage, List Operations, Subscription
Suspension, Fan-Out Manager, Circuit Breaker States, Back-Pressure Handling,
Performance Tuning…). This is reference material for someone who already knows the
shape of what they are building, not a path from zero.

#### Legacy-API sediment is a grep hazard specific to agents

A human uses the guides index; an agent greps `docs/`. Grepping for how to create
a trust relationship returns, out of ten hits across the docs tree:

- `docs/migration/v3.7.rst:199` — `actor.create_trust(...)` (superseded)
- `docs/migration/v3.7.rst:213`, `:471` — `actor.trust.create_verified_trust(...)` (superseded)
- `docs/migration/v3.7.rst:538` — `actor.create_trust(peerid=...)` (superseded)
- `docs/contributing/style-guide.rst:169`, `:249`, `:269` — illustrative signatures, not real API
- `docs/guides/trust-relationships.rst:16`, `:73`, `:160` — the current API

Seven of ten hits are deprecated or fictional. Migration and style-guide docs are
doing their jobs, but they are indistinguishable from current API to a grep.
**MCP has no equivalent legacy sediment** — it is a newer capability.

### The two agent-facing files serve the wrong audience

`AGENTS.md` (105 lines) and `CLAUDE.md` (401 lines) are both contributor-facing:
project structure, poetry/pyright/ruff commands, test execution modes, the
pre-commit checklist, the release process.

`AGENTS.md` is additionally stale. Last touched **2025-12-30**; `CLAUDE.md` was
last touched **2026-08-21** — roughly eight months of drift.

| `AGENTS.md` claim | Reality |
| --- | --- |
| `thoughts/shared/` — "Development notes, patterns, plans" (`AGENTS.md:99`) | No such directory. It was real and was deleted 2026-02-25 in `61d3807`. The convention is five dirs: `research/`, `plans/`, `verifications/`, `reference/`, `todo/` (`thoughts/README.md:13-19`) |
| `actingweb/db/dynamodb/    # Database backend` (`AGENTS.md:15`) | PostgreSQL backend also exists (`actingweb/db/postgresql/`) |
| "Change version in three files: `pyproject.toml`, `actingweb/__init__.py`, `CHANGELOG.rst`" (`AGENTS.md:77-80`) | `CLAUDE.md` documents a tag-driven release where the bump rides in the release PR and ordinary PRs need no bump at all |

**`AGENTS.md` contains zero mentions of MCP, trust, subscriptions, or peers.** The
only match for that whole set of terms across the file is the word "oauth" inside
a commit-message formatting example (`AGENTS.md:104`). The two capabilities this
research is about are absent from the file most likely to be read first by an
agent entering the repo.

**The drift has a mechanical cause, and it is fixable.**
`.github/workflows/claude-code-review.yml:12-16` lists `AGENTS.md`, `CLAUDE.md`,
`thoughts/**` and `TODO.md` under `paths-ignore`. Verified. The repo's primary
agent entry point is the one file categorically exempt from automated review. The
workflow's own comment says the list is "deliberately narrow" and invites
widening. `CLAUDE.md` stays current only because humans edit it during feature
work; `AGENTS.md` has no such pull. The dating is sharper than the staleness
figure suggests: `AGENTS.md` was committed in `a15b3d3` at 2025-12-30 10:32, and
the PostgreSQL backend landed in `5aa593a` at 2025-12-30 16:58 the same day — the
`db/dynamodb/  # Database backend` line was accurate for about six and a half
hours.

### `AGENTS.md` cannot reach library consumers

This is decided by mechanism, not convention (see the companion research for the
primary sources):

- **The spec's resolution rule anchors to the file being edited.** agents.md's
  FAQ: *"The closest AGENTS.md to the edited file wins."* A consumer's agent edits
  files in *their* repo, never in the library's. A library's `AGENTS.md` is
  unreachable by a consumer **by construction**.
- **Claude Code does not read `AGENTS.md` at all** — its memory documentation
  states *"Claude Code reads `CLAUDE.md`, not `AGENTS.md`."*
- The same reasoning makes a **wheel-shipped** `AGENTS.md`/`CLAUDE.md` inert:
  reachable only if the consumer's agent happens to read files inside
  `site-packages`, which is not a designed path and usually sits outside the
  project tree. No library was found doing this deliberately.

**The thin-pointer pattern is validated by local precedent.**
`actingweb_mcp/AGENTS.md` is 759 bytes and is a pure pointer:

> *"Instructions for AI coding agents working on this repository live in
> `CLAUDE.md` — that is the single source of truth. This file exists so Codex (and
> any other agent that defaults to `AGENTS.md`) lands on the same content as
> Claude Code."*

Verified: it was last touched 2026-05-29 and is still correct, **because it
delegates rather than duplicates**. This repo's `AGENTS.md`, which duplicates, was
wrong within six and a half hours of being written.

### Agent Skills are the mechanism that reaches consumers

Details and sources in the companion research; the load-bearing facts:

- A skill is a folder with `SKILL.md` (YAML frontmatter: `name`, `description`)
  plus optional `scripts/`, `references/`, `assets/`. Originally developed by
  Anthropic, released as an open standard, now vendor-neutral (agentskills.io).
- **Progressive disclosure** is the property that matters for a library: only
  `name` + `description` load at startup; the full `SKILL.md` loads when a task
  matches. Substantial guidance costs a consumer nothing until it activates.
- **Distribution works today, two ways**: `npx skills add owner/repo` from any
  GitHub repository, or a Claude Code plugin marketplace via a `marketplace.json`
  in the library's own repo.
- **Precedent**: Read the Docs ships `github.com/readthedocs/skills` (announced
  2026-02-11), including a skill for authoring `.readthedocs.yaml`. A docs platform
  shipping skills to its users is exactly the library→consumer pattern.
- **Exemplar**: Laravel Boost implements guidelines + on-demand skills + a docs
  MCP server, with a third-party package convention that auto-installs a package's
  skills. **There is no Python/PyPI equivalent** — nothing scans installed
  distributions for bundled skills.

**ActingWeb already has the third leg** — it ships an MCP server — which most
Python libraries do not.

**This is gated by `.gitignore`.** `.claude/` is ignored at `.gitignore:176` and
`git ls-files` returns zero `.claude` entries, so a fresh clone receives no
skills, commands, or agent definitions. Anyone adding a tracked `.claude/skills/`
must narrow that ignore first.

### Agent-affordance inventory

Checked and **absent**: `.claude/skills/`, `.claude/commands/`, `.claude/agents/`,
`.cursorrules`, `.cursor/`, `.github/copilot-instructions.md`, `llms.txt`,
`docs/llms.txt`, `llms-full.txt`, `mcp.json`, `.well-known/`.

`.github/` contains only workflows: `claude-code-review.yml`, `claude.yml`,
`publish-to-pypi.yml`, `tests.yml`.

No prior work exists on this topic — grepping `thoughts/` and `CHANGELOG.rst` for
`AGENTS.md`, `llms.txt`, or "discoverab*" returns a single incidental hit
(`thoughts/research/2026-07-30-mcp-trust-cache-crosses-clients.md:697`, citing
AGENTS.md for its quality gates). **`AGENTS.md` has never appeared in
`CHANGELOG.rst`**, nor has `llms.txt` — no release entry describes documentation
or DX as work in its own right. This is greenfield.

A second, older work register also exists: root `TODO.md` (3,396 bytes, last
commit 2026-01-02) duplicates the role of `thoughts/todo/`, and
`thoughts/todo/INDEX.md` does not reference it. An agent looking for open work
finds two registers with no stated relationship.

### Four markdown files are invisible to the published docs

`conf.py:62` sets `source_suffix = {'.rst': 'restructuredtext'}`, and the `.md`
alternative is commented out at `conf.py:61`. Consequently these are present in
the repo but never built or published to readthedocs:

- `docs/guides/caching.md`
- `docs/guides/oauth-login-flow.md`
- `docs/guides/postgresql-migration.md` (a `.rst` twin exists and *is* in the toctree at `docs/guides/index.rst:31`)
- `docs/contributing/TESTING.md`

The effect is inverted for our question: an agent with the repo checked out *can*
read them; a reader on readthedocs cannot. `docs/_build/` is correctly gitignored
(`.gitignore:83`) and tracked at 0 files, so it does not pollute greps.

### The reference application

`README.rst:303-304` points at `https://github.com/actingweb/actingwebdemo`. Both
that URL and the older `gregertw/actingwebdemo` resolve (the latter 301-redirects
after an org transfer), so the link is correct. Note the demo's own
`pyproject.toml` declares `"Repository" = "https://github.com/gregertw/actingwebdemo"`,
which does not match what the library's README sends readers to.

A local checkout at `/Users/wedel/src/actingweb/actingwebdemo` shows the demo
covers **both** capabilities:

- MCP — `application.py`, `shared_hooks/app/method_hooks.py`
- p2p — `shared_hooks/protocol/subscription_hooks.py`, `shared_hooks/app/callback_hooks.py`, `shared_hooks/app/ui_hooks.py`

It has a `CLAUDE.md` but no `AGENTS.md`, and pins `actingweb = { version =
">=3.9.0", extras = ["flask"] }` (`actingwebdemo/pyproject.toml:18`) — a floating
lower bound rather than a pin to 3.14, so an agent reading it cannot tell which
API era it demonstrates. Its `poetry.lock` **resolves `actingweb 3.9.0`**, so the
deployed code really is five minor releases old, not merely permitted to be.

Two further sibling apps exist locally: `actingweb_mcp` (the production consumer
whose upgrade produced `thoughts/research/2026-07-25-v3.13.0rc1-consumer-feedback.md`)
and `actingweb_firstapp` (a Flutter/Dart mobile client). `actingweb_mcp` **pins
`=3.14.0` exactly** and was last committed 2026-08-22; it is the better-maintained
reference consumer, and the source of the `AGENTS.md` pointer pattern above.

### What already works well

Worth recording so a follow-up plan does not over-correct:

- `README.rst` leads with the AI/MCP story and puts `@mcp_tool` in the first example.
- `docs/guides/index.rst:34-78` groups guides into labelled categories
  (Authentication, Trust & Relationships, Data Management, Integration,
  Operations) rather than an alphabetical dump, and states its audience at `:5`.
- `index.rst:8-21` opens with a "Choose Your Path" router keyed to four intents.
- `py.typed` ships; `interface/` and `mcp/` sub-packages are well-documented and
  cleanly exported (with the hook-boundary caveat in Layer 2).
- The receiver side of p2p is properly documented, with the full hook signature.
- `actingwebdemo` exercises both capabilities.
- The docs build is warning-clean today: 0 warnings under CI's
  `sphinx-build -W --keep-going`.

### External conventions (as of August 2026)

Full evidence, sources and evidence tiers are in
`thoughts/research/2026-08-22-agent-consumable-library-conventions.md`. The
conclusions that bear on this repository:

- **No coding agent auto-fetches `llms.txt` at runtime.** Cursor staff logged
  support as an unimplemented feature request in June 2025, still open; no vendor
  documents runtime fetching; a ~300,000-domain study found `llms.txt` did not
  make a domain more likely to be cited. Countervailing: Google Lighthouse now
  *audits* for it from Chrome M150, in an "Agentic Browsing" category with no
  weighted score — auditing for it is not consuming it. Generation cost is near
  zero: **`sphinx-llms-txt`** is on PyPI, advertises zero-configuration operation,
  and emits both `llms.txt` and `llms-full.txt` during a normal Sphinx build. Read
  the Docs serves these files but does not generate them. Adopt it as a substrate
  for Tier-2 tooling, not as a direct agent affordance.
- **`AGENTS.md` is contributor-scoped by mechanism** — see the section above.
- **Agent Skills are the only mechanism targeting the consuming case** — see the
  section above.
- **Context7 is the live-documentation path agents actually use, and ActingWeb is
  not in it.** Context7 (Upstash) indexes library documentation and serves it to
  Claude Code, Cursor and others via MCP plus a distributed skill/plugin; the top
  100 libraries refresh daily and the top 1,000 every 15 days. Querying its search
  API for `actingweb` returns `{"results":[],"searchFilterApplied":false}`. The
  endpoint is undocumented, so this was corroborated against known-indexed
  libraries on the same day: `?query=fastapi` returns `/websites/fastapi_tiangolo`
  and `?query=django` returns `/django/django` with
  `"lastUpdateDate":"2026-08-22T02:31:00.562Z","state":"finalized"`. The empty
  result is a genuine absence. Indexing is **self-serve and requires no
  ownership**; a committed `context7.json` gives parsing control.
- **The one rigorous study finds context files do not help.** Gloaguen et al.,
  *"Evaluating AGENTS.md"*, arXiv 2602.11988 (ETH Zurich): context files did not
  generally improve task success and inference costs rose >20%. The transferable
  nuance is that **instructions were well-followed while repository overviews were
  unhelpful.** Its scope is the *contributing* case; the consuming case is
  entirely unmeasured. **Design consequence**: prefer concrete task recipes over
  prose overviews in every agent-facing artifact — `AGENTS.md`, the
  `actingweb/__init__.py` docstring, and any skill.

## Open questions

- **How an agent discovers ActingWeb by capability** rather than by name. The
  attempt to test PyPI capability-search was abandoned when the control query
  proved the scrape method broken. Unresolved.
- **Whether `@app.subscription_hook` is genuinely dead** or invoked through a path
  grep missed (dynamic dispatch, the handler layer). If dead, this is a bug
  affecting a live deployment (`actingwebdemo` uses it), not a docs issue.
- **The `@app.callback_hook("subscription")` two-parameter form** at
  `subscriptions.rst:546-553` — defect or deliberate legacy illustration.
- **The remaining hook-decorator docstrings** (`action_hook`, `method_hook`,
  `lifecycle_hook`, `property_hook`, `callback_hook`, `subscription_hook`) were
  never individually audited. Spot-checks elsewhere were positive; the remainder is
  unevidenced.

Decisions taken on the findings above are recorded in
`thoughts/plans/2026-08-22-ai-agent-discoverability.md`.

## Code References

- `actingweb/__init__.py:1-21` — no module docstring; `__all__` lists legacy lazy-loaded modules
- `actingweb/interface/__init__.py:1-6` — orienting docstring; clean exports; `lifecycle_hook` absent
- `actingweb/mcp/__init__.py:1-20` — orienting docstring; exports `mcp_tool`/`mcp_resource`/`mcp_prompt`
- `actingweb/mcp/decorators.py:14-25` — `mcp_tool` signature
- `actingweb/mcp/decorators.py:142` — `mcp_resource` docstring teaching nonexistent `@resource_hook`
- `actingweb/py.typed` — ships inline type information
- `actingweb/interface/app.py:72` — `_sync_subscription_callbacks = False`, contradicting the docstring
- `actingweb/interface/app.py:112,1262` — `self._config` and the `get_config()` accessor
- `actingweb/interface/app.py:499-513` — `with_mcp` signature and docstring
- `actingweb/interface/app.py:1039-1241` — the full hook-decorator set; no `trust_hook`, no `mcp_tool_hook`
- `actingweb/interface/app.py:1158-1170` — `with_subscription_processing` parameters
- `actingweb/interface/app.py:1214-1241` — `subscription_data_hook`, with inline example at `:1225`
- `actingweb/interface/hooks.py:230-231` — trust events are lifecycle events
- `actingweb/interface/hooks.py:473` — `callback_hook` contract `(actor, name, data) -> bool`
- `actingweb/interface/hooks.py:726,732,1152` — `execute_subscription_hooks`, zero call sites
- `actingweb/interface/hooks.py:822-828` — `execute_action_hooks(action_name, actor, data, auth_context=None)`
- `actingweb/interface/trust_manager.py:18-52,215-234` — `create_relationship` returns `TrustRelationship | None`; `.peer_id`
- `actingweb/interface/subscription_manager.py:257-282` — `subscribe_to_peer` with full docstring
- `actingweb/interface/subscription_config.py:32` — `SubscriptionProcessingConfig.enabled` defaults to `False`
- `actingweb/permission_integration.py:316-324` — `add_trust_type(..., acl_rules=...)`
- `pyproject.toml:4,12,13-23,25-27` — description, keywords, classifiers, wheel `include`
- `conf.py:61-62` — `source_suffix` restricted to `.rst`
- `.gitignore:83,176` — `_build/` ignored; `.claude/` ignored entirely
- `.github/workflows/claude-code-review.yml:12-16` — `AGENTS.md` under `paths-ignore`

## Documentation References

- `README.rst:1-3,28-30,74-107,158-165,187-195,276-294,303-304` — AI-first framing, MCP example, dead doc pointers, demo link
- `AGENTS.md:15,77-80,99,104` — stale structure, version process, `thoughts/shared/`, sole "oauth" mention
- `docs/quickstart/overview.rst:28-36` — the database prerequisite the MCP quickstart omits
- `docs/quickstart/getting-started.rst:114-146` — actor creation, `hooks=app.hooks`; `:133-142` the `peer_id` defect; `:275-285` teaches the dead `subscription_hook`
- `docs/guides/mcp-quickstart.rst:13-19,24-77,48,96-147,149-191` — the MCP recipe and its 401/database/link gaps
- `docs/guides/mcp-applications.rst:954` — "Example: Complete MCP Application"; `:765,772` transposed `execute_action_hooks`
- `docs/guides/trust-relationships.rst:15-26,61-99,127,180,188` — the joined recipe, the `peer_id` gap, the nonexistent `trust_hook`
- `docs/guides/subscriptions.rst:121-207,144-154,161-182,546-553` — receiver-side processing; the unverified `callback_hook` form
- `docs/guides/access-control-simple.rst:23,41,65,169-171` — the "complete example" with two nonexistent APIs; the `acl_rules` requirement
- `docs/guides/troubleshooting.rst:184` — nonexistent `trust_hook`
- `docs/reference/hooks-reference.rst:104-108,230-240` — lifecycle hook signatures; no `subscription_data_hook` entry
- `docs/guides/index.rst:5,34-78` — audience statement and categorized routing
- `index.rst:8-21` — "Choose Your Path" intent router
- `docs/migration/v3.7.rst:199,213,471,538` — superseded trust API visible to greps
- `docs/contributing/style-guide.rst:169,249,269` — illustrative, non-API signatures
- `thoughts/README.md:13-19` — the five-directory convention `AGENTS.md` contradicts
- `thoughts/research/2026-07-25-v3.13.0rc1-consumer-feedback.md` — prior first-consumer friction report

## External References

- https://agents.md/ and https://github.com/openai/agents.md — the `AGENTS.md` spec; the "closest file to the edited file wins" resolution rule
- https://aaif.io/projects/agents-md — stewarded by the Agentic AI Foundation (Linux Foundation)
- https://code.claude.com/docs/en/memory — "Claude Code reads `CLAUDE.md`, not `AGENTS.md`"
- https://agentskills.io/ and https://github.com/agentskills/agentskills — Agent Skills, the vendor-neutral open standard
- https://code.claude.com/docs/en/plugin-marketplaces — `marketplace.json`, third-party distribution
- https://github.com/readthedocs/skills — a docs platform shipping skills to its users
- https://laravel.com/docs/12.x/boost — Laravel Boost: guidelines + skills + docs MCP, with a third-party package convention
- https://forum.cursor.com/t/cursor-not-support-llms-txt-standard/108980 — Cursor staff, June 2025: `llms.txt` support logged, unimplemented
- https://seranking.com/blog/llms-txt/ — ~300,000-domain adoption study; no citation benefit measured
- https://developer.chrome.com/docs/lighthouse/agentic-browsing/llms-txt — Lighthouse audits for `llms.txt` from Chrome M150
- https://github.com/jdillard/sphinx-llms-txt and https://pypi.org/project/sphinx-llms-txt/ — zero-config Sphinx generator
- https://about.readthedocs.com/blog/2026/02/llms-txt-support/ — RTD serves `llms.txt`; does not generate it
- https://github.com/langchain-ai/mcpdoc — serving a *user-defined* list of `llms.txt` files to agents via an MCP `fetch_docs` tool
- https://context7.com/docs/adding-libraries — self-serve indexing, no ownership required
- https://github.com/pypa/trove-classifiers/pull/207 — `Framework :: Model Context Protocol`, open since 2025-03-14
- https://arxiv.org/abs/2602.11988 — Gloaguen et al., "Evaluating AGENTS.md" (ETH Zurich)
- Context7 search API queried 2026-08-22: `GET https://context7.com/api/v1/search?query=actingweb` → `{"results":[],"searchFilterApplied":false}`

## Method Note

Findings were verified against commit `dbfb7cc`. The wheel and sdist at
`dist/actingweb-3.14.0*` were opened and enumerated; signatures and docstrings
were read from source; every claim that an API does not exist was established by
`grep` over `actingweb/`; doc code samples were compared against the
implementations they document; `git log` established the `AGENTS.md`/`CLAUDE.md`
drift and the six-and-a-half-hour `AGENTS.md` accuracy window; and both
`actingwebdemo` URLs, PyPI's JSON API, the readthedocs deep links and the Context7
index were queried live.

Claims explicitly marked as unverified in the Open questions section were not
re-checked. External-convention claims are sourced in the companion research
document, which re-sourced every claim from a primary document or a study with
methodology after discarding an initial SEO content-farm cohort; its mechanics
(the Agent Skills schema, `npx skills add`, the Laravel Boost third-party
convention) were **not** independently re-verified here and should be confirmed
before being built on.
