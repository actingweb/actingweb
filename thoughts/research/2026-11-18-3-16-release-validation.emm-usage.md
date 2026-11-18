# How Emm (actingweb_mcp) uses the actingweb library

**Date:** 2026-11-18
**Belongs to:** [`2026-11-18-3-16-release-validation.md`](2026-11-18-3-16-release-validation.md)
**Read at:** `../actingweb_mcp` `main` (`c1be751c`), through git, names only; this repository at `15b0e35`.


Read at Emm's `main` (commit `c1be751c`), through git only; pinned library `=3.15.1`. Compared against the library working tree on branch `release/3.16.0-release-validation`. Scope: production code, i.e. everything except `tests/`, `evals/`, `frontend/`, `plugin/` and `scripts/` (scripts are reported separately where they touch the library). `path:line` is Emm's file at main, first or most representative use; "sites" counts call sites in production code. Names only for environment variables and IAM actions.

## 1. Imports

45 distinct names from 34 library modules in production code (210 name-import sites summed over names); 25 further names are imported by scripts only (section 7h). Every imported name still resolves in the library tree (checked statically). `hooks/actingweb/` is Emm's own package; the relative imports in `hooks/__init__.py` are not library imports.

| Library module | Name | First use (path:line) | Import sites (production) | Import sites (scripts) |
|----------------|------|-----------------------|---------------------------|------------------------|
| `actingweb` | `attribute` | api/apple_entitlement.py:23 | 41 | 18 |
| `actingweb` | `auth` | helpers/template_helpers.py:267 | 1 | 0 |
| `actingweb` | `request_context` | application.py:458 | 1 | 0 |
| `actingweb.actor` | `Actor` | api/trust.py:185 | 1 | 12 |
| `actingweb.attribute_list_store` | `AttributeListStore` | api/trust.py:1090 | 8 | 8 |
| `actingweb.aw_proxy` | `AwProxy` | hooks/mcp/tools/execute_method.py:137 | 1 | 0 |
| `actingweb.aw_web_request` | `AWWebObj` | helpers/template_helpers.py:268 | 1 | 0 |
| `actingweb.config` | `Config` | helpers/config.py:125 | 1 | 0 |
| `actingweb.constants` | `OAUTH2_SYSTEM_ACTOR` | routes/websocket_local.py:83 | 2 | 0 |
| `actingweb.db` | `get_attribute` | helpers/beta_mode.py:213 | 5 | 4 |
| `actingweb.db` | `get_property` | helpers/shares.py:254 | 5 | 4 |
| `actingweb.db.dynamodb` | `auto_create_enabled` | hooks/mcp/services/trace_storage.py:33 | 1 | 0 |
| `actingweb.handlers` | `mcp` | application.py:319 | 1 | 0 |
| `actingweb.handlers.mcp` | `mcp_www_authenticate` | application.py:363 | 1 | 0 |
| `actingweb.interface` | `ActorInterface` | api/stripe_webhook.py:149 | 14 | 1 |
| `actingweb.interface` | `DeletionStatus` | api/revenuecat_webhook.py:150 | 6 | 1 |
| `actingweb.interface.actor_interface` | `ActorInterface` | api/auth_demo.py:172 | 19 | 14 |
| `actingweb.interface.app` | `ActingWebApp` | api/apple_entitlement.py:38 | 31 | 0 |
| `actingweb.interface.oauth_client_manager` | `OAuth2ClientManager` | api/oauth_clients.py:13 | 2 | 0 |
| `actingweb.interface.property_store` | `NotifyingListProperty` | repositories/property_list_accessor.py:15 | 1 | 0 |
| `actingweb.log_filter` | `RequestContextFilter` | application.py:208 | 1 | 0 |
| `actingweb.logging_config` | `configure_actingweb_logging_with_context` | helpers/template_helpers.py:6 | 1 | 0 |
| `actingweb.mcp` | `mcp_prompt` | hooks/mcp/prompts.py:35 | 1 | 0 |
| `actingweb.mcp` | `mcp_tool` | hooks/mcp/tool_decorator.py:14 | 1 | 0 |
| `actingweb.oauth2` | `create_apple_authenticator` | hooks/actingweb/lifecycle_hooks.py:432 | 1 | 0 |
| `actingweb.oauth2` | `create_oauth2_trust_relationship` | api/oauth_password.py:316 | 1 | 0 |
| `actingweb.oauth2_server.oauth2_server` | `get_actingweb_oauth2_server` | api/oauth_password.py:248 | 2 | 0 |
| `actingweb.oauth2_server.token_manager` | `ActingWebTokenManager` | cleanup_handler.py:37 | 1 | 0 |
| `actingweb.oauth2_server.token_manager` | `TokenStoreUnavailable` | api/auth_demo.py:31 | 2 | 0 |
| `actingweb.oauth_session` | `OAuth2SessionManager` | cleanup_handler.py:36 | 1 | 0 |
| `actingweb.oauth_session` | `get_oauth2_session_manager` | api/auth_demo.py:200 | 2 | 0 |
| `actingweb.peer_capabilities` | `get_cached_capabilities_store` | api/trust_unified.py:1053 | 3 | 2 |
| `actingweb.peer_permissions` | `get_peer_permission_store` | api/trust_unified.py:1169 | 4 | 3 |
| `actingweb.peer_profile` | `get_peer_profile_store` | api/trust_unified.py:797 | 3 | 3 |
| `actingweb.permission_evaluator` | `check_property_access` | api/memory_types.py:14 | 4 | 0 |
| `actingweb.permission_integration` | `AccessControlConfig` | application.py:49 | 1 | 0 |
| `actingweb.property` | `Property` | helpers/share_mail.py:305 | 1 | 0 |
| `actingweb.property` | `PropertyListStore` | helpers/shares.py:246 | 1 | 0 |
| `actingweb.property_list` | `ListItemHandle` | repositories/property_list_accessor.py:16 | 1 | 0 |
| `actingweb.remote_storage` | `RemotePeerStore` | api/memory_api.py:532 | 13 | 9 |
| `actingweb.runtime_context` | `RuntimeContext` | helpers/run_record.py:113 | 5 | 0 |
| `actingweb.runtime_context` | `get_client_info_from_context` | hooks/mcp/protocol/client_detection.py:189 | 1 | 0 |
| `actingweb.trust` | `Trust` | api/trust.py:863 | 1 | 0 |
| `actingweb.trust_permissions` | `TrustPermissions` | api/memory_types.py:436 | 5 | 0 |
| `actingweb.trust_permissions` | `get_trust_permission_store` | api/memory_types.py:436 | 10 | 0 |

Notes: `from actingweb import attribute` (41 sites) is the most-imported name; `ActorInterface` is imported from both `actingweb.interface` (14) and `actingweb.interface.actor_interface` (19); `ActingWebApp` (31) is imported almost everywhere under `TYPE_CHECKING` for route registration signatures. Underscore-private library names are never imported, but several are reached by attribute access (sections 7d, 7e).

## 2. The application builder

All in `application.py` at main. Values from the environment are named by variable only.

### 2a. Constructor and chain (in order)

| # | Call | path:line | Arguments (names; literal non-secret values) |
|---|------|-----------|-----------------------------------------------|
| 1 | `ActingWebApp(...)` | application.py:514 | `aw_type` = literal URN `urn:actingweb:actingweb.io:actingweb-ai-memory`; `database` = `helpers.config.DATABASE` (env `DATABASE_BACKEND`, Emm default `postgresql`); `fqdn` = env `APP_HOST_FQDN` (default `localhost`); `proto` = env `APP_HOST_PROTOCOL` (default `https://`) |
| 2 | `.with_web_ui` | application.py:520 | `enable=False` |
| 3 | `.with_devtest` | application.py:521 | `enable` = env `DEVTEST_MODE` == "true" |
| 4 | `.with_mcp` | application.py:527 | `enable=True`, `server_name="emm"`, `instructions=<literal text>` |
| 5 | `.with_subscription_processing` | application.py:547 | `auto_sequence=True`, `auto_storage=True`, `auto_cleanup=True`, `gap_timeout_seconds=5.0`, `max_pending=100` |
| 6 | `.with_peer_profile` | application.py:554 | `attributes=["displayname", "email"]` |
| 7 | `.with_peer_capabilities` | application.py:557 | `enable=True` |
| 8 | `.with_peer_permissions` | application.py:558 | `enable=True` |
| 9 | `.with_unique_creator` | application.py:561 | `enable=True` |
| 10 | `.with_email_as_creator` | application.py:562 | `enable=True` |
| 11 | `.with_indexed_properties` | application.py:563 | `["oauthId", "email"]` (positional) |
| 12 | `.with_legacy_property_index` | application.py:566 | `enable=False`. **Removed in 3.16** (tombstone raises `RuntimeError`); dropped by the adoption diff |
| 13 | `.add_actor_type` | application.py:567 | `name="myself"`, `factory` = env `APP_HOST_PROTOCOL` + env `APP_HOST_FQDN` + `/`, `relationship="friend"` |

### 2b. Conditional builder calls after the chain

| Call | path:line | Condition | Arguments (names) |
|------|-----------|-----------|-------------------|
| `app.with_sync_callbacks` | application.py:583 | env `AWS_LAMBDA_FUNCTION_NAME` set | `enable=True` |
| `app.with_oauth` | application.py:605 | env `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` set | `provider="google"`, `client_id`, `client_secret`, `scope="openid email profile"`, `auth_uri`, `token_uri` (Google endpoints, literals), `redirect_uri` (= proto + fqdn + `/oauth/callback`) |
| `app.with_google_native` | application.py:626 | env `GOOGLE_IOS_CLIENT_ID` or `GOOGLE_ANDROID_CLIENT_ID` set | `client_id`, `web_client_id`, `ios_client_id`, `android_client_id`, `android_server_client_id` (env `GOOGLE_ANDROID_SERVER_CLIENT_ID`) |
| `app.with_github` | application.py:646 | env `GH_OAUTH_CLIENT_ID` and `GH_OAUTH_CLIENT_SECRET` set | `client_id`, `client_secret`, `mobile_redirect_uri` (app deep link literal) |
| `app.with_apple_sign_in` | application.py:671 | env `APPLE_SIWA_CLIENT_ID`, `APPLE_SIWA_BUNDLE_ID`, `APPLE_SIWA_KEY_ID`, `APPLE_PRIVATE_KEY_PEM`, `APPLE_TEAM_ID` all set | `client_id`, `audiences=[client id, bundle id]`, `team_id`, `key_id`, `private_key_pem`, `mobile_redirect_uri` |

Not called anywhere in production code: `with_app_version`, `with_open_factory`, `with_spa_redirect_origins`, `with_spa_cors_origins`, `with_dynamodb`, `with_bot`, `with_list_item_limits`, `with_refresh_token_grace`, `with_thread_pool_workers`, `with_callback_delivery`, `add_service` and the `add_dropbox/gmail/github/box` helpers. No `.with_*`/`.add_*` call on the app exists outside `application.py`.

### 2c. Access control and integration

| Call | path:line | Arguments |
|------|-----------|-----------|
| `AccessControlConfig(app.get_config())` | application.py:700 | the app's `Config` |
| `access_control.add_trust_type` x3 | application.py:705, 783, 811 | see section 4b |
| `access_control.configure_oauth2_trust_types` | application.py:873 | `allowed_trust_types=["mcp_client_readonly", "mcp_client_readwrite"]`, `default_trust_type="mcp_client_readwrite"` |
| `app.integrate_fastapi(fastapi_app, templates_dir=...)` | application.py:905 | `templates_dir` = `"templates"` when the directory exists, else `None`. No other option. Called after Emm's static and SPA routes are registered, before its `/api` routes |
| `app.get_config()` | api/apple_entitlement.py:142 (first) | 140 call sites (131 on `aw_app`, 9 on `app`) |
| `app.is_mcp_enabled()` | hooks/__init__.py:50 | 1 (guarded by `hasattr`) |
| `Mangum(fastapi_app, lifespan="off", api_gateway_base_path="")` | application.py:948 | Lambda adapter (not a library API) |

Flask integration: not used.

## 3. Hooks

All registered by decorator on the app. No `app_callback_hook`, no `subscription_hook`, no `www` hook, no `callback_hook(..., allow_anonymous=...)` anywhere (every `callback_hook` call has one positional argument and no keyword).

### 3a. Lifecycle hooks (10)

| Event | path:line | Declared signature | Returns |
|-------|-----------|--------------------|---------|
| `actor_created` | hooks/actingweb/lifecycle_hooks.py:224 | `on_actor_created(actor, **kwargs)` | None; sets properties `email`, `created_at`, `mcp_usage_count`, seeds the `service` attribute bucket and default memory lists |
| `actor_deleted` | hooks/actingweb/lifecycle_hooks.py:298 | `on_actor_deleted(actor, **kwargs)` | None; reads `actor.core_actor.store.oauth_refresh_token` and config before deletion |
| `actor_deleted_complete` | hooks/actingweb/lifecycle_hooks.py:383 | `on_actor_deleted_complete(actor, actor_id=None, **kwargs)` (`actor` may be None) | None; revokes the Apple refresh token via `create_apple_authenticator(config).revoke_token(token=...)` |
| `oauth_success` | hooks/actingweb/lifecycle_hooks.py:463 | `on_oauth_success(actor, **kwargs)` (reads `kwargs["user_info"]`) | `True` always; sets `oauth_success_at`, `displayname`, `email` |
| `trust_initiated` | hooks/actingweb/lifecycle_hooks.py:511 | `on_trust_initiated_hook(actor, peer_id, relationship, trust_data, **kwargs)` | None; WebSocket notification |
| `trust_request_received` | hooks/actingweb/lifecycle_hooks.py:547 | `async on_trust_request_received_hook(actor, peer_id, relationship, trust_data, **kwargs)` | None; reads the peer profile, WebSocket notification |
| `trust_fully_approved_local` | hooks/actingweb/lifecycle_hooks.py:592 | `on_trust_fully_approved_local_hook(actor, peer_id, relationship, trust_data, **kwargs)` | None; WebSocket notification |
| `trust_fully_approved_remote` | hooks/actingweb/lifecycle_hooks.py:630 | `async on_trust_fully_approved_remote_hook(actor, peer_id, relationship, trust_data, **kwargs)` | None; notification, then auto-subscribes to the peer's `properties` (`on_trust_approved_async`, line 135) |
| `trust_deleted` | hooks/actingweb/lifecycle_hooks.py:675 | `on_trust_deleted_hook(actor, peer_id, relationship, trust_data, **kwargs)` (reads `kwargs["initiated_by_peer"]`) | None; WebSocket notification |
| `subscription_deleted` | hooks/actingweb/lifecycle_hooks.py:718 | `on_subscription_deleted_hook(actor, peer_id, subscription_id, subscription_data, **kwargs)` (reads `kwargs["initiated_by_peer"]`) | None; revokes the peer's granted patterns through `TrustPermissionStore.store_permissions` |

Two of the ten are `async def` (`trust_request_received`, `trust_fully_approved_remote`).

### 3b. Property hooks (1)

| Property | Operations handled | path:line | Declared signature | Returns |
|----------|--------------------|-----------|--------------------|---------|
| `"*"` | `get` (hide), `put`, `post` (protect and JSON-decode); other operations pass through | hooks/actingweb/property_hooks.py:27 | `handle_all_properties(actor, operation, value, path)` | `None` to hide `auth_token` and `_`-prefixed names on `get`, `None` to refuse writes to `auth_token`, `created_at`, `actor_type`, `email`, `displayname` by a non-power user; otherwise the value (a string value is JSON-decoded when it parses) |

### 3c. Callback hooks (3)

| Name | `allow_anonymous` | path:line | Declared signature | Returns |
|------|-------------------|-----------|--------------------|---------|
| `ping` | not passed | hooks/actingweb/callback_hooks.py:170 | `handle_ping_callback(actor, name, data)` | dict `{status, timestamp, actor_id}` |
| `status` | not passed | hooks/actingweb/callback_hooks.py:184 | `handle_status_callback(actor, name, data)` | dict of counts when `data["method"] == "GET"`, else `False` |
| `permissions` | not passed | hooks/actingweb/callback_hooks.py:202 | `handle_permission_callback(actor, name, data)` | `None` always; reads `granting_actor_id` and `permission_changes.granted_patterns/revoked_patterns`, sends WebSocket notifications. `permissions` is one of the library's own callback names |

### 3d. Subscription data hooks (1)

| Target | path:line | Declared signature | Returns |
|--------|-----------|--------------------|---------|
| `"properties"` | hooks/actingweb/callback_hooks.py:143 | `on_property_change(actor, peer_id, target, data, sequence, callback_type)` | None; `callback_type` `"resync"` or diff, forwards to WebSocket only (storage is the library's `auto_storage`) |

### 3e. Method hooks (8)

Signature for all: `(actor, method_name, data)` (the three resource hooks name the third parameter `params`).

| Name | Kind | path:line | Returns |
|------|------|-----------|---------|
| `extract_and_store`, `load_context`, `whats_new`, `browse_category`, `daily_news` | MCP prompts, each also decorated with `mcp_prompt(name=, description=, arguments=)` | hooks/mcp/prompts.py:37, 99, 223, 308, 450 | `str` (prompt text); four of five are `async` |
| `all_memories`, `profile_summary`, `recent_activity` | MCP resources (`memories://all`, `actingweb://profile/summary`, `actingweb://activity/recent?days={days}`) | hooks/mcp/resources.py:493, 513, 533 | dict (resource contents) |

The three resource hooks do **not** use `mcp_resource`: they set `_mcp_type = "resource"` and `_mcp_metadata = {uri_template, name, description, mime_type}` on the function with `setattr` (hooks/mcp/resources.py:501-511 and the two that follow).

### 3f. Action hooks (39, one mechanism)

Every one is `async def handle_*(actor, action_name, data) -> Dict[str, Any]` (three name the second parameter `_action_name`), returns an MCP result dict, and is also decorated with Emm's `mcp_tool` wrapper (`hooks/mcp/tool_decorator.py:17`, which mirrors `title` into `annotations` and calls `actingweb.mcp.mcp_tool`). `mcp_tool` keyword names used: `title`, `description`, `input_schema`, `annotations` (39 each), `visibility_predicate` (24), `description_predicate` (4). First: hooks/mcp/tools/agent_run.py:348.

Names: `agent_run agent_run_complete agent_run_task memory_create_type memory_delete memory_delete_type describe_method execute_method memory_get how_to_use instruction_delete instruction_list instruction_load instruction_merge_preview instruction_request_update_window instruction_save instruction_settings instruction_settings_update list_connections memory_move output_categories output_create output_dashboard output_delete output_delete_category output_edit output_get output_list output_move output_publish_html output_search output_update memory_save memory_search status task_draft memory_types memory_update work_on_task`

(`status` is both a callback hook name and an action hook name.)

### 3g. Trust hooks

No separate mechanism: the five `trust_*` lifecycle events in 3a.

## 4. Trust

### 4a. Calls

| API | path:line (first) | Sites | Purpose |
|-----|-------------------|-------|---------|
| `actor.trust.relationships` (property) | api/bootstrap.py:104 | 25 | list every relationship (UI lists, MCP client detection, counting, permission sweeps) |
| `actor.trust.get_relationship(peer_id)` | api/trust.py:94 | 17 | fetch one relationship before acting on a peer |
| `actor.trust.get_peer_profile(peer_id)` | api/memory_types.py:375 | 9 | cached peer `displayname`/`email` |
| `actor.trust.get_peer_capabilities(peer_id)` | hooks/mcp/tools/describe_method.py:105 | 2 | cached peer methods/actions for `describe_method` and `list_connections` |
| `actor.trust.delete_relationship(peer_id)` | api/trust.py:104 | 1 | remove a broken peer relationship |
| `actor.trust.create_relationship(remote_url, relationship, "", description)` | api/trust.py:258 | 1 | initiate trust from a background task, run through `loop.run_in_executor` (positional args) |
| `Actor(actor_id=, config=)` then `ActorInterface(core_actor)` | api/trust.py:188-189 | 1 | rebuild the actor inside that background task |
| `Trust(actor_id=, peerid=, config=)` + `.get()` + `.modify(last_accessed=...)` | api/trust.py:868-876 | 1 | stamp last-connected on a peer after a successful sync (core `actingweb.trust.Trust`, not the manager) |
| `get_trust_permission_store(config)` | api/memory_types.py:438 | 12 | obtain the per-relationship permission store |
| `TrustPermissionStore.get_permissions(actor_id, peer_id)` | api/memory_types.py:439 | 12 | read a relationship's override |
| `TrustPermissionStore.store_permissions_async(permissions)` | api/memory_types.py:476 | 5 | grant/revoke memory types from the SPA API |
| `TrustPermissionStore.store_permissions(permissions)` | hooks/actingweb/lifecycle_hooks.py:795 | 5 | revoke on unsubscribe, type deletion, type creation by an MCP client |
| `TrustPermissions(actor_id=, peer_id=, trust_type=, properties=)` | api/memory_types.py:448 | 7 | build an override (properties dict with `patterns`, `excluded_patterns`) |
| `get_peer_permission_store(config)` + `.get_permissions(actor_id, peer_id)` | api/trust_unified.py:87-88 | 4 + 4 | what a peer has granted this actor |
| `get_peer_profile_store(config)` + `.get_profile(actor_id, peer_id)` | api/trust_unified.py:693-694 | 3 + 3 | cached peer profile |
| `get_cached_capabilities_store(config)` + `.get_capabilities(actor_id, peer_id)` | api/trust_unified.py:712-713 | 3 + 3 | cached peer capabilities (`.methods`, `.actions`, `.fetched_at` read) |
| `check_property_access(...)` (5 positional) | api/memory_types.py:345 | 4 | evaluate a peer's access to a memory type |
| `create_oauth2_trust_relationship(actor=, email=, trust_type=, oauth_tokens=, established_via=, client_id=)` | api/oauth_password.py:318 | 1 | trust for an MCP client approved by password sign-in |
| `access_control.add_trust_type` | application.py:705 | 3 | see 4b |

Relationship attributes read: `peerid`, `relationship`, `peer_type`, `description`, `peer_approved`, `approved`, `client_name`, `client_version`, `peer_identifier`, `base_uri`, `oauth_client_id`, `last_accessed`, `is_active`, `established_via`, `created_at`, `user_agent`, `to_dict()`. One site reads `trust.desc` behind `hasattr` (hooks/mcp/protocol/client_detection.py:214); the manager's relationship object exposes `description`, not `desc`.

Not used: `TrustManager` by name, `approve_relationship`, `modify_trust`, `get_trust`, `delete_peer_trust`, `refresh_peer_profile*`, `refresh_peer_capabilities*`, `get_peer_methods/actions`, `create_verified_trust`, `PeerPermissionStore`/`TrustPermissionStore` class names (only the `get_*_store` factories).

### 4b. Trust types registered

| Name | path:line | `oauth_scope` | Property patterns / operations | methods / tools / resources / prompts |
|------|-----------|---------------|--------------------------------|----------------------------------------|
| `mcp_client_readonly` | application.py:705 | `"mcp"` | `memory_*`, `output_*`, `instruction_*`, `actions`, `creator`, `template_*` / `read` | methods `get_*`, `list_*`, `search_*`; tools: explicit list of 17 names; resources: 3 exact URIs; prompts `*` |
| `mcp_client_readwrite` | application.py:783 | `"mcp"` | same patterns / `read`, `write` | all `*` |
| `subscriber` | application.py:811 | `None` | `displayname`, `email` / `read` | all empty; carries `acl_rules` |

`subscriber` `acl_rules` at main, in order (path, method, access):

| Path | Method | Access |
|------|--------|--------|
| `subscriptions/<id>` | `POST` | `a` |
| `subscriptions/<id>/<subid>` | `GET` | `a` |
| `properties` | `GET` | `a` |
| `callbacks` | `""` (all methods) | `a` |
| `trust/<type>/<id>` | `GET` | `a` |
| `methods` | `POST` | `a` |
| `permissions/<id>` | `GET` | `a` |

The adoption diff adds `subscriptions/<id>/<subid>` `PUT` and `DELETE` (section 11).

## 5. Subscriptions

| API | path:line (first) | Sites | Purpose |
|-----|-------------------|-------|---------|
| `actor.subscriptions.subscribe_to_peer_async(peer_id=, target="properties", subtarget="", resource="", granularity="high")` | api/trust_unified.py:181; hooks/actingweb/lifecycle_hooks.py:165 | 2 | subscribe to a peer's whole `properties` target (manual, and automatic on `trust_fully_approved_remote`) |
| `actor.subscriptions.unsubscribe_from_peer(peer_id)` | api/trust_unified.py:287 | 1 | drop all outbound subscriptions to a peer, via `asyncio.to_thread` |
| `actor.subscriptions.revoke_peer_subscription(peer_id, sub_id)` | api/trust_unified.py:383 | 1 | end a peer's inbound subscription, via `asyncio.to_thread` |
| `actor.subscriptions.sync_peer_async(peer_id)` | api/trust.py:776 | 1 | manual "sync all" per peer; reads `.success`, `.subscriptions_synced`, `.total_diffs_processed`, `.error`; branches on the substrings `404`/`does not exist` and `403`/`Forbidden` in `.error` |
| `actor.subscriptions.suspend(target="properties", subtarget=<list name>)` | api/memory_import.py:619 | 1 | silence callbacks during a bulk import |
| `actor.subscriptions.resume(target="properties", subtarget=<list name>)` | api/memory_import.py:828 | 1 | resume and send a resync; uses the returned count |
| `actor.subscriptions.get_subscriptions_to_peer(peer_id)` | api/trust_unified.py:61 | 5 | outbound subscriptions to one peer |
| `actor.subscriptions.get_subscriptions_from_peer(peer_id)` | api/trust_unified.py:907 | 3 | inbound subscriptions from one peer |
| `actor.subscriptions.all_subscriptions` | api/trust_unified.py:867; hooks/actingweb/callback_hooks.py:198 | 2 | list/count |
| `actor.subscriptions.outbound_subscriptions` | api/trust.py:673 | 1 | find peers with a `properties` subscription |
| `RemotePeerStore(actor, peer_id)` | api/memory_api.py:534 | 13 | open a peer's replica (methods in section 6) |
| `app.with_subscription_processing(...)` | application.py:547 | 1 | section 2 |
| `app.subscription_data_hook("properties")` | hooks/actingweb/callback_hooks.py:143 | 1 | section 3d |

Subscription objects: `peer_id`, `target`, `subscription_id`, `is_outbound`, `to_dict()` read.

Not used in production code: `subscribe_to_peer` (sync), `unsubscribe`, `sync_peer` (sync), `sync_subscription*`, `rebuild_subscription*`, `is_suspended`, `get_subscription*`, `get_subscription_with_diffs` (scripts only), `notify_subscribers`, `register_diffs`, `SubscriptionProcessingConfig`, `CallbackProcessor`, `PeerCapabilities`, `get_peer_capabilities` as a function (only the `actor.trust` method and the cached store).

## 6. Shared data ("memories")

### 6a. Publishing

Shared data is property lists named `memory_<type>`; a subscriber sees a list only after an explicit grant (a `TrustPermissions` override listing the list names as patterns; the `subscriber` type itself grants only `displayname` and `email`). `output_*`, `instruction_*`, `template_*`, `actions` use the same list storage; the MCP client trust types grant them by pattern, and the `subscription_deleted` hook strips `memory_`, `output_`, `instruction_`, `template_` patterns plus `actions` and `creator` from a peer's override (hooks/actingweb/lifecycle_hooks.py:772-791), so a peer override may carry them too. Which of them a subscriber is ever granted in practice was not determined; the grant API reads are filtered on the `memory_` prefix. Almost every list call goes through `repositories/property_list_accessor.py` (`PropertyListAccessor`); the "callers" column counts Emm call sites of the accessor method.

| Library call | path:line of the library call | Callers | Note |
|--------------|-------------------------------|---------|------|
| `getattr(actor.property_lists, name)` | repositories/property_list_accessor.py:85 (first of 3 there) | 15 further direct sites, e.g. hooks/actingweb/lifecycle_hooks.py:116 | obtain / lazily create a list; outside the accessor the object is only read (`to_list` through `get_memory_items`, metadata), given metadata, or deleted whole |
| `list.append(item)` | repositories/property_list_accessor.py:391 | 12 | the only `append` in production code |
| `list.update_by_handle(handle, item)` | repositories/property_list_accessor.py:363 | 14 | the only item update in production code |
| `list.delete_by_handle(handle)` | repositories/property_list_accessor.py:338 | 9 | the only item delete in production code |
| `list.items_with_handles()` | repositories/property_list_accessor.py:311 | 17 | read with handles before a mutation |
| `list.clear()` | api/memory_import.py:611; repositories/property_list_accessor.py:422 | 1 + 0 | import in replace mode; `replace_all` has no production caller |
| `list.extend(items)` | repositories/property_list_accessor.py:424 | 0 | inside `replace_all`, no production caller |
| `list.delete()` (whole list) | repositories/local_memory_repository.py:859; repositories/output_repository.py:1590, 1595; repositories/instruction_repository.py:409; hooks/mcp/services/memory_type_evaluator.py:458 | 5 | delete a type/category list |
| `list.set_description` / `set_explanation` | memory_config.py:444, 446; repositories/property_list_accessor.py:426, 428 | 2 + 2 | type metadata (explanation holds a JSON payload) |
| `list.get_description` / `get_explanation` | memory_config.py:455, 458; repositories/property_list_accessor.py:420, 421 | 2 + 2 | read type metadata |
| `list.get_metadata()` | repositories/property_list_accessor.py:166 | 1 | `length` hint |
| `list.to_list(consistent=...)` | memory_config.py:582 | 19 via `accessor.to_items` | full read |
| `list.to_indexed_list()`, `len(list)`, `list[i]` | repositories/property_list_accessor.py:233, 261, 263 | 0 direct | v1-hole fallback read |
| `list.prime_from_rows(rows)` + `to_list_from_rows(rows)` | repositories/property_list_accessor.py:564-565, 608 | 7 + 1 | batched reads from one prefix query |
| `actor.property_lists.exists(name)` | repositories/property_list_accessor.py:62 | 41 via `accessor.exists` | |
| `actor.property_lists.list_all()` | repositories/property_list_accessor.py:464 | 10 via `accessor.list_all` | |
| `actor.property_lists.list_prefix_with_rows(prefix)` | repositories/property_list_accessor.py:466, 483 | 2 | |
| `actor.property_lists.list_all_with_rows()` | repositories/property_list_accessor.py:536 | 4 | |
| Scalar properties written | hooks/actingweb/lifecycle_hooks.py:231-233, 475, 498, 507; hooks/mcp/tools/shared.py:166 | 7 | `email`, `created_at`, `mcp_usage_count`, `oauth_success_at`, `displayname` (attribute-style assignment on `actor.properties`) |

Not used anywhere in production code: `insert`, `pop`, `remove`, `update_where`, `remove_where`, `append_once`, `item_at`, `slice`, `find`, `find_all`, `index`, `count`, `verify`, `compact`, `repair_keys`, `sweep_span_orphans`, `migrate_to_v2` (one script), `check_item_size`, `sizes_from_rows`. An AST pass over production code for objects obtained from `property_lists`, `accessor.get_list` or `accessor.get_or_create_list` found no subscript assignment or `del` on a list; the one subscript read is the v1 fallback at repositories/property_list_accessor.py:263.

Suspension during bulk import: section 5 (`suspend`/`resume` per list name as `subtarget`).

### 6b. Reading the replica (subscriber side)

| Call | path:line (first) | Sites | Purpose |
|------|-------------------|-------|---------|
| `RemotePeerStore(actor, peer_id)` | api/memory_api.py:534 | 13 | |
| `store.get_list(name)` | api/memory_api.py:546 | 9 | read a replicated `memory_*` list |
| `store.list_all_lists()` | api/memory_api.py:537 | 4 | discover replicated lists (filtered on the `memory_` prefix) |
| `store.get_all_properties()` | api/trust.py:981 | 3 | everything replicated from a peer; reads each entry's `["type"]` |
| `store.get_value("profile")` | api/trust_unified.py:73 | 1 | replicated scalar |
| `store.delete_all()` | api/trust.py:728 | 1 | purge orphaned replica data |
| `store.bucket` | api/trust.py:1119 | 8 | bucket name passed to `AttributeListStore` |
| `AttributeListStore(actor_id=, bucket=store.bucket, config=)` | api/trust.py:1117 | 8 | open the replica's attribute lists directly |
| `list_store.exists(name)`, `getattr(list_store, name)`, `.get_metadata()` | api/trust.py:1122-1124 | 8 each | list metadata (`updated_at`, description) of a replicated list |

Not used: `get_remote_bucket` (scripts only), `set_value`, `set_list`, `delete_list`, `delete_value`, `list_scalar_names`, `list_all_scalars`, `get_storage_stats`, `apply_callback_data`, `apply_resync_data`, `apply_permission_data`.

### 6c. Data hooks that fire

| Hook | path:line | What Emm does |
|------|-----------|---------------|
| `subscription_data_hook("properties")` | hooks/actingweb/callback_hooks.py:143 | on `diff`: per key, a list operation (`{"list", "operation", ...}`) or a scalar value, forwarded to the WebSocket layer; on `resync`: entries with `_list: True` forwarded as resync |
| `callback_hook("permissions")` | hooks/actingweb/callback_hooks.py:202 | WebSocket notification per granted/revoked `memory_*` pattern |
| `lifecycle_hook("subscription_deleted")` | hooks/actingweb/lifecycle_hooks.py:718 | revoke grants |
| `property_hook("*")` | hooks/actingweb/property_hooks.py:27 | filters `get`/`put`/`post` on properties, the peer-facing read path included |

## 7. Other library APIs used directly

### 7a. Actor and ActorInterface

| API | path:line (first) | Sites | Purpose |
|-----|-------------------|-------|---------|
| `ActorInterface(core_actor)` | helpers/template_helpers.py:336; api/trust.py:189 | 2 | wrap the actor returned by auth; wrap a rebuilt `Actor` |
| `ActorInterface.get_by_id(actor_id, config)` | api/revenuecat_webhook.py:336 | 4 | webhook and email paths |
| `ActorInterface.get_by_creator(email, config)` | api/auth_demo.py:174 | 3 | password/demo sign-in, share recipient lookup |
| `ActorInterface.get_deletion_status(actor_id, config)` + `DeletionStatus.DELETED` / `.NOT_DELETED` | api/revenuecat_webhook.py:154 | 7 | distinguish deleted from unknown actors |
| `actor.core_actor` (`.config`, `.store.oauth_refresh_token`) | hooks/actingweb/lifecycle_hooks.py:318 | 8 | config access; Apple refresh token |
| `actor.id`, `actor.creator`, `actor.config` | throughout | many | |
| `Actor(actor_id=, config=)` | api/trust.py:188 | 1 | section 4a |
| `auth.check_and_verify_auth_async(appreq=, actor_id=, config=)` + `AWWebObj(url=, params=, body=, headers=, cookies=)` | helpers/template_helpers.py:276-286 | 1 | the auth gate Emm's authenticated `/api` routes share; reads `auth_result["authenticated"]`, `["response"]["code"/"headers"/"text"]`, `["redirect"]`, `["actor"]`, `["auth"].acl["relationship"/"peerid"]` |

Not used: `ActorInterface.create`, `get_by_property`, `actor.delete()`, `modify_creator`, `refresh`, `as_peer`, `as_client`, `get_peer_info`, `attribute_lists`, `services`.

### 7b. Properties

| API | path:line (first) | Sites |
|-----|-------------------|-------|
| `actor.properties.<name>` read (`email`, `displayname`, `mcp_usage_count`) | api/service_info.py:160 | 9 |
| `actor.properties.<name> = value` (`email`, `created_at`, `mcp_usage_count`, `oauth_success_at`, `displayname`) | hooks/actingweb/lifecycle_hooks.py:231 | 7 |
| `actor.properties.get(name[, default])` (`mcp_usage_count`, `email`, `created_at`) | api/stripe_subscription.py:322 | 6 |
| `actor.properties.to_dict()` | hooks/actingweb/callback_hooks.py:194 | 1 |
| `Property(name="email", actor_id=, config=).get()` (core class) | helpers/share_mail.py:308 | 1 |
| `PropertyListStore` (core `actingweb.property`) subclassed to override `exists` | helpers/shares.py:246-259 | 1 |
| `get_property(config)` (db level): `.get(actor_id=, name=)`, `.create_if_not_exists(actor_id=, name=, value=)`, `.set_if_value_equals(actor_id=, name=, expected=, value=)`, `.delete_if_value_equals(actor_id=, name=, value=)` | repositories/memory_id_seq.py:74 | 12 `get_property` calls | atomic counters and an import lock stored as plain properties; two sites read the list meta row by its storage name `list:<name>-meta` (helpers/shares.py:256, repositories/property_list_accessor.py:500) |

### 7c. Attributes

| API | path:line (first) | Sites |
|-----|-------------------|-------|
| `attribute.Attributes(actor_id=, bucket=, config=)` | api/apple_entitlement.py:201 | 82 constructor sites |
| `.get_attr(name=)` | api/context_creator.py:453 | 47 |
| `.set_attr(name=, data=[, ttl_seconds=])` | api/context_creator.py:460 | 66 |
| `.delete_attr(name=)` | helpers/dashboard_documents.py:138 | 24 |
| `.conditional_update_attr(name=, old_data=, new_data=)` | api/memory_review.py:104 | 11 |
| `.get_bucket()` | api/service_info.py:303 | 3 |
| `get_attribute(config).get_attr_strict(actor_id=, bucket=, name=)` (db level) | helpers/beta_mode.py:219 | 5 |

Bucket names: `service`, `subscription`, `demo_auth`, `guided_instructions`, `mcp_write_tracking`, `internal`, `shares`, `shares_received`, `share_consent`, `share_requests`, `websocket_connections`, `websocket_connection_index`, `websocket_subscriptions` (the two connection buckets live under Emm's own system actor id). Library-owned buckets read directly: `spa_access_tokens` under `OAUTH2_SYSTEM_ACTOR` (routes/websocket_local.py:85, 265) and `_internal` / `auth_method` (helpers/shares.py:923).

Not used: `InternalStore`, `Buckets`, `create_attr_if_absent`, `delete_attr_conditional`, `delete_bucket` (scripts only), attribute lists on the actor (`actor.attribute_lists`).

### 7d. Config

| API | path:line | Sites |
|-----|-----------|-------|
| `Config(aw_type=, database=, fqdn=, proto=)` built directly | helpers/config.py:140 | 1 (used by the cleanup and WebSocket Lambdas, which never build the `ActingWebApp`; this `Config` carries none of the builder settings such as indexed properties or unique creator) |
| `config.fqdn`, `config.proto` read | application.py:374 (first) | about 19 |
| `config.new_token()` | api/auth_demo.py:203 | 2 (one asserts the result is 40 lowercase hex) |
| `getattr(config, "_oauth2_trust_types", None)` | api/oauth_password.py:118 | 1 (private attribute) |

No Config attribute is assigned by Emm.

### 7e. OAuth2 and MCP

| API | path:line | Sites | Purpose |
|-----|-----------|-------|---------|
| `with_oauth`, `with_google_native`, `with_github`, `with_apple_sign_in`, `with_mcp` | application.py | 1 each | section 2 |
| `mcp_tool` (through Emm's wrapper) | hooks/mcp/tool_decorator.py:14 | 39 | section 3f |
| `mcp_prompt(name=, description=, arguments=)` | hooks/mcp/prompts.py:38 | 5 | |
| `mcp_resource` | not used | 0 | resources set `_mcp_type`/`_mcp_metadata` by hand (section 3e) |
| `get_actingweb_oauth2_server(config)` | application.py:416; api/oauth_password.py:250 | 2 | |
| `oauth2_server.token_manager.validate_access_token(token)` (returns a 3-tuple, index 0 used) | application.py:427 | 1 | account-status gate in front of `/mcp` |
| `oauth2_server.token_manager.create_authorization_code(actor_id=, client_id=, provider_token_data=, user_email=, trust_type=, code_challenge=, code_challenge_method=)` | api/oauth_password.py:340 | 1 | password approval on the MCP authorize page |
| `oauth2_server.client_registry.validate_client(client_id)`, `.validate_redirect_uri(client_id, redirect_uri)` | api/oauth_password.py:251, 254 | 1 each | |
| `getattr(oauth2_server, "_store_mcp_client_info_in_trust", None)` | api/oauth_password.py:360 | 1 | private; the name no longer exists in the library tree (also absent at the pinned 3.15.1), so the guarded call is a silent no-op |
| `TokenStoreUnavailable` | application.py:428; api/auth_demo.py:209 | 2 | |
| `actingweb.handlers.mcp._token_cache`, `._cache_ttl` | application.py:321, 324 | 1 each | private module globals, to mirror the library's five-minute token cache |
| `mcp_www_authenticate(base_url)` | application.py:374 | 1 | 401 challenge for an unauthenticated `initialize` |
| `get_oauth2_session_manager(config)`: `.store_access_token(token, actor_id, email)`, `.create_refresh_token(actor_id, email)`, `.validate_access_token(token)` | api/auth_demo.py:202-208; websocket_handlers/default.py:355-356 | 2 | demo sign-in mints SPA tokens itself; WebSocket auth |
| `OAuth2SessionManager(config)`: `.clear_expired_sessions()`, `.cleanup_expired_tokens()` | cleanup_handler.py:49-61 | 1 | scheduled cleanup Lambda |
| `ActingWebTokenManager(config)`: `.cleanup_expired_tokens()` | cleanup_handler.py:70 | 1 | scheduled cleanup Lambda |
| `OAuth2ClientManager(actor_id, config)`: `create_client(client_name=, trust_type=, client_uri=, redirect_uris=)`, `get_client`, `list_clients`, `delete_client`, `regenerate_client_secret`, `generate_access_token(scope=)` | api/oauth_clients.py:40 | 5 constructors | MCP client management API |
| `create_apple_authenticator(config).revoke_token(token=)` | hooks/actingweb/lifecycle_hooks.py:434 | 1 | |
| `RuntimeContext(actor).get_mcp_context()` | helpers/run_record.py:117 | 5 | which MCP client is calling |
| `get_client_info_from_context(actor)` | hooks/mcp/protocol/client_detection.py:191 | 1 | |
| `OAUTH2_SYSTEM_ACTOR` | routes/websocket_local.py:83 | 2 | |

### 7f. Proxy, logging, context, backend helpers

| API | path:line | Sites | Purpose |
|-----|-----------|-------|---------|
| `AwProxy(peer_target={"id", "peerid"}, config=, timeout=20)`; `.trust`, `.create_resource(path="methods/<name>", params=)`, `.last_response_code` | hooks/mcp/tools/execute_method.py:139-175 | 1 | call a peer's method |
| `configure_actingweb_logging_with_context(level=, db_level=, handlers_level=, enable_context=)` | helpers/template_helpers.py:70, 88 | 2 | |
| `RequestContextFilter` | application.py:208 | 1 | added to root handlers at startup |
| `request_context.set_actor_id(actor_id)` | application.py:460 | 1 | actor id in `/mcp` log records |
| Logger names set to WARNING: `actingweb.actor`, `actingweb.permission_evaluator`, `actingweb.oauth2_server`, `actingweb.aw_proxy` | application.py:238 | 1 | |
| `actingweb.db.dynamodb.auto_create_enabled()` | hooks/mcp/services/trace_storage.py:33 | 1 | gate Emm's own table creation on the library's switch |

### 7g. Maintenance modules and console scripts

| Item | Where | Note |
|------|-------|------|
| Library console scripts (`actingweb-unique-creators`, `actingweb-property-lookup`, `actingweb-verify-property-lists`, ...) | none in code, CI or scripts at main | only a prose mention in docs/repository-pattern.md:484. The adoption diff is the first invocation (`actingweb-unique-creators enable --apply` in scripts/test-backends.sh) |
| `actingweb.maintenance.*` imports | none | |
| Alembic against the library's packaged `db/postgresql/alembic.ini` | .github/workflows/integration-tests.yml:151, e2e-tests.yml:216, ai-evaluation.yml:96; scripts/migrate_db.py:34 | PostgreSQL schema for tests and local development |

### 7h. Scripts (operator tools, not production paths)

Scripts reuse the production APIs above (attributes, `ActorInterface.get_by_id`, `RemotePeerStore`, the accessor) and add these, which production code does not touch:

| Library name | Script (first) | Files |
|--------------|----------------|-------|
| `actingweb.config` | scripts/backfill_output_link_ids.py:225 | 19 |
| `actingweb.db.get_actor` | scripts/restore_actor.py:1320 | 4 |
| `actingweb.db.get_attribute_bucket_list` | scripts/restore_actor.py:1320 | 3 |
| `actingweb.db.get_peer_trustee` | scripts/restore_actor.py:1817 | 1 |
| `actingweb.db.get_peer_trustee_list` | scripts/restore_actor.py:1320 | 3 |
| `actingweb.db.get_property_list` | scripts/measure_embedding_coverage.py:95 | 7 |
| `actingweb.db.get_subscription` | scripts/restore_actor.py:1817 | 1 |
| `actingweb.db.get_subscription_diff` | scripts/restore_actor.py:1817 | 1 |
| `actingweb.db.get_subscription_diff_list` | scripts/restore_actor.py:1320 | 3 |
| `actingweb.db.get_subscription_list` | scripts/restore_actor.py:1320 | 3 |
| `actingweb.db.get_trust` | scripts/restore_actor.py:1817 | 1 |
| `actingweb.db.get_trust_list` | scripts/restore_actor.py:1320 | 3 |
| `actingweb.db.dynamodb.property_lookup.DbPropertyLookup` | scripts/backfill_output_link_ids.py:79 | 7 |
| `actingweb.db.dynamodb.property_lookup.PropertyLookupV2` | scripts/verify_integrity.py:1368 | 3 |
| `actingweb.db.dynamodb.property_lookup.compute_lookup_key` | scripts/verify_integrity.py:1368 | 1 |
| `actingweb.db.dynamodb.subscription_suspension.DbSubscriptionSuspension` | scripts/debug_actor.py:249 | 2 |
| `actingweb.db.postgresql.connection.close_pool` | scripts/debug_actor.py:1554 | 5 |
| `actingweb.db.postgresql.connection.get_connection` | scripts/manage_actors.py:95 | 6 |
| `actingweb.db.postgresql.property_lookup.DbPropertyLookup` | scripts/backfill_output_link_ids.py:77 | 7 |
| `actingweb.db.postgresql.subscription_suspension.DbSubscriptionSuspension` | scripts/debug_actor.py:245 | 2 |
| `actingweb.logging_config.configure_actingweb_logging` | scripts/backfill_output_link_ids.py:65 | 18 |
| `actingweb.mcp.decorators.get_mcp_metadata` | scripts/regenerate_eval_mocks.py:35 | 1 |
| `actingweb.oauth2.create_google_authenticator` | scripts/seed_demo_actor.py:314 | 1 |
| `actingweb.remote_storage.get_remote_bucket` | scripts/debug_actor.py:664 | 4 |
| `import actingweb` (to locate the packaged `alembic.ini`) | scripts/migrate_db.py:31 | 1 |
| `actor.subscriptions.get_subscription_with_diffs(peer_id=, subscription_id=)` + `.get_diffs()` | scripts/debug_actor.py:286 | 1 |
| `list.migrate_to_v2()` | scripts/seed_demo_actor.py:713 | 1 |
| `Attributes.delete_bucket`, db-level `set_attr(actor_id=, bucket=, name=, data=)` | scripts/restore_actor.py:1775 | 2 |

`scripts/restore_actor.py:221` hard-codes the indexed property names `("oauthId", "email")` beside the builder's list.

## 8. HTTP surface

### 8a. Library routes Emm's frontend calls on its own server

| Route pattern | Methods | path:line |
|---------------|---------|-----------|
| `/<id>/properties` | GET | frontend/src/api/client.ts:924 |
| `/<id>/properties/<name>` | GET, PUT, DELETE | frontend/src/api/client.ts:926-930; frontend/src/context/AuthContext.tsx:131 (`displayname`) |
| `/<id>/properties/<name>/metadata` | GET, PUT | frontend/src/api/client.ts:932-935 |
| `/<id>/properties/<name>/items` | GET, POST (`action` add / update / delete with `item_value`, `item_index`) | frontend/src/api/client.ts:939-952 |
| `/<id>/trust` | GET, POST | frontend/src/api/client.ts:958, 964 |
| `/<id>/trust/<relationship>/<peerid>` | GET, PUT, DELETE | frontend/src/api/client.ts:961-984 |
| `/<id>/meta`, `/<id>/meta/trusttypes` | GET | frontend/src/api/client.ts:1010, 1012 |
| `/<id>` | DELETE | frontend/src/api/client.ts:2079 |
| `/oauth/config` | GET | frontend/src/context/AuthContext.tsx:213 |
| `/oauth/session` | GET | frontend/src/context/AuthContext.tsx:262, 941 |
| `/oauth/spa/authorize` | POST | frontend/src/context/AuthContext.tsx:586; frontend/src/auth/MobileAuthProvider.ts:243 |
| `/oauth/spa/token` | POST | frontend/src/auth/TokenManager.ts:670; frontend/src/auth/MobileAuthProvider.ts:189, 214 |
| `/oauth/spa/session/<session_id>` | GET | frontend/src/context/AuthContext.tsx:725 |
| `/oauth/spa/revoke` | POST | frontend/src/context/AuthContext.tsx:850 |
| `/oauth/logout` | POST | frontend/src/context/AuthContext.tsx:827 |
| `/oauth/callback?...` | GET | frontend/src/context/AuthContext.tsx:738 |

Of these, `/oauth/spa/session/<session_id>` and `/oauth/spa/revoke` are not described anywhere under the library's `docs/` (the first appears only in `CHANGELOG.rst`). The `/items` list endpoint with positional `item_index` is documented in `docs/guides/property-lists.rst`.

### 8b. Library routes Emm's server calls on peers

| Route | Method | path:line | How |
|-------|--------|-----------|-----|
| `<peer>/meta` (reads `aw_trust_types`) | GET | api/trust.py:197-204 | plain `httpx`, unauthenticated, before creating trust |
| `<peer>/methods/<method_name>` | POST | hooks/mcp/tools/execute_method.py:167 | `AwProxy.create_resource` |
| Trust, subscription, callback, permission routes | - | - | only through the library (`create_relationship`, `subscribe_to_peer_async`, `sync_peer_async`, `unsubscribe_from_peer`, `revoke_peer_subscription`, permission store notifications) |

### 8c. Routes Emm mounts beside the library's

160 route registrations at main.

| Group | Count | Registered | Notes |
|-------|-------|------------|-------|
| `/{actor_id}/api/...` (memory, outputs, instructions, shares, trust, service, subscription billing, context creator, ...) | 122 | after `integrate_fastapi` (application.py:910-944) | Emm's own JSON API; its authenticated routes go through `auth.check_and_verify_auth_async` (section 7a) |
| `/api/auth/demo`, `/api/suggest-topic-areas`, `/api/suggest-area-questions`, `/api/suggest-task-detail-areas`, `/api/rebuild-task-prompt` | 5 | after | |
| `/oauth/authorize/password` (POST) | 1 | after | sibling of the library's `/oauth/authorize` |
| `/webhook/stripe`, `/webhook/revenuecat` | 2 | after | |
| `/`, `/login`, `/callback`, `/oauth/email` (GET and POST), `/terms`, `/privacy`, `/data-deletion`, `/support`, `/{actor_id}/share/{share_hash}`, `/{actor_id}/app`, `/{actor_id}/app/{path}` | 12 | **before** `integrate_fastapi` (routes/spa.py:138-209) | `/`, `/login` and `/oauth/email` (GET and POST) are paths the library also registers; Emm's win because they are registered first. The library registers no `/callback` and no `/{actor_id}/app` |
| `/health`, favicons, `/robots.txt`, `/security.txt`, `/.well-known/security.txt`, `/sitemap.xml`, `/llms.txt`, `/llms-full.txt`, `/setup*`, `/connect-claude*` | 16 | before (helpers/static_routes.py) | |
| `/static` (mount), `/ws` (WebSocket, local only) | 2 | application.py:892, 284 | production WebSocket is a separate API Gateway API with three Lambdas |

Middleware in front of the library's `/mcp`: `mcp_authenticated_request_guard` (application.py:382) answers an unauthenticated `initialize` with 401 itself, and gates authenticated requests on Emm's account status.

## 9. Deployment shape

| Aspect | Value | Source |
|--------|-------|--------|
| Runtime | AWS Lambda container image behind API Gateway HTTP API, FastAPI through Mangum (`lifespan="off"`); handler `application.handler`; arm64, 1024 MB, 120 s timeout; 5-minute warm-up schedule | serverless.yml:236-300; application.py:948-991; Dockerfile-fastapi.lambda:58 |
| Other functions | `cleanup` (daily schedule, `cleanup_handler.handler`), three WebSocket Lambdas (`websocket_handlers/*`); these build `Config` directly, not the `ActingWebApp` | serverless.yml:318-382; helpers/config.py:140 |
| Callbacks | `with_sync_callbacks(enable=True)` on Lambda; default async fire-and-forget locally. No `callback_delivery_budget_seconds`, `serialize_own_host_callbacks` or `max_concurrent_callbacks` set | application.py:581-588 |
| Local | uvicorn, port 5000, long-running | application.py:994-1005 |
| Database, production | DynamoDB, selected through `DATABASE_BACKEND`; table auto-creation turned off through `AWS_DB_AUTO_CREATE_TABLES`; tables from CloudFormation or created earlier | serverless.yml:123, 137 |
| Database, tests | PostgreSQL 16 for the main suites (integration, e2e, AI evaluation workflows); DynamoDB Local for the `backend_specific` and `server_smoke` jobs, the `quick-eval` workflow and `scripts/test-backends.sh`; Emm's code default is `postgresql` | .github/workflows/integration-tests.yml:165, 505; .github/workflows/quick-eval.yml:53; scripts/test-backends.sh:44; helpers/config.py:15 |
| Python | `^3.13` in pyproject; Lambda base image `python:3.13`; CI `3.13` | pyproject.toml:10; Dockerfile-fastapi.lambda:1 |
| Library pin | `actingweb = { version = "=3.15.1", extras = ["fastapi"] }` | pyproject.toml:11 |

## 10. Names only

### 10a. Environment variables shared with or configuring the library

| Variable | Read by library | Read in Emm production code (sites; first) | Set in serverless.yml | In CI / test scripts |
|----------|-----------------|---------------------------------------------|-----------------------|----------------------|
| `APP_HOST_FQDN` | yes | 16; api/auth_demo.py:88 | yes | yes |
| `APP_HOST_PROTOCOL` | yes | 14; api/stripe_subscription.py:640 | yes | yes |
| `DATABASE_BACKEND` | yes | 2; helpers/config.py:15 | yes | yes |
| `AWS_DB_PREFIX` | yes | 2; helpers/config.py:16 | yes | yes |
| `AWS_DB_HOST` | yes | 1; hooks/mcp/services/trace_storage.py:74 | no | yes |
| `AWS_DB_AUTO_CREATE_TABLES` | yes | 0 (through `auto_create_enabled()`) | yes | no |
| `AWS_DEFAULT_REGION` | yes | 0 | no | yes |
| `AWS_LAMBDA_FUNCTION_NAME` | yes | 9; api/revenuecat_webhook.py:650 | set by Lambda | no |
| `LOG_LEVEL` | yes | 5; cleanup_handler.py:15 | yes | yes |
| `PG_DB_HOST`, `PG_DB_PORT`, `PG_DB_NAME`, `PG_DB_USER`, `PG_DB_PASSWORD` | yes | 0 | no | yes |
| `DEVTEST_MODE` | no (Emm's name, feeds `with_devtest`) | 1; application.py:521 | no | yes |
| `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_IOS_CLIENT_ID`, `GOOGLE_ANDROID_CLIENT_ID`, `GOOGLE_ANDROID_SERVER_CLIENT_ID`, `GH_OAUTH_CLIENT_ID`, `GH_OAUTH_CLIENT_SECRET`, `APPLE_SIWA_CLIENT_ID`, `APPLE_SIWA_BUNDLE_ID`, `APPLE_SIWA_KEY_ID`, `APPLE_PRIVATE_KEY_PEM`, `APPLE_TEAM_ID` | no (Emm's names, feed the OAuth builders) | 1 each; application.py:597-661 | yes | not determined |
| `AW_SKIP_DOTENV` | no (Emm's own) | 1; application.py:29 | no | no |

Library variables Emm sets or reads nowhere: `INDEXED_PROPERTIES`, `USE_PROPERTY_LOOKUP_TABLE`, `PG_DB_PREFIX`, `PG_DB_SCHEMA`, `PG_DB_URL`, `PG_POOL_*`, `ACTINGWEB_DEBUG`, `ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH`, `ACTINGWEB_PG_DELETE_DIAGNOSTICS`, `APP_BOT_*`, `AWS_EXECUTION_ENV`.

### 10b. IAM and DynamoDB

Source: `serverless.yml:197-234` (the only policy file found; no terraform or separate template) and `tests/test_dynamodb_iam_coverage.py`.

| Statement | Actions granted | Resource pattern |
|-----------|-----------------|------------------|
| DynamoDB | `dynamodb:Query`, `dynamodb:Scan`, `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:DeleteItem`, `dynamodb:BatchWriteItem` | tables matching `<AWS_DB_PREFIX>_*` |
| Bedrock | `bedrock:InvokeModel` | model and inference-profile resources (not library related) |
| WebSocket | `execute-api:ManageConnections` | connection resources |

Deliberately absent (comment at serverless.yml:212): `dynamodb:CreateTable`, `dynamodb:DescribeTable`. Also not granted: `dynamodb:BatchGetItem`, `dynamodb:ConditionCheckItem`, `dynamodb:TransactGetItems`.

Tables declared in CloudFormation by Emm: `<AWS_DB_PREFIX>_rate_limits` (Emm's own), `<AWS_DB_PREFIX>_property_lookup_v2`, `<AWS_DB_PREFIX>_subscription_suspensions`. Emm's own extra table by code: `<AWS_DB_PREFIX>_ai_traces`. The library's other tables (actors, properties, attributes, trusts, subscriptions, ...) are not declared there, and no `<AWS_DB_PREFIX>_creators` table is declared.

The coverage test maps pynamodb/boto call shapes in the installed library to action names, among them `TransactWrite` to `dynamodb:TransactWriteItems` and `.batch_get(` to `dynamodb:BatchGetItem`, and exempts `CreateTable`/`DescribeTable` as auto-create only (tests/test_dynamodb_iam_coverage.py:33-72).

Against this library tree: `PropertyLookupV2.batch_get` (startup readiness check) needs `BatchGetItem`, and the `TransactWrite` calls in `db/dynamodb/actor.py` and `property.py` need `ConditionCheckItem`; the 3.16 migration guide states both, says IAM has no `TransactWriteItems` action, and lists a new `<prefix>_creators` table. None of the three is in Emm's policy or template at main, and the adoption diff does not touch `serverless.yml`.

## 11. The adoption diff

Worktree branch `actingweb-3-16-adoption`, based on main's head; uncommitted; four files changed (`poetry.lock` skipped).

| File | Change | Library change it answers |
|------|--------|---------------------------|
| application.py | removes `.with_legacy_property_index(enable=False)` from the builder chain | 3.16 removed the legacy reverse-lookup path; the method is a tombstone that raises `RuntimeError` at configure time (`CHANGELOG.rst`, "One reverse-lookup mechanism"; `actingweb/interface/app.py:522`) |
| application.py | adds `("subscriptions/<id>/<subid>", "PUT", "a")` and `("subscriptions/<id>/<subid>", "DELETE", "a")` to the `subscriber` trust type's `acl_rules` | 3.16: "An access row authorises the method a request performs; a PUT or DELETE is no longer admitted by a GET row". The same changelog entry says a subscriber type with only a GET row needs no new rows, because the built-in `owner` rows now cover a peer's own subscription; whether these two rows are still needed against the current tree was not determined |
| pyproject.toml | comments out the `=3.15.1` pin and points `actingweb` at a local path dependency (a library worktree, `develop = true`, `extras = ["fastapi"]`) | run against the unreleased library; not a release-ready pin |
| scripts/test-backends.sh | before starting the server on DynamoDB Local: `python -c "import application"` once (creates tables, expected to fail), then `actingweb-unique-creators enable --apply`, then start; log is appended instead of overwritten | 3.16: `unique_creator` readiness is checked at start (`UniqueCreatorNotReady`); a fresh store starts once, runs `enable --apply`, and starts again |

Not in the diff although 3.16 touches them: the IAM policy and CloudFormation tables (section 10b), the PostgreSQL CI path (Alembic is already run from the packaged config), and the direct `Config(...)` in `helpers/config.py`.
