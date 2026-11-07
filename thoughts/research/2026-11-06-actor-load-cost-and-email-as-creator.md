# Research: what an actor load costs a consumer, and where "creator equals email" could be enforced

**Date:** 2026-11-06
**Branch:** docs/3-16-rollup-records
**Commit:** fea9e42

Follow-up to `thoughts/research/2026-11-05-subs-list-cache-lifetime.md`. The
plan from that note has the MCP handler build an `Actor` per request. Its
review found the cost is two reads, not one, for a consumer that sets
`with_email_as_creator(True)`. The owner asked for the actual scale
consequence for a consumer like `actingweb_mcp`, and whether the invariant the
load-time check serves can be enforced where the email is written instead.

Everything here was read from the code. Nothing was run; the read counts are
derived, and the two recorded measurements are cited as such. The consumer
pins `actingweb == 3.15.1` (`../actingweb_mcp/pyproject.toml:11`); the email
check on load is the same in that version.

## Research Questions

1. **How many actor loads does a request make, and which pay the `_internal`
   Query?** One per authenticated REST or SPA request, through
   `Auth.__init__`; zero on a warm MCP call. Every load pays the Query under
   the flag except one call site. See "Loads per request".
2. **What does the consumer's traffic look like?** One load and one
   `ActorInterface` per SPA request; no consumer code loads the same actor a
   second time, and no request path loads peer actors in a loop. See "The
   consumer".
3. **What is in `_internal`, and how big is it?** A fixed set of about a dozen
   keys plus one `oauth_tokens:<peer>` row per MCP client trust, about 2 to
   2.5 KB for a typical actor; 1 RCU until roughly three interactive MCP
   clients. See "The bucket".
4. **Is the bucket read per request anyway?** On peer-bearer requests, yes
   (`trustee_root`). On SPA-bearer and provider-bearer requests it is read only
   because of the email flag. See "Who else reads it".
5. **What would per-request MCP actors add to a tool call?** Three consistent
   reads (actor row, `_internal`, the consumer's usage counter), and a
   subscription Query for actors that have subscribers. See "A warm tool call".
6. **What is the invariant, who writes the email, and what depends on the
   load-time rewrite?** The `_internal` attribute `email` is copied to the
   creator on load for a vouched actor. Nine writers, no shared function. The
   SDK rename was designed so that the next load completes it. See "The
   invariant" and "Writers".
7. **What are the options and what does each cost?** Five, from "keep" to
   "enforce at the writers". See "Decisions Needed".

## Summary

Today every authenticated REST and SPA request in `actingweb_mcp` loads its
actor once and, because of `with_email_as_creator(True)`, issues one strongly
consistent Query over the `_internal` bucket to compare the stored email with
the creator. For SPA-bearer traffic nothing else on the request reads that
bucket, so the Query exists only for the check. The MCP path is the one place
that does not pay it: a warm `tools/call` reads neither the actor row nor
`_internal`, because the cached `ActorInterface` carries both.

Building the actor per MCP request therefore does not introduce a new kind of
read. It moves the actor GetItem and the `_internal` Query from about once per
actor per process to once per call, and ends two memos the consumer's tool
wrapper benefits from: the `mcp_usage_count` property read and, for actors
with subscribers, the subscription list. That is three to four consistent
reads and round trips added per tool call, against a warm floor of about one
trust GetItem, one subscription Query and one PutItem before the tool body
runs.

The check itself can move, but not for free. The source of truth is the
`_internal` attribute, not a property, and every library path that writes it
either sets the creator in the same step or deliberately leaves the next load
to finish the job. The vouched SDK rename is the second kind: the email write
is its commit point and "the load is a writer in the protocol". Enforcing at
write time means redesigning that rename (the open
`thoughts/todo/vouched-rename-one-transaction.md`) and sweeping actors that
already have a mismatch.

## Detailed Findings

### Loads per request

`Actor.get()` runs the check on every load unless `rewrite_email=False`
(`actor.py:374-425`). Only `get_from_creator`'s enforced branch passes it
(`actor.py:522`); `Actor.__init__` has no such parameter (`:113-142`). The
check reads `self.store.email` (`:406`), which loads the whole bucket:
`InternalStore._ensure_loaded` → `get_bucket(strict=False)`
(`attribute.py:28-48`) → a consistent Query on DynamoDB
(`db/dynamodb/attribute.py:126-130`), one `SELECT` on PostgreSQL. The bucket
is loaded once per `Actor` instance and served from memory afterwards.

| Request | `Actor` loads | `_internal` read |
| --- | --- | --- |
| REST with basic auth (`auth.py:111`) | 1 | Only under the flag |
| REST with a peer bearer token | 1 | Always: `trustee_root` at `auth.py:240-242` |
| REST or SPA with an SPA bearer | 1 | Only under the flag (returns at `auth.py:300-301`) |
| REST with a provider OAuth2 bearer | 1 | Only under the flag (`auth.py:330-346`) |
| Subscription callback received (`handlers/callbacks.py:178`) | 1 | Always (peer bearer) |
| MCP `tools/call`, warm | 0 | None |
| MCP `tools/call`, cache miss (`handlers/mcp.py:2480`) | 1, plus 1 on a client's first authentication (`:3091`) and 1 when `clientInfo` changed (`:2791`) | Under the flag |
| Property write fanning out to S subscribers | 0 | None; `register_diffs` and `callback_subscription` construct no actor |

`ActorInterface(...)` reads nothing (`interface/actor_interface.py:65-94`). The
integrations construct no actor themselves; they reach `Auth` through the
handlers.

### The consumer

- **SPA API.** All 164 uses across 27 files go through
  `_validate_actor_with_role`
  (`../actingweb_mcp/helpers/template_helpers.py:262-336`), which calls
  `check_and_verify_auth_async` and returns `ActorInterface(auth_result["actor"])`:
  one load, one wrapper. `get_all_relationships`
  (`api/trust_unified.py:463-470`) loops over trust relationships and loads no
  peer actors.
- **MCP tools.** `save`, `search` and `get` are wrapped in
  `with_usage_tracking` (`hooks/mcp/tools/shared.py:169-207`), which reads and
  writes the property `mcp_usage_count` (`:160`, `:166`). No tool module
  constructs an actor.
- **Websocket** connect and authenticate load no actor
  (`websocket_handlers/connect.py:52-76`, `default.py:355-356`).
- **Other actors** are loaded only on share creation
  (`helpers/shares.py:427`, through `get_by_creator`, which does not pay the
  Query), in one background task (`api/trust.py:188`), and in webhooks and
  trial emails (`api/revenuecat_webhook.py:189`, `:336`,
  `api/stripe_webhook.py:577`, `helpers/trial_emails.py:67`).

### The bucket

`_internal` has its own key range. MCP and SPA tokens, permission overrides and
clients live in other buckets, mostly on the system actor.

Keys the library writes: `auth_method`, `vouched_creator` and its pending
twin, `email`, `created_at`, `oauth_provider`, `oauth_sub` or
`oauth_github_id`, the four provider-token fields (`oauth_token`, its expiry,
`oauth_refresh_token`, its timestamp), the email-verification fields for
email-form accounts, the adoption fields, `session_generation`,
`trustee_root`, and **one `oauth_tokens:<peer_id>` row per MCP client trust**
(`interface/trust_manager.py:668-677`), with no TTL, deleted with the trust
(`trust.py:193-206`). The consumer adds none.

Size, from the row model and not measured: about 10 to 12 core rows and 1.8 to
2.5 KB for a Google-signed-in actor; each `oauth_tokens:` row adds 0.3 to
0.7 KB. A consistent Query costs ceil(bytes / 4 KB) RCU, so 1 RCU up to two or
three interactive MCP clients and about one more per further six. The only
growth is that per-trust row: bounded by the trust count, with no cap or
expiry of its own (the retention question in
`thoughts/todo/dcr-registrations-and-client-trust-rows-never-expire.md`).

### Who else reads it

- `store.trustee_root` on every bearer request that is neither an SPA token nor
  a provider token, that is, peer trust tokens (`auth.py:241`, `:576`); and on
  `/meta` and the actor root (`handlers/meta.py:18`, `handlers/root.py:77`).
- `store.oauth_token…` on logout only (`handlers/oauth2_endpoints.py:1273`,
  `handlers/oauth2_spa.py:2012`).
- `store.auth_method` on a create race and during sign-in only.

SPA and MCP token validation read other buckets. The consumer's own middleware
reads no `.store`.

### A warm tool call

For the consumer's configuration:

| Read | Where | Today, warm | With per-request actors |
| --- | --- | --- | --- |
| Actor row GetItem | `actor.py:389` | 0 | +1 |
| `_internal` Query | `actor.py:406` | 0 | +1 under the flag |
| Creator-holder read | `actor.py:363` | 0 | +1 only while the stored email differs from the creator |
| Token validation, 2 GetItem | `oauth2_server/token_manager.py:1254-1261` | 0 | 0 if the token-cache hit path is kept |
| Trust list Query | `handlers/mcp.py:2593` | 0 | 0 if the trust cache is kept |
| Trust GetItem for the trust type | `permission_evaluator.py:606-610` | 1 when there is no override | unchanged |
| `mcp_usage_count` GetItem | `shared.py:160` → `property.py:357-365` | 0 after the first per cached instance | +1 |
| `mcp_usage_count` PutItem | `shared.py:166` | 1 | unchanged |
| Subscription Query in `register_diffs` | `actor.py:3879` | 1 with no subscribers, 0 with some | +1 for actors with subscribers |
| Tool body (`save`: write-tracking and lock GetItems, 1 to 2 `service` Queries; `search`: a whole-partition dump) | consumer | as today | unchanged |

Added per call: three consistent reads, or four for an actor with subscribers,
about 3 to 4 RCU. Against a tool body: a `search` on a median account
(11.5 RCU for the dump) gains about a quarter; on the consumer's heaviest
account (1,352.5 RCU) well under one percent. These are arithmetic, not
measurements.

Recorded measurements that give a baseline:

- Warm SPA `review-status`, "the floor of an `/api/*` request — auth plus a
  trivial read": p50 77 ms
  (`../actingweb_mcp/thoughts/research/2026-08-24-spa-fanout-cost-and-latency.md:207-227`).
- One Query of a 10-attribute bucket: 1 RCU, 48 ms; seven `get_attr`: 7 RCU,
  286 ms; laptop wall times, upper bounds (`:294-307`).
- `get_by_id` costs "2 reads for a live actor (GetItem plus a consistent
  `_internal`-bucket query, because `force_email_prop_as_creator` …)"
  (`../actingweb_mcp/thoughts/plans/2026-07-26-orphan-attribute-writes-and-guards.md:117-120`).
- No per-call read count or latency for an MCP `tools/call` is recorded
  anywhere.

### The invariant

- **Source of truth:** the `_internal` attribute `email`. In 2017 it was the
  property `email` (`CHANGELOG.rst:6484-6487`); nothing links that property to
  the creator now, although `docs/quickstart/configuration.rst:44` still says
  "Copy ``email`` property to ``creator``."
- **Direction:** stored email into creator, never the reverse.
- **Gates** (`actor.py:401-425`): the flag; a stored email that differs from
  the creator; a vouched store (`oauth2.py:1855-1863`); and, with
  `unique_creator` on, no other actor holding the email, which is one more
  consistent read per load while a mismatch lasts (`actor.py:356-372`).
- **What the rename writes** (`actor.py:1027-1054`): on DynamoDB with
  uniqueness, one transaction over the actor row and the new `creators`
  record; on PostgreSQL one conditional `UPDATE`. `CreatorTaken` is caught and
  logged; a `DbError` propagates out of the load.
- **Defaults:** a bare `Config` has the flag on (`config.py:125`);
  `ActingWebApp` has it off (`interface/app.py:103`).

### Writers

| Writer | Where | Sets the creator in the same step? | Relies on the next load? |
| --- | --- | --- | --- |
| OAuth create, address identifier | `oauth2.py:1950-1952` | Yes | No |
| OAuth create, provider-id identifier | `oauth2.py:1942-1946` | No | Only reachable with the flag off; a mismatch appears if the flag is turned on later |
| Sign-in seeding of a missing email | `oauth2.py:2431-2456` | Yes for an address creator | Provider-id creators: yes |
| Clean in place | `oauth2.py:3111` | Same rule | Same |
| Vouched SDK rename | `interface/actor_interface.py:593`, then `modify` at `:604` | In a second write, another table | **Yes, by design**: the email write is the commit point (`thoughts/plans/2026-11-02-3-16-owner-decided-followups.md:707-737`, `CHANGELOG.rst:282-286`) |
| Rename restore | `interface/actor_interface.py:640-646` | Puts the old email back | No |
| `unique_creators resolve` | `maintenance/unique_creators.py:582` | Clears the email | No |
| devtest attribute PUT | `handlers/devtest.py:53-55` | No | Yes |
| Application code on `actor.core_actor.store.email` | public through `interface/actor_interface.py:384` | No | Yes; the 2017 use case |

There is no shared function: the writers call `InternalStore.__setattr__`,
`set_if_absent` or `set_confirmed` directly.

Paths that create a mismatch without writing the email:

- `PUT /<id>/trust/trustee {"creator": "trustee"}` under the pin keeps the
  marker and leaves the email (`actor.py:936`, `:978-983`); the next vouched
  load would move the creator back to the email, which then fails the
  `trustee_root` token check that needs `creator == "trustee"`
  (`auth.py:246-251`). Traced, not tested: the one handoff test runs with the
  flag off (`tests/test_trust_creator_rename.py:67`).
- `Actor.modify(creator=…)` called directly.
- `mark_actors_vouched` on an actor that already has a mismatch.
- Turning the flag on over actors created with it off.

### What depends on the load-time rewrite

- **The SDK rename.** `_rename_vouched` and `_rename_pinned` rely on the next
  load to finish after a raise, and check the outcome with a fresh load that
  itself moves the creator (`interface/actor_interface.py:613-624`). The open
  todo says "The next load … finishes it"
  (`thoughts/todo/vouched-rename-one-transaction.md:20-22`).
- **Request authentication.** Basic auth compares the username with the
  creator (`auth.py:152`), and a provider token compares its email with the
  creator (`auth.py:330-334`, `:518-525`), both after the load at `:111`. A
  vouched actor whose email changed is reachable under the new address because
  the load heals it first.
- **Tests:** `tests/test_rename_pending_vouch.py:265-309`,
  `tests/test_adoption_summary_and_handoff.py:436-453`,
  `tests/integration/test_unique_creator_states.py:753-809` and `:154-167`,
  `tests/integration/test_unique_creators_command.py:177-183`.
- **Documentation:** `CHANGELOG.rst:233-242`, `:282-290`, `:312-315`,
  `:519-525`, `:737-739`, `:2027-2031`; `docs/migration/v3.16.rst:348-350`,
  `:386-390`, `:950-952`.
- **The consumer:** enables both flags; never writes the stored email and has
  no "change my email" feature; shows `actor.creator` as the account email in
  MCP resources and tools (`hooks/mcp/resources.py:155`, `:207`,
  `hooks/mcp/tools/guide.py:431`).

No recorded decision says whether to keep the load-time rewrite itself.

### Existing mismatches

They can arise from every row above that relies on the next load. The parts of
a sweep exist: the consistent actor scan with resume and rate limit in
`maintenance/mark_actors_vouched.py:159-160`, the rename with a holder check
in `maintenance/unique_creators.py` (`move_default_creator`), and the
readiness pattern in `interface/app.py:1557-1690`. A readiness marker would
have to be redone when the flag is turned on.

## Documentation Impact

### The cost of an actor load

- `docs/` — no page states what a load costs or that the flag adds a Query:
  none.
- `docs/quickstart/configuration.rst:44` — "Copy ``email`` property to
  ``creator``"; already wrong against the code (it is the internal attribute).
- `docs/guides/authentication.rst:1045`, `:1058-1061` — labels the flag
  "(default)" and describes it as the email-required identity mode. The
  default differs between `Config` and `ActingWebApp`.

### The rewrite

- `docs/migration/v3.16.rst:348-350`, `:386-390`, `:950-952` and the
  `Unreleased` changelog entries listed above describe "every load moves the
  creator to the stored email". False under any option that removes or
  narrows the load-time check; they are unreleased, so they would be rewritten
  rather than amended.

## Decisions Needed

### Decision 1: what the MCP path does about the check

Bears on `thoughts/plans/2026-11-06-subs-list-cache-lifetime.md`.

**Options:**

1. **Full load per MCP request.** GetItem plus the `_internal` Query under the
   flag; an MCP request costs what an SPA request already costs. No new
   parameter; the check behaves the same everywhere.
2. **The MCP load skips the check** (`rewrite_email=False`, as a keyword on
   `Actor.__init__`). One read per request; `_internal` is loaded only if a
   hook touches it. MCP authentication does not compare the creator (the token
   is bound to the actor id), so nothing on the request needs the heal. An
   actor reached only over MCP keeps a stale `creator` until a REST, SPA or
   sign-in load; the consumer shows `actor.creator` as the account email in
   MCP resources.
3. **Keep the row in a short identity cache instead of building per request.**
   Zero reads on a warm call; needs a preloaded-row path on `Actor.__init__`
   and leaves the row and the check up to 300 s behind.

### Decision 2: whether the check moves off the load path altogether

Larger than the MCP question: it removes one consistent Query from every
flagged SPA and provider-bearer request, which for the consumer is all of its
SPA traffic.

**Options:**

1. **Leave it on load.** No change.
2. **A cheaper check on load:** read the one attribute with
   `Attributes.get_attr` (a GetItem; `attribute.py:283-332` skips the bucket
   read) and load the bucket only on a mismatch. Same number of round trips
   as today on the common path, smaller read; saves nothing where the request
   reads the bucket anyway.
3. **Check only where a human is authenticated** (sign-in, cookie and session
   validation, `/www`), skip it on bearer, peer and MCP loads. `Auth` loads the
   actor before it knows the credential type (`auth.py:111`), so the decision
   has to move ahead of the load. Requests authenticated by a provider token's
   email stop healing until a sign-in.
4. **Enforce at the writers and drop the check.** One helper sets the stored
   email and renames the creator together, fail-closed; the load does one
   read. Requires: the vouched rename redesigned so it no longer depends on
   the next load (the one-transaction todo); the trustee handoff decided;
   application and devtest writes of `store.email` no longer moving the
   creator (a `Behavior change`); a sweep and a readiness marker for existing
   mismatches, redone when the flag is turned on; and the unreleased 3.16
   entries that describe the load-time heal rewritten.
5. **Carry the email on the actor row.** One read; a schema change on both
   backends.

**Recommendation:** none between these. Options 1 to 3 are small; option 4 is
the only one that removes the Query from every request, and it is a plan of
its own whose first dependency is an open todo.

## Release shape

Decision 1 belongs to the `subs-list-cache-lifetime` plan (3.16). Option 2
adds a keyword-only parameter with a default, which the release rule allows in
a patch, and is a `**Behavior change:**` for MCP hooks that read
`actor.creator`. Decision 2, options 3 to 5, are a minor each: a behaviour
change for consumers, and for 4 and 5 an operator step.

## Code References

- `actingweb/actor.py:113-142` — `Actor.__init__`, no `rewrite_email` parameter
- `actingweb/actor.py:356-425` — `_email_held_elsewhere` and the check in `get()`
- `actingweb/actor.py:522` — the one `rewrite_email=False` call site
- `actingweb/actor.py:1027-1054` — `modify(creator=…)`
- `actingweb/attribute.py:28-48`, `:283-332` — the lazy bucket load; the point read
- `actingweb/auth.py:111`, `:152`, `:240-242`, `:300-346` — the load and the credential branches
- `actingweb/handlers/mcp.py:2280-2342`, `:2480`, `:2791`, `:3091` — the warm path and the MCP loads
- `actingweb/interface/actor_interface.py:593-646` — the vouched rename and its restore
- `actingweb/interface/trust_manager.py:668-677` — the per-trust `oauth_tokens:` row
- `actingweb/oauth2.py:1938-1952`, `:2431-2456`, `:3111` — the OAuth writers of the email
- `actingweb/maintenance/mark_actors_vouched.py:159-160`, `unique_creators.py:439-464` — sweep building blocks
- `../actingweb_mcp/application.py:561-562` — both flags on
- `../actingweb_mcp/helpers/template_helpers.py:262-336` — the SPA load
- `../actingweb_mcp/hooks/mcp/tools/shared.py:149-207` — the usage counter

## External References

None.
