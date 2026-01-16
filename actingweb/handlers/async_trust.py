"""
Async-capable handler for ActingWeb trust endpoint.

This handler provides async versions of HTTP methods for optimal performance
with FastAPI and other async frameworks. It properly awaits async trust
operations without blocking the event loop.
"""

import json
import logging

from actingweb.handlers.trust import TrustHandler

logger = logging.getLogger(__name__)


class AsyncTrustHandler(TrustHandler):
    """Async-capable trust handler for FastAPI integration.

    Provides async versions of HTTP methods that properly await async trust
    operations. Use this handler with FastAPI for optimal async performance.

    The key improvement is that POST requests (trust relationship creation)
    use async methods that don't block the event loop with time.sleep()
    during peer HTTP calls.

    Inherits all synchronous methods from TrustHandler for backward compatibility.
    """

    async def post_async(self, actor_id: str) -> None:
        """
        Handle POST requests to trust endpoint asynchronously.

        POST /trust - Create reciprocal trust relationship with peer actor

        This async version prevents blocking the event loop when making
        HTTP calls to the peer actor during trust establishment.
        """
        myself = self.require_authenticated_actor(actor_id, "trust", "POST")
        if not myself:
            return
        desc = ""
        relationship = self.config.default_relationship
        try:
            body = self.request.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", "ignore")
            elif body is None:
                body = "{}"
            params = json.loads(body)
            if "url" in params:
                url = params["url"]
            else:
                url = ""
            if "relationship" in params:
                relationship = params["relationship"]
            if "desc" in params:
                desc = params["desc"]
        except ValueError:
            url = self.request.get("url")
            relationship = self.request.get("relationship")
        if len(url) == 0:
            self.response.set_status(400, "Missing peer URL")
            return

        # Use developer API - ActorInterface with TrustManager
        actor_interface = self._get_actor_interface(myself)
        if not actor_interface:
            if self.response:
                self.response.set_status(500, "Internal error")
            return

        secret = self.config.new_token()
        # Use async version to prevent blocking event loop
        new_trust_rel = await actor_interface.trust.create_relationship_async(
            peer_url=url,
            secret=secret,
            description=desc,
            relationship=relationship,
        )
        if not new_trust_rel:
            self.response.set_status(408, "Unable to create trust relationship")
            return

        new_trust = new_trust_rel.to_dict()

        # Trigger trust_initiated lifecycle hook to notify application of outgoing trust request
        if self.hooks:
            try:
                peerid = new_trust.get("peerid", "")
                logger.debug(
                    f"trust_initiated hook called for {actor_id} -> {peerid}, "
                    f"relationship={relationship}"
                )
                self.hooks.execute_lifecycle_hooks(
                    "trust_initiated",
                    actor=actor_interface,
                    peer_id=peerid,
                    relationship=relationship,
                    trust_data=new_trust,
                )
                logger.info(
                    f"trust_initiated hook triggered for {actor_id} -> {peerid}"
                )
            except Exception as e:
                logger.error(f"Error triggering trust_initiated hook: {e}")

        self.response.headers["Location"] = str(
            self.config.root
            + (myself.id or "")
            + "/trust/"
            + new_trust["relationship"]
            + "/"
            + new_trust["peerid"]
        )
        out = json.dumps(new_trust)
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        self.response.set_status(201, "Created")
