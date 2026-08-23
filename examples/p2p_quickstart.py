"""
Two-actor peer-to-peer quickstart.

Actor A publishes a property change; actor B has subscribed to actor A's
"properties" target and receives the change through a subscription data
hook. Both actors are served by the same ActingWebApp instance -- peer-to-
peer trust works between actors on the same server exactly as it does
between actors on different servers, since the handshake is a real HTTP
call either way.

Narrated in docs/guides/p2p-quickstart.rst, which literalinclude's the
sections below by their "start:"/"end:" marker comments. Also imported
directly by tests/test_p2p_quickstart.py, so the document and the test
exercise the same code.

Run this file directly against a locally running server (see the guide's
"Run it" step) to see the full flow end-to-end.
"""

import os

from actingweb.interface import ActingWebApp, ActorInterface

# start: app-setup
app = (
    ActingWebApp(
        aw_type="urn:actingweb:example.com:p2p",
        database="dynamodb",
        fqdn=os.getenv("APP_HOST_FQDN", "localhost:5000"),
        # Defaults to http:// for local development. Subscription callbacks
        # are outbound HTTP calls the library makes to the URL it recorded
        # for the peer at trust time -- if that URL's scheme doesn't match
        # what the server actually speaks, callbacks fail silently (an SSL
        # handshake error against a plain-HTTP port, or the reverse). Set
        # APP_HOST_PROTO=https:// in production, matching your real proto.
        proto=os.getenv("APP_HOST_PROTO", "http://"),
    )
    .with_web_ui(False)
    .with_devtest(enable=False)
    .with_subscription_processing(
        auto_sequence=True,
        auto_storage=True,
        auto_cleanup=True,
    )
)


@app.subscription_data_hook("properties")
def on_properties_changed(
    actor: ActorInterface,
    peer_id: str,
    target: str,
    data: dict,
    sequence: int,
    callback_type: str,
) -> None:
    # Data is already sequenced, deduplicated, and stored in RemotePeerStore
    # by the time this fires -- see docs/guides/subscriptions.rst.
    print(f"[{actor.id}] update from {peer_id} ({callback_type} #{sequence}): {data}")


@app.lifecycle_hook("trust_request_received")
def on_trust_request_received(actor: ActorInterface, peer_id: str, **kwargs) -> None:
    # Fires on the actor RECEIVING a trust request -- here, actor A (the
    # publisher) when actor B (the subscriber) calls create_relationship().
    # Auto-approving here is what makes subscribe_to_peer() below succeed:
    # a subscription request is rejected with 403 until both sides of the
    # relationship are approved, not just the side that initiated it.
    # Demo-only: never auto-approve an unverified peer in a real
    # application -- see the Security Note in docs/guides/p2p-quickstart.rst.
    actor.trust.approve_relationship(peer_id=peer_id)


# end: app-setup


# start: publish
def publish_status(actor: ActorInterface, status: str) -> None:
    """Actor A: write a property. Subscribers to "properties" see this."""
    actor.properties.status = status


# end: publish


# start: subscribe
def establish_trust_and_subscribe(subscriber: ActorInterface, publisher_url: str):
    """
    Actor B: establish trust with actor A, approve it, then subscribe.

    create_relationship() implicitly approves the relationship on the
    *initiating* (subscriber) side only -- the peer's side stays unapproved
    until the peer approves it too, which is what the on_trust_request_received
    hook above does. subscribe_to_peer() below would otherwise get a 403:
    subscription requests require an approved relationship on *both* sides.

    Approving a trust relationship grants the peer whatever the trust type
    permits. Do not auto-approve trust with an unverified peer in a real
    application -- see docs/guides/access-control.rst.
    """
    rel = subscriber.trust.create_relationship(
        peer_url=publisher_url, relationship="friend"
    )
    if rel is None:
        raise RuntimeError("Failed to create trust relationship")
    subscriber.trust.approve_relationship(peer_id=rel.peer_id)
    subscriber.subscriptions.subscribe_to_peer(peer_id=rel.peer_id, target="properties")
    return rel


# end: subscribe


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    # Bind port defaults to the port in APP_HOST_FQDN (falling back to 5000)
    # so the server's own actor URLs match where it's actually listening.
    _port = int(os.getenv("APP_HOST_FQDN", "localhost:5000").rsplit(":", 1)[-1])
    api = FastAPI(title="p2p quickstart")
    app.integrate_fastapi(api)
    uvicorn.run(api, host="0.0.0.0", port=_port)
