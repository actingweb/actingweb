# Emm's review of the rc3 work, and the `GET /mcp` loop settled

**Filed:** 2026-11-23 by the Emm AI repository (`actingweb_mcp`). Read
against `fix/4.0.0-rc3-consumer-fixes` (`bee0eb5` with the work
uncommitted, then `9e47157`) and `thoughts/plans/2026-11-23-emm-4-0-rc2-production-observations.md`.
Emm's plan (`actingweb_mcp`: `thoughts/plans/2026-11-22-actingweb-4-0-improvements.md`)
is updated to it. This replaces Emm's note of 2026-11-22 about its rc3
assumptions.

## `GET /mcp`: the loop ended with the rc2 deploy

The first report said the loop continued after the deploy. That was wrong.
From the production function's log (`mangum.http` lines, CloudWatch Logs
Insights, 2026-11-23):

- **Before:** on 3.15.1, `GET /mcp 200` about 243,000 times on most
  days from 2026-11-06 to the deploy (daily counts read back to
  2026-11-02; between 47,000 and 405,000, with 234 on 2026-11-05). In the
  last two days it was flat at about 10,065 an hour, every hour. The
  "840 invocations in five minutes" of the first report is that rate.
- **The cut:** the last `GET /mcp 200` is at 2026-11-22 11:10:12.690 UTC.
  The first `405` is at 11:10:19.223.
- **Which version wrote the 200s:** in 11:00 to 11:20, three log streams
  (Lambda instances) wrote 200s only, the last ending 11:10:12; three
  other streams wrote one 405 each at 11:10:19. No stream wrote both.
- **Since:** five `GET /mcp` in all, each a 405 (three at 11:10:19, one
  on 2026-11-23 08:03, one 10:27). The function handled about 900
  requests in the 24 hours after the deploy.
- The other methods did not take the loop over: since the deploy
  `POST /mcp` is 346 × 200, 72 × 400 and 39 × 202.

So the client stops when it gets the 405, and MCP-3 holds as it is.
`todo/mcp-get-polled-after-the-405.md` can be deleted. The headers of the
looping requests were never captured and are no longer needed. The
`POST /mcp 400` share is the same before and after the deploy (about 16
percent over the three days before it), so it is not new in rc2; what
they are was not examined.

## Item 6: the query answers yes or no, Emm needs the actor

`is_token_cached(token, config)` cannot replace Emm's private read. Emm's
guard in front of `/mcp` refuses a suspended account. When
`validate_access_token` answers "invalid" or the token store faults, but
the library would still serve the token from its cache, the guard needs
the actor the cached entry belongs to, to read that account's status
(`application.py`, `_library_cached_actor_id`). With a yes alone it can
only let the request through unchecked or refuse it.

With it: the guard calls the query and drops `_token_cache` and
`_cache_ttl`. Without it: Emm keeps the private read; nothing else in Emm
waits on this.

What would serve: the same predicate answering the entry's `actor_id` (or
`None`). It exposes one field the caller could get from a successful
`validate_access_token` anyway.

## The rest, as Emm will use it

| Item | rc3 | Emm |
| --- | --- | --- |
| 1 | Tool result with five fixed texts; `ToolError` | Lets `DbError` through in all 39 tools. Emm's own fault types often have no `DbError` cause, so Emm turns them into `ToolError` with the retryable text at one place. It would import `TOOL_FAULT_TEXTS` from `handlers/mcp.py` for that text: say if that constant is not meant to be imported, or export the texts from `actingweb.mcp` |
| 2, 3 | `actingweb.faults`; collision is 500 | Not used now |
| 5 | Redirect helper | The password route moves to `complete_client_authorization` |
| 7, 10 | Dropped | Emm keeps its record and calls `read_tombstone`. The todo's findings changed Emm's design: its cleanup reads the actor row first (`get_by_id`), and treats a gone row with any tombstone as deleted |
| 8 | List readers let other exceptions through | Checked by Emm's full suite on rc3 |
| 9 | `store.loaded` documented | Used in `actor_deleted` |
| 11 | `strict=True` | All eleven of Emm's callers move to it, and the new unlock-window swap. The reworked meaning (a fault raises; `False` is "the condition did not hold"; read the row to know) suits Emm: the unlock-window payload carries a value unique to the call |

Proposed to Emm's owner, not yet decided: Emm pins rc3 before it touches
its tools, which needs rc3 on TestPyPI after two of its eleven phases.
The plan is not approved yet.
