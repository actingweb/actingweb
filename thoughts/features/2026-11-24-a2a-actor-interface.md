# Feature: Actors reachable over A2A

**Date:** 2026-11-24
**Author:** Greger Wedel (with Claude)

## Problem

A developer who builds on the library can today let an AI client reach an
actor through MCP. That serves a model working for the actor's own owner.
It does not serve the case ActingWeb was designed for: a *different* party's
agent asking the actor for something, and getting only what the owner granted
that party. For that, the only interface is the ActingWeb REST protocol, which
ordinary agent frameworks do not speak.

The Agent2Agent protocol (A2A, 1.0 since March 2026, under the Linux
Foundation's Agentic AI Foundation since August 2026) is becoming the standard
way one agent asks another for work. It standardises how a task is asked for
and answered, and leaves open who may ask: it has no relationship between two
agents, no per-caller permission and no consent step, and none of that is on
its roadmap. ActingWeb standardises exactly that part and says little about
tasks. An actor that spoke A2A would be reachable by any A2A agent, under the
owner's own trust and permission rules.

**Demand evidence:** none yet, hypothesis. No consumer has asked for this and
no caller is waiting. The motive is to innovate: to put ActingWeb's trust
model where the agent ecosystem can see and use it while that ecosystem is
still settling its conventions.

## Users

- **The consumer developer** (primary) — builds an application on the
  library, today `actingweb_mcp` (Emm AI) and the demo. Wants to expose
  actors over A2A the way MCP is exposed: register what the application
  offers, switch it on, and write only the logic that decides what a request
  means and what to answer.
- **The actor's owner** — the person an actor belongs to. Decides which
  outside agent may talk to their actor, at which trust level, and can narrow
  or withdraw that at any time.
- **The calling agent** — another person's assistant (scenario 1) or a
  service's agent, for example a shop or a booking system (scenario 3). Speaks
  standard A2A and knows nothing about ActingWeb unless it chooses to.

An owner's own agent on another platform calling the actor as a sub-agent is
*not* a target: MCP covers it.

## Premises

1. This is the right problem: MCP makes an actor a tool server for its
   owner's model; A2A is for another party's agent calling as a peer, which is
   what trust relationships were designed for. A2A is the modern front door
   for peer-to-peer access, not a second MCP. — agreed 2026-11-24
2. Doing nothing costs nothing today: nothing breaks and nobody is waiting.
   The cost is that ActingWeb's trust and permission model, the thing A2A
   lacks, stays invisible to the agent ecosystem while it settles. — agreed
   2026-11-24

## Desired Outcome

An actor's owner can let another person's or a service's agent talk to their
actor over standard A2A, and that agent gets only what the owner granted that
specific caller. The owner can narrow or withdraw it at any time without
affecting anyone else. A developer on the library gets this by registering
skills and a handler and switching A2A on: the library handles the protocol,
the scaffolding and the access control, and the application's handler decides
what the request means and what to answer.

## Background: A2A 1.0 against ActingWeb 1.5

Sources: `docs/protocol/actingweb-spec.rst` and the A2A specification
(<https://a2a-protocol.org/latest/specification/>, with its topic pages and
`a2a.proto`), read 2026-11-24. The A2A side is paraphrased from a summarised
reading; check the specification's own wording before citing it normatively.

| Concern | ActingWeb 1.5 | A2A 1.0 |
| --- | --- | --- |
| Unit | One actor per user; everything under the actor's root URI | One agent per service; many agents on a host by URL prefix or an opaque `tenant` the client echoes |
| Discovery | `GET /<actor>/meta` without trust; option tags | Agent Card at `/.well-known/agent-card.json`; skills, capabilities, extensions; optional JWS signature; an authenticated extended card |
| Who may call | A persistent, bilateral trust relationship per peer: shared secret, owner approval, trust type, per-peer overrides, revocable by either side | Out-of-band credentials (API key, bearer, OAuth2, OIDC, mTLS); authorization left to the implementation; no relationship, no per-peer grant |
| What is exchanged | Data: properties, lists, subscriptions to changes; actions and methods | Tasks: free-form messages with text, file and data parts; a task state machine; artifacts |
| Invoking work | `POST /actions/<name>`, optionally a `Location` to poll and DELETE | `SendMessage` returns a Task or a bare Message; `GetTask`, `ListTasks`, `CancelTask` |
| Async | Callbacks with sequence numbers, gap detection, resync | Push webhook per task, delivery attempted at least once, no sequence; SSE streaming |
| Wire | REST paths, HTTP status codes | JSON-RPC, gRPC or HTTP+JSON; `A2A-Version` header; camelCase ProtoJSON; standard error set |
| Optional features | Option tags | Extensions by URI, activated per request with `A2A-Extensions` |

A message names no skill: the receiving agent decides what it means. The
official Python SDK (`a2a-sdk` 1.3.1) is Starlette/FastAPI only and uses
protobuf types.

## User Experience

**Main path:**
1. A developer registers an A2A handler and the skills it offers, defines
   what each trust type may reach over A2A (the properties and attributes a
   caller's request may read, allowed actions and methods, and a
   configuration or prompt for that level), and switches A2A on.
2. Every actor now answers A2A at `/<actor_id>/a2a` and serves an Agent Card
   (where the card itself lives is an open question). Anyone can read the
   card; it shows nothing private and declares the ActingWeb extension.
3. The owner, in the consumer application's own interface, sets their own
   configuration for a trust type (and may later set one for a single
   relationship), as owners differentiate access to memories in Emm AI today.
   Then, in the same interface (built on library
   primitives, as the connection screen for MCP clients is today), creates a
   connection for a caller, chooses its trust type or takes the default, and
   passes the credential on out of band.
4. The caller's agent fetches the extended card with that credential and sees
   the skills its trust allows (if the standard lets the extended card differ
   per caller; otherwise the skills offered to trusted callers).
5. It sends a message. The library authenticates it, checks access, and calls
   the handler with the message, who the peer is and its trust type. The handler
   can read three layers of configuration: what the application configured
   for that trust type, what this owner configured for that trust type, and
   what this owner configured for this specific relationship. The handler reaches the actor's data through an
   accessor scoped to the trust (`actor.trust.X.properties`,
   `actor.trust.X.attributes`): it can look up, filter and query, and sees
   only what trust X is allowed. Saving something as a result of the
   processing (a new memory, an updated document) is the consumer's decision,
   made in the handler with these primitives; the library puts no blanket
   refusal on writes.
6. The handler returns an answer; the library sends it back as a valid A2A
   response.
7. The owner later narrows or removes the connection; the caller's requests
   reflect that, at once where the change was made and within a stated bound
   everywhere else.

**Edge paths:**
- **No credential, or a revoked one** — refused before the handler runs.
- **A trust type with no A2A access** — refused before the handler runs.
- **The handler fails** — the caller gets a generic A2A error with no
  internal detail.
- **The caller asks for something not offered** (streaming, push, an
  unsupported version) — a standard A2A "not supported" error; the card never
  advertised it.
- **The caller is an ActingWeb actor with an approved relationship** — it
  uses A2A with its existing trust secret, no new credential, provided the
  relationship's permissions allow A2A.
- **The caller knows the extension and has no relationship** — it requests
  trust at the actor's `/trust` endpoint, the owner approves in the consumer
  application, and it then uses A2A with that relationship.

## Acceptance Criteria

- **AC-1** (main path, step 2) — When A2A is enabled, an unauthenticated GET
  of an actor's card returns a valid A2A 1.0 Agent Card naming
  `/<actor_id>/a2a` as its interface.
- **AC-2** (main path, step 2) — The public card contains no skill, data or
  description the application marked as restricted to trusted callers.
- **AC-3** (main path, step 2) — The card declares the ActingWeb extension,
  naming the actor's root URI and the trust types it offers.
- **AC-4** (main path, step 1) — When A2A is enabled, the actor's option tags
  include `a2a`.
- **AC-5** (main path, step 3) — When the owner creates a connection for an
  A2A caller with a trust type, a credential is returned that authenticates
  as that peer.
- **AC-6** (main path, step 4) — An authenticated caller's extended card
  lists exactly the skills its trust type and overrides permit. Conditional:
  the owner agreed to this "if the standard allows that"; whether the
  extended card may differ per caller is an open question below.
- **AC-7** (main path, step 5) — A permitted caller's message reaches the
  handler together with the peer's identity, its trust type and that trust
  type's configuration.
- **AC-8** (main path, step 5) — The scoped accessor for a trust returns, on
  lookup, filter and query, the properties and attributes granted to that
  trust and nothing else.
- **AC-9** (main path, step 5) — The handler can invoke only the actions and
  methods granted to that peer; another is refused.
- **AC-10** (main path, step 6) — What the handler returns is delivered to
  the caller as a valid A2A response.
- **AC-11** (edge: no or invalid credential) — A message with no credential,
  or an invalid one, is answered 401 and the handler is not called.
- **AC-12** (edge: trust type with no A2A access) — A message from a peer
  whose trust grants no A2A access is refused and the handler is not called.
- **AC-13** (main path, step 7) — After the owner removes a connection, that
  caller's next request to the process that served the removal is refused,
  and every other process refuses it within a stated bound. (Revocation does
  not cross processes today, `thoughts/todo/mcp-cache-lifecycle-and-revocation.md`;
  the bound is an open question.)
- **AC-14** (main path, step 7) — After the owner changes a peer's
  permissions, the scoped accessor reflects it within the window the
  trust-permissions spec gives (TPM-1, TPM-2).
- **AC-15** (edge: ActingWeb peer) — An ActingWeb peer with an approved
  relationship that permits A2A is served using its trust secret.
- **AC-16** (edge: handler fails) — When the handler raises, the caller gets
  an A2A internal error that names nothing internal.
- **AC-17** (edge: not offered) — An operation the actor does not offer gets
  the standard A2A "unsupported operation" error.
- **AC-18** (main path, all steps) — Every other criterion in this list holds
  on both the Flask and the FastAPI integration.
- **AC-19** (edge: extension-aware caller) — A caller that knows the
  extension can request trust at the actor's `/trust` endpoint and, after the
  owner approves, use A2A with that relationship.

- **AC-20** (main path, step 1) — When A2A is not enabled, the actor's option
  tags do not include `a2a`.
- **AC-21** (main path, step 1) — When A2A is not enabled, the A2A paths
  answer 404.
- ~~**AC-22** (main path, step 5) — A write to a property or an attribute
  through the scoped accessor of an A2A grant is refused and changes
  nothing.~~ Dropped 2026-11-24 (owner): writes are not refused blanket; what
  the processing saves is decided at the consumer level. See AC-28.
- **AC-23** (edge: handler fails) — When the handler raises, the failure is
  logged with the request's correlation id.
- **AC-24** (edge: not offered) — A request with an unsupported `A2A-Version`
  gets the standard A2A "version not supported" error.

- **AC-25** (main path, step 5) — The handler can read what this actor's
  owner configured for the caller's trust type.
- **AC-26** (main path, step 5) — The handler can read what this actor's
  owner configured for the caller's specific relationship.
- **AC-27** (main path, step 3) — After the owner changes either
  configuration, the handler's next read in the process that served the
  change returns the new value.
- **AC-28** (main path, step 5) — A handler that saves to the actor's
  properties or attributes while processing a permitted request succeeds:
  the library does not refuse a write because the request arrived over A2A.

- **AC-29** (main path, step 1) — The published protocol specification
  defines the `a2a` option tag and an OPTIONAL A2A chapter stating what an
  actor that advertises the tag serves and how its trust and permission
  model applies.

AC-25 to AC-29 were added on 2026-11-24 after the owner's review of the
written document. AC-20 to AC-24 were split from AC-4, AC-8, AC-16 and AC-17 after the owner's
read-back of 2026-11-24, so each criterion states one behaviour.

Pass/fail before shipping. Success Measures below tell whether the outcome
happened.

## Success Measures

| Measure | Target | How we observe it |
| --- | --- | --- |
| An unmodified A2A client talks to an actor | The official SDK's client fetches the card and completes a message exchange | An integration test, and a manual run against the demo |
| Conformance | An official A2A conformance kit passes for the operations offered | A CI run, if such a kit exists and can be scoped to a subset (open question) |
| Developer effort | The demo exposes A2A with one handler and a short configuration | Line count in `examples/demo/` |

Uptake (a consumer enabling A2A after release) cannot be observed: we would
only know by being told. It is an open question below, not a measure. With no
demand evidence, the three above are what this round can honestly be judged
on.

## Hypothesis (untested)

An A2A bridge per actor, modelled on the protocol's `/mcp` chapter, with an
ActingWeb extension declared in the card.

- **The library owns** the Agent Card and extended card, the A2A wire format
  and error set, version handling, authentication of the caller as a trust
  relationship, the permission check, the scoped accessor, and the `a2a`
  option tag. The protocol specification gains an OPTIONAL A2A chapter.
- **The consumer owns** the handler (what a message means, what to answer,
  whether a model is involved), the skills it advertises, what each trust
  type may reach over A2A, and the owner-facing interface for creating and
  approving connections.
- **Admission** reuses what exists for MCP clients: the owner creates a
  connection backed by a trust relationship and gets a credential to hand
  over. ActingWeb peers use their trust secret. An extension-aware caller
  uses the ordinary trust request.
- **Per-trust-level grant** is a combination of the properties and
  attributes a caller's request may read, a configuration or prompt
  associated with the level, and a set of allowed methods and actions.
- **Configuration has three layers** the handler can read: the application's
  for a trust type, the owner's for a trust type, and the owner's for one
  relationship. How Emm AI lets an owner differentiate access to memory
  types is the reference to study.
- **Per-relationship access may become a supported library and protocol
  capability.** Emm AI's per-trust memory access configuration was first
  built at application level, not in the library. The owner believes the
  library has since gained some support for per-relationship access, in
  particular where one actor's properties are synchronised into another
  actor's attribute cache (to be confirmed by research). This feature should
  evaluate whether that mechanism is extended into supported library
  functionality, and whether the protocol specification should describe it.
- **The protocol specification is updated as part of this work**
  (`docs/protocol/actingweb-spec.rst`): an OPTIONAL A2A chapter, the `a2a`
  option tag, and whatever the per-relationship access evaluation concludes
  belongs there. It is a deliverable of the plan, not a follow-up.
- **Writes are the consumer's.** The library scopes what a caller may read
  and invoke, and gives the handler what it needs to decide; it does not
  refuse writes the handler makes as a result of the processing.
- **The scoped accessor** (`actor.trust.X.properties` / `.attributes`) is a
  general library primitive, useful beyond A2A.

**Alternatives considered:**
- **Ideal: full two-way A2A** — streaming, push notifications mapped onto
  callbacks, signed cards, 0.3 compatibility and an outbound client, probably
  on `a2a-sdk`. Not chosen for this round: no counterpart to test against,
  and the SDK would leave Flask applications out.
- **Lateral: ActingWeb as an A2A extension only** — publish trust,
  permissions and subscriptions as an extension and serve no task interface.
  Not chosen alone, because an ordinary A2A agent could then do nothing; its
  extension declaration is kept as part of the chosen hypothesis.
- **Structured invocation by the library** — the caller names a skill and
  arguments in a data part and the library dispatches it. Not chosen: it is a
  convention ordinary A2A clients do not know, and the owner's decision is
  that the consumer owns the processing.

## Not In Scope

- Outbound calls from an actor to A2A agents — inbound first (owner,
  2026-11-24); to be looked at after.
- Any interpretation of messages inside the library — the consumer owns that.
- gRPC, signed cards, A2A 0.3 compatibility — no caller needs them yet.
- A registry or directory of actors' cards — A2A defines none.

**Undecided (owner, 2026-11-24):**

- Whether the smallest version (card, authenticated message in, answer out)
  is the right scope. Streaming, push notifications and long-running tasks
  are neither in nor out until research answers the questions below; a
  handler that calls a model may run longer than a blocking request
  tolerates.
- What `X` in `actor.trust.X` names: one peer's relationship (with its
  overrides) or a trust type. Not asked.
- Where the Agent Card lives. The owner fixed `/<actor_id>/a2a` as the
  endpoint; the card's own location was not decided.

## Open Questions

### About the codebase
- How is a trust relationship created for an MCP client today, in the library
  and in the consumer's interface (`../actingweb_mcp`, its SPA), and which of
  those primitives can create one for an A2A caller unchanged? What
  credential does the caller end up holding?
- How are per-trust-type permissions and per-peer overrides evaluated today,
  and can they express "these properties and attributes, read-only" and
  "these actions and methods" for A2A? Is a new permission category for A2A
  needed beside `tools`, `resources` and `prompts`?
- Attributes are not in the protocol's permission structure. What decides
  access to an attribute today, and what would a grant on attributes look
  like?
- Where would a per-trust-type configuration or prompt be stored, and is
  there an existing place for trust-type metadata?
- What would `actor.trust.X.properties` and `.attributes` need to offer
  (lookup, filter, query, lists), and where else in the library would the
  scoped accessor replace hand-written checks?
- Should the scoped accessor itself offer writes, limited to what the trust
  is granted to write, or is it a read view with writes made through the
  ordinary actor interface?
- Where do an owner's configuration for a trust type and for one
  relationship live today (per-peer permission overrides, trust-row fields,
  properties), and what does a single primitive that returns all three
  layers look like?
- How long can a removed trust or a narrowed permission stay in force in
  another process today, and what bound can AC-13 and AC-14 promise?
- Which choices in the inbound design would make outbound calls to A2A
  agents harder later (how a remote A2A agent is held as a peer, where its
  credential lives)?
- How does the MCP bridge hand a request to an application hook on Flask and
  on FastAPI, and can an A2A handler reuse that path, including async
  handlers?
- How do memory types and differentiated access work in the sibling
  repository `../actingweb_mcp`, which parts were built at application level
  only, and which belong in the library?
- What per-relationship access support does the library have today, in
  particular when one actor's properties are synchronised into another
  actor's attribute cache? What does it cover, where does it stop, and what
  would extending it into a supported capability take?
- Which parts of per-relationship access are already in the protocol
  specification (the permission structure, the permission query and
  permission callback), and what would have to be added for a peer on
  another implementation to rely on it?
- Does the A2A chapter and tag make the specification 1.6, and what does the
  specification's changelog and the library's version rule require for it?
- Do the request deadline and the callback delivery budget constrain how long
  a blocking `SendMessage` may run on a serverless deployment?
- Does anything already serve `/.well-known/` documents per actor or per
  application that the card should sit beside?

### About users and the outside world
- May a server answer `SendMessage` with a bare Message and keep no task
  state, and what must `GetTask`, `ListTasks` and `CancelTask` answer then?
- Is any binding mandatory? Which one should be served first (JSON-RPC or
  HTTP+JSON), and what do the common A2A clients default to?
- Where should a per-actor card live? A2A defines the well-known path per
  domain only. Is `/<actor_id>/a2a` for the card and the interface acceptable
  to real clients, and should the `tenant` field carry the actor id?
- Does the standard let the extended card differ per caller (AC-6), or only
  between authenticated and not?
- How does an A2A client express the credential schemes the library can
  issue (bearer secret, OAuth2 client credentials) in `securitySchemes`?
- What must an extension specification contain (URI, params, version rule),
  and where should the ActingWeb extension's document be published?
- Is there an official A2A conformance kit, and can it be run against a
  subset of operations?
- How could uptake be observed after release without the library reporting
  anything home?
- Hand-write the wire layer, or depend on `a2a-sdk` for types only? What
  does the SDK cost in dependencies (protobuf, google-api-core) for an
  application that does not use A2A?
- Which A2A clients and agent platforms could serve as a real counterpart
  for a first end-to-end test?
- What do streaming and push notifications require of a server that offers
  them, in enough detail to decide the scope left undecided above?
