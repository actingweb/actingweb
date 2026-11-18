# The upgrade walked as the application's maintainer (3.15.1 -> "3.16", shipping as 4.0.0)

**Date:** 2026-11-18
**Belongs to:** [`2026-11-18-3-16-release-validation.md`](2026-11-18-3-16-release-validation.md)
**Read at:** `../actingweb_mcp` `main` (`c1be751c`), through git, names only; this repository at `241a67a`.


Sources read: `usage.md` (the consumer inventory), the release inventory,
`CHANGELOG.rst` 5-3623 ("CL", `Unreleased`), `docs/migration/v3.16.rst` ("guide"),
the rest of `docs/`. Line numbers are the working tree's on branch
`release/3.16.0-release-validation` (the release inventory's are older and have
moved). "Answered" means answered by those three documents only. Code lines are
`actingweb/...` in the same tree. Nothing was run; the sibling repository was not read.

Verdict counts are at the end of (a).

## (a) Questions

Groups follow the task's numbering (1-11); group 0 is the release's name; group 12 holds the inventory items the release changes that fit none of the eleven.

| # | question | answered where (file:line, section title) | verdict |
|---|----------|--------------------------------------------|---------|
| 0.1 | The documents say "3.16". Is that the `4.0.0` I am asked to install, and why a major? | Nowhere: guide title `docs/migration/v3.16.rst:2`, CL heading `Unreleased` (CL 5); no "4.0" in guide, `docs/migration/index.rst` or CL 5-3623 | NOT ANSWERED |
| 1.1 | DynamoDB, table auto-create off: which commands run before the new code starts, in which order? | `docs/quickstart/deployment.rst:186-209` "Operator commands" (one ordered list); guide 23-50 (start-here warning), 1097-1169 "Step 0", 1363-1382 "Upgrade order, with both flags on", 791-815 "What to run" (`--properties` when names are set in the builder), 315-346 (mark vouched before the first sign-in) | partly: the order is given; missing is who creates `<prefix>_creators` when tables are managed as infrastructure (see 1.2), and that the commands learn builder-only settings from options, never from the application (see 3.3) |
| 1.2 | Which tables must exist with auto-create off, and who creates the new one? | `docs/reference/database-backends.rst:381-437` "Required DynamoDB tables" (nine tables; `<prefix>_creators` is not in the table); `:607-617` and guide 1071, 1160 say `enable --apply` "creates and fills" it | partly: the required-tables table omits `<prefix>_creators`; nowhere says `enable --apply` creates it whatever the auto-create setting, that it needs `DescribeTable` + `CreateTable`, or that a table declared in a template beforehand (hash key `creator`, string, on-demand) is accepted and only filled |
| 1.3 | Which commands run after the deploy, in which order? | `deployment.rst:206-209` (`enable --apply`, `creator-to-email --apply` again); guide 1164-1169 (then `report`), 2072-2079 (`actingweb-verify-property-lists --attributes`), 723-729 (`actingweb-deletions report`), 1808-1822 (`actingweb-peer-state report`, `prune --apply`, restart), 687 (grep the log) | partly: five places, no single after-deploy list and no order among them; "restart the application's processes" has no meaning given for a function platform |
| 1.4 | PostgreSQL test database: order? | guide 30-40 (start once, `enable --apply`, start; `alembic upgrade head`), 832-835, 2065-2070; `deployment.rst:194-205` | partly: on PostgreSQL Alembic creates the tables, so the "start once to create the tables" step is not needed (not said); `deployment.rst` lists Alembic as step 4, after the backfill that needs its table (see (c) C1) |
| 1.5 | How do I know each step worked? | guide 348-371 (mark-vouched output, exit codes), 1149-1151 and 1278-1279 (`report` exits 1 / 2), 808-811 (backfill marks a name only on a clean pass), 1351-1354 (sweep marker), 760-775 (the refusal text) | answered |
| 1.6 | My worker functions and tests build `Config()` themselves and never call `integrate_*`. What changes for them? | guide 85-91 (item 4), 383-390, 1091-1093; CL 1855 | answered (the indexed-name default of a bare `Config` differing from the application's is covered by guide 781-789 "every process that shares a store must configure the same names") |
| 2.1 | Is there one complete list of the IAM actions and tables the release adds? | guide 1104-1147 (table "What 3.16 adds to a role that lists actions"); `docs/quickstart/configuration.rst:242`; `database-backends.rst:457-475` | partly: complete for the serving role as far as the code's call shapes show; missing (i) the operator role's own list (`DescribeTable` on the actor, property and creators tables, `CreateTable` on creators, `Scan`), (ii) that a role without `ConditionCheckItem` still starts and how the gap then shows |
| 2.2 | Is the statement about `TransactWriteItems` and IAM clear and correct? | guide 1143-1147; `configuration.rst:242` (last sentence) | answered; correct (AWS developer guide, "Using IAM with DynamoDB transactions": Put/Update/Delete/Get are governed by the item actions, a condition check by `dynamodb:ConditionCheckItem`) |
| 2.3 | My policy grants on `<prefix>_*`. Do I still have to add the new table to the policy? | guide 1104 ("If your IAM policy lists tables by name") | answered (a wildcard resource covers it; only the two actions are missing) |
| 3.1 | What does the start-up check say on a store that is not ready? | guide 23-50, 760-775 (text quoted), 1172-1178, 2065-2068, 1351-1354; CL 1831, 2651 | answered |
| 3.2 | Where in my process does the check run, how often, and what does a refusal look like on a function platform? | Nowhere (guide and `deployment.rst` name `integrate_*` only) | NOT ANSWERED |
| 3.3 | No shell on the function: where do the operator commands run, and how do they learn what my builder sets? | guide 793-797 (`--properties`), 1101-1102 ("with the application's environment"); `deployment.rst:189-191`; nothing on where | NOT ANSWERED for "where"; partly for the options (each is in its own section, no one list) |
| 4.1 | What does a rollback to 3.15.1 leave behind, and after which step is it too late? | Fragments: guide 1203-1212 (the flag, not the version), 2081-2083 (attribute lists), 1450-1455 (spanned items), 643-645 (sequence numbers), 1545-1548 (`append_once`); CL 981 (keep the v1 table and GSI while a rollback is possible) | partly: no section; not stated which steps are irreversible (first sign-in of an unmarked actor, `resolve --apply`, `creator-to-email --apply`, first write to a replica list, first spanned item) and which are inert for 3.15.1 |
| 5.1 | Peers that are other actors of my own deployment: anything to order? | guide 643-645, 2072-2079, 1450-1455 (finish the rollout before lists convert / larger items); 2334-2345 and `deployment.rst:88-111` (own-host callbacks on a function platform) | answered |
| 5.2 | Peers in other applications still on 3.15.1: who upgrades first, and what does such a peer see? | Fragments: guide 2203-2206 (a 3.15 subscriber of a 3.16 publisher upgrades first), 1446-1449, 1767-1806 (re-pair), 2224-2241 (admin peer); CL 3099 (a 3.15 subscriber's `sync_peer` deletes its trust), CL 337 (permission callback 503 is resent only by a 3.16 sender) | partly: no one section; the upgrade order (subscribers first) is stated for one case only |
| 5.3 | What do I run about peers after the upgrade? | guide 1808-1822 "Remove what was written before"; `docs/guides/database-maintenance.rst` "Peer State Written Before 3.16" | answered (but see 1.3 for "restart") |
| 8.1 | Do my trust types still admit what they admitted (a subscriber-only type with seven access rows; two MCP client types)? | guide 1665-1685, 1753-1765 (rows, own paths), 1862-1870 and 1916-1936 (a stated rule denies; a subscription needs read access; "a consumer subscriber whose type reads named properties keeps subscribing to the whole target"), 1951-1961 (client list) | answered, with one check the maintainer must make: a type that states `methods` (even `[]`) no longer lets its `methods` access row admit anything (guide 1916-1920) |
| 8.2 | Are the `PUT` and `DELETE` rows I added on `subscriptions/<id>/<subid>` needed? | guide 1665-1680 ("needs nothing new ... PUT and DELETE rows an application added are harmless"), item 18 (154-159); CL 1670 | answered: redundant, harmless (code confirms, see "Answer to 8" below) |

| 6.1 | `actor_created`, `actor_deleted`, `actor_deleted_complete`: new arguments, new firing cases, order? | guide 453-467 "Hooks" (`reason`, `replaced_by_identifier`, may fire more than once, `auth_method` set first), 64-71, 1225-1228 (successor's `actor_created` before the squatter's `actor_deleted`), 727-729 (`actingweb-deletions` runs no hooks); CL 2084, 2094 | answered |
| 6.2 | `oauth_success`: what is in `user_info`, what does my return decide, what if my hook's read faults? | guide 673-690 "Verified provider addresses", 617-621; CL 776-799 (`user_info["unverified_email"]`, no `email`), 3576 (provider tokens stored only once the hook accepts) | answered |
| 6.3 | The five `trust_*` hooks and `subscription_deleted`: arguments, when each fires, async hooks, a fault inside one? | guide 2024-2055 "Trust hooks fire once, with the same arguments", 1713-1719 (approve-on-create fires `trust_fully_approved_local`, not `trust_initiated`), 1767-1771 (no `trust_request_received` on a re-pair), 617-624; CL 1550; `docs/guides/async-hooks-migration.rst` | partly: 617-624 says the runners let `DbError` through and names four hooks whose fault is logged; it does not say `trust_deleted` fails the request (503 on `DELETE`, raised from `sync_peer`) while the other trust hooks and `subscription_deleted` are logged |
| 6.4 | Property hook `"*"`: is it handed something else, when is it skipped, is its value what subscribers get? | guide 1876-1881 "Property hooks", 2284-2285 (the stored value is sent); CL 56 (lines 72-79, 97-100: a direct GET of a plain-text value now runs the read hook, `None` -> 404), 1656; `docs/guides/property-lists.rst:969-998` (hooks per item route) | answered |
| 6.5 | Callback hooks `ping` and `status` (no `allow_anonymous`): who may call, what is in `data`, how is `False` answered? | guide 1721-1751 "Callbacks are authenticated"; `docs/reference/hooks-reference.rst:62-74`; CL 204, 1092, 2501-2514 | partly: `hooks-reference.rst:72-74` says `data` holds `anonymous`; on GET and DELETE the hook gets `{"method"}` only; `raw_body` (bytes) and `headers` for authenticated POST/PUT are in CL 2508-2510 only |
| 6.6 | Callback hook `permissions` (a library name): is my hook still called, with what, when? | guide 1740-1744 (direct request 403, "not the library's own dispatch"), 2139-2145 (`deleted_names`, `not_evaluated`); CL 337-342, 1449 | partly: not stated that the hook now runs only for a callback the store accepted (it ran for every one), and still runs when nothing changed |
| 6.7 | `subscription_data_hook("properties")`: new shapes, new callers, resync contents? | guide 2118-2133 "What to check in your application", 2265-2318 "What a subscriber receives", 2400-2446 (whole baseline from a poll or rebuild), 1446-1449 (`"spanned": true`); `hooks-reference.rst:197-270` | answered (a fault in the hook is logged and dropped, which 617 does not say: folded into 6.3's block) |
| 6.8 | Method and action hooks, MCP tools/prompts: decision before the hook, per-request actor? | guide 1916-1928, 1554-1577 "MCP actors are built per request"; CL 105, 1464 | answered |
| 6.9 | MCP resource hooks that set `_mcp_type`/`_mcp_metadata` by hand and return a dict: still resolved, same answer? | CL 3132-3152 (FIXED "FastAPI answered `resources/read` differently from Flask") | answered (changelog only; the guide has no section: a dict is now indented JSON with the declared `mime_type`, the hook's third argument gains template variables and `uri`) |
| 7.1 | `subscribe_to_peer_async`, `unsubscribe_from_peer`, `revoke_peer_subscription`: results, exceptions? | guide 2316-2318, 559-572 (`DbError` from the accessors), 1930-1936 | answered |
| 7.2 | `sync_peer_async`: result fields, error text, what it does to the trust? | CL 3099 (probe path; local trust deleted only on 401/403/404); guide 2436-2446 (429, application's configuration), 2040-2045 | partly: no document describes `PeerSyncResult.error`; the HTTP detail a caller would branch on is in `subscription_results[i].error` / `.error_code` |
| 7.3 | `suspend` / `resume`: return value, faults? | guide 647-652, 2356-2360, 2370-2379 | answered |
| 7.4 | `all_subscriptions`, `outbound_subscriptions`, `get_subscriptions_*` on a long-lived actor object? | guide 1578-1588 "One subscription read per instance" | answered |
| 7.5 | `trust.create_relationship` from a worker thread, toward a peer I already trust or whose request waits? | guide 1713-1719, 1767-1806 "Re-pairing" | answered |
| 7.6 | Core `Trust(...).get()` / `.modify(last_accessed=)`? | guide 550-557 (reads raise; writes raise), 2040-2045 | answered |
| 7.7 | Trust-permission store (`get_permissions`, `store_permissions[_async]`, `TrustPermissions`), peer-permission/profile/capability stores, `check_property_access`? | guide 1735-1740, 2004-2017 (a client's override must name its row's type), 1687-1703, 1835-1850; CL 32, 918 | answered |
| 7.8 | `RemotePeerStore` and `AttributeListStore` reads on a replica: results, exceptions, layout? | guide 2057-2083 "Attribute lists and list diffs", 2146-2166 (`get_metadata()["length"]` advisory; `$aux`; go through the store); CL 1249, 1266, 2997, 3594 | answered |
| 9.1 | `actingweb.handlers.mcp._token_cache` / `_cache_ttl`, which I mirror | guide 1554-1561 (the actor cache is gone, the token and trust caches stay); `docs/guides/caching.rst:83-110` (entry layout with `"config"`, "internal") | partly: not stated that an entry counts only when its `"config"` is the application's own `Config` object, so entries written by other code are misses |
| 9.2 | `config._oauth2_trust_types` | guide 1959-1961 | answered |
| 9.3 | `oauth2_server._store_mcp_client_info_in_trust` | - | answered by absence: the name exists in neither version (the guarded call was already a no-op) |
| 9.4 | My own authorize route (`create_oauth2_trust_relationship` + `create_authorization_code`) | guide 1975-1981 "Your own sign-in route"; CL 2485 | partly, and wrong as written: see (c) C7 (`complete_client_authorization` runs the decision hook only when `decide_trust=` is passed) |
| 9.5 | Tokens I mint through the session manager; the cleanup calls; in processes with a bare `Config` | CL 405-433 (chain-revoked marker, `delete_expired` raises), 801; guide 84-91, 383-390 | answered |
| 9.6 | The library's `spa_access_tokens` bucket under the OAuth2 system actor, read directly | `docs/sdk/attributes-buckets.rst:244` | answered: unchanged (bucket, key, value fields). No document warns that it is private |
| 9.7 | `_internal` / `auth_method`, read directly | `docs/guides/authentication.rst:325-380`; guide 253-257, 507-511; CL 2696 | answered: same bucket and shape, more values (`app`, `factory`, `operator`, `creator_changed`, ...) |
| 9.8 | Property-list meta row read by its storage name `list:<name>-meta`; my `PropertyListStore` subclass | guide 2060-2065 and 2157-2159 speak of attribute lists only | partly: unchanged for property lists, but the guide's "the row names changed" does not say property lists are not meant |
| 9.9 | `Attributes` (`get_attr`, `set_attr`, `conditional_update_attr`, `get_bucket`) and `get_attr_strict` | guide 550-563, 660-661, 868-869; `docs/sdk/attributes-buckets.rst:170-180`; CL 892 | answered |
| 9.10 | `auth.check_and_verify_auth_async(appreq=, actor_id=, config=)` behind my own routes | guide 983-994 (keyword-only `config`), 578-583 (a `DbError` from your own route answers 503) | partly: `docs/guides/authentication.rst:649-665` lists the outcomes without the raised `DbError` |
| 9.11 | I write the `email` *property* in hooks, with `with_email_as_creator` on: does the creator rule act on it? | guide 1284-1311 names `store.email` only | partly: no sentence says the property of the same name is not the stored email |
| 9.12 | Operator-script names (`DbPropertyLookup`, `PropertyLookupV2`, `compute_lookup_key`, `DbSubscriptionSuspension`, `get_remote_bucket`, `migrate_to_v2`, `delete_bucket`) | CL 966-985, 1778-1829; guide 737-749, 951-963, 1456-1460, 2152-2156 | answered |
| 10.1 | `GET/PUT/DELETE /<id>/properties[/<name>]`, `/metadata` | guide 2196-2219, 594-596 (503 after a kept write), 1872-1874; CL 1135, 1143 | answered |
| 10.2 | `/<id>/properties/<name>/items` (`add`/`update`/`delete` by index) | `docs/guides/property-lists.rst` "Three ways to address an item"; guide 594-596 (a retried add is a second item), 1433-1436 (413), 1490-1493 (409) | answered |
| 10.3 | `/<id>/trust`, `/<id>/trust/<rel>/<peer>` | guide 1687-1703, 2050-2055, 2257-2263; CL 1108, 857 | answered (the boolean flags are stated for "the answer to a trust request"; the owner's `POST /<id>/trust` answers the same way and is not named) |
| 10.4 | `/<id>/meta`, `/meta/trusttypes` | guide 996-1013, 2196-2200 | answered |
| 10.5 | `DELETE /<id>` | guide 586-588, 716-729; CL 2369 | answered |
| 10.6 | `/oauth/config`, `/oauth/session`, `/oauth/spa/authorize`, `/oauth/spa/token`, `/oauth/callback` | guide 1040-1060 "SPA error codes", 1399-1407, 311-313; `docs/guides/spa-authentication.rst`; CL 1731, 2133 (refresh cookie on `path=/`, changelog only) | answered |
| 10.7 | `POST /oauth/logout` | guide 1043-1045; CL 3176 (an MCP token ends only the MCP chain) | partly, and wrong as written: see (c) C8 (its own 503/500 carry no `X-ActingWeb-Error` and no `code`) |
| 10.8 | `GET /oauth/spa/session/<session_id>` | Nowhere under `docs/` (no hit for `spa/session/`) | NOT ANSWERED |
| 10.9 | `POST /oauth/spa/revoke` | Nowhere under that path (`/oauth/revoke` is described: `spa-authentication.rst:1092-1113`, guide 1043) | NOT ANSWERED |
| 10.10 | Do the cross-site rules touch my SPA's calls? | guide 1599-1635 "Cross-site requests" (a Bearer request without the session cookie is not checked) | answered |
| 11.1 | Dependency floors? | CL 381-399 (`pyjwt >=2.15,<3`; lock moves) | answered (changelog only; the guide does not mention it) |
| 11.2 | Python version? | CL 2586-2590; `docs/quickstart` (python `^3.11`) | answered |
| 11.3 | How do I install the release candidate (and pin it with extras)? | Nowhere in the three documents (`CONTRIBUTING.rst:240-246` has the pip line; it is not under `docs/`) | NOT ANSWERED |
| 12.1 | (Inventory items outside the eleven groups.) What happens to my existing users at their first sign-in after the upgrade (factory, MCP sign-up and email-form actors without a marker)? | guide 52-78 (items 1-2), 259-313 "Two populations, two behaviours", 315-375 "Marking actors you trust before the first sign-in" | answered |
| 12.2 | Should I close the factory? | guide 79-80, 435-451 "Closing the factory", 1171 | answered |
| 12.3 | Publishing property lists on DynamoDB: large items, size errors, names? | guide 123-131 (item 14), 1409-1496 "Spanned list items" (incl. 1425-1431: develop on PostgreSQL, run DynamoDB) | answered |
| 12.4 | What do `set_description`, `clear()`, `extend()`, `delete()` on a list now send my subscribers? | guide 2085-2102 "The diffs" (`metadata`, `clear`, `extend`, `delete_all`), 2286-2288 | answered |
| 12.5 | Calling a peer's method through `AwProxy.create_resource("methods/<name>")`: new refusals? | guide 1916-1928 (a stated rule denies; 403), 1687-1689 (unapproved peer gets nothing); CL 3110 | answered |
| 12.6 | `OAuth2ClientManager` (`create_client`, `delete_client`, `generate_access_token`) | guide 419-433 (`ClientRegistrationError`), 1983-1988; CL 434-470 (`delete_client` returns `False` for a non-owner, the connection still ends) | answered (the `delete_client` change is in the changelog only) |
| 12.7 | `ActorInterface.get_by_id`, `get_by_creator`, `get_deletion_status` in webhooks and sign-in routes | guide 559-572 (they raise `DbError`), 654-657, 1084-1086 (addresses are lowercased); CL 2019 | answered |
| 12.8 | Synchronous callbacks behind a gateway with a response limit: new settings? | guide 2323-2345 "Callback delivery"; `deployment.rst:68-111` "Callback Delivery by Deployment Shape" | answered |
| 12.9 | The rest of my builder chain (`with_subscription_processing` arguments, `with_oauth` with my own `redirect_uri`, `with_mcp`, provider helpers, `add_actor_type`) | guide 44-48 and 2347-2351 (removed settings: none of mine), 2459-2469 (own `redirect_uri` still wins), 745-749 (the removed legacy call) | answered |
| 12.10 | MCP: sign-ups, client registration, client levels with my configured list | guide 402-433 "The MCP OAuth server", 1948-2017 "An MCP client's access level" | answered |
| 12.11 | I read a peer's `/meta` (`aw_trust_types`) before pairing; the protocol version changed | guide 2488-2495, 996-1013, 2196-2200 (scalar `/meta` paths are `text/plain`) | answered |
| 12.12 | Email sign-in pages and the verification link (I serve my own `/oauth/email`) | guide 692-714; CL 683, 822, 2148 | answered for the library's handler; what a shadowing route must replicate is the application's own (to-do D20) |

Counts: 73 questions. answered 50, partly 17, NOT ANSWERED 6
(0.1, 3.2, 3.3, 10.8, 10.9, 11.3).

### Answer to 8, from the code

- The built-in rows: `actingweb/config.py:358` `("owner", "subscriptions/<id>", "GET", "a")`
  and `:359` `("owner", "subscriptions/<id>/<subid>", "GET,PUT,DELETE", "a")`.
- A row matches by role, path prefix and method list: `actingweb/access_table.py:59-77`
  (`owner` matches when `caller_peerid == path_peerid`, `:70-74`; the method test is
  `acl[2].find(method) != -1`, `:77`), so a `GET` row never admits `PUT`/`DELETE`
  and the search goes on to the next row.
- The handlers ask for the method performed, naming the path's peer:
  `actingweb/handlers/subscription.py:67-76` (`_authorize_subscription_write` ->
  `authorize(method, "subscriptions", "<id>/<subid>", path_peer=peerid)`), called by
  `put` (`:500-508`) and `delete` (`:565-573`); `actingweb/handlers/base_handler.py:373-403`
  passes `peerid=path_peer`, which is what the `owner` rows compare.
- So a subscriber of any type is admitted to `PUT`/`DELETE` on its own subscription by
  `config.py:359`. The two added rows are inserted at index 0
  (`actingweb/permission_integration.py:417`) and match first for a `subscriber` peer,
  with the same outcome: **redundant**.
- They widen nothing: after any row matches, a peer caller must be the peer the path
  names (`actingweb/auth.py:793-812`; `admin` is the only exemption, `:805-807`), so
  another subscriber's `PUT`/`DELETE` is 403 with or without them: **not wrong**.
- Callbacks: the type's `callbacks` row is redundant too. `config.py:310`
  `("any", "callbacks", "", "a")` admits every authenticated caller, and the two peer
  branches bind the caller to the path's peer with `peer_caller_only=True`
  (`actingweb/handlers/callbacks.py:516-523` DELETE, `:631-638` permissions,
  `:886-893` subscriptions).
- The one row of the seven whose effect can change is `methods POST`: the access
  table is asked only when the type's grant does not mention the category
  (`actingweb/access_decision.py:10-13`, `:197`, `:222`;
  `actingweb/permission_evaluator.py:406-408`), and `add_trust_type`
  turns `"methods": []` into a stated rule `{"allowed": []}`
  (`actingweb/permission_integration.py:440-443`). The inventory says the type's
  methods are "empty" without saying whether the key is present: to-do D7.

## (b) Missing text, as the generic pattern

Each block: the question it closes, the proposed text, where it belongs, the code
that makes it true. "Verified" = read in the code at the lines given.

**B0 (0.1) The version.** Belongs: top of the guide and its `docs/migration/index.rst`
row. Text: "This release was developed as 3.16 and is published as 4.0.0: it
removes public names and changes wire answers, which the version policy makes a
major. Every '3.16' in this guide, in messages and in code comments means 4.0.0."
Not verifiable in code (`pyproject.toml:3` and `actingweb/__init__.py:31` still say
`3.15.1`); it is the release decision of commit `241a67a`.

**B1 (1.2) The creators table under infrastructure-as-code.** Belongs: guide,
"Creator uniqueness", after "DynamoDB permissions"; and a row in
`docs/reference/database-backends.rst` "Required DynamoDB tables". Text:
"`actingweb-unique-creators enable --apply` creates `<prefix>_creators` itself when
it does not exist, whatever `AWS_DB_AUTO_CREATE_TABLES` says; the role that runs it
then needs `DescribeTable` and `CreateTable`. A deployment that declares its tables
in a template declares this one first (hash key `creator`, string; no range key;
on-demand billing) and deploys the template before running the command: `enable`
finds the table and only fills it. Either way the application starts only after
`enable --apply` has written the backfill-complete item, so the table and its
contents come before the release's code." Row for the table: "`<prefix>_creators` |
`creator` | - | With creator uniqueness (the default)". Verified:
`actingweb/maintenance/unique_creators.py:1001-1002` (`if not Creator.exists():
Creator.create_table(wait=True)`, no auto-create test); `actingweb/db/dynamodb/creator.py:20-30`
(hash key `creator`, `PAY_PER_REQUEST`); `actingweb/db/dynamodb/_backfill_probe.py:26-49`
(start-up reads the backfill item); `actingweb/db/verify_tables.py:77-80`.
Not verified: that a template refuses to create a table that already exists (the
platform's behaviour, not the library's).

**B2 (1.3) One after-deploy list.** Belongs: `docs/quickstart/deployment.rst`
"Operator commands", replacing its last paragraph; the guide's "Start here" points
to it. Text: "After every instance runs the release, in this order: (1)
`actingweb-unique-creators enable --apply`, then `report` (and `resolve --apply`,
`enable --apply` if it lists anything); (2) under `with_email_as_creator`,
`creator-to-email --apply`; (3) `actingweb-verify-property-lists --attributes`;
(4) `actingweb-deletions report`; (5) `actingweb-peer-state report`, then `prune
--apply`, then replace the running processes (they keep the permissions they
cached); on a function platform that means forcing new instances, for example by
publishing a new version or changing an environment variable." Verified: each
command and its purpose against guide 1164-1169, 1380-1382, 2072-2079, 723-729,
1808-1822; that the processes cache until replaced is the guide's own statement
(1820-1821). Not verified in code: the function-platform sentence (platform
behaviour). The order of (3)-(5) among themselves is not constrained by any code
I read; say "in any order" if the authors agree.

**B3 (3.2) The start-up check on a function platform.** Belongs:
`docs/quickstart/deployment.rst`, "AWS Lambda (Serverless)". Text: "`integrate_flask`
and `integrate_fastapi` run `check_ready()` when they are called, that is while the
module that builds the application is imported, not in a startup event (an adapter
that turns the ASGI lifespan off does not skip it). On a function platform every
new instance runs it during initialisation (on DynamoDB with table auto-creation
off; with it on, a table pre-warm comes first): one `BatchGetItem` on the lookup table,
one consistent `GetItem` on the creators table and, with `with_email_as_creator`,
one read of the readiness marker; a passing answer is remembered for the instance.
A refusal raises from the import, so every invocation of that instance fails until
the store is ready; a read fault during initialisation refuses too. Run the
commands before the release's code is deployed, and alarm on initialisation errors
during the rollout." Verified: `actingweb/interface/app.py:1923` (call inside
`integrate_fastapi`), `:1660-1717` (the four checks; each sets a per-process
`_..._checked` flag, `:1770`, `:1810`, `:1836`, `:1882`), `:1730-1740` and
`:1782-1792` (a fault refuses), `actingweb/db/dynamodb/property_lookup.py:127`
(`batch_get`), `actingweb/db/dynamodb/_backfill_probe.py:39`,
`actingweb/maintenance/email_as_creator.py:97-104`. Not verified: how a given
platform reports a failed import.

**B4 (3.3) Where the commands run and what they are told.** Belongs: same
"Operator commands" section. Text: "The commands are console scripts of the
package. They do not import the application: run them from any machine that has
the release installed and can reach the database (an operator's machine, a CI job,
a one-off task), with the application's `DATABASE_BACKEND` (they default to
`dynamodb` when it is unset, whatever the application's own default), prefix,
region and credentials. What the application sets in its builder they must be
told: `--properties a,b` on every `actingweb-property-lookup` subcommand when the
names come from `with_indexed_properties()`; `--email-as-creator` on
`actingweb-mark-actors-vouched` and `--default-creator-to-email` on `resolve`
under `with_email_as_creator`; `--no-unique-creator` on `actingweb-deletions` and
`python -m actingweb.db.verify_tables` for an application that opted out. On
DynamoDB the role that runs them needs, beyond the serving role's actions,
`DescribeTable` on the actor, property and creators tables, `CreateTable` on the
creators table and `Scan`." Verified: `actingweb/maintenance/unique_creators.py:191-194`,
`property_lookup.py:177-180`, `mark_actors_vouched.py:314`, `deletions.py:100-103`
and `:390-396`, `peer_state.py:123` (each builds its own `Config` from
`DATABASE_BACKEND`, default `dynamodb`); `Model.exists()` calls at
`unique_creators.py:329, 408, 1001` and `property_lookup.py:206`;
`mark_actors_vouched.py:293-296`.

**B5 (2.1) What a missing `ConditionCheckItem` looks like.** Belongs: guide, under
the IAM table (1112-1147). Text: "The start-up check reads with `GetItem` and
`BatchGetItem` only, so it catches a missing `BatchGetItem` or an unreadable
creators table, not a missing `ConditionCheckItem`. A role without it starts.
The gap shows later, on four paths: an unchanged indexed value whose lookup row
is claimed (logged `LOOKUP_HEAL_FAILED`, the request succeeds); an indexed write
that takes over a stale lookup row (`DbError`, 503); a sign-in that repairs a
stale creator record (`DbError`); and a creator rename. None of them runs on
every request, so test the policy before the deploy rather than waiting for it."
Verified: `actingweb/db/dynamodb/property.py:355-392` (claim; fault logged),
`:466-481` with `actingweb/db/dynamodb/property_lookup.py:250-258` (take-over's
condition checks inside the write), `actingweb/actor.py:960-966` with
`actingweb/db/dynamodb/actor.py:996-1000` (stale-record release at sign-in),
`actingweb/db/dynamodb/actor.py:445-452` (rename); start-up reads as in B3.
Not verified: the error class IAM's refusal surfaces as on each path (inferred
from the `DbError` wrapping of `_run_transaction`; the release inventory marks
the rename's as unverified too).

**B6 (4.1) Rolling back to the previous release.** Belongs: a new guide section
"Rolling back to 3.15", linked from "Start here". Text (each sentence a claim to
keep or drop; the first sentence is my inference and is NOT verified): "Running the commands changes nothing a 3.15 process cannot live
with, except two: `resolve --apply` renames duplicate actors to
`<creator>#dup-<hash>` and clears their stored email, and `creator-to-email
--apply` moves creators; neither is undone by a rollback. Once the release serves
traffic, these are not reversible: an unmarked actor cleaned at its first sign-in
(passphrase, trusts, subscriptions, sessions and clients are gone), a `factory`
actor replaced at a sign-in (its data is gone), an attribute list or a replica
converted by its first change (a 3.15 process reads it as empty until
`sync_peer()` or the next write), and, on DynamoDB, a list item over the span
threshold or a list on which `append_once` ran (a 3.15 reader sees the storage
envelope). So: mark actors before the first sign-in, and decide on a rollback
before peers' callbacks have converted the replicas. After a rollback, a 3.15
process creates and renames actors without writing creator records; before going
forward again run `enable --apply` and `report`. Keep the v1 lookup table and the
`property-index` GSI until no rollback is planned." Verified in code:
`actingweb/attribute_list.py:15-25` (conversion on the first mutation; old writers
then write beside it); the rest restates guide 259-283, 1196-1198, 1340-1345,
1450-1455, 1545-1548, 2081-2083, 1164-1169 and CL 981. NOT verified, and to be
checked before it is written: how a 3.15.1 process behaves on PostgreSQL with
`ux_actors_creator` in place and after revisions `f6a7b8c9d0e1`/`a7b8c9d0e1f2`
(the second's downgrade fails when a key is longer than 255 characters:
`actingweb/db/postgresql/migrations/versions/a7b8c9d0e1f2*.py:71-83`); whether
tokens and the `path=/` refresh cookie issued by the release are accepted by 3.15.1.

**B7 (5.2) Peers on the previous release.** Belongs: guide, a short section
"Peers that have not upgraded" before "Specification 1.5", collecting what is now
spread out. Text: "Upgrade subscribers before the publishers they subscribe to. A
3.15 subscriber of an upgraded publisher: reads a `text/plain` value at a
single-property subscription as a failed fetch; answers `unknown operation` to a
spanned list reference and stores nothing; receives list diffs where REST edits
sent scalars; and, when its `sync_peer` probe is refused, deletes its own trust
row, after which its new trust request is refused (403) until the upgraded side's
owner removes the old row with `?notify=false`. A 3.15 peer of any role: no
longer reads the passphrase or changes the trustee as `admin`; gets 403 instead of
200 `false` for a callback name nothing handles and 403 instead of 404 for an
unknown subscription id; is refused a repeated trust request without the current
secret; and does not resend a permission callback answered 503." Verified: none
of this was re-read in the 3.15.1 sources by me; it restates guide 2203-2206,
1446-1449, 2085-2102, 1767-1806, 2224-2241, 1744-1746 and CL 3099, 337, 1695,
which the release inventory checked against `v3.15.1` (its rows for merges
6569ff25, e928e5bd, 6f4a7a4b). Mark as "to verify against the wire-row tests".

**B8 (11.3) Installing a pre-release.** Belongs: top of the guide (or
`docs/quickstart/getting-started.rst`). Text: "Release candidates are published to
TestPyPI, not PyPI: `pip install --index-url https://test.pypi.org/simple/
--extra-index-url https://pypi.org/simple/ 'actingweb[fastapi]==X.Y.ZrcN'`. A
resolver that pins exactly (`==3.15.1`) must name the candidate's version and the
extra index." Verified: `.github/workflows/publish-to-pypi.yml:53-72, 98` (the
pre-release pattern and the TestPyPI job), `pyproject.toml:69-73` (extras). Not
verified: the equivalent source declaration for Poetry (a `[[tool.poetry.source]]`
entry for TestPyPI); test it before printing it.

**B9 (1.4) PostgreSQL order.** Belongs: guide warning (30-40) and
`deployment.rst:194-205`. Text: "On PostgreSQL `alembic upgrade head` comes first:
it creates the tables (a fresh database needs no first start to create them) and
the `property_lookup_backfill` table the backfill writes its markers to. Then
`actingweb-unique-creators enable --apply`, then start." Verified:
`actingweb/db/postgresql/property_lookup.py:143-204` (markers are rows of
`property_lookup_backfill`), `actingweb/maintenance/property_lookup.py:195-199`
(the command refuses without the tables, naming Alembic),
`actingweb/maintenance/unique_creators.py:1067-1068, 1183-1189` (PostgreSQL
`enable` builds the index; no table is created by it).

**B10 (6.3, 6.7) Which hooks fail the request on a fault.** Belongs: guide,
"Fault contract", the **Hooks** paragraph (617-624). Text: "The runner lets a
`DbError` through; the caller decides. It fails the request for the property,
method, action and callback hooks, for `oauth_success`, `actor_deleted` and
`trust_deleted` (a trust `DELETE` answers 503, `sync_peer` raises). It is
logged, and the request goes on, for `actor_created`, `actor_adopted`,
`actor_deleted_complete`, the other `trust_*` hooks, `subscription_deleted` and
every `subscription_data_hook` (a data hook runs at most once per diff)."
Verified by me: the runner (`actingweb/interface/hooks.py:940-949`), the data
hook's fold (`actingweb/handlers/callbacks.py:141-145`). The per-hook split is
the sub-audit's reading (`actingweb/handlers/trust.py:579-599, 872-893`,
`actingweb/interface/trust_manager.py:267-289`, `actingweb/oauth2.py:2018-2053`,
`actingweb/actor.py:1369-1381`); re-read those call sites before printing it.

**B11 (6.5) A callback hook's `data`.** Belongs:
`docs/reference/hooks-reference.rst:72-74`. Text: "On POST and PUT `data` is the
body's JSON object plus `method`, `anonymous`, `headers` (without
`Authorization` and `Cookie`) and `raw_body` (bytes: remove it before
serialising `data`). On GET and DELETE it is `{"method": ...}` only. A PUT
reaches the hook as `"PUT"`." Verified: `actingweb/handlers/callbacks.py:373-385`
(POST/PUT), `:486-487`, `:599-600` (GET, DELETE), `:499-502` (PUT).

**B12 (6.6) When the `permissions` hook runs.** Belongs: guide 2139-2145, and
the hooks reference's permission callback entry. Text: "A `permissions` callback
hook runs only for a callback the store accepted: not for an older one, nor one
refused (400, 403) or answered 503. It still runs when the accepted callback
changed nothing. Before, it ran for every callback." Verified:
`actingweb/handlers/callbacks.py:863-871` (`if self.hooks and success`).

**B13 (7.2) `sync_peer` results.** Belongs: `docs/guides/subscriptions.rst`,
where `sync_peer` is described. Text: "`PeerSyncResult.error` is set only when
the peer no longer holds the trust (`"Trust relationship has been revoked by
peer"`); the status and text of a failed poll are per subscription, in
`subscription_results[i].error_code` and `.error` (429: a rebuild is not due
yet, retry later)." Verified: `actingweb/interface/subscription_manager.py:2249,
3978` (the only `error=` on the peer result), `:329-351` (per-subscription
fields). The 429 sentence restates guide 2434-2436.

**B14 (9.1) The MCP caches are not an extension point.** Belongs:
`docs/guides/caching.rst:83-110` and guide "MCP actors are built per request".
Text: "An entry of the token cache is honoured only when its `"config"` is the
application's own `Config` object and it is younger than the TTL; no actor is
cached any more. Code in front of `/mcp` that needs to know a token is valid
calls the token manager, not the cache." Verified:
`actingweb/handlers/mcp.py:108-127` (layout, no actor cache), `:2326-2331` (the
identity test).

**B15 (9.8, 9.11) Two sentences that prevent a wrong reading.** Belongs: guide
2157-2159 and 1284-1291. Text: "Property lists keep their row names
(`list:<name>-meta`, `list:<name>-#<rank>`); only attribute lists changed." and
"The rule acts on the stored email in `_internal` (`core_actor.store.email`), not
on a property named `email`." First sentence verified by the sub-audit
(`actingweb/property.py:75-117`), second by the sub-audit
(`actingweb/creator_sync.py:62-80`, `actingweb/attribute.py:226-250`); neither
re-read by me.

**B16 (9.10) `check_and_verify_auth` and faults.** Belongs:
`docs/guides/authentication.rst:649-665`. Text: "A database fault while
authenticating raises `DbError` out of the call; let it reach the integration,
which answers 503 with `Retry-After`." Sub-audit: `actingweb/auth.py:948-1030`;
not re-read by me.

**B17 (10.8, 10.9) The two SPA routes.** Belongs:
`docs/guides/spa-authentication.rst`, endpoint reference. Text: "`GET
/oauth/spa/session/<session_id>` hands a browser the session a redirect-based
sign-in left for it: 200 `{success, access_token, actor_id, email, expires_at,
redirect_url}` (no refresh token in the body). It can be read once; a repeat
within 30 seconds is honoured, after that the answer is 404. Errors carry
`X-ActingWeb-Error` and `code`." and "`POST /oauth/spa/revoke` is the same
endpoint as `/oauth/revoke`." Verified by me: the routes exist
(`actingweb/interface/integrations/fastapi_integration.py:932-944`), the
30-second grace (`actingweb/constants.py:195-196`, `actingweb/oauth_session.py:238`).
Response fields and the alias are the sub-audit's reading
(`actingweb/handlers/oauth2_spa.py:1733`, `actingweb/oauth_session.py:230`);
re-read before printing.

## (c) Wrong for this deployment shape

- **C1. `docs/quickstart/deployment.rst:194-205` orders `alembic upgrade head`
  (step 4) after `actingweb-property-lookup backfill --apply` (step 3).** On
  PostgreSQL the backfill writes its markers to `property_lookup_backfill`
  (`actingweb/db/postgresql/property_lookup.py:168`), which revision
  `f6a7b8c9d0e1` creates; guide 832-835 says "before". Alembic belongs first.
- **C2. Guide 1104-1110: "Without them the startup check cannot read the table
  and the application refuses to start"** follows a sentence that lists
  `ConditionCheckItem` among "them". The start-up check performs no condition
  check (`actingweb/interface/app.py:1660-1717`; reads at
  `db/dynamodb/property_lookup.py:127`, `db/dynamodb/_backfill_probe.py:39`): a
  role that lacks only `ConditionCheckItem` (this deployment's case, together
  with `BatchGetItem`) starts once `BatchGetItem` is added, and fails later
  (B5).
- **C3. Guide 30-32 and item "A fresh deployment starts once (which creates the
  tables and stops)"** assumes table auto-creation. With auto-creation off the
  first start creates nothing (`actingweb/interface/app.py:1637-1638` returns;
  `actingweb/db/dynamodb/_ensure.py:82-84`), and `enable` refuses when the actor
  table does not exist (`actingweb/maintenance/unique_creators.py:408-413`): the
  tables come from the template, then `enable --apply`. The production store is
  not fresh, so this bites only a new environment (a preview stack).
- **C4. `docs/reference/database-backends.rst:381-437`: "every table below must
  already exist"** and the table lacks `<prefix>_creators`, which is required by
  default (`actingweb/db/verify_tables.py:77-80`). The prose at `:607` has it.
- **C5. The guide's IAM paragraph tells the operator role "`CreateTable` and
  `Scan`" (1108-1109).** The commands also call `DescribeTable` on the actor,
  property and creators tables whatever the auto-create setting
  (`actingweb/maintenance/unique_creators.py:329, 408, 1001`;
  `property_lookup.py:206`). A serving role built without `DescribeTable` (this
  one) cannot run them; the operator's own credentials can.
- **C6. Not wrong, but silent for this shape:** `configuration.rst:242` lists the
  least-privilege actions as `GetItem, PutItem, UpdateItem, DeleteItem, Query,
  Scan`; the list write paths use `BatchWriteItem`
  (`actingweb/db/dynamodb/property.py:824, 940`), which no document names. This
  deployment's policy already grants it; not new in this release (not checked
  against `v3.15.1`).

- **C7. Guide 1975-1981 (also `docs/guides/oauth2-setup.rst:223`,
  `docs/guides/mcp-applications.rst:1190`, `docs/reference/hooks-reference.rst:298`):
  `complete_client_authorization(...)` "applies the list, the
  `oauth2_trust_requested` hook, the trust and the code".** Called as shown, it
  does not run the hook: `decide_trust` defaults to `None`
  (`actingweb/oauth2_server/oauth2_server.py:1186`) and then only the client list
  is checked (`:1025-1038`). An application with its own authorize route (this
  one) that follows the guide gets no decision hook unless it passes
  `decide_trust=`, which no document names.
- **C8. Guide 1043-1045 and CL 1731: "every error the SPA token endpoints
  answer (`/oauth/spa/*`, `/oauth/revoke` and `/oauth/logout`) now carries a
  stable code".** `/oauth/logout`'s own 503 is `{"success": false, "error":
  "temporarily_unavailable", ...}` with `Retry-After` and neither the header nor
  `code` (`actingweb/handlers/oauth2_endpoints.py:1244-1254`); only a `DbError`
  answered by the shared fault handler carries them. A frontend that applies
  "a 401/503 without the header is not the library's" to logout misreads it.
- **C9. `docs/reference/hooks-reference.rst:72-74`** says a callback hook's
  `data` holds `anonymous`; on GET and DELETE it holds `method` only (B11).

## (d) Application to-do list, in order

Done already (inventory section 11): the `with_legacy_property_index` call is
removed; two access rows added; a local path pin; `scripts/test-backends.sh`
runs `enable --apply`. Still to do:

**Before any deploy (repository changes)**

- D1. `serverless.yml` IAM (197-234): add `dynamodb:BatchGetItem` and
  `dynamodb:ConditionCheckItem` to the DynamoDB statement. The `<prefix>_*`
  resource already covers `<prefix>_creators`. Update
  `tests/test_dynamodb_iam_coverage.py`: map `TransactWrite` to
  `ConditionCheckItem` plus the item actions, not to `TransactWriteItems`
  (guide 1143-1147).
- D2. Decide who owns `<prefix>_creators`: let `enable --apply` create it
  (operator credentials with `DescribeTable`/`CreateTable`; the table then lives
  outside the template, like the older library tables), or declare it in
  `serverless.yml` (hash key `creator`, S, on-demand) and deploy that template
  change with the 3.15.1 code first. Do not do both in the wrong order (B1).
- D3. `pyproject.toml`: replace the path dependency with the candidate's pin and
  the TestPyPI source; check that nothing pins `pyjwt` below 2.15; regenerate the
  lock (B8).
- D4. `application.py` (581-588): on Lambda add
  `with_callback_delivery(serialize_own_host_callbacks=False,
  callback_delivery_budget_seconds=<under the gateway's 30 s>)`
  (`deployment.rst:88-111`).
- D5. `application.py`: add `with_list_item_limits(span_threshold=390_000,
  max_bytes=4 * 2**20)` so the PostgreSQL test suites span as DynamoDB does
  (guide 1425-1431); catch `ListItemTooLargeError` where
  `repositories/property_list_accessor.py` appends and updates.
- D6. `application.py` (811): the two added `subscriptions/<id>/<subid>` rows
  are redundant; remove them or keep them, nothing depends on it. The
  `callbacks` row is redundant too.
- D6a. Decide on `with_open_factory(False)`: the deployment signs users in
  through OAuth, MCP and its own routes; if nothing of its own posts to the
  library's `POST /`, close it (guide 79-80), at least for the rollout window
  (guide 1171).
- D7. `application.py` (811): check how the `subscriber` type states `methods`.
  If the permissions dict has the key (even `[]`), peers' `POST /methods/<name>`
  (`hooks/mcp/tools/execute_method.py:167` on the calling side) is now 403
  despite the `methods POST` access row: drop the key or list the methods. Same
  check for `actions`. Not determinable from the inventory.
- D8. `api/oauth_password.py` (118, 248-360): replace the hand-rolled sequence
  with `complete_client_authorization(...)`, passing `decide_trust=` if the
  decision hook is wanted (C7); stop reading `config._oauth2_trust_types`
  (use `client_trust_type_acceptable` / `default_client_trust_type`); delete the
  dead `_store_mcp_client_info_in_trust` lookup.
- D9. `api/oauth_clients.py`: answer `ClientRegistrationError` from
  `create_client` as a server error; `delete_client` returning `False` no longer
  means "nothing happened" (CL 434).
- D10. `application.py` (319-324, 416-460): the mirror of `_token_cache` /
  `_cache_ttl`. Read-only use still works; do not write entries (B14). Prefer
  `token_manager.validate_access_token`, and let `DbError` /
  `TokenStoreUnavailable` answer 503.
- D11. `hooks/actingweb/callback_hooks.py`: `ping` and `status` now need an
  authenticated caller (401 without credentials): check every caller (monitors,
  the frontend). `status` and `ping` must not serialise `data` whole
  (`raw_body` is bytes). The `permissions` hook runs only for accepted
  callbacks; read `permission_changes["deleted_names"]` if
  `auto_delete_on_revocation` is on.
- D12. `hooks/actingweb/callback_hooks.py:143` (data hook) and the frontend's
  WebSocket consumer: accept list diffs from REST edits (`delete` with
  `old_item`, `extend`, `metadata`, `delete_all`), `"spanned": true` references
  (re-read the list), deletes as `""`, a whole baseline as `"resync"` from a
  poll or rebuild, and the ISO `Z` timestamp.
- D13. `hooks/actingweb/lifecycle_hooks.py`: `actor_deleted` /
  `actor_deleted_complete` check `reason == "replaced_at_adoption"` before
  revoking the Apple token or notifying; `oauth_success` reads
  `user_info.get("unverified_email")` and must not assume `email`; a `DbError`
  in `oauth_success` or `trust_deleted` now fails the request (catch it if the
  WebSocket notification must not block a trust delete).
- D14. `hooks/actingweb/property_hooks.py`: unchanged contract; note the hook
  now also guards a direct GET of a plain-text value. Values it hides still
  reach subscribers through pushed diffs (as in 3.15.1): the grant, not the
  hook, must exclude `auth_token` and `_*`.
- D15. `hooks/mcp/tools/shared.py:166` (`mcp_usage_count` read-modify-write on
  every tool call): two reads and a write per call on a per-request actor
  (guide 1572-1577); batch it or move it to an atomic counter.
- D16. `hooks/mcp/resources.py`: the three resource hooks' dict results are now
  served as indented JSON with the declared `mime_type`, and `params` gains
  template variables and `uri` (CL 3132); check MCP clients that parsed
  `text/plain`.
- D17. `api/trust.py:776` (`sync_peer_async`): the `404`/`403` substring
  branches on `.error` never matched; read
  `subscription_results[i].error_code` (B13). `api/trust.py:868-876`:
  `Trust.modify` can return `False` and raise `DbError`.
- D18. Fault handling across `api/` and `repositories/`: any `except Exception`
  around library reads that means "absent" must re-raise `DbError` (guide
  654-671); `helpers/template_helpers.py:276` must let `DbError` out of
  `check_and_verify_auth_async`; `helpers/shares.py:246-259`
  (`PropertyListStore.exists` override) now sees `DbError` instead of `False`.
- D19. Frontend (`frontend/src/api/client.ts`, `AuthContext.tsx`,
  `TokenManager.ts`): `GET /properties/<name>` of a text value is `text/plain`
  (`displayname` at `AuthContext.tsx:131`); 409 `name_taken`; 503 with
  `Retry-After` on writes (do not blindly retry an `items` add); `DELETE /<id>`
  can answer 503; trust `PUT` needs `approved: true`; trust answers carry
  booleans; apply the "401 with `X-ActingWeb-Error` is final" rule on refresh
  but not on `/oauth/logout` (C8); the refresh cookie is on `path=/`.
- D20. `templates/` (if it overrides library templates; unknown from the
  inventory): `form_nonce` in `aw-oauth-authorization-form.html`, the `error`
  branch of `aw-oauth-confirm.html`, the `confirm` state of
  `aw-verify-email.html`. The application's own `/`, `/login` and
  `/oauth/email` routes shadow the library's: check whether they call the
  library's email-form internals, whose answers changed (guide 692-714).
- D21. `helpers/config.py:140` (bare `Config` in the cleanup and WebSocket
  functions): pass the application's indexed names (`["oauthId", "email"]`) and
  `force_email_prop_as_creator` so every process sharing the store agrees
  (guide 781-789, 1356-1361); they create no actors, so no `check_ready()` is
  needed as long as that stays true. `cleanup_handler.py`: the cleanup calls can
  raise `DbError`.
- D21a. `helpers/shares.py:923` reads `_internal`/`auth_method` directly: check
  its comparisons against the new value set (`app`, `factory`, `operator`,
  `creator_changed`, `email_unverified`, `email_verified`, `oauth2_bearer`,
  `system`, `<provider>_oauth2`; `docs/guides/authentication.rst:325-380`).
  `routes/websocket_local.py:85, 265` reads `spa_access_tokens` directly:
  unchanged, but prefer `get_oauth2_session_manager(config).validate_access_token`.
- D22. `scripts/`: `restore_actor.py` (writes actors and `_internal` directly:
  run `resolve --apply`, `enable --apply` and the `creator-to-email` dry run
  after a restore; guide 1265-1268, 1395-1396); `scripts/test-backends.sh` and
  the three workflows that run Alembic: order `alembic upgrade head` ->
  `actingweb-unique-creators enable --apply` -> start, with
  `DATABASE_BACKEND=postgresql` exported for the command (it defaults to
  `dynamodb`); test fixtures that wipe DynamoDB Local tables must run `enable
  --apply` again.
- D23. DynamoDB: confirm native TTL is enabled on `<prefix>_attributes`
  (`ttl_timestamp`); the chain-revoked markers rely on it (CL 406-433).

**Production, before the release's code is deployed** (operator machine or CI
job with the release installed, production environment, operator credentials;
every `actingweb-property-lookup` call with `--properties oauthId,email`)

- D24. `actingweb-mark-actors-vouched --email-as-creator --dry-run`, then
  without `--dry-run` (MCP sign-ups and every pre-release actor without a
  marker; otherwise each is cleaned at its next sign-in).
- D25. `actingweb-unique-creators report` -> `resolve --apply
  --default-creator-to-email` (choose `--keep` where it matters) -> `enable
  --apply`.
- D26. `actingweb-property-lookup report` -> `backfill --apply` (or
  `mark-complete --apply` if the 3.13 backfill ran).
- D27. `actingweb-unique-creators creator-to-email` (read the dry run) ->
  `--apply`.
- D28. Deploy D1/D2 if not yet live, then deploy the code. Watch for
  initialisation errors (`StoreNotReady` at import, B3).

**After every instance runs the release**

- D29. `enable --apply` again -> `report`; `creator-to-email --apply` again.
- D30. `actingweb-verify-property-lists --attributes`; `actingweb-deletions
  report` (run the Apple-token cleanup by hand for ids it finishes);
  `actingweb-peer-state report` -> `prune --apply` -> force new function
  instances.
- D31. Grep the logs for `not verified by the provider`, `LOOKUP_HEAL_FAILED`,
  `update the trust's base URI`, `Refused a permission callback`.
- D32. Peers: any environment still on 3.15.1 that subscribes to this one
  (a preview or staging stack) upgrades first or accepts B7's list; trusts it
  dropped are re-paired after the owner removes the stale row with
  `?notify=false`.
- D33. Only then raise any client-side item size limit, and only then drop the
  v1 lookup table and the `property-index` GSI.
