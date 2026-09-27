# MCP token manager hygiene follow-ups (PR #148 review)

**Provenance:** the Claude code review of PR #148 (2026-09-26), verified
against `a3950a9` on 2026-09-27. All Low; none changes behaviour a consumer
sees. Filed rather than fixed so the hardening PR could merge on the
agreed exit rule (fix only High, Medium and regressions).

1. **`validate_access_token` drops the owner it already has.**
   `oauth2_server/token_manager.py`, the expired branch of
   `validate_access_token`, calls `self._remove_access_token(token)` with
   `token_data["actor_id"]` in hand. The no-`actor_id` branch re-reads the
   index and the actor row, deletes the actor row *before* the index row
   (the reverse of the 3.15 index-first order), and uses a plain
   `delete_attr` instead of `delete_confirmed`. Validity is not at stake, the
   token is already past `expires_at`, but it is two reads and one ordering
   inconsistency per expired presentation. Pass
   `actor_id=token_data["actor_id"]` (and `google_token_key` when present).
   While there, make the fallback branch delete the index row first too,
   so the invariant's docstring is true of both branches.

2. **`summarize_payload` runs before the level check.** Thirteen
   `logger.debug(f"...{summarize_payload(...)}")` sites in `actor.py` and
   `aw_proxy.py` evaluate the summary whatever the level. The work is a
   sorted, sanitised key listing, no value serialisation, and it replaced
   `f"{data}"` on the same lines, which stringified the whole payload; so
   it is cheaper than before, not a regression. Still, `aw_proxy` is a
   documented performance-sensitive logger: guard with
   `logger.isEnabledFor(logging.DEBUG)` or pass the summary lazily.

3. **Duplicated helpers.** `single_use._mask` and
   `token_manager._mask_token` are the same function; `token_manager`
   already imports from `single_use`, so import the one. The TTL stamp
   `int(time.time()) + ttl_seconds + TTL_CLOCK_SKEW_BUFFER` is written in
   both backends' `set_attr` and again in their new
   `conditional_update_attr`; one helper per backend module (or one in
   `db/`) keeps the skew buffer in one place.

4. **The two rotation ladders are still two implementations.** The SPA
   (`handlers/oauth2_spa.py`) and MCP (`token_manager.refresh_access_token`)
   reuse ladders share `single_use.consume_once` but not the tiers or the
   theft response. This is what
   `thoughts/plans/2026-09-26-spa-refresh-reuse-after-dropped-rotation.md`
   is for; recorded here only so the review's point is not re-filed.
