# A bare `Config()` in a background process silently differs from the app

**Filed:** 2026-11-25, by the A2A research
(`thoughts/research/2026-11-24-a2a-actor-interface.tasks.md`, "Worker
execution paths").

Some processes build a plain `Config()` and load an actor with `get_by_id`
instead of building the app:
- the library's operator commands (`maintenance/property_lookup.py:176-184`,
  `maintenance/peer_state.py:120-124`)
- one consumer's cleanup and WebSocket Lambdas

Such a process writes through the same stores as the app, but with a
different setup. Nothing warns about it:

- **Hooks.** The app's hooks are wired only on the app path (`app.py:1728`),
  so property and list hooks don't run.
- **Delivery.** Without the app's `_subscription_config`, `deliver()` waits for
  every subscriber callback (`callback_sender.py:278-312`).
- **Indexed properties.** A bare `Config` defaults to
  `["oauthId","email","externalUserId"]` (`config.py:420`). An app that
  configures a different set then indexes differently in the two processes.
- **List-item limits.** These are the backend defaults
  (`config.py:262`), not the app's `with_list_item_limits()`. A list then
  spans or refuses items differently in the two processes.
- **Readiness.** `check_ready()` runs only from `integrate_*`.
- **Logging.** Log lines show `[-:-:-]` without `set_request_context()`.

The documented path is `get_by_id(actor_id, config=app.get_config())`
(`docs/sdk/actor-interface.rst:35-50`), but no guide describes a worker or
background process as a deployment shape. The A2A tasks plan documents its own
task workers, which build the app. This todo covers every other background
process.

**Options:**
- **A deployment-shape section in the docs:** build the app, call
  `get_config()` and `check_ready()`, set the request context.
- **A warning** when stores are used with a `Config` that no app built.
- **The operator commands build the configuration from the same environment
  as the app.** Most of them already read the same variables.
