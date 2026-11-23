# Research: the consumer's review of the rc3 work, triaged

**Date:** 2026-11-23
**Plan:** thoughts/plans/2026-11-23-emm-4-0-rc2-production-observations.md (done; pull request 188)
**Source:** two reports in `thoughts/inbound/`, both filed 2026-11-23 by the
Emm AI repository (`actingweb_mcp`): `emm-review-of-rc3.md`, read against
this branch at `9e47157`, and `emm-answers-after-rc3-verification.md`, read
against `c1f08ce` and the second verification. Both are deleted; this note
and the todos it names are the record.
**Checked against:** `fix/4.0.0-rc3-consumer-fixes` at `61f2167`.

`emm-review-of-rc3.md` was committed to this branch in `1a7d000` before
anyone here had read it: it arrived in the working tree during the plan's
first iteration and went in with a `git add` of `thoughts/`. It is removed
by the commit that adds this note.

## `GET /mcp`: the loop ended with the rc2 deploy

Reported, from the production function's log (CloudWatch Logs Insights,
2026-11-23); none of it can be checked from this tree:

- **Before:** on 3.15.1, about 243,000 `GET /mcp 200` on most days from
  2026-11-06 to the deploy (daily counts read back to 2026-11-02: between
  47,000 and 405,000, with 234 on 2026-11-05); flat at about 10,065 an hour
  in the last two days. The first report's "840 invocations in five
  minutes" is that rate.
- **The cut:** the last `GET /mcp 200` at 2026-11-22 11:10:12.690 UTC, the
  first 405 at 11:10:19.223.
- **Which version wrote the 200s:** between 11:00 and 11:20, three Lambda
  instances wrote 200s only, the last ending 11:10:12; three others wrote
  one 405 each at 11:10:19. No instance wrote both.
- **Since:** five `GET /mcp` in all, each a 405. About 900 requests in the
  24 hours after the deploy.

So the client stops when it gets the 405, and MCP-3 holds as written. The
first report's "the loop continues" was wrong, and the reading the first
triage listed third (the 200s were the previous version's, during the
rollover) was the right one. `todo/mcp-get-polled-after-the-405.md` is
deleted. Nothing about it gates 4.0.0. The plan's one deferred decision is
closed by this, and the second verification's "needs an answer before
4.0.0" no longer applies.

## `POST /mcp` answers 400 for about one request in six

Reported: since the deploy `POST /mcp` is 346 × 200, 72 × 400 and 39 × 202,
and the 400 share was the same over the three days before it (about 16
percent). The reporter did not examine what they are.

Checked: `POST /mcp` answers 400 in three places (`handlers/mcp.py`): a body
that is empty or not JSON (`-32700`), a JSON batch or other non-object
(`-32600`), and an `MCP-Protocol-Version` header the server does not speak
(`-32600`). Each writes one INFO line that says which
(`MCP POST rejected: …`, `Rejecting unsupported MCP-Protocol-Version …`).
The third is the expected first request of a dual-era client, which then
falls back to `initialize`
(`todo/mcp-2026-07-28-dual-era-support.md`). If that is what the 72 are,
they are the first evidence that a client this deployment serves is
dual-era; the reporter's INFO log can say. Recorded in that todo.

## The token-cache query answers yes or no; the consumer needs the actor

Claim: `is_token_cached(token, config)` cannot replace the consumer's
private read. Its guard in front of `/mcp` refuses a suspended account.
When `validate_access_token` answers "invalid" or the token store faults,
and the library would still serve the token from its cache, the guard
needs the actor the entry belongs to.

Checked: true of the function as shipped (it returns `bool`). The entry
holds `actor_id` (`handlers/mcp.py`, the cache write), and a successful
`validate_access_token` returns the same id, so answering it exposes
nothing new to a caller that holds the token. Filed:
`todo/mcp-token-cache-query-answers-no-actor.md`. The consumer keeps its
private read meanwhile and nothing else of its plan waits on this.

## The rest

| Item | The consumer says | Check |
| --- | --- | --- |
| The five texts | The ones its plan quotes; nothing to change | They are `TOOL_FAULT_TEXTS` and `TOOL_FAILURE_TEXT` at `61f2167` |
| `TOOL_FAULT_TEXTS` | It asked whether the constant may be imported, then withdrew the question: it re-raises its own fault types as `DbError(...) from` them and asks `classify_fault` | Nothing to do. The constant is not exported from `actingweb.mcp` and stays the handler's own |
| `ToolError` without a fault | Relies on: logged at INFO, 400 on `/actions/<name>` | Holds (`handlers/mcp.py` `_tool_failure_result`, `handlers/actions.py` `_answer_tool_error`) |
| The classifier (items 2, 3) | Used after all | - |
| `strict=True` | All eleven of its callers and one new one; its test proxy over the backend classes passes the keyword on | Since `61f2167` the wrapper checks the backend method's signature first: a proxy whose `conditional_update_attr` takes neither `strict` nor `**kwargs` now gets a `TypeError` naming the keyword. Tell the consumer |
| Deletion (items 7, 10) | Keeps its record and `read_tombstone`; its cleanup reads the actor row first and treats a gone row with any tombstone as deleted | Consistent with `todo/deletion-cleanup-across-processes.md` |
| The release | Its plan pins rc3 from TestPyPI after two of its phases (proposed to its owner, not approved) | Waits on the release, which is outside pull request 188 |
