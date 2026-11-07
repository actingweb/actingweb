# Research: the specification against the library, for a version 1.5

**Date:** 2026-11-06
**Branch:** docs/3-16-rollup-records
**Commit:** fea9e42

Asked for by the owner while planning the `ListAttribute` port: a full sweep of
`docs/protocol/actingweb-spec.rst` (version 1.4, 3,375 lines) against what the
library does at fea9e42, so that each disagreement can be settled on one side or
the other in a version 1.5, and so the version the library announces can move.

Everything here was read from the code and the tests. Nothing was run against a
server, so a status code is "pinned" only where a test is named.

## Research Questions

1. **Where do the specification and the library disagree?** 144 places, in
   six chapters. Tables under "Findings".
2. **Which of those are the library breaking a MUST or SHOULD, and which are
   the specification being stale, silent, ambiguous or self-contradictory?**
   Each row carries its kind. Counts under "Summary".
3. **Which are recorded, deliberate decisions?** Marked in the last column
   of each table, with where.
4. **What does the library announce as its protocol version, who reads it, and
   what breaks if it changes?** It announces `"1.0"`; nothing in the library
   compares versions; two test assertions pin the value. See "The announced
   version".
5. **Which findings are already covered by a plan?** Those in "Already
   planned"; they are not repeated in the tables except where a row adds to
   them.

## Summary

The kinds:

- **CODE** — the library breaks a MUST or SHOULD as written.
- **STALE** — the specification describes something the library deliberately
  does differently, or no longer does.
- **SILENT** — the library has behaviour a peer can see that the specification
  does not describe.
- **AMBIG** — the specification can be read two ways.
- **INTERNAL** — the specification contradicts itself.

| Chapter | Rows | CODE | STALE | SILENT | AMBIG / INTERNAL |
| --- | --- | --- | --- | --- | --- |
| A. Introduction, actor, `/meta` | 21 | 8 | 0 | 6 | 7 |
| P. `/properties` | 20 | 9 | 0 | 9 | 2 |
| O. Optional endpoints and `/mcp` | 25 | 6 | 4 | 10 | 5 |
| T. `/trust` | 26 | 8 | 4 | 8 | 6 |
| S. `/subscriptions`, establishing to updates | 29 | 12 | 3 | 8 | 6 |
| C. Callbacks, limits, security | 23 | 13 | 0 | 7 | 3 |
| **Total** | **144** | **56** | **11** | **48** | **29** |

(A row with two kinds is counted under the first; A21 conforms in spirit and
is counted in the last column.)

Five findings break interoperability with a peer built from the specification
alone:

- **T1.** The trust verification field is `verification_token` on the wire; the
  specification says `verificationToken`. Verification fails in both
  directions.
- **P1 to P4.** None of the specification's list-item URLs works.
  `POST /properties/notes` writes the body's keys as unrelated root
  properties and answers 201; `GET`, `PUT` and `DELETE` on
  `/properties/notes/N` return the whole list, 400 and 404.
- **S9.** A subscription on a subtarget, the form the specification mandates
  for lists, has its diffs stored by the library's receiver as scalars named
  `list`, `operation`, `var1`.
- **S1.** A delete produces no diff, no sequence number and no gap for a
  subscriber at the deleted level or below.
- **S16.** A publisher that answers a subscription request with only what the
  specification requires (201 and `Location`) is rejected by the library as
  subscriber, which needs `subscriptionid` in a body the specification does
  not define.

Three findings are security-relevant rather than conformance-only:

- **S8b.** Stored diffs are not permission-filtered; a poll, or the
  low-granularity fetch, returns values a callback would have withheld.
- **T2.** The permission query endpoint lets an approved peer read another
  peer's permissions and refuses some peers their own.
- **T8.** Trustee bearer access does not require the trust relationship the
  specification makes a precondition.

One finding is about the library's own documentation: almost all of the
back-pressure, compression, payload-limit and granularity-downgrade behaviour
the specification describes lives in `FanOutManager` (`actingweb/fanout.py`),
which the publish path (`register_diffs` → `callback_subscription`) never
calls. `docs/quickstart/deployment.rst:118-122` and
`docs/guides/subscriptions.rst:833` describe it as if it were live.

## Findings

Paths are relative to `actingweb/` unless they start with `docs/`, `tests/` or
`thoughts/`. "Spec" is the line in `docs/protocol/actingweb-spec.rst`.

### A. Introduction, the actor, `/meta` (spec 1-780)

| ID | Spec | Requirement | Library | Kind | Side that looks wrong | Recorded |
| --- | --- | --- | --- | --- | --- | --- |
| A1 | 560-562 | Actors MUST implement instantiation through a factory | `with_open_factory(False)` answers 403 (`handlers/factory.py:215-225`); default open | CODE, opt-in | Library, on purpose; the spec has no OAuth-only exception | `interface/app.py:354-355`, `docs/migration/v3.16.rst:59-60` |
| A2 | 748-761 | `/meta` example nests `"actingweb": {version, supported}` | Flat object: `id`, `type`, `version`, `desc`, `info`, `trustee_root`, `specification`, `aw_version`, `aw_supported`, `aw_formats`, `aw_trust_types` (`handlers/meta.py:22-46`); `tests/integration/test_basic_flow.py:131-137` accepts both | CODE or STALE | Undecided; the flat shape is what every deployed actor emits | None |
| A3 | 740, 754 | `/meta/actingweb/version` MUST return the spec version supported | `"1.0"` (`config.py:426`), while serving 1.2 to 1.4 behaviour | INTERNAL + CODE | Both: the spec's header says 1.4 and its examples say 1.0 | See "The announced version" |
| A4 | 734 | `/meta/version` is the mini-application's version, "a.b.c … digits 0-9" | The library's own package version (`interface/app.py:1456`, `__init__.py:31`), e.g. `3.15.1`, pre-releases included; the builder has no application-version setting | CODE (meaning), STALE (format) | Library for meaning; spec for the single-digit rule | None |
| A5 | 732-744 | Scalar `/meta/*` paths return `text/plain` | No `Content-Type` set (`handlers/meta.py:58-77`); Flask defaults to `text/html` (`flask_integration.py:714-718`); inferred, no test | CODE | Library | None |
| A6 | 738 | `/meta/info` returns 302 with `Location` | 200 with the URL as body (`handlers/meta.py:66-67`) | CODE | Library | None |
| A7 | 584-586 | A create MUST return 201 with `Location`; the JSON body is OPTIONAL | JSON create conforms. Form create with the UI on answers 200 with a template and no `Location` (`handlers/factory.py:329-331`); with OAuth configured it redirects and creates nothing | CODE | Library, for non-JSON clients | Partly, `docs/migration/v3.16.rst:44-51` |
| A8 | 778 | Other `/meta` paths are reserved | Serves `/meta/trustee_root`, `/meta/specification`, `/meta/actingweb/trust_types` (a different shape from `/meta/trusttypes`); `/meta/desc` appends the actor id | SILENT | Either | None |
| A9 | 405-457 | The option-tag list | Lacks `permissioncallback`, `permissionquery`, `mcp`, `callbacks`, defined only later (2131, 2955, 1358, 623) | INTERNAL | Spec | n/a |
| A10 | — | — | `subscriptionbatch` is always advertised (`config.py:536`) and read by peers | SILENT | Spec | `thoughts/plans/2026-11-01-single-mode-and-consumer-primitives.md:139-143` |
| A11 | 2131, 623-627 | Advertise what is served | `permissionquery` and `permissioncallback` are advertised only with `peer_permissions_caching` (`config.py:551-555`); the endpoints answer regardless | CODE | Library | Same plan, D14 |
| A12 | 596-598 vs 2302 | Only creator or admin may delete an actor; a trustee has root access "like creator" | A trustee can delete (`config.py:342-344`) | INTERNAL | Spec | None |
| A13 | 584-590 | No duplicate-create rule | Duplicate creator 403, reserved creator 400, form create for an existing creator 302 to `/login` (`handlers/factory.py:257-305`) | SILENT | Spec | `docs/migration/v3.16.rst:85-92` |
| A14 | 584-590 | No response body defined | Create and `GET /<id>` return `{id, creator, passphrase[, trustee_root]}` | SILENT | Spec | None |
| A15 | 587-590 | 400 only for input problems | Every `create()` failure that is not a fault answers 400 "Not created" (`handlers/factory.py:306-317`) | CODE, minor | Library | None |
| A16 | 595-603 | DELETE, no status given | 204; wrong credentials 403; concurrent wipe 503; `GET ?_method=DELETE` unless cross-site | SILENT | Spec | `docs/migration/v3.16.rst:102-109` |
| A17 | 574-577 | Default creator "creator" with passphrase "secret" | Default creator yes; the passphrase is random (`actor.py:694-697`) | AMBIG | Spec | n/a |
| A18 | 744 | `formats` lists the OPTIONAL formats | Returns `"json"`, the mandatory one; form data is accepted and unlisted | AMBIG | Either | None |
| A19 | 405-407 | Mandatory and optional paths | Also serves `/login`, `/oauth/*`, `/.well-known/*`, `/<id>/app`, `/<id>/permissions/<peer>`, `/<id>/services`, `/bot`, `/mcp` | SILENT | Spec, informational | n/a |
| A20 | 2 vs 740, 754 | Header says 1.4, examples say 1.0 | n/a | INTERNAL | Spec | n/a |
| A21 | 534-538 | RECOMMENDED: UUID v5 of the base URI | v5 of URL + time + random, hex without hyphens (`config.py:511-512`) | Conforms in spirit | Neither | `actor.py:646-648` |

Option tags, complete: advertised and implemented — `trust`, `subscriptions`,
`actions`, `resources`, `methods`, `callbacks`, `nestedproperties`,
`listproperties`, `subscriptionresync`, `subscriptionbatch`, and conditionally
`www`, `oauth`, `trustpermissions`, `mcp`, `permissioncallback`,
`permissionquery`. Defined and neither advertised nor implemented —
`onewaytrust`, `sessions`, `proxy`, `callbackcompression`. Read from peers but
defined nowhere — `subscriptionhealth`, `subscriptionstats`
(`peer_capabilities.py:123-149`).

### P. `/properties` (spec 781-1105)

| ID | Spec | Requirement | Library | Kind | Side | Recorded |
| --- | --- | --- | --- | --- | --- | --- |
| P1 | 1027-1038 | `POST /properties/notes` appends; MUST return 201 | `handlers/properties.py:1075-1077` sets 400 without returning, then writes each body key as a root simple property and answers 201 (`:1716`, `:1726`). Two tests rely on this "append" (`tests/integration/test_subscription_baseline_storage.py:71-93`, `test_subscription_sync_coverage.py:321-327`) and in fact create a property named `value` | CODE | Library: a missing `return` | Partly, `thoughts/plans/2026-08-08-property-list-index-integrity.md:1009-1012` (calls `/items` an extension) |
| P2 | 1004-1005 | `GET /properties/notes/0` MUST return that item; 404 out of range | Returns the whole array; the item form is `?index=N` (`:342-344`) | CODE | Library | Same plan `:1043-1045` (out of scope) |
| P3 | 1042-1052 | `PUT /properties/notes/0` replaces; 404 beyond length; example answers 201 | 400 through the name-collision check (`:1024-1029`); `?index=N` replaces | CODE | Library | Same |
| P4 | 1063-1070 | `DELETE /properties/notes/1` removes and re-indexes | Always 404 (`:1853-1855`); item delete exists only through `/items` and the bulk POST | CODE | Library | Same |
| P5 | 912, 1052 | A successful PUT MUST return 201 | 204 everywhere (`:982`, `:1033`, `:892`), pinned by `test_basic_flow.py:192`, `:289`, `:353` | CODE | Either; 204 is what clients depend on | None |
| P6 | 1018-1022 | Name collision between a list and a property SHOULD be 409 | 400 on a nested PUT; 500 on single-segment PUT, POST of a simple key over a list, and list creation over a property (uncaught `ValueError`) | CODE | Library | None |
| P7 | 829-831, 842-843, 847-849 | Content type of a single value | Always `application/json`, with non-JSON text written raw (`:512-516`) | INTERNAL + CODE | Both | None |
| P8 | 937-938, 946 | POST: an error MUST change nothing and return 409; unsupported names 400 | Keys applied one by one, no rollback; hook-rejected keys skipped; 403 only when nothing was accepted | CODE | Library | Partly, same plan `:1040-1042` |
| P9 | 920-921 | PUT to an unsupported name MUST be 404 | Any name is accepted; a hook rejection answers 400 | CODE / AMBIG | Spec does not say how a name is "unsupported" | None |
| P10 | 822-823 | Actors MUST NOT apply logic on PUT or POST | Property hooks can transform and reject | AMBIG | Unclear | None |
| P11 | 1044-1045, 1070 | Out of range is 404 | `/items` and the bulk POST answer 400 | CODE | Library | `/items` is recorded as an extension; its codes are not |
| P12 | 951-1104 | — | A list is created only by `POST /properties {"name": {"_type": "list"}}` or a form field; the spec has no creation operation | SILENT | Spec | None |
| P13 | — | — | `?index=N` on GET and PUT | SILENT | Spec | Same plan `:1043-1045` |
| P14 | — | — | `/properties/<name>/items`, which also shadows a nested path ending in `items` or `metadata` | SILENT | Spec | Same plan `:1009-1014` |
| P15 | — | — | 409 `list_corrupted` with `detail` and `remedy` | SILENT | Spec | Same plan `:1035-1039` |
| P16 | — | — | 413 `list_item_too_large`; 503 `list_metadata_contended` with `Retry-After`; 503 on a database fault | SILENT | Spec | `CHANGELOG.rst:840`, `:1405` |
| P17 | 863-887 | Root `format` responses | A corrupted list appears as an error object inside the root listing, or turns the whole GET into 409 | SILENT | Spec | Partly |
| P18 | 1082-1087 | Metadata GET shape | Adds `"_list": true`; PUT validation codes | SILENT | Spec, minor | None |
| P19 | 797-800 | Methods | `DELETE /properties` clears everything; `DELETE` of a missing name answers 204; `PUT /properties` raises `IndexError` (500); `GET ?_method=PUT` writes | SILENT | Spec | None |
| P20 | 854-856, 1012 | Authorization | The root GET drops denied names silently rather than answering 403; a hook returning `None` answers 404 | SILENT | Spec | None |

The region says nothing about which subscription diff a `/properties`
operation produces; that is in chapter S.

### O. Optional endpoints and `/mcp` (spec 1106-1405)

| ID | Spec | Requirement | Library | Kind | Side | Recorded |
| --- | --- | --- | --- | --- | --- | --- |
| O1 | 1156-1158 | Unauthenticated `/callbacks` requests MUST return 401 | A generic `/callbacks/<x>` answers 200 with an empty body and runs nothing (`handlers/callbacks.py:433-440`, `base_handler.py:385-386`); an unknown subscription answers 404. Traced, no test | CODE | Library; the spec's "anonymous POST" carve-out at 1155 also clashes with its own MUST | None |
| O2 | 1158-1159 | Unknown `/callbacks` URI with credentials SHOULD be 403 | 200 with body `false`: the handler tests `is not None`, the registry returns `False` (`:465`, `interface/hooks.py:706-709`) | CODE | Library | None |
| O3 | 1129 | A successful action MUST return 201 | 200 (`handlers/actions.py:230`, `:292`) | CODE | Library | None |
| O4 | 1292-1296 | `/www/init` MUST present a form posting to `/properties`, with HTTP Digest | No Digest anywhere; the library's template has no form | CODE or STALE | Spec looks stale | None |
| O5 | 1323-1333, 434-435 | `/oauth` handles the per-actor OAuth2 flow | No `/<id>/oauth` route; `CallbackOauthHandler` is unrouted; the `oauth` tag means "a login provider is configured" (`config.py:545-546`); the default `redirect_uri` is the unrouted `/oauth` (`config.py:363-364`) | STALE | Spec | `CHANGELOG.rst:5914`; D14 of the 2026-11-01 plan |
| O6 | 1345-1347 | `/resources` map to MCP resources | MCP resources come from method hooks (`handlers/mcp.py:1515`, `:1940`) | STALE | Spec | None |
| O7 | 1355, 1379 | MCP access control "identically" to REST | MCP is fail-closed with its own `tools` category; REST `/actions` falls back to the ACL | INTERNAL | Spec: 2150-2160 define separate categories | `CHANGELOG.rst:3684` for MCP |
| O8 | 1354 | Transport follows MCP | No batches, no SSE on GET, `listChanged` advertised and never sent, `resources/templates/list` unimplemented | CODE, against MCP | Library, all recorded | `thoughts/todo/mcp-batch-receive.md`, `mcp-oauth-connector-conformance-followups.md` |
| O9 | 1373 | SHOULD validate arguments | `tools/call` passes arguments to the hook unvalidated (`handlers/mcp.py:1653`) | CODE | Library | Partly, a roadmap item |
| O10 | 1357, 1368 | Bind each MCP session to one actor | No server-side session; the actor is resolved per request from the bearer token | AMBIG | Spec | `thoughts/todo/mcp-2026-07-28-dual-era-support.md:129-133` |
| O11 | 1360-1368 | Path, transport and auth are implementation-defined | Root `/mcp` only; Bearer; 401 with `WWW-Authenticate` and `-32002`; 503 with `Retry-After` on a token-store fault; 404 when disabled; 202 for notifications; `-32003` when no trust | SILENT | Neither; no profile a second implementation could follow | — |
| O12 | 1354 | — | Revisions `2024-11-05` to `2025-11-25`; an unsupported header answers 400 `-32600` | SILENT | Neither | Same dual-era todo `:91-106` |
| O13 | 1354 | — | `structuredContent` only at `2025-06-18` and later | SILENT | Neither | The 2026-05-26 plan |
| O14 | 1304-1333 | — | The whole root OAuth surface: `/login`, `/oauth/callback`, `/oauth/register`, `/oauth/authorize`, `/oauth/token`, `/oauth/revoke`, `/oauth/spa/*`, the `.well-known` documents, refresh rotation with grace, `/<id>/services/<name>/callback` | SILENT | Spec | Known gaps in the connector-conformance todo |
| O15 | 1235-1268 | `/sessions` (OPTIONAL) | Not routed, no tag | SILENT | Neither | `thoughts/todo/sessions-endpoint-and-advertised-options.md` |
| O16 | 1209-1210 | `_method` on POST for `/resources` | `_method` is honoured on GET, on other endpoints, not on `/resources` | STALE | Spec | None |
| O17 | 1218-1230 | `GET /methods/x?param=…` may carry parameters | The hook receives only `{"method": "GET"}` (`handlers/methods.py:163-165`) | STALE | Spec's example cannot work | None |
| O18 | 1217-1233 | `/methods` has no restrictions | JSON only; JSON-RPC 2.0 with `-32600`/`-32601`/`-32603` at HTTP 200; `None` from a hook is 400 on POST, 404 on GET | SILENT | Spec | None |
| O19 | 1121-1123 | Actions respond to POST | JSON only; unknown action 400 on POST, 404 on GET; unauthenticated 403 rather than 401 | AMBIG | Spec | None |
| O20 | 1133-1139 | Action instance URL and DELETE cancel | No `Location`, so no instance URL | SILENT | Neither | — |
| O21 | 1202-1210 | `/resources` method semantics | Dispatches to `resource_<name>` hooks; unhandled 404; POST 201 | SILENT | Neither | — |
| O22 | 1287-1288 | `/www` unrestricted | An unknown `/www/<x>` answers 200 with body `False` (the same `None`/`False` mismatch as O2) | SILENT | Neither by the spec's terms | — |
| O23 | 1279-1285 | — | Browser redirects to `/login`, `/www`, `/app` (the library registers no `/app` route) | SILENT | Neither | `docs/reference/routing-overview.rst` |
| O24 | 1358, 1393 | MCP MUST be indicated by a tag | `mcp` is advertised; the tag list does not define it | INTERNAL | Spec | D14 |
| O25 | 1395-1399 | `trustpermissions` SHOULD be included | Conforms; the sentence sits in the MCP chapter | AMBIG, placement | Spec | — |

### T. `/trust` (spec 1406-2341)

| ID | Spec | Requirement | Library | Kind | Side | Recorded |
| --- | --- | --- | --- | --- | --- | --- |
| T1 | 1584-1586, 1701 | The verify GET returns the secret in `verificationToken` | Reads and writes `verification_token` (`actor.py:1975-1977`, `db/dynamodb/trust.py:174`) | STALE | Spec | None |
| T2 | 2036-2042 | `GET /permissions/{peerid}`: only that peer | Role rows decide (`config.py:316-319`); the peer id is compared only for `owner` rows (`auth.py:800-804`). Any approved associate, friend, partner or admin peer can read another peer's; `viewer`, `mcp_client` and custom types are refused their own | CODE | Library | None |
| T3 | 1636-1644 | Pending 202, refused 403, approved 201, for the peer's bearer GET | Pending answers 403; approved 200; there is no refused state (`handlers/trust.py:590-609`) | CODE | Library for pending; 200 vs 201 may be stale spec | None |
| T4 | 1533-1536 | Creator and admin get the same codes as the owner of the relationship | Creator gets 202 with a body on a pending row; the peer gets 403 | CODE | Library | None |
| T5 | 1486-1490 | `GET /trust/<type>` MUST (then MAY) be supported | Always 404; filtering is by query string on `/trust`, and `?type=` filters on the peer's mini-app type | CODE / INTERNAL | Both | None |
| T6 | 1881-1882 | At most one relationship per peer | A repeated `POST /trust/<rel>` for an existing peer replaces the row, secret included (upsert on both backends); no 409 | SILENT | Spec | Test docstring only |
| T7 | 1440-1442 | Either side can revoke unilaterally | An owner DELETE without `?peer=true` answers 502 and keeps the row when the peer cannot be reached | STALE | Spec, against a deliberate design | `thoughts/reference/trust-row-deletion-invariants.md:38` |
| T8 | 2307-2310 | A trustee relationship MUST exist before trustee bearer access | Granted on `trustee_root` + creator "trustee" + passphrase length; no trust row is checked (`auth.py:240-265`) | CODE | Library | None |
| T9 | 2298-2305 | Passphrase strength over 80 bits; trustee endpoints | Strength is length × log2(94); the trustee also gets `/services` | AMBIG / SILENT | Spec | None |
| T10 | 1594-1605, 1571-1573 | `secret`, `baseuri`, `id`, `type` MUST be sent; immediate refusal 403 | Only `baseuri` and `id` are required; a missing `secret` is generated; the `trust_request_received` hook fires after the row is written | AMBIG | Spec states only the sender's duty | None |
| T11 | 1538-1562 vs 1494 | All fields MANDATORY, including `secret`; the list MUST NOT include it | The list omits secret and token; a single GET includes both | INTERNAL | Spec | `CHANGELOG.rst:2325-2332` |
| T12 | 1785-1790 | OAuth2 metadata only on OAuth2 trusts | `created_at`, `last_accessed`, `established_via`, `last_connected_via`, `last_connected_at`, `aw_supported`, `aw_version`, `capabilities_fetched_at` appear on ordinary trusts | STALE / SILENT | Spec | None |
| T13 | 1555-1559 | `verified`, `approved`, `peer_approved` are Bool | The two creation responses carry the strings `"true"`/`"false"` (`trust.py:428-430`) | CODE | Library | None |
| T14 | 1747-1751 | PUT updates `baseuri`, `desc`, `approved` | Only `approved: true` is applied; a JSON `false` raises `AttributeError` and answers 500 (`handlers/trust.py:736-743`) | CODE / SILENT | Library | None |
| T15 | 1612-1629 | The POST answers a bare 202 | Returns the whole new row, with `secret` and its own `verification_token` | SILENT | Spec | None |
| T16 | 1665-1673, 1739-1743 | The approval notification carries `{"approved": True}`; refusals too | Only approvals are notified; the receiver needs a JSON boolean `true` | INTERNAL / SILENT | Spec (`True` is not JSON) | None |
| T17 | 1844-1847 | Initiate: 201 with `Location` | Every failure answers 408 | SILENT | Spec | `thoughts/verifications/2026-10-31-spanned-list-items-7.md:93-96` (open) |
| T18 | 1866-1896 | Types: associate, friend, partner, proxy, admin | Registry defaults: associate, viewer, friend, partner, admin, mcp_client; any name is accepted; a row named `trustee`, `admin` or `creator` takes that role's access | SILENT / STALE | Spec | None |
| T19 | 2105-2109 | Permission query errors | An unregistered type answers 500 on one endpoint and 404 on the other; only PUT checks the trust row exists | SILENT | Spec, and the two endpoints differ | None |
| T20 | 2017-2020, 2164-2182 | "The GET permissions endpoint" returns effective permissions | `/trust/<rel>/<peer>/permissions` is flat and unmerged; `/permissions/<peer>` is nested and merged | AMBIG | Spec | None |
| T21 | 2131-2132 | When to advertise the two permission tags | See A11 | SILENT | Spec | The 2026-11-01 plan `:142` |
| T22 | 2237-2243 | Default to deny when no rule matches | `NOT_FOUND` is treated as allow on property reads (`handlers/properties.py:582-584`, `interface/authenticated_views.py:537`) | CODE | Library | None |
| T23 | 2334-2340 | Creator MUST use basic auth | An OAuth2 or SPA bearer whose email matches the creator is the creator; an invalid bearer answers 403, not 401 | STALE / SILENT | Spec | None |
| T24 | 1704, 1711, 1714 | Step numbering and URI in the second sequence table | n/a; the library follows the first table | INTERNAL | Spec | None |
| T25 | 2284-2290 | Trustee set by PUT | The trustee can change its own root; 204, 400, 409; DELETE clears it | SILENT | Spec | The 2026-10-28 plan `:757` |
| T26 | — | — | 503 with `Retry-After` on a fault; `?permissions=true`; `/trust/<rel>/<peer>/shared_properties` | SILENT | Spec | `thoughts/reference/trust-row-deletion-invariants.md:11-12` |

Not determined: whether a non-admin peer can PUT its own trust row (the code
comment and `CHANGELOG.rst:399-400` say yes; a trace through
`base_handler.py:388-390` says 403; no test).

### S. `/subscriptions`: establishing, enumerating, getting updates (spec 2342-2908)

| ID | Spec | Requirement | Library | Kind | Side | Recorded |
| --- | --- | --- | --- | --- | --- | --- |
| S1 | 2609-2610, 2536-2537 | A DELETE MUST send `""` as a diff | `add_diff` refuses an empty blob before taking a sequence number (`subscription.py:155-157`). A subscriber on the deleted subtarget or below gets nothing; a `/properties` subscriber gets `{"name": ""}`. REST sends `""`, the interface layer sends `'""'`, which is delivered | CODE | Library | None for simple properties |
| S2 | 2531-2533, 2497-2499 | Every subscription in scope MUST get a diff | A resource-level subscriber gets nothing when its parent is overwritten without that key (`actor.py:3959-3965`); pinned by `tests/integration/test_subscription_flow.py:778-782` | CODE | Library | None |
| S3 | 2424-2425 | The actor MUST record and act on any change | Web-UI edits register no diff: property create and update (`handlers/www.py:1498`), list create (`:1416-1434`), item add, update, delete (`:1151`, `:1238`, `:1259`, `:1309`, `:1328`), metadata (`:1057-1059`) | CODE | Library | No |
| S4 | 2509-2513 | The diff follows the hierarchy | Paths of three or more segments are collapsed to the resource level; the diff misstates the change | CODE | Library | None |
| S5 | 2497-2499 | The diff is the new representation | A REST PUT registers the request body, not the hook-transformed value that was stored (`handlers/properties.py:981`, `:985`) | CODE | Library | None |
| S6 | 2770-2771 | The timestamp of the update | On DynamoDB every diff carries the process start time: `default=datetime.datetime.utcnow()` is evaluated at import (`db/dynamodb/subscription_diff.py:34`) | CODE | Library | None |
| S7 | 2758 | Timestamp format `…T…Z` | The callback sends `str(datetime)` (space, no `Z`); the poll endpoints use the ISO form | CODE | Library | None |
| S8a | 2383-2386 | The publisher MUST validate read access when a subscription is created | Creation checks the ACL only | STALE | Spec | `CHANGELOG.rst:5619` |
| S8b | same | — | The permission filter runs only when a callback is sent (`actor.py:2636-2644`); `add_diff` stores the unfiltered diff (`:4040`) and both poll endpoints return it. A callback filtered to nothing uses a sequence number and sends nothing | CODE | Library | No |
| S9 | 2523-2529, 2620-2622 | A subtarget subscription's diff is relative to the subtarget | The receiver hands the diff to `apply_callback_data` without re-nesting (`handlers/callbacks.py:516`, `:649`); each top-level key becomes a stored property | CODE | Library, receiving side | None |
| S10 | 2679-2736 vs 2523-2529 | Every list example is wrapped in the list's name; the hierarchy rule says a subtarget subscriber gets it unwrapped | The library sends unwrapped to a subtarget subscriber, wrapped to a target one | INTERNAL | Spec | None |
| S11 | 2885-2887, 2895-2896 | Repeated GETs MUST give the same result | `GET …/<seqnr>` deletes the diff it returns | STALE | Spec, if kept | `CHANGELOG.rst:6670`, `:1677` |
| S12 | 2829-2832 | Any 2xx means received and the diff MUST be cleared | A 204 does not clear; high-granularity diffs stay until a poll clears them | STALE | Spec | `thoughts/reference/2026-01-29-subscription-callback-flows.md:212-236` |
| S13 | 2892-2894 | Diffs at or below the sequence MUST be cleared | `{"sequence": 0}` clears everything on both backends | CODE | Library | None |
| S14 | 2539-2541 vs 3207-3208 | A number per diff, vs numbers continue under back-pressure | Sequence numbers are used without a diff in three cases | INTERNAL | Spec | `CHANGELOG.rst:1871-1890` |
| S15 | 2424-2425 | — | Suspension: no diff and no number while suspended, a resync on resume | SILENT | Spec | `CHANGELOG.rst:1892-1898` |
| S16 | 2389-2391 | 201 with `Location`; no body defined | As subscriber the library requires `subscriptionid` in a JSON body and otherwise fails with 408 (`actor.py:2416-2422`) | SILENT | Either | None |
| S17 | 2389-2391 | A relative `Location` | Absolute | CODE, minor | Either | None |
| S18 | 2539, 2461 | The sequence is 1 for a new subscription | A new subscription shows `"sequence": 0`; the first diff is 1 | AMBIG | Spec | None |
| S19 | 2375-2381 | Granularity high, low or none | Not validated; any other value sends a callback with neither `data` nor `url` | SILENT | Either | None |
| S20 | 2446-2448 | `peerid` at the root, not per element | Both; elements also carry `id` and `callback`, and the list holds both directions | CODE, minor | Either | None |
| S21 | 2433-2438 | `POST /subscriptions` MUST be supported | 204 "Created" with `Location`; 408 on failure; a repeat creates another subscription | SILENT | Spec | None |
| S22 | — | Deletion | Authorised as GET; notifies the peer; cleanup on both sides | SILENT | Spec | None |
| S23 | 2646-2651 | `index` is the index affected | Negative indices are passed through by the sender (`pop` sends −1 by default) | AMBIG | Spec | Receiver side is planned |
| S24 | 2633-2635 | `metadata` has no stated meaning | Emitted for description edits, without the text, and for `compact`, `repair_keys`, `sweep_span_orphans`, `migrate_to_v2` | SILENT | Spec | None |
| S25 | 2536-2537 | Only `""` means deleted | `null` is treated as a delete by the receiver | SILENT | Spec | None |
| S26 | 2746-2750 | The callback goes to "the subscription URI" | `…/callbacks/subscriptions/<id>/<subid>` | AMBIG | Spec | None |
| S27 | 2847-2856 | The low-granularity example | Invalid JSON | INTERNAL | Spec | None |
| S28 | 2829-2837 | Only 2xx defined | The receiver also answers 503 `callback_in_progress` with `Retry-After`, 400, 404, 403; a missing `sequence` is treated as 0 | SILENT | Spec | `CHANGELOG.rst:1662-1666` |

### C. Resync, permission callback, delivery, limits, back-pressure, compression, overlap, security (spec 2909-3375)

| ID | Spec | Requirement | Library | Kind | Side | Recorded |
| --- | --- | --- | --- | --- | --- | --- |
| C1 | 3283-3289 | One callback per change; the most specific subscription | Every matching subscription gets its own diff and callback (`actor.py:3916-4059`). Two overlapping subscriptions from one peer land in the same `RemotePeerStore`, and a list `append` is applied twice | CODE | Library | None |
| C2 | 3177-3222 | Circuit breaker, 429 and 503 handling SHOULD exist | The live sender only logs the status (`actor.py:2712-2720`). The breaker and `Retry-After` handling are in `FanOutManager`, which nothing calls | CODE | Library; its docs also describe it as live | None for the live path |
| C3 | 3193-3196 | 503 means the receiver is unavailable; stop all callbacks to the actor | The library as receiver answers 503 for per-callback conditions (a claim in progress, a failed diff fetch, a store fault) | SILENT / AMBIG | Spec | `CHANGELOG.rst:1655-1692` |
| C4 | 3141-3150 | A payload over the limit MUST become a resync or low granularity | No size limit on the live path; scalar diffs are never capped; the span threshold (390,000 bytes, DynamoDB only) covers list diffs and is above the RECOMMENDED 256 KB | CODE | Library | None for scalars |
| C5 | 3152-3157 | A large `extend` SHOULD be split | Never split; over the threshold it becomes a reference | CODE | Adjacent to the reference form | `CHANGELOG.rst:1049-1063` |
| C6 | 2941-2946 | On a resync: discard cached state; GET the `url` | The receiver rebuilds the path instead of using `url`, and overwrites only the keys it receives, so deleted keys stay | CODE | Step 2 library; step 1 deliberate | `remote_storage.py:525-531` |
| C7 | same | — | A failed baseline fetch is applied as `{}` and the sequence moves on | CODE | Library | `thoughts/todo/subscription-subscriber-fault-hardening.md:80-88` |
| C8 | 2912-2915, 3122-3123 | `subscriptionresync` as a sender capability | The library reads it as the receiver's capability and sends a resync optimistically when the cache is cold | INTERNAL / AMBIG | Spec | None |
| C9 | 2375-2381 | `none` suppresses callbacks | A `none` subscription still gets a resync POST on resume | CODE | Library | None |
| C10 | 3048-3052 | Permission callbacks on a type-default change and on revocation | Sent only when a grant is stored; `delete_permissions` and type-default changes send nothing | CODE | Library | None |
| C11 | 3066-3069 | An older callback SHOULD be ignored | The store step ignores it; deletion of revoked data and the hook run anyway | CODE | Library | Delete-first is `CHANGELOG.rst:1202-1211`; staleness is not |
| C12 | 2955 | The `permissioncallback` tag | The sender never checks the peer's tags; the config comment contradicts the code (`config.py:166`, `trust_permissions.py:175-187`) | AMBIG | Spec | None |
| C13 | 3001-3028, 3062 | The permission body and 204 | Body has an `actions` category the example lacks; also 400, 403, 404, 500, 503 | SILENT | Spec | None |
| C14 | 3125-3127 | On a gap the receiver SHOULD poll | It queues and waits; a poll starts only when a later callback arrives after the timeout | CODE | Library | Partly, the same todo `:30-35` |
| C15 | 3172-3191 | 429 as the back-pressure signal | Never sent; a full pending queue answers 400. `docs/guides/subscriptions.rst:833` says 429 | SILENT | Library docs | None |
| C16 | — | — | Gap timeout 5 s, 100 pending, claim lease 60 s | SILENT | Spec | `CHANGELOG.rst:1655-1692` |
| C17 | 3227-3262 | Compression; receivers MUST handle both | Tag never advertised; no inbound decompression; `FanOutManager` checks the wrong tag name (`fanout.py:502`) | AMBIG + CODE | Spec must say whom the MUST binds | The 2026-11-01 plan `:143-145` |
| C18 | 3093-3096 | The downgrade `url` points at the diff | `FanOutManager` points at the resource | CODE, unused class | Library | None |
| C19 | 3218-3219 | A failed probe extends the cooldown | Same cooldown | CODE, unused class | Library | None |
| C20 | 2922-2946 | The resync body | `subtarget` is `null` when unset; `resource` never sent; 200 counts as delivered | SILENT | Spec | None |
| C21 | 3106-3107 | No automatic retry | `resume_subscriptions()` re-sends to subscribers that missed, on the next explicit call | SILENT | Neither | `CHANGELOG.rst:1223-1228` |
| C22 | 3207-3208 | Sequence numbers continue; diffs stay available | A write whose diff cannot be registered answers 503; a low-granularity diff is deleted by its fetch | SILENT | Spec | `CHANGELOG.rst:1213-1221` |
| C23 | 3360-3364 | `_method` MUST be supported | Honoured on GET only, and only for some methods per handler; refused cross-site since 3.16 | CODE + SILENT | Library for coverage; spec for the refusal | `docs/reference/security.rst:28-46` |

Also in the region: 3337-3341 says "three elements" and lists four (INTERNAL);
3332 calls https "MANDATORY", which is not an RFC 2119 keyword (AMBIG); the
security chapter does not mention the 3.16 cross-site refusal, creator
uniqueness, deletion tombstones, the `X-ActingWeb-Error` header or 503 with
`Retry-After` on store faults (SILENT).

## The announced version

- Set at `config.py:426` (`self.aw_version = "1.0"`); served as text at
  `/meta/actingweb/version` (`handlers/meta.py:72-73`) and as `aw_version` in
  the `/meta` object (`:30`). Nowhere else on the wire.
- A peer's value is fetched by `PeerCapabilities.refresh()`
  (`peer_capabilities.py:199-203`), stored on the trust row (`aw_version`, a
  string column on both backends) and read only by `get_version()`
  (`:151-156`).
- No library code compares or branches on a version. Capability decisions use
  option tags (`peer_capabilities.py:103-113`).
- Two assertions pin `"1.0"`: `tests/integration/test_basic_flow.py:134` and
  `:150`. Test fixtures elsewhere already use `"1.4"` as a peer's value.
- The specification says the value is "the version number of this
  specification that the mini-application supports" (740) and nothing about
  how a peer treats a higher, lower or unknown one.
- Not determined: whether `../actingweb_mcp`, `../actingwebdemo` or another
  peer compares against `"1.0"`.

## Already planned

`thoughts/plans/2026-11-06-attribute-list-v2-port.md` covers: REST and web-UI
list edits emitting the list-diff format; `delete_all` for a whole-list delete;
an empty `extend` for list creation; `clear` then `extend` for a full state sent
to a peer without resync support; the `spanned`/`bytes` reference form written
into the specification; `pop` with a negative index on the receiver.

After its review that plan also took, from this sweep: S3 (every web-UI
write registers its diff, lists and simple properties), S8b (a diff is
permission-filtered before it is stored), S9 (the receiver applies a diff
relative to the subscription's subtarget), and the receiver half of S23
(negative indices). It declined C1 (two overlapping subscriptions apply a list
`append` twice) and left it to the specification plan.

`thoughts/plans/2026-11-06-subs-list-cache-lifetime.md` covers a finding the
sweep did not list: a peer with a `friend` relationship can address another
peer's subscriptions over REST (`config.py:336`), and the authenticated view
lists every peer's.

The medium-sized library fixes that remain for the specification plan are S1,
S2, S4, C1, C6 and C7.

## Proposed dispositions

The owner's direction (2026-11-06): version 1.5 is full conformance, and the
library is the working code, so the specification follows the library unless
a deviation is a defect. Each library deviation is classified:

- **Defect** — the behaviour does not deliver the function either document
  intends (a bug, a silent loss, a wrong answer). The library is fixed; the
  specification keeps or sharpens its rule.
- **Necessity** — the library's behaviour is what makes the function work, or
  is a recorded decision with a reason. The specification is rewritten to it.
- **Taste** — either would work. The library is deployed, so the
  specification is rewritten to it.

Every STALE, SILENT, AMBIG and INTERNAL row is a specification edit that
describes what the library does, with five exceptions listed after the table.

| ID | Class | Resolution | Size of a library fix |
| --- | --- | --- | --- |
| A1 | Necessity | Spec: the factory MAY be closed; a closed factory answers 403 | — |
| A2 | Taste | Spec: `/meta` returns the flat object | — |
| A3 | Defect | Library announces `1.5`; spec examples follow | Small |
| A4 | Defect (meaning), taste (format) | Library: the application sets its own version; spec: any dotted version string | Small |
| A5 | Defect | Library: `text/plain` on scalar `/meta/*` | Small |
| A6 | Taste | Spec: `/meta/info` returns the URL as text | — |
| A7 | Necessity | Spec: the 201 and `Location` rule is for API clients; a browser form may be answered with a page or a redirect | — |
| A11 | Defect | Library: advertise `permissionquery` and `permissioncallback` whenever the endpoints answer | Small |
| A15 | Taste | Spec: a create that fails for a reason other than a store fault answers 400 | — |
| P1 | Defect | Library: `POST /properties/<list>` appends and answers 201 with `Location`; the two tests that rely on the stray write are corrected | Small |
| P2-P4 | Taste, with a defect inside | Spec: `?index=N` and `/items` are the item forms. Library: a path-addressed request on a list answers 404 instead of the whole list, 400 or a false 404. Owner check: the alternative is implementing the path forms as aliases | Small either way |
| P5 | Taste | Spec: a successful PUT answers 204 | — |
| P6 | Defect | Library: every name collision answers 409, none 500 | Small |
| P7 | Defect | Library: a non-JSON value is labelled `text/plain`; spec: one rule instead of two | Small; owner check on clients that expect `application/json` |
| P8 | Necessity | Spec: POST applies keys independently, lists what it accepted, 403 when nothing was | — |
| P9 | Taste | Spec: a rejected write answers 400 | — |
| P11 | Taste | Spec: `/items` and bulk updates answer 400 for an index out of range | — |
| O1 | Defect | Library: an unauthenticated `/callbacks/<x>` answers 401 | Small |
| O2 | Defect | Library: an unknown callback answers 403; the same `None`/`False` fix gives an unknown `/www/<x>` 404 (O22) | Small |
| O3 | Taste | Spec: a successful action answers 200 | — |
| O4 | Stale spec | Spec: drop Digest and the form requirement | — |
| O8 | Out of scope | The specification delegates transport to MCP; the gaps against MCP revisions stay in their todos | — |
| O9 | Taste | Spec: argument validation MAY be done by the implementation | — |
| T2 | Defect, security | Library: only the peer itself, the creator and admin read `/permissions/<peer>`; every relationship type can read its own | Small |
| T3, T4 | Taste | Spec: a pending relationship answers 403 to the peer, an approved one 200, a refused one is deleted (404); approval is notified by POST | — |
| T5 | Taste | Spec: `/trust` filters by query string; `GET /trust/<type>` is not defined | — |
| T8 | Necessity; owner check | Spec: trustee access is `trustee_root` set, creator `trustee`, and a passphrase of sufficient length; no trust relationship is required. Security-relevant, so the owner confirms | — |
| T13 | Defect | Library: booleans in both creation responses | Small |
| T14 | Defect | Library: `approved: false` answers 400 rather than 500; spec: PUT accepts `approved: true` and `permissions` | Small |
| T22 | Necessity; owner check | Spec: when no pattern matches, the relationship's access rules decide | — |
| S1 | Defect | Library: a delete is recorded and delivered as `""` at every subscription level, with a sequence number; REST and the interface layer use one representation | Medium |
| S2 | Defect | Library: a resource-level subscriber is sent `""` when its resource disappears with its parent | Medium |
| S3 | Defect | Library: every web-UI write registers its diff | Small (lists are in the `ListAttribute` plan; simple properties are not) |
| S4 | Defect | Library: a write below the resource level sends the resource's stored value | Medium |
| S5 | Defect | Library: the diff is the value that was stored, after hooks | Small |
| S6 | Defect | Library: each DynamoDB diff gets its own timestamp | Small |
| S7 | Defect | Library: callbacks send the ISO form the poll endpoints use | Small |
| S8b | Defect, security | Library: a diff is permission-filtered before it is stored | Medium |
| S9 | Defect | Library: the receiver applies a diff relative to the subscription's subtarget and resource | Medium |
| S13 | Defect | Library: `{"sequence": 0}` clears nothing (the internal "0 means all" default leaks through `handlers/subscription.py:428`) | Small |
| S16 | Necessity | Spec: the 201 body carries the subscription, `subscriptionid` included | — |
| S17 | Taste | Spec: `Location` is an absolute URI | — |
| S20 | Taste | Spec: elements carry `peerid`, `id` and `callback` | — |
| C1 | Necessity on the sender, defect on the receiver | Spec: each subscription is delivered independently. Library: a subscriber with overlapping subscriptions applies a change once, from the most specific one | Medium |
| C2, C4, C5, C17-C19 | Open | Waiting on the `FanOutManager` history; see "Open" below | — |
| C6 | Necessity (step 2), defect (step 1) | Spec: the receiver fetches from the peer's known base URI, not from `url`. Library: a resync removes keys in the subscription's scope that the baseline no longer has | Medium |
| C7 | Defect | Library: a failed baseline fetch does not advance the sequence (recorded in `thoughts/todo/subscription-subscriber-fault-hardening.md`) | Medium |
| C9 | Defect | Library: a `none` subscription gets no resync callback | Small |
| C10 | Defect (delete), taste (type default) | Library: deleting a grant notifies the peer; spec: a type-default change MAY notify | Small |
| C11 | Defect | Library: an older permission callback deletes nothing and runs no hook | Small |
| C14 | Necessity | Spec: a receiver MAY wait a short time for out-of-order callbacks before polling | — |
| C23 | Taste | Spec: `_method` MAY be supported on GET for browser forms and is refused cross-site | — |

Five rows that are not library deviations but are not plain specification
edits either:

- **T6** (SILENT, security-relevant). A repeated unauthenticated
  `POST /trust/<rel>` naming an existing peer id replaces the row, secret and
  base URI included. Proposed: the library answers 409; the specification says
  so.
- **T1** (STALE). The wire name is `verification_token`. Proposed: the
  specification follows; no alias.
- **A8** (SILENT). The extra `/meta` paths: define them in the specification,
  or stop serving the ones nothing reads.
- **S19** (SILENT). An unknown granularity value is accepted and produces an
  empty callback. Proposed: the library answers 400.
- **P19** (SILENT). `PUT /properties` raises and answers 500. Proposed: the
  library answers 405 or 400.

Totals under these proposals: 32 library fixes (21 small, 8 medium, plus T6,
S19 and P19), of which three are security fixes (T2, S8b, T6); every other
row is a specification edit. Four carry an owner check: P2 to P4 (as one),
P7, T8 and T22.

### Open

The back-pressure, payload-limit and compression rows (C2, C4, C5, C17 to
C19) depend on what is done about `FanOutManager`; see the next section.

## `FanOutManager`: history and the gap

The owner's question: "I thought the library implemented what is needed to
scale, so we need to understand the gap."

### History

| When | What |
| --- | --- |
| 2026-01-18 | `thoughts/research/2026-01-18-library-extraction-candidates-from-actingweb-mcp.md:543-590` flags the publish loop as CRITICAL: "Callbacks are sent **sequentially**… **Sequential network I/O** blocks the caller… **No backpressure**", and recommends a `FanOutManager` |
| 2026-01-20 | `thoughts/plans/2026-01-20-auto-subscription-handling.md`, Phase 4 (`:1984-1987`): "Implement scalable callback delivery with parallel requests, circuit breakers, and automatic granularity downgrade for large payloads" |
| 2026-01-22 | Commit `876fa1a` (PR #65) adds `actingweb/fanout.py`, exports it, adds four fan-out settings to the subscription config, adds unit tests |
| 2026-03-21 | First release containing it, `v3.10.0` |
| 2026-10-29 to 2026-11-03 | Unreleased 3.16 work on the class only: a breaker whose saved state cannot be read skips the delivery (`4275401`); the in-progress 503 does not count against the breaker; the docstrings say the breaker is per process |

It was never wired in. `git log --all -S"deliver_to_subscribers"` and
`-S"FanOutManager("` find no commit that calls it from `actor.py`,
`handlers/`, `interface/` or `subscription.py`. No step of the January plan
changes `register_diffs` or `callback_subscription`; its Phase 5 ("Integration
Layer", `:2437-2765`) connects only the receiving side, and its "Remaining
Work" lists only end-to-end testing. The four settings Phase 5 added
(`subscription_config.py:40-44`, documented at `interface/app.py:1367-1370`)
are read by nothing.

It also could not be dropped into the publish path as written:
`deliver_to_subscribers(subscriptions, payload, target, sequence)` takes one
sequence number for all subscribers (`fanout.py:341-347`), while each
subscription has its own (`subscription.py:148-168`); it expects `subid` and
`callback_url` keys the stored rows do not have (`fanout.py:372-374`); it does
no permission filtering and stores no diff.

### What the live path does

- **Sending is serial and synchronous in the common case.** The properties
  handler has no async methods, so under FastAPI it runs in a pool thread
  with no event loop, and `callback_subscription` falls back to a blocking
  `requests.post(…, timeout=(5, 10))` (`actor.py:2703`, `:2788-2793`). Flask
  has no loop at all. So for a REST property write, S subscribers delay the
  HTTP response by the sum of S round trips, each including the receiver's
  own processing, whatever `with_sync_callbacks` says. The fire-and-forget
  branch (`:2743-2787`) runs only when the caller is already on the event
  loop; it creates one unbounded task and one HTTP client per callback and
  keeps no reference to the task.
- **A failed or slow subscriber** is logged (`:2706-2729`). No retry, no
  back-off, no breaker, no size cap. The sender does nothing with a 429 or a
  503 except log it.
- **What makes that survivable:** every diff is stored before the POST
  (`:4040`) and stays until the subscriber acknowledges or fetches it, so a
  missed callback is recoverable by polling; `granularity` `low` and `none`
  let a subscriber opt out of bodies or of callbacks; `suspend_subscriptions`
  and `resume_subscriptions` (`:3017-3108`) let an application stop diffs and
  callbacks around a bulk change and send one resync afterwards (the consumer
  does this around imports, `../actingweb_mcp/api/memory_import.py:434`,
  `:584`); and since 3.16 a list diff over the span threshold is sent as a
  reference.
- **What a write costs per matching subscriber:** one subscription read, one
  sequence-increment write, one diff-row write, one trust read, a permission
  check per top-level key, and the POST.
- **The receiving side** exerts back-pressure the sender ignores: a full
  pending queue answers 400, a sequence already claimed answers 503 with
  `Retry-After: 5`.
- **The 3.13 scalability work** covered storage (Scan to Query, table guards,
  the reorder that saves a read per write). It did not touch callback
  fan-out.

### The gap

| The specification describes | In `FanOutManager` | On the live path | What covers it instead |
| --- | --- | --- | --- |
| A payload limit, with downgrade to low granularity or a resync (3141-3150) | Yes, above 64 KB (`fanout.py:486-491`), with a wrong URL | No | The subscriber's own choice of `low`; references for list diffs over 390,000 bytes on DynamoDB. A plain property diff is uncapped, and one over the row limit fails to store and leaves a gap |
| Splitting a large `extend` (3152-3157) | No | No | One reference |
| 429 handling (3177-3191) | Counts a failure and parses `Retry-After`; does not pause | Logged | The stored diff and polling |
| 503 handling (3193-3203) | Counts a failure; no back-off | Logged | The stored diff and polling |
| A circuit breaker (3211-3222) | Yes, per process, with defects | No | Nothing automatic; suspension is per target, by the application |
| Compression (3224-3262) | Checks the wrong tag, so it never compresses for a conforming peer | No | Nothing; the library does not advertise the tag or decode inbound gzip |
| One callback per change across overlapping subscriptions (3281-3289) | No | No | Nothing |
| Bounded concurrency (not in the specification) | A semaphore of 10 | Serial, or unbounded when async | — |

Defects inside the class, each confirmed: it checks `supports("compression")`
where the tag is `callbackcompression` (`fanout.py:502`,
`peer_capabilities.py:121`); its downgrade URL points at the resource rather
than a diff, and it stores no diff to point at (`:620-623`); a failed
half-open probe reopens with the same cooldown, and half-open lets every
request through, not one (`:118-128`, `:147-148`).

### Documentation that describes it as live

- `docs/quickstart/deployment.rst:118-122` — a per-worker breaker backing off
  a peer: true of the class only.
- `docs/guides/subscriptions.rst` — `:51`, `:76-79`, `:90-104` say callbacks
  are fire-and-forget by default (false for REST writes on both
  integrations); `:63` says sync mode guarantees delivery (delivery is
  at-most-once); `:472-478` says `resume()` returns immediately (not in sync
  mode); `:495-523`, `:733-743`, `:806-828`, `:861-877` show a `FanOutManager`
  API that does not exist (`deliver()`, `success_count`, `failures`);
  `:647-658` and `:833` give receiver status codes the receiver never sends.
- `docs/guides/troubleshooting.rst:215-224`, `:288-307` — an open breaker as a
  cause of missing callbacks, and "FanOutManager handles retries
  automatically": false.
- `docs/migration/v3.10.rst:20`, `:110-137`, `:455`, `:593-597` — the same
  wrong API and a 429 the library never sends.
- `CHANGELOG.rst:5081` calls it part of handling incoming callbacks, and
  `:5088` says deliveries suspend automatically on failure: both false.
- `interface/app.py:1365-1370`, `subscription_config.py:23` — document four
  parameters that do nothing, and "back-pressure (429)".

No todo or recorded decision addresses wiring it in. The 2026-08-20 plan
records the synchronous fan-out as "a documented cost, not a fixed one"
(`thoughts/plans/2026-08-20-v2-positional-access-cost.md:275-279`).

Not determined: PR #65's description and review comments (the GitHub CLI was
refused a TLS connection from the sandbox); real latencies (the timeout
arithmetic is read from the code).

### What that leaves to decide

**Options:**

1. **Wire delivery through a rebuilt fan-out in the publish path.**
   `register_diffs` keeps its per-subscriber diff, sequence and permission
   filter, and hands the POSTs to a sender that runs them concurrently with a
   bound, off the request's response where the deployment allows, honours 429
   and 503, keeps a per-peer breaker and caps the payload. The existing class
   is the starting point for the breaker and the concurrency, not for the
   interface. Changes callback timing for every subscriber; a plan of its
   own.
2. **Parallelise only.** Keep the live sender's semantics, send to the S
   subscribers concurrently with a bound so a write waits for the slowest
   subscriber, not the sum. No breaker, no back-off. Small.
3. **Remove the class and say what the library does.** Delete
   `fanout.py`, its settings and tests; the specification marks back-pressure,
   the breaker and compression as optional mechanisms the reference library
   does not implement, and states the stored diff plus polling as the
   recovery path. The documentation is corrected to the serial, synchronous
   send.
4. **Leave the class, correct the documentation, file the design as a todo.**

Whichever is chosen, the documentation rows above are wrong today and are
corrected by the specification plan.

## Documentation Impact

### The specification

Every row above whose side is "Spec" is an edit to
`docs/protocol/actingweb-spec.rst`. Rows whose side is "Library" need no edit
if the code is changed, and an edit if the specification is changed to match
instead.

### Library documentation found wrong on the way

- `docs/quickstart/deployment.rst:118-122` — describes the per-worker circuit
  breaker as part of callback fan-out; the live path has none (C2).
- `docs/guides/subscriptions.rst:833` — "the library returns HTTP 429"; it
  answers 400 (C15).
- `config.py:166` comment — "Only applies when peer_permissions_caching is
  enabled"; the code does not check it (C12).
- `interface/subscription_manager.py:708` docstring — `"sequence": 1`; a new
  subscription shows 0 (S18).
- `tests/integration/test_spa_api.py:330-332` — describes `?type=` as a
  relationship filter; it filters on the peer's mini-app type (T5).

## Decisions Needed

### Decision 1: what version 1.5 is

**Options:**

1. **A specification the library conforms to.** Every row is settled: the
   specification is edited where it is stale, silent, ambiguous or
   contradictory, and for each CODE row either the library is fixed or the
   specification is changed to describe what the library does. The library
   then announces `1.5` truthfully.
2. **A corrected specification, with known deviations listed.** The
   specification is edited for its own faults (STALE, SILENT, AMBIG,
   INTERNAL); CODE rows that are not fixed in 3.16 are recorded as deviations
   (a todo each, or a "known deviations" appendix). The library announces
   `1.5` with that list.
3. **The four additions only.** Version 1.5 is the list-diff clarifications
   and the reference form already agreed; the sweep becomes a backlog.

### Decision 2: the CODE rows, by cost

Each needs "fix the library", "change the specification to match" or "record
as a deviation". Grouped by what fixing the library takes:

- **Small, local fixes** (a status code, a missing `return`, a header, a type):
  A5, A6, A15, P1, P6, P11, O1, O2, O3, T3, T4, T13, T14, S6, S7, S13, S17,
  S20, C9, C17 (the tag name), C23.
- **Changes clients may depend on** (the specification could move instead):
  A2, A4, P5, S16, S18, T5.
- **Wire behaviour with a design in it**: P2 to P4 (path-addressed list
  items), P8 (all-or-nothing POST), S1 and S2 (diffs for deletes and for
  resources that disappear), S3 (web-UI edits), S4 and S5 (deep paths, hook
  transforms), S9 (subtarget-level diffs on the receiver), C1 (overlap), C4
  and C5 (payload limits), C6 and C7 (resync on the receiver), C10 and C11
  (permission callbacks), C14 (poll on a gap), T22 (default deny).
- **Security-relevant**: S8b, T2, T8.
- **The unused `FanOutManager`** (C2, C18, C19, and the back-pressure and
  compression chapters as a whole): wire it into the publish path, remove it,
  or have the specification mark those sections as optional and unimplemented
  by the reference library.

### Decision 3: the specification-side rows

STALE, SILENT, AMBIG and INTERNAL rows are edits to the specification with no
code change. The choice is how far 1.5 goes in describing library-specific
surface: the root OAuth endpoints (O14), the MCP profile (O11 to O13), the
`/items` and `?index=` forms (P13, P14), the error bodies (P15, P16), the trust
row's extra fields (T12), the receiver's status codes (S28, C16).

### Decision 4: when the announced version moves

1. **With the specification edit**, in the plan that writes 1.5.
2. **Only when the library conforms** to what 1.5 says (Decision 1, option 1).

Either way the two assertions in `tests/integration/test_basic_flow.py` change,
and the specification's own examples at 740 and 754 stop saying `1.0`.

## Release shape

3.16, the unreleased minor, for whatever is taken now. Specification edits are
documentation. Each CODE row fixed in the library is a wire-visible change:
most are `**Breaking:**` or `**Behavior change:**` entries under `CHANGED`
(status codes, response shapes, diffs that start to be sent), and S8b, T2 and
T8 are `SECURITY` entries. The rows marked "design" are each large enough for a
plan of their own.

## Code References

- `actingweb/config.py:426`, `:526-562` — the announced version and the option tags
- `actingweb/handlers/meta.py:22-161` — `/meta`
- `actingweb/handlers/factory.py:215-335` — actor creation
- `actingweb/handlers/properties.py:287-2422` — `/properties`, lists, `/items`
- `actingweb/handlers/callbacks.py:33-471` — `/callbacks`
- `actingweb/handlers/actions.py`, `methods.py`, `resources.py`, `www.py` — the optional endpoints
- `actingweb/handlers/trust.py:110-1381`, `handlers/permissions.py:60-141` — `/trust`, permission query
- `actingweb/auth.py:131-420`, `:786-812` — bearer, trustee and role checks
- `actingweb/handlers/subscription.py:17-598` — `/subscriptions`
- `actingweb/actor.py:2623-2793` — `callback_subscription`
- `actingweb/actor.py:3856-4076` — `register_diffs`
- `actingweb/subscription.py:155-196` — `add_diff`
- `actingweb/db/dynamodb/subscription_diff.py:34` — the import-time timestamp default
- `actingweb/callback_processor.py:78-1066` — the receiving side
- `actingweb/remote_storage.py:328-620` — applying diffs and resyncs
- `actingweb/fanout.py` — `FanOutManager`, not called by the publish path
- `actingweb/trust_permissions.py:175-594` — permission callbacks
- `tests/integration/test_basic_flow.py:131-150` — the version assertions

## External References

None.
