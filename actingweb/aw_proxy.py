import base64
import json
import logging
from typing import Any

import httpx
import requests

from actingweb import request_context, trust

logger = logging.getLogger(__name__)

try:
    from urllib.parse import urlencode as urllib_urlencode
except ImportError:
    from urllib.parse import urlencode as urllib_urlencode

# Type alias for timeout parameter
TimeoutType = int | float | tuple[int | float, int | float] | None


class AwProxy:
    """Proxy to other trust peers to execute RPC style calls.

    Initialise with either trust_target to target a specific
    existing trust or use peer_target for simplicity to use
    the trust established with the peer.

    Args:
        trust_target: Trust object for the target peer
        peer_target: Simplified peer target dict
        config: Configuration object
        timeout: HTTP timeout in seconds. Either a single value (used for both
                 connect and read timeouts) or a tuple (connect_timeout, read_timeout).
                 Default: (5, 20) = 5s connect, 20s read timeout.

    Provides both sync methods (using ``requests``) and async methods
    (using ``httpx``) for peer communication:

    - Sync: ``get_resource()``, ``create_resource()``, ``change_resource()``, ``delete_resource()``
    - Async: ``get_resource_async()``, ``create_resource_async()``, ``change_resource_async()``, ``delete_resource_async()``

    Use async methods in FastAPI routes for non-blocking I/O.
    """

    def __init__(
        self,
        trust_target: Any = None,
        peer_target: dict[str, Any] | None = None,
        config: Any = None,
        timeout: TimeoutType = None,
    ):
        self.config = config
        self.last_response_code = 0
        self.last_response_message = 0
        self.last_location: str | None = None
        self.peer_passphrase: str | None = None
        # Set timeout - supports tuple (connect, read) or single value
        # Default: (5, 20) = 5s connect, 20s read timeout
        if timeout is None:
            self.timeout: tuple[int | float, int | float] = (5, 20)
        elif isinstance(timeout, tuple):
            self.timeout = timeout
        else:
            # Single value provided, use for both connect and read
            self.timeout = (timeout, timeout)
        # Pre-compute httpx timeout for async methods (proper connect/read separation)
        # httpx.Timeout accepts tuple format: (connect, read, write, pool)
        self._httpx_timeout = httpx.Timeout(
            timeout=float(self.timeout[1]),  # default for unspecified
            connect=float(self.timeout[0]),
            read=float(self.timeout[1]),
        )
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

    def _add_correlation_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """Add request correlation headers for tracing peer-to-peer requests.

        Generates a new request ID for the outgoing request and includes the
        current request ID as the parent for request chain tracking.

        Args:
            headers: Existing headers dictionary to add correlation headers to

        Returns:
            Updated headers dictionary with correlation headers
        """
        # Generate new request ID for the outgoing peer request
        new_request_id = request_context.generate_request_id()
        headers["X-Request-ID"] = new_request_id

        # Add parent request ID if we're in a request context
        parent_request_id = request_context.get_request_id()
        if parent_request_id:
            headers["X-Parent-Request-ID"] = parent_request_id
            # Log correlation for traceability
            logger.debug(
                f"Peer request correlation: new_id={new_request_id[:8]}... "
                f"parent_id={parent_request_id[:8]}..."
            )
        else:
            logger.debug(f"Peer request: new_id={new_request_id[:8]}... (no parent)")

        return headers

    def _bearer_headers(self):
        headers = (
            {"Authorization": "Bearer " + self.trust["secret"]}
            if self.trust and self.trust.get("secret")
            else {}
        )
        return self._add_correlation_headers(headers)

    def _basic_headers(self):
        if not self.peer_passphrase:
            return self._add_correlation_headers({})
        u_p = ("trustee:" + self.peer_passphrase).encode("utf-8")
        headers = {"Authorization": "Basic " + base64.b64encode(u_p).decode("utf-8")}
        return self._add_correlation_headers(headers)

    def _maybe_retry_with_basic(self, method, url, data=None, headers=None):
        # Only retry if we have a peer passphrase available
        if not self.peer_passphrase:
            return None
        try:
            bh = self._basic_headers()
            # If original headers had correlation headers, preserve them in retry
            if headers:
                if "X-Request-ID" in headers:
                    bh["X-Request-ID"] = headers["X-Request-ID"]
                if "X-Parent-Request-ID" in headers:
                    bh["X-Parent-Request-ID"] = headers["X-Parent-Request-ID"]
            if data is None:
                if method == "GET":
                    return requests.get(url=url, headers=bh, timeout=self.timeout)
                if method == "DELETE":
                    return requests.delete(url=url, headers=bh, timeout=self.timeout)
            else:
                if method == "POST":
                    return requests.post(
                        url=url,
                        data=data,
                        headers={**bh, "Content-Type": "application/json"},
                        timeout=self.timeout,
                    )
                if method == "PUT":
                    return requests.put(
                        url=url,
                        data=data,
                        headers={**bh, "Content-Type": "application/json"},
                        timeout=self.timeout,
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
        logger.debug(f"Fetching peer resource from {url}")
        try:
            response = requests.get(url=url, headers=headers, timeout=self.timeout)
            # Retry with Basic if Bearer gets redirected/unauthorized/forbidden
            if response.status_code in (302, 401, 403):
                retry = self._maybe_retry_with_basic("GET", url, headers=headers)
                if retry is not None:
                    response = retry
            self.last_response_code = response.status_code
            self.last_response_message = response.content
        except Exception:
            logger.debug("Not able to get peer resource")
            self.last_response_code = 408
            return {
                "error": {
                    "code": 408,
                    "message": "Unable to communciate with trust peer service.",
                },
            }
        logger.debug(f"Get trust peer resource response: {response.status_code}")
        if response.status_code < 200 or response.status_code > 299:
            logger.info("Not able to get trust peer resource.")
        try:
            result = response.json()
        except (TypeError, ValueError, KeyError):
            logger.debug(
                "Not able to parse response when getting resource at(" + url + ")"
            )
            # If response was an error status and JSON parsing failed, return structured error
            if response.status_code < 200 or response.status_code > 299:
                result = {
                    "error": {
                        "code": response.status_code,
                        "message": f"HTTP {response.status_code} with non-JSON response",
                    }
                }
            else:
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
        logger.debug(
            "Creating trust peer resource at (" + url + ") with data(" + str(data) + ")"
        )
        try:
            response = requests.post(
                url=url, data=data, headers=headers, timeout=self.timeout
            )
            if response.status_code in (302, 401, 403):
                retry = self._maybe_retry_with_basic(
                    "POST", url, data=data, headers=headers
                )
                if retry is not None:
                    response = retry
            self.last_response_code = response.status_code
            self.last_response_message = response.content
        except Exception:
            logger.debug("Not able to create new peer resource")
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
        logger.debug(f"Create trust peer resource response: {response.status_code}")
        if response.status_code < 200 or response.status_code > 299:
            logger.warning("Not able to create new trust peer resource.")
        try:
            result = response.json()
        except (TypeError, ValueError, KeyError):
            logger.debug(
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
        # Use _bearer_headers() to include correlation headers
        headers = self._bearer_headers()
        headers["Content-Type"] = "application/json"
        url = self.trust["baseuri"].strip("/") + "/" + path.strip("/")
        logger.debug(
            "Changing trust peer resource at (" + url + ") with data(" + str(data) + ")"
        )
        try:
            response = requests.put(
                url=url, data=data, headers=headers, timeout=self.timeout
            )
            if response.status_code in (302, 401, 403):
                retry = self._maybe_retry_with_basic(
                    "PUT", url, data=data, headers=headers
                )
                if retry is not None:
                    response = retry
            self.last_response_code = response.status_code
            self.last_response_message = response.content
        except Exception:
            logger.debug("Not able to change peer resource")
            self.last_response_code = 408
            return {
                "error": {
                    "code": 408,
                    "message": "Unable to communciate with trust peer service.",
                },
            }
        logger.debug(f"Change trust peer resource response: {response.status_code}")
        if response.status_code < 200 or response.status_code > 299:
            logger.warning("Not able to change trust peer resource.")
        try:
            result = response.json()
        except (TypeError, ValueError, KeyError):
            logger.debug(
                "Not able to parse response when changing resource at(" + url + ")"
            )
            result = {}
        return result

    def delete_resource(self, path=None):
        if not path or len(path) == 0:
            return None
        if not self.trust or not self.trust["baseuri"] or not self.trust["secret"]:
            return None
        # Use _bearer_headers() to include correlation headers
        headers = self._bearer_headers()
        url = self.trust["baseuri"].strip("/") + "/" + path.strip("/")
        logger.info(f"Deleting peer resource at {url}")
        try:
            response = requests.delete(url=url, headers=headers, timeout=self.timeout)
            if response.status_code in (302, 401, 403):
                retry = self._maybe_retry_with_basic("DELETE", url, headers=headers)
                if retry is not None:
                    response = retry
            self.last_response_code = response.status_code
            self.last_response_message = response.content
        except Exception:
            logger.debug("Not able to delete peer resource")
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
        self,
        method: str,
        url: str,
        data: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response | None:
        """Async retry with Basic auth if Bearer fails."""
        if not self.peer_passphrase:
            return None
        try:
            bh = self._basic_headers()
            # If original headers had correlation headers, preserve them in retry
            if headers:
                if "X-Request-ID" in headers:
                    bh["X-Request-ID"] = headers["X-Request-ID"]
                if "X-Parent-Request-ID" in headers:
                    bh["X-Parent-Request-ID"] = headers["X-Parent-Request-ID"]
            async with httpx.AsyncClient(timeout=self._httpx_timeout) as client:
                if data is None:
                    if method == "GET":
                        return await client.get(url, headers=bh)
                    if method == "DELETE":
                        return await client.delete(url, headers=bh)
                else:
                    final_headers = {**bh, "Content-Type": "application/json"}
                    if method == "POST":
                        return await client.post(
                            url, content=data, headers=final_headers
                        )
                    if method == "PUT":
                        return await client.put(
                            url, content=data, headers=final_headers
                        )
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
        logger.debug(f"Fetching peer resource async from {url}")
        try:
            async with httpx.AsyncClient(timeout=self._httpx_timeout) as client:
                response = await client.get(url, headers=headers)
                # Retry with Basic if Bearer gets redirected/unauthorized/forbidden
                if response.status_code in (302, 401, 403):
                    retry = await self._maybe_retry_with_basic_async(
                        "GET", url, headers=headers
                    )
                    if retry is not None:
                        response = retry
                self.last_response_code = response.status_code
                self.last_response_message = response.content
        except httpx.TimeoutException:
            logger.debug("Timeout getting peer resource async")
            self.last_response_code = 408
            return {
                "error": {
                    "code": 408,
                    "message": "Timeout communicating with trust peer service.",
                },
            }
        except httpx.ConnectError as e:
            logger.debug(f"Connection error getting peer resource async: {e}")
            self.last_response_code = 502
            return {
                "error": {
                    "code": 502,
                    "message": "Unable to connect to trust peer service.",
                },
            }
        except httpx.NetworkError as e:
            logger.debug(f"Network error getting peer resource async: {e}")
            self.last_response_code = 502
            return {
                "error": {
                    "code": 502,
                    "message": "Network error communicating with trust peer service.",
                },
            }
        except Exception as e:
            logger.warning(f"Unexpected error getting peer resource async: {e}")
            self.last_response_code = 500
            return {
                "error": {
                    "code": 500,
                    "message": "Internal error communicating with trust peer service.",
                },
            }
        logger.debug(f"Get trust peer resource async response: {response.status_code}")
        if response.status_code < 200 or response.status_code > 299:
            logger.info("Not able to get trust peer resource async.")
        try:
            result = response.json()
        except (TypeError, ValueError, KeyError):
            logger.debug(
                "Not able to parse response when getting resource async at(" + url + ")"
            )
            # If response was an error status and JSON parsing failed, return structured error
            if response.status_code < 200 or response.status_code > 299:
                result = {
                    "error": {
                        "code": response.status_code,
                        "message": f"HTTP {response.status_code} with non-JSON response",
                    }
                }
            else:
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
        logger.debug(
            "Creating trust peer resource async at ("
            + url
            + ") with data("
            + str(data)
            + ")"
        )
        try:
            async with httpx.AsyncClient(timeout=self._httpx_timeout) as client:
                response = await client.post(url, content=data, headers=headers)
                if response.status_code in (302, 401, 403):
                    retry = await self._maybe_retry_with_basic_async(
                        "POST", url, data=data, headers=headers
                    )
                    if retry is not None:
                        response = retry
                self.last_response_code = response.status_code
                self.last_response_message = response.content
        except httpx.TimeoutException:
            logger.debug("Timeout creating peer resource async")
            self.last_response_code = 408
            return {
                "error": {
                    "code": 408,
                    "message": "Timeout communicating with trust peer service.",
                },
            }
        except httpx.ConnectError as e:
            logger.debug(f"Connection error creating peer resource async: {e}")
            self.last_response_code = 502
            return {
                "error": {
                    "code": 502,
                    "message": "Unable to connect to trust peer service.",
                },
            }
        except httpx.NetworkError as e:
            logger.debug(f"Network error creating peer resource async: {e}")
            self.last_response_code = 502
            return {
                "error": {
                    "code": 502,
                    "message": "Network error communicating with trust peer service.",
                },
            }
        except Exception as e:
            logger.warning(f"Unexpected error creating peer resource async: {e}")
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
        logger.debug(
            f"Create trust peer resource async response: {response.status_code}"
        )
        if response.status_code < 200 or response.status_code > 299:
            logger.warning("Not able to create new trust peer resource async.")
        try:
            result = response.json()
        except (TypeError, ValueError, KeyError):
            logger.debug(
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
        # Use _bearer_headers() to include correlation headers
        headers = self._bearer_headers()
        headers["Content-Type"] = "application/json"
        url = self.trust["baseuri"].strip("/") + "/" + path.strip("/")
        logger.debug(
            "Changing trust peer resource async at ("
            + url
            + ") with data("
            + str(data)
            + ")"
        )
        try:
            async with httpx.AsyncClient(timeout=self._httpx_timeout) as client:
                response = await client.put(url, content=data, headers=headers)
                if response.status_code in (302, 401, 403):
                    retry = await self._maybe_retry_with_basic_async(
                        "PUT", url, data=data, headers=headers
                    )
                    if retry is not None:
                        response = retry
                self.last_response_code = response.status_code
                self.last_response_message = response.content
        except httpx.TimeoutException:
            logger.debug("Timeout changing peer resource async")
            self.last_response_code = 408
            return {
                "error": {
                    "code": 408,
                    "message": "Timeout communicating with trust peer service.",
                },
            }
        except httpx.ConnectError as e:
            logger.debug(f"Connection error changing peer resource async: {e}")
            self.last_response_code = 502
            return {
                "error": {
                    "code": 502,
                    "message": "Unable to connect to trust peer service.",
                },
            }
        except httpx.NetworkError as e:
            logger.debug(f"Network error changing peer resource async: {e}")
            self.last_response_code = 502
            return {
                "error": {
                    "code": 502,
                    "message": "Network error communicating with trust peer service.",
                },
            }
        except Exception as e:
            logger.warning(f"Unexpected error changing peer resource async: {e}")
            self.last_response_code = 500
            return {
                "error": {
                    "code": 500,
                    "message": "Internal error communicating with trust peer service.",
                },
            }
        logger.debug(
            f"Change trust peer resource async response: {response.status_code}"
        )
        if response.status_code < 200 or response.status_code > 299:
            logger.warning("Not able to change trust peer resource async.")
        try:
            result = response.json()
        except (TypeError, ValueError, KeyError):
            logger.debug(
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
        # Use _bearer_headers() to include correlation headers
        headers = self._bearer_headers()
        url = self.trust["baseuri"].strip("/") + "/" + path.strip("/")
        logger.info(f"Deleting peer resource async at {url}")
        try:
            async with httpx.AsyncClient(timeout=self._httpx_timeout) as client:
                response = await client.delete(url, headers=headers)
                if response.status_code in (302, 401, 403):
                    retry = await self._maybe_retry_with_basic_async(
                        "DELETE", url, headers=headers
                    )
                    if retry is not None:
                        response = retry
                self.last_response_code = response.status_code
                self.last_response_message = response.content
        except httpx.TimeoutException:
            logger.debug("Timeout deleting peer resource async")
            self.last_response_code = 408
            return {
                "error": {
                    "code": 408,
                    "message": "Timeout communicating with trust peer service.",
                },
            }
        except httpx.ConnectError as e:
            logger.debug(f"Connection error deleting peer resource async: {e}")
            self.last_response_code = 502
            return {
                "error": {
                    "code": 502,
                    "message": "Unable to connect to trust peer service.",
                },
            }
        except httpx.NetworkError as e:
            logger.debug(f"Network error deleting peer resource async: {e}")
            self.last_response_code = 502
            return {
                "error": {
                    "code": 502,
                    "message": "Network error communicating with trust peer service.",
                },
            }
        except Exception as e:
            logger.warning(f"Unexpected error deleting peer resource async: {e}")
            self.last_response_code = 500
            return {
                "error": {
                    "code": 500,
                    "message": "Internal error communicating with trust peer service.",
                },
            }
        logger.debug(
            f"Delete trust peer resource async response: {response.status_code}"
        )
        if response.status_code < 200 or response.status_code > 299:
            logger.warning("Not able to delete trust peer resource async.")
        try:
            result = response.json()
        except (TypeError, ValueError, KeyError):
            logger.debug(
                "Not able to parse response when deleting resource async at("
                + url
                + ")"
            )
            result = {}
        return result
