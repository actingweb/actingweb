# MCP token manager hygiene follow-ups (PR #148 review)

**Provenance:** the Claude code review of PR #148 (2026-09-26), verified
against `a3950a9` on 2026-09-27. Both Low; neither changes behaviour a
consumer sees. Filed rather than fixed so the hardening PR could merge on the
agreed exit rule (fix only High, Medium and regressions).

1. **`summarize_payload` runs before the level check.** Thirteen
   `logger.debug(f"...{summarize_payload(...)}")` sites in `actor.py` and
   `aw_proxy.py` evaluate the summary whatever the level. The work is a
   sorted, sanitised key listing, no value serialisation, and it replaced
   `f"{data}"` on the same lines, which stringified the whole payload; so
   it is cheaper than before, not a regression. Still, `aw_proxy` is a
   documented performance-sensitive logger: guard with
   `logger.isEnabledFor(logging.DEBUG)` or pass the summary lazily.

2. **The two rotation ladders are still two implementations.** The SPA
   (`handlers/oauth2_spa.py`) and MCP (`token_manager.refresh_access_token`)
   reuse ladders share `single_use.consume_once` but not the tiers or the
   theft response. This is what
   `thoughts/plans/2026-09-26-spa-refresh-reuse-after-dropped-rotation.md`
   is for; recorded here only so the review's point is not re-filed.
