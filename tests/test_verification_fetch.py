"""The verification fetch against real sockets (reverify-9 Issues 1 and 2,
reverify-10 Issues 1 to 4).

A verification GET goes to a base URI the requester chose. The caller must
get its answer by the deadline whatever the peer does, and a peer that
trickles must not keep the pool's worker: when the deadline passes, the
caller shuts the socket down, over TLS and through a proxy too, and also a
socket that connects only after the deadline. A full pool refuses at once.
These tests use real local sockets, since a fake ``iter_content`` cannot
show a read that blocks; production peers are HTTPS, so most run over TLS.
"""

from __future__ import annotations

import datetime
import ipaddress
import json
import socket
import ssl
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from actingweb import actor as actor_module


def _tls_context(directory: Path) -> tuple[ssl.SSLContext, Path]:
    """A server context with a self-signed certificate for 127.0.0.1, and
    the certificate's path, for the client to trust."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path = directory / "peer.pem"
    key_path = directory / "peer.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    return context, cert_path


@pytest.fixture
def no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")


def _all_workers_then_honest(
    slow_url: str, fast_url: str, deadline: float = 0.5, settle: float = 0.3
) -> tuple[Any, float]:
    """As many slow fetches as the pool has workers, each cut at
    ``deadline``; then, ``settle`` seconds later (a worker frees itself
    once its read fails), an honest one: its answer, and how long it took."""
    n = actor_module._VERIFY_WORKERS

    def slow(_: int) -> Any:
        return actor_module._bounded_get_json(slow_url, {}, time.monotonic() + deadline)

    with ThreadPoolExecutor(max_workers=n) as callers:
        assert list(callers.map(slow, range(n))) == [(None, None)] * n
    time.sleep(settle)
    started = time.monotonic()
    answer = actor_module._bounded_get_json(fast_url, {}, time.monotonic() + 3)
    return answer, time.monotonic() - started


class _Server:
    """A local HTTP server: ``trickle`` sends a header byte every 0.2 s and
    never finishes; ``fast`` answers 200 with a JSON body at once."""

    def __init__(self, mode: str, context: ssl.SSLContext | None = None) -> None:
        self.mode = mode
        self.context = context
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
        scheme = "https" if self.context or self.mode == "tls_handshake" else "http"
        return f"{scheme}://127.0.0.1:{self.port}"

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
            if self.mode == "tls_handshake":
                # A TLS record header announcing 16 KB, then its bytes one
                # by one: the client's handshake waits for the whole record.
                conn.recv(4096)
                conn.sendall(b"\x16\x03\x03\x40\x00")
                for _ in range(10_000):
                    if self.stop.is_set():
                        return
                    conn.sendall(b"\x02")
                    time.sleep(0.2)
                return
            if self.context is not None:
                conn = self.context.wrap_socket(conn, server_side=True)
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

    def test_the_workers_are_free_again(
        self, servers: tuple[_Server, _Server], no_proxy: None
    ) -> None:
        """As many trickling peers as the pool has workers, then an honest
        one: it is answered, because the trickles' sockets were shut down
        at their deadline and their workers released."""
        trickle, fast = servers
        (status, body), took = _all_workers_then_honest(
            trickle.url + "/meta", fast.url + "/meta"
        )
        assert status == 200 and body == {"id": "fast", "approved": True}
        assert took < 2.0

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


@pytest.fixture
def tls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_proxy: None
) -> ssl.SSLContext:
    """A server context; the client trusts its certificate (through the
    environment, as an operator's CA bundle would be)."""
    context, cert_path = _tls_context(tmp_path)
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(cert_path))
    return context


class TestOverTls:
    """Reverify-10 Issue 1: production peers are HTTPS. The TLS wrap
    detaches the socket the connection opened, so the shutdown must reach
    the socket the TLS layer reads from."""

    def test_a_trickled_handshake_frees_its_worker(self, tls: ssl.SSLContext) -> None:
        slow, fast = _Server("tls_handshake"), _Server("fast", tls)
        try:
            (status, body), took = _all_workers_then_honest(
                slow.url + "/meta", fast.url + "/meta"
            )
        finally:
            slow.close()
            fast.close()
        assert status == 200 and body == {"id": "fast", "approved": True}
        assert took < 2.0

    def test_trickled_headers_after_the_handshake_free_their_worker(
        self, tls: ssl.SSLContext
    ) -> None:
        slow, fast = _Server("trickle", tls), _Server("fast", tls)
        try:
            (status, body), took = _all_workers_then_honest(
                slow.url + "/meta", fast.url + "/meta"
            )
        finally:
            slow.close()
            fast.close()
        assert status == 200 and body == {"id": "fast", "approved": True}
        assert took < 2.0


class TestThroughAProxy:
    """Reverify-10 Issue 1: with the environment's proxy (owner decision:
    kept), the socket to the proxy is tracked and shut down too; a SOCKS
    proxy is refused for a verification."""

    @pytest.fixture
    def proxy(
        self, monkeypatch: pytest.MonkeyPatch, no_proxy: None
    ) -> Iterator[_Server]:
        # The "proxy" trickles its answer: to a plain GET, and to a CONNECT.
        server = _Server("trickle")
        monkeypatch.setenv("HTTP_PROXY", server.url)
        monkeypatch.setenv("HTTPS_PROXY", server.url)
        monkeypatch.setenv("NO_PROXY", "127.0.0.1")
        monkeypatch.setenv("no_proxy", "127.0.0.1")
        yield server
        server.close()

    @pytest.mark.parametrize("scheme", ["http", "https"])
    def test_a_proxied_fetch_frees_its_worker(
        self, proxy: _Server, scheme: str
    ) -> None:
        fast = _Server("fast")
        try:
            (status, body), took = _all_workers_then_honest(
                f"{scheme}://peer.example.test/meta", fast.url + "/meta"
            )
        finally:
            fast.close()
        assert status == 200 and body == {"id": "fast", "approved": True}
        assert took < 2.0

    def test_a_socks_proxy_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, no_proxy: None
    ) -> None:
        monkeypatch.setenv("HTTPS_PROXY", "socks5://127.0.0.1:9")
        started = time.monotonic()
        assert actor_module._bounded_get_json(
            "https://peer.example.test/meta", {}, time.monotonic() + 3
        ) == (None, None)
        assert time.monotonic() - started < 1.0


class TestLateAndFull:
    """Reverify-10 Issues 2 and 3."""

    def test_a_socket_connected_after_the_deadline_is_shut_down(
        self, tls: ssl.SSLContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A connect (or a DNS answer) slower than the time left: the socket
        arrives after the caller has gone, and is shut down at once."""
        # urllib3.connection calls it as ``connection.create_connection``,
        # through this module.
        import urllib3.util.connection as connection_util

        slow, fast = _Server("trickle", tls), _Server("fast", tls)
        real = connection_util.create_connection

        def late(address: Any, *args: Any, **kwargs: Any) -> Any:
            if address[1] == slow.port:
                time.sleep(1.0)
            return real(address, *args, **kwargs)

        monkeypatch.setattr(connection_util, "create_connection", late)
        try:
            (status, body), took = _all_workers_then_honest(
                slow.url + "/meta", fast.url + "/meta", deadline=0.3, settle=1.5
            )
        finally:
            slow.close()
            fast.close()
        assert status == 200 and body == {"id": "fast", "approved": True}
        assert took < 2.0

    def test_a_full_pool_refuses_at_once(self, tls: ssl.SSLContext) -> None:
        """Every worker busy: a further verification fails closed now, not
        after waiting out its deadline in the queue."""
        slow = _Server("trickle", tls)
        n = actor_module._VERIFY_WORKERS
        callers = ThreadPoolExecutor(max_workers=n)
        try:
            busy = [
                callers.submit(
                    actor_module._bounded_get_json,
                    slow.url + "/meta",
                    {},
                    time.monotonic() + 2,
                )
                for _ in range(n)
            ]
            time.sleep(0.5)
            started = time.monotonic()
            assert actor_module._bounded_get_json(
                slow.url + "/meta", {}, time.monotonic() + 2
            ) == (None, None)
            assert time.monotonic() - started < 0.5
            assert [f.result() for f in busy] == [(None, None)] * n
        finally:
            callers.shutdown(wait=True)
            slow.close()
        time.sleep(0.3)
