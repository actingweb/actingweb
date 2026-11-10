# Fixed imports after removing init_actingweb
import json
import logging
from typing import Any

from actingweb.handlers import base_handler

from ..access_decision import decide, evaluator_or_none, forbidden_body
from ..permission_evaluator import PermissionType, get_permission_evaluator

logger = logging.getLogger(__name__)

# A resource route's operation for the grant (3.16).
_OPERATION = {"GET": "read", "PUT": "write", "POST": "write", "DELETE": "delete"}


class ResourcesHandler(base_handler.BaseHandler):
    def _grant_allows(
        self, actor_id: str, auth_result: Any, name: str, method: str
    ) -> bool:
        """A peer's ``/resources/<name>`` request is decided by its grant for
        the ``resources`` category (3.16, spec: one grant for REST and MCP
        resources): GET is ``read``, PUT and POST ``write``, DELETE
        ``delete``; a grant that does not mention resources leaves it to the
        access table with the request's method. A caller that is not a peer
        is decided by the access table, as before. A refusal is 403 and the
        hook does not run."""
        acl = getattr(auth_result.auth_obj, "acl", None)
        peer_id = str(acl.get("peerid", "") or "") if isinstance(acl, dict) else ""
        if not peer_id:
            return bool(auth_result.authorize(method, "resources", name))
        decision = decide(
            self.config,
            actor_id,
            peer_id,
            PermissionType.RESOURCES,
            name or "",
            _OPERATION[method],
            method=method,
            evaluator=evaluator_or_none(self.config, get_permission_evaluator),
        )
        if decision.allowed:
            return True
        logger.debug(
            f"Resource access denied: {actor_id} -> {peer_id} -> {name!r} "
            f"({method}, {decision.reason})"
        )
        if self.response:
            self.response.set_status(403, "Forbidden")
            self.response.headers["Content-Type"] = "application/json"
            self.response.write(json.dumps(forbidden_body(decision)))
        return False

    def get(self, actor_id, name):
        auth_result = self._authenticate_dual_context(
            actor_id, "resources", "resources", name
        )
        if not auth_result.success:
            return
        myself = auth_result.actor
        if not self._grant_allows(actor_id, auth_result, name, "GET"):
            return
        # Execute callback hook for resource GET
        pair = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                pair = self.hooks.execute_callback_hooks(
                    f"resource_{name}", actor_interface, {"method": "GET"}
                )
        if pair:
            out = json.dumps(pair)
            if self.response:
                self.response.write(out)
                self.response.headers["Content-Type"] = "application/json"
                self.response.set_status(200)
        else:
            if self.response:
                self.response.set_status(404)

    def delete(self, actor_id, name):
        auth_result = self._authenticate_dual_context(
            actor_id, "resources", "resources", name
        )
        if not auth_result.success:
            return
        myself = auth_result.actor
        if not self._grant_allows(actor_id, auth_result, name, "DELETE"):
            return
        # Execute callback hook for resource DELETE
        pair = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                pair = self.hooks.execute_callback_hooks(
                    f"resource_{name}", actor_interface, {"method": "DELETE"}
                )
        if pair:
            if isinstance(pair, int) and 100 <= pair <= 999:
                return
            if pair:
                out = json.dumps(pair)
                if self.response:
                    self.response.write(out)
                    self.response.headers["Content-Type"] = "application/json"
                    self.response.set_status(200)
        else:
            if self.response:
                self.response.set_status(404)

    def put(self, actor_id, name):
        auth_result = self._authenticate_dual_context(
            actor_id, "resources", "resources", name
        )
        if not auth_result.success:
            return
        myself = auth_result.actor
        if not self._grant_allows(actor_id, auth_result, name, "PUT"):
            return
        try:
            body: str | bytes | None = self.request.body
            if body is None:
                body_str = "{}"
            elif isinstance(body, bytes):
                body_str = body.decode("utf-8", "ignore")
            else:
                body_str = body
            params = json.loads(body_str)
        except (TypeError, ValueError, KeyError):
            if self.response:
                self.response.set_status(400, "Error in json body")
            return

        # Execute callback hook for resource PUT
        pair = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                data = params.copy()
                data["method"] = "PUT"
                pair = self.hooks.execute_callback_hooks(
                    f"resource_{name}", actor_interface, data
                )
        if pair:
            if isinstance(pair, int) and 100 <= pair <= 999:
                return
            if pair:
                out = json.dumps(pair)
                if self.response:
                    self.response.write(out)
                    self.response.headers["Content-Type"] = "application/json"
                    self.response.set_status(200)
        else:
            if self.response:
                self.response.set_status(404)

    def post(self, actor_id, name):
        auth_result = self._authenticate_dual_context(
            actor_id, "resources", "resources", name
        )
        if not auth_result.success:
            return
        myself = auth_result.actor
        if not self._grant_allows(actor_id, auth_result, name, "POST"):
            return
        try:
            body: str | bytes | None = self.request.body
            if body is None:
                body_str = "{}"
            elif isinstance(body, bytes):
                body_str = body.decode("utf-8", "ignore")
            else:
                body_str = body
            params = json.loads(body_str)
        except (TypeError, ValueError, KeyError):
            if self.response:
                self.response.set_status(400, "Error in json body")
            return

        # Execute callback hook for resource POST
        pair = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                data = params.copy()
                data["method"] = "POST"
                pair = self.hooks.execute_callback_hooks(
                    f"resource_{name}", actor_interface, data
                )
        if pair:
            if isinstance(pair, int) and 100 <= pair <= 999:
                return
            if pair:
                out = json.dumps(pair)
                if self.response:
                    self.response.write(out)
                    self.response.headers["Content-Type"] = "application/json"
                    self.response.set_status(201, "Created")
        else:
            if self.response:
                self.response.set_status(404)
