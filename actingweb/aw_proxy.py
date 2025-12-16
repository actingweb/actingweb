import base64
import json
import logging
from typing import Any

import httpx
import requests

from actingweb import trust

try:
    from urllib.parse import urlencode as urllib_urlencode
except ImportError:
    from urllib.parse import urlencode as urllib_urlencode


class AwProxy:
    """Proxy to other trust peers to execute RPC style calls.

    Initialise with either trust_target to target a specific
    existing trust or use peer_target for simplicity to use
    the trust established with the peer.

    Provides both sync methods (using ``requests``) and async methods
    (using ``httpx``) for peer communication:

    - Sync: ``get_resource()``, ``create_resource()``, ``change_resource()``, ``delete_resource()``
    - Async: ``get_resource_async()``, ``create_resource_async()``, ``change_resource_async()``, ``delete_resource_async()``

    Use async methods in FastAPI routes for non-blocking I/O.
    """

    def __init__(self, trust_target=None, peer_target=None, config=None):
        self.config = config
        self.last_response_code = 0
        self.last_response_message = 0
        self.last_location = None
        self.peer_passphrase = None
        if trust_target and trust_target.trust:
            self.trust = trust_target
            self.actorid = trust_target.id
        elif peer_target and peer_target["id"]:
            self.actorid = peer_target["id"]
            self.trust = None
            # Capture peer passphrase if available for Basic fallback (creator 'trustee')
            if "passphrase" in peer_target and peer_target["passphrase"]:
                self.peer_passphrase = peer_target["passphrase"]
            if peer_target["peerid"]:
                self.trust = trust.Trust(
                    actor_id=self.actorid,
                    peerid=peer_target["peerid"],
                    config=self.config,
                ).get()
                if not self.trust or len(self.trust) == 0:
                    self.trust = None

    def _bearer_headers(self):
        return (
            {"Authorization": "Bearer " + self.trust["secret"]}
            if self.trust and self.trust.get("secret")
            else {}
        )

    def _basic_headers(self):
        if not self.peer_passphrase:
            return {}
        u_p = ("trustee:" + self.peer_passphrase).encode("utf-8")
        return {"Authorization": "Basic " + base64.b64encode(u_p).decode("utf-8")}

    def _maybe_retry_with_basic(self, method, url, data=None, headers=None):
        # Only retry if we have a peer passphrase available
        if not self.peer_passphrase:
            return None
        try:
            bh = self._basic_headers()
            if data is None:
                if method == "GET":
                    return requests.get(url=url, headers=bh, timeout=(5, 10))
                if method == "DELETE":
                    return requests.delete(url=url, headers=bh, timeout=(5, 10))
            else:
                if method == "POST":
                    return requests.post(
                        url=url,
                        data=data,
                        headers={**bh, "Content-Type": "application/json"},
                        timeout=(5, 10),
                    )
                if method == "PUT":
                    return requests.put(
                        url=url,
                        data=data,
                        headers={**bh, "Content-Type": "application/json"},
                        timeout=(5, 10),
                    )
        except Exception:
            return None
        return None

    def get_resource(self, path=None, params=None):
        if not path or len(path) == 0:
            return None
        if not params:
            params = {}
        if not self.trust or not self.trust["baseuri"] or not self.trust["secret"]:
            return None
        url = self.trust["baseuri"].strip("/") + "/" + path.strip("/")
        if params:
            url = url + "?" + urllib_urlencode(params)
        headers = self._bearer_headers()
        logging.debug("Getting trust peer resource at (" + url + ")")
        try:
            response = requests.get(url=url, headers=headers, timeout=(5, 10))
            # Retry with Basic if Bearer gets redirected/unauthorized/forbidden
            if response.status_code in (302, 401, 403):
                retry = self._maybe_retry_with_basic("GET", url)
                if retry is not None:
                    response = retry
            self.last_response_code = response.status_code
            self.last_response_message = response.content
        except Exception:
            logging.debug("Not able to get peer resource")
            self.last_response_code = 408
            return {
                "error": {
                    "code": 408,
                    "message": "Unable to communciate with trust peer service.",
                },
            }
        logging.debug(
            "Get trust peer resource POST response:("
            + str(response.status_code)
            + ") "
            + str(response.content)
        )
        if response.status_code < 200 or response.status_code > 299:
            logging.info("Not able to get trust peer resource.")
        try:
            result = response.json()
        except (TypeError, ValueError, KeyError):
            logging.debug(
                "Not able to parse response when getting resource at(" + url + ")"
            )
            result = {}
        return result

    def create_resource(self, path=None, params=None):
        if not path or len(path) == 0:
            return None
        if not params:
            params = {}
        if not self.trust or not self.trust["baseuri"] or not self.trust["secret"]:
            return None
        data = json.dumps(params)
        headers = {**self._bearer_headers(), "Content-Type": "application/json"}
        url = self.trust["baseuri"].strip("/") + "/" + path.strip("/")
        logging.debug(
            "Creating trust peer resource at (" + url + ") with data(" + str(data) + ")"
        )
        try:
            response = requests.post(
                url=url, data=data, headers=headers, timeout=(5, 10)
            )
            if response.status_code in (302, 401, 403):
                retry = self._maybe_retry_with_basic("POST", url, data=data)
                if retry is not None:
                    response = retry
            self.last_response_code = response.status_code
            self.last_response_message = response.content
        except Exception:
            logging.debug("Not able to create new peer resource")
            self.last_response_code = 408
            return {
                "error": {
                    "code": 408,
                    "message": "Unable to communciate with trust peer service.",
                },
            }
        if "Location" in response.headers:
            self.last_location = response.headers["Location"]
        else:
            self.last_location = None
        logging.debug(
            "Create trust peer resource POST response:("
            + str(response.status_code)
            + ") "
            + str(response.content)
        )
        if response.status_code < 200 or response.status_code > 299:
            logging.warning("Not able to create new trust peer resource.")
        try:
            result = response.json()
        except (TypeError, ValueError, KeyError):
            logging.debug(
                "Not able to parse response when creating resource at(" + url + ")"
            )
            result = {}
        return result

    def change_resource(self, path=None, params=None):
        if not path or len(path) == 0:
            return None
        if not params:
            params = {}
        if not self.trust or not self.trust["baseuri"] or not self.trust["secret"]:
            return None
        data = json.dumps(params)
        headers = {
            "Authorization": "Bearer " + self.trust["secret"],
            "Content-Type": "application/json",
        }
        url = self.trust["baseuri"].strip("/") + "/" + path.strip("/")
        logging.debug(
            "Changing trust peer resource at (" + url + ") with data(" + str(data) + ")"
        )
        try:
            response = requests.put(
                url=url, data=data, headers=headers, timeout=(5, 10)
            )
            if response.status_code in (302, 401, 403):
                retry = self._maybe_retry_with_basic("PUT", url, data=data)
                if retry is not None:
                    response = retry
            self.last_response_code = response.status_code
            self.last_response_message = response.content
        except Exception:
            logging.debug("Not able to change peer resource")
            self.last_response_code = 408
            return {
                "error": {
                    "code": 408,
                    "message": "Unable to communciate with trust peer service.",
                },
            }
        logging.debug(
            "Change trust peer resource PUT response:("
            + str(response.status_code)
            + ") "
            + str(response.content)
        )
        if response.status_code < 200 or response.status_code > 299:
            logging.warning("Not able to change trust peer resource.")
        try:
            result = response.json()
        except (TypeError, ValueError, KeyError):
            logging.debug(
                "Not able to parse response when changing resource at(" + url + ")"
            )
            result = {}
        return result

    def delete_resource(self, path=None):
        if not path or len(path) == 0:
            return None
        if not self.trust or not self.trust["baseuri"] or not self.trust["secret"]:
            return None
        headers = {"Authorization": "Bearer " + self.trust["secret"]}
        url = self.trust["baseuri"].strip("/") + "/" + path.strip("/")
        logging.debug("Deleting trust peer resource at (" + url + ")")
        try:
            response = requests.delete(url=url, headers=headers, timeout=(5, 10))
            if response.status_code in (302, 401, 403):
                retry = self._maybe_retry_with_basic("DELETE", url)
                if retry is not None:
                    response = retry
            self.last_response_code = response.status_code
            self.last_response_message = response.content
        except Exception:
            logging.debug("Not able to delete peer resource")
            self.last_response_code = 408
            return {
                "error": {
                    "code": 408,
                    "message": "Unable to communciate with trust peer service.",
                },
            }

    # Async methods using httpx for non-blocking HTTP requests
    # These are useful in async frameworks like FastAPI to avoid blocking the event loop

    async def _maybe_retry_with_basic_async(
        self, method: str, url: str, data: str | None = None
    ) -> httpx.Response | None:
        """Async retry with Basic auth if Bearer fails."""
        if not self.peer_passphrase:
            return None
        try:
            bh = self._basic_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                if data is None:
                    if method == "GET":
                        return await client.get(url, headers=bh)
                    if method == "DELETE":
                        return await client.delete(url, headers=bh)
                else:
                    headers = {**bh, "Content-Type": "application/json"}
                    if method == "POST":
                        return await client.post(url, content=data, headers=headers)
                    if method == "PUT":
                        return await client.put(url, content=data, headers=headers)
        except Exception:
            return None
        return None

    async def get_resource_async(
        self, path: str | None = None, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Async version of get_resource using httpx.

        Use this method in async contexts (e.g., FastAPI routes) for non-blocking
        HTTP calls to peer actors.

        Args:
            path: The resource path on the peer actor (e.g., "trust/friend/permissions")
            params: Optional query parameters

        Returns:
            The JSON response from the peer, or None if the request failed.
        """
        if not path or len(path) == 0:
            return None
        if not params:
            params = {}
        if not self.trust or not self.trust["baseuri"] or not self.trust["secret"]:
            return None
        url = self.trust["baseuri"].strip("/") + "/" + path.strip("/")
        if params:
            url = url + "?" + urllib_urlencode(params)
        headers = self._bearer_headers()
        logging.debug("Getting trust peer resource async at (" + url + ")")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                # Retry with Basic if Bearer gets redirected/unauthorized/forbidden
                if response.status_code in (302, 401, 403):
                    retry = await self._maybe_retry_with_basic_async("GET", url)
                    if retry is not None:
                        response = retry
                self.last_response_code = response.status_code
                self.last_response_message = response.content
        except httpx.TimeoutException:
            logging.debug("Timeout getting peer resource async")
            self.last_response_code = 408
            return {
                "error": {
                    "code": 408,
                    "message": "Timeout communicating with trust peer service.",
                },
            }
        except httpx.ConnectError as e:
            logging.debug(f"Connection error getting peer resource async: {e}")
            self.last_response_code = 502
            return {
                "error": {
                    "code": 502,
                    "message": "Unable to connect to trust peer service.",
                },
            }
        except httpx.NetworkError as e:
            logging.debug(f"Network error getting peer resource async: {e}")
            self.last_response_code = 502
            return {
                "error": {
                    "code": 502,
                    "message": "Network error communicating with trust peer service.",
                },
            }
        except Exception as e:
            logging.warning(f"Unexpected error getting peer resource async: {e}")
            self.last_response_code = 500
            return {
                "error": {
                    "code": 500,
                    "message": "Internal error communicating with trust peer service.",
                },
            }
        logging.debug(
            "Get trust peer resource async response:("
            + str(response.status_code)
            + ") "
            + str(response.content)
        )
        if response.status_code < 200 or response.status_code > 299:
            logging.info("Not able to get trust peer resource async.")
        try:
            result = response.json()
        except (TypeError, ValueError, KeyError):
            logging.debug(
                "Not able to parse response when getting resource async at(" + url + ")"
            )
            result = {}
        return result

    async def create_resource_async(
        self, path: str | None = None, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Async version of create_resource (POST) using httpx.

        Args:
            path: The resource path on the peer actor
            params: Data to send as JSON body

        Returns:
            The JSON response from the peer, or None if the request failed.
        """
        if not path or len(path) == 0:
            return None
        if not params:
            params = {}
        if not self.trust or not self.trust["baseuri"] or not self.trust["secret"]:
            return None
        data = json.dumps(params)
        headers = {**self._bearer_headers(), "Content-Type": "application/json"}
        url = self.trust["baseuri"].strip("/") + "/" + path.strip("/")
        logging.debug(
            "Creating trust peer resource async at ("
            + url
            + ") with data("
            + str(data)
            + ")"
        )
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, content=data, headers=headers)
                if response.status_code in (302, 401, 403):
                    retry = await self._maybe_retry_with_basic_async(
                        "POST", url, data=data
                    )
                    if retry is not None:
                        response = retry
                self.last_response_code = response.status_code
                self.last_response_message = response.content
        except httpx.TimeoutException:
            logging.debug("Timeout creating peer resource async")
            self.last_response_code = 408
            return {
                "error": {
                    "code": 408,
                    "message": "Timeout communicating with trust peer service.",
                },
            }
        except httpx.ConnectError as e:
            logging.debug(f"Connection error creating peer resource async: {e}")
            self.last_response_code = 502
            return {
                "error": {
                    "code": 502,
                    "message": "Unable to connect to trust peer service.",
                },
            }
        except httpx.NetworkError as e:
            logging.debug(f"Network error creating peer resource async: {e}")
            self.last_response_code = 502
            return {
                "error": {
                    "code": 502,
                    "message": "Network error communicating with trust peer service.",
                },
            }
        except Exception as e:
            logging.warning(f"Unexpected error creating peer resource async: {e}")
            self.last_response_code = 500
            return {
                "error": {
                    "code": 500,
                    "message": "Internal error communicating with trust peer service.",
                },
            }
        if "Location" in response.headers:
            self.last_location = response.headers["Location"]
        else:
            self.last_location = None
        logging.debug(
            "Create trust peer resource async response:("
            + str(response.status_code)
            + ") "
            + str(response.content)
        )
        if response.status_code < 200 or response.status_code > 299:
            logging.warning("Not able to create new trust peer resource async.")
        try:
            result = response.json()
        except (TypeError, ValueError, KeyError):
            logging.debug(
                "Not able to parse response when creating resource async at("
                + url
                + ")"
            )
            result = {}
        return result

    async def change_resource_async(
        self, path: str | None = None, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Async version of change_resource (PUT) using httpx.

        Args:
            path: The resource path on the peer actor
            params: Data to send as JSON body

        Returns:
            The JSON response from the peer, or None if the request failed.
        """
        if not path or len(path) == 0:
            return None
        if not params:
            params = {}
        if not self.trust or not self.trust["baseuri"] or not self.trust["secret"]:
            return None
        data = json.dumps(params)
        headers = {
            "Authorization": "Bearer " + self.trust["secret"],
            "Content-Type": "application/json",
        }
        url = self.trust["baseuri"].strip("/") + "/" + path.strip("/")
        logging.debug(
            "Changing trust peer resource async at ("
            + url
            + ") with data("
            + str(data)
            + ")"
        )
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.put(url, content=data, headers=headers)
                if response.status_code in (302, 401, 403):
                    retry = await self._maybe_retry_with_basic_async(
                        "PUT", url, data=data
                    )
                    if retry is not None:
                        response = retry
                self.last_response_code = response.status_code
                self.last_response_message = response.content
        except httpx.TimeoutException:
            logging.debug("Timeout changing peer resource async")
            self.last_response_code = 408
            return {
                "error": {
                    "code": 408,
                    "message": "Timeout communicating with trust peer service.",
                },
            }
        except httpx.ConnectError as e:
            logging.debug(f"Connection error changing peer resource async: {e}")
            self.last_response_code = 502
            return {
                "error": {
                    "code": 502,
                    "message": "Unable to connect to trust peer service.",
                },
            }
        except httpx.NetworkError as e:
            logging.debug(f"Network error changing peer resource async: {e}")
            self.last_response_code = 502
            return {
                "error": {
                    "code": 502,
                    "message": "Network error communicating with trust peer service.",
                },
            }
        except Exception as e:
            logging.warning(f"Unexpected error changing peer resource async: {e}")
            self.last_response_code = 500
            return {
                "error": {
                    "code": 500,
                    "message": "Internal error communicating with trust peer service.",
                },
            }
        logging.debug(
            "Change trust peer resource async response:("
            + str(response.status_code)
            + ") "
            + str(response.content)
        )
        if response.status_code < 200 or response.status_code > 299:
            logging.warning("Not able to change trust peer resource async.")
        try:
            result = response.json()
        except (TypeError, ValueError, KeyError):
            logging.debug(
                "Not able to parse response when changing resource async at("
                + url
                + ")"
            )
            result = {}
        return result

    async def delete_resource_async(
        self, path: str | None = None
    ) -> dict[str, Any] | None:
        """Async version of delete_resource (DELETE) using httpx.

        Args:
            path: The resource path on the peer actor

        Returns:
            The JSON response from the peer, or None if the request failed.
        """
        if not path or len(path) == 0:
            return None
        if not self.trust or not self.trust["baseuri"] or not self.trust["secret"]:
            return None
        headers = {"Authorization": "Bearer " + self.trust["secret"]}
        url = self.trust["baseuri"].strip("/") + "/" + path.strip("/")
        logging.debug("Deleting trust peer resource async at (" + url + ")")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.delete(url, headers=headers)
                if response.status_code in (302, 401, 403):
                    retry = await self._maybe_retry_with_basic_async("DELETE", url)
                    if retry is not None:
                        response = retry
                self.last_response_code = response.status_code
                self.last_response_message = response.content
        except httpx.TimeoutException:
            logging.debug("Timeout deleting peer resource async")
            self.last_response_code = 408
            return {
                "error": {
                    "code": 408,
                    "message": "Timeout communicating with trust peer service.",
                },
            }
        except httpx.ConnectError as e:
            logging.debug(f"Connection error deleting peer resource async: {e}")
            self.last_response_code = 502
            return {
                "error": {
                    "code": 502,
                    "message": "Unable to connect to trust peer service.",
                },
            }
        except httpx.NetworkError as e:
            logging.debug(f"Network error deleting peer resource async: {e}")
            self.last_response_code = 502
            return {
                "error": {
                    "code": 502,
                    "message": "Network error communicating with trust peer service.",
                },
            }
        except Exception as e:
            logging.warning(f"Unexpected error deleting peer resource async: {e}")
            self.last_response_code = 500
            return {
                "error": {
                    "code": 500,
                    "message": "Internal error communicating with trust peer service.",
                },
            }
        logging.debug(
            "Delete trust peer resource async response:("
            + str(response.status_code)
            + ") "
            + str(response.content)
        )
        if response.status_code < 200 or response.status_code > 299:
            logging.warning("Not able to delete trust peer resource async.")
        try:
            result = response.json()
        except (TypeError, ValueError, KeyError):
            logging.debug(
                "Not able to parse response when deleting resource async at("
                + url
                + ")"
            )
            result = {}
        return result
