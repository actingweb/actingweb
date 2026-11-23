# `GET /mcp` reported as still polled about once a second by Claude Code

**Filed:** 2026-11-22, from a consumer's production report on 4.0.0rc2
(`thoughts/research/2026-11-22-emm-4-0-rc2-production-observations.md`).
Checked against `master` at `bee0eb5`. **Waiting on the reporter.** If the
loop is confirmed on rc2 it needs its answer before 4.0.0: any fix is a
wire change.

## Reported

In production on rc2 (AWS Lambda), client Claude Code 2.1.330 with the
consumer's plugin (`clientInfo.name` `claude-code`): while a session was
open, about one `GET /mcp` a second, each answered 200 in about 16 ms.
Seen in the first minutes after the deploy, not throughout the day. The
application function ran about 840 times in a five-minute window shortly
before the deploy, which the consumer attributes to the same loop without
having separated it from other traffic. Only three requests since the
deploy were answered 405. The consumer has no gateway access log, so the
looping requests' headers are unknown.

## Checked

- rc2 answers 405 to an authenticated `GET /mcp` whose `Accept` contains
  `text/event-stream` (`handlers/mcp.py:923`; MCP-3 in
  `specs/mcp-server.md`; `test_an_authenticated_stream_opener_gets_405`).
  Any other authenticated GET gets the 200 document.
- Header casing does not explain it. The handler reads `Accept` and
  `accept`; the FastAPI integration passes Starlette's lower-case names
  through and Flask passes `Accept`.
- Three readings fit, and the tree cannot choose between them: the looping
  GET is authenticated and carries no `text/event-stream` in `Accept`; it
  is answered before the handler sees it (the consumer's own middleware);
  or the 200s were written by the previous version while the deploy rolled
  over, and rc2's 405 did stop the loop. The timing (first minutes only,
  three 405s in all) fits the last one.

## Next

1. Ask the reporter (it confirmed on 2026-11-22 that the headers are not
   captured yet) whether the loop reproduces on rc2 now, and which
   version wrote the 200s. If it does not reproduce, delete this file.
2. If it does: the capture it offered (a local stage through the tunnel's
   inspector), with the method, `Accept`, `Mcp-Session-Id` and
   `MCP-Protocol-Version` of the looping requests, and whether the 200 is
   this library's document.
3. Only then choose. The reporter's suggestion, an unconditional 405 for an
   authenticated `GET /mcp` with the document at `/mcp/info` only, rewrites
   MCP-3 and removes a documented answer. It is not to be made on a guess.
