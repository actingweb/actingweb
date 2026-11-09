"""The verification fetch against real sockets (reverify-9 Issues 1 and 2).

A verification GET goes to a base URI the requester chose. The caller must
get its answer by the deadline whatever the peer does, and a peer that
trickles must not keep the pool's worker: when the deadline passes, the
caller shuts the socket down. These tests use real local sockets, since a
fake ``iter_content`` cannot show a read that blocks.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from actingweb import actor as actor_module


class _Server:
    """A local HTTP server: ``trickle`` sends a header byte every 0.2 s and
    never finishes; ``fast`` answers 200 with a JSON body at once."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(32)
        self.port = self.sock.getsockname()[1]
        self.closed_by_peer = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _serve(self) -> None:
        self.sock.settimeout(0.2)
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                continue
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        try:
            conn.recv(4096)
            if self.mode == "fast":
                body = json.dumps({"id": "fast", "approved": True}).encode()
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    + f"Content-Length: {len(body)}\r\n\r\n".encode()
                    + body
                )
                return
            for byte in b"HTTP/1.1 200 OK\r\nX-Slow: " + b"a" * 10_000:
                if self.stop.is_set():
                    return
                conn.sendall(bytes([byte]))
                time.sleep(0.2)
        except OSError:
            self.closed_by_peer += 1
        finally:
            conn.close()

    def close(self) -> None:
        self.stop.set()
        self.sock.close()


@pytest.fixture
def servers() -> Iterator[tuple[_Server, _Server]]:
    trickle, fast = _Server("trickle"), _Server("fast")
    yield trickle, fast
    trickle.close()
    fast.close()


class TestTheSocketIsShutDown:
    def test_the_caller_returns_by_the_deadline(
        self, servers: tuple[_Server, _Server]
    ) -> None:
        trickle, _ = servers
        started = time.monotonic()
        status, body = actor_module._bounded_get_json(
            trickle.url + "/trust/friend/x", {}, time.monotonic() + 0.5
        )
        assert (status, body) == (None, None)
        assert time.monotonic() - started < 1.5

    def test_the_workers_are_free_again(self, servers: tuple[_Server, _Server]) -> None:
        """As many trickling peers as the pool has workers, then an honest
        one: it is answered, because the trickles' sockets were shut down
        at their deadline and their workers released."""
        trickle, fast = servers
        n = actor_module._VERIFY_WORKERS

        def slow(_: int) -> Any:
            return actor_module._bounded_get_json(
                trickle.url + "/meta", {}, time.monotonic() + 0.5
            )

        with ThreadPoolExecutor(max_workers=n) as callers:
            assert list(callers.map(slow, range(n))) == [(None, None)] * n
        started = time.monotonic()
        status, body = actor_module._bounded_get_json(
            fast.url + "/meta", {}, time.monotonic() + 3
        )
        assert status == 200 and body == {"id": "fast", "approved": True}
        assert time.monotonic() - started < 2.0

    def test_no_redirect_is_followed(self) -> None:
        """A 302 is the answer, not a hop to the location it names."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        def answer() -> None:
            conn, _ = server.accept()
            conn.recv(4096)
            conn.sendall(
                b"HTTP/1.1 302 Found\r\nLocation: http://169.254.169.254/\r\n"
                b"Content-Length: 0\r\n\r\n"
            )
            conn.close()

        threading.Thread(target=answer, daemon=True).start()
        try:
            status, body = actor_module._bounded_get_json(
                f"http://127.0.0.1:{port}/meta", {}, time.monotonic() + 3
            )
        finally:
            server.close()
        assert status == 302 and body is None
