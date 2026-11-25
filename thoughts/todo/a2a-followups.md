# A2A follow-ups left out of the first round

**Filed:** 2026-11-25, from the A2A feature's "Not In Scope" section and the
research note's owner decisions (`thoughts/research/2026-11-24-a2a-actor-interface.md`).

Each item is out of the first round by an owner decision, and each comes with
the reason it was left out. Each waits on `a2a-actor-interface.md` landing.

- **Outbound A2A: an actor calling other agents.** The owner put inbound first.
  - The trust row holds one shared `secret`, used as both the inbound and the
    outbound bearer.
  - `aw_proxy` assumes an ActingWeb peer's `baseuri`.
  - A remote A2A agent instead needs three things: a card URL, an interface
    URL (perhaps with a `tenant`), and a credential of its own for the
    outbound direction.
- **Push notifications and streaming.** Decision 16 is polling only.
  - Push needs a delivery path that retries and persists; `callback_sender`
    has neither.
  - Streaming needs SSE.
- **A worker that calls back over HTTP.** Decision 12 opens the handle in the
  worker's own process. An HTTP backend behind the same handle interface
  would add an authenticated route and a third kind of bearer.
- **A second worker taking over a lapsed task.** Decision 15 fails the task at
  its deadline. Takeover needs a lease and token rotation, like the deletion
  lease.
- **`input_required`**, if the plan leaves it out.
  - A2A answers it with a `SendMessage` carrying the task id.
  - MCP's 2026-07-28 tasks extension answers it with `tasks/update`.
- **Finding an actor's card.** Decision 8 serves the card per actor, with no
  host-root card or redirect.
  - The cheaper aid is to show the card URL in the web UI and the SPA's
    metadata.
  - The conformance kit can't find a per-actor card without being told where
    it is.
- **OAuth2 authorization code for A2A clients.** This is the per-user OAuth
  that Gemini Enterprise and Copilot Studio use, and it was left out of the
  first round (`…a2a-actor-interface.auth.md`, A1). The user who signs in
  belongs to the platform, so the token would stand for that user's own actor,
  which is on-behalf access. Supporting it needs a completion path that knows
  the client's class, so the token stands for the third-party client. About
  400–700 lines.
- **gRPC, signed cards and A2A 0.3 compatibility.** No caller needs them yet.
