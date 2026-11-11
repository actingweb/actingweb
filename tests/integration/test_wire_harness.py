"""Tests of the wire harness itself: recorder, normaliser, comparer, registry.

Most need no server; the last one records a real write between two wire apps.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
import requests

from . import _wire
from ._wire import RecordingMiddleware, normalise, start_recording, stop_recording

pytestmark = [pytest.mark.wire, pytest.mark.xdist_group(name="wire_peer_paths")]

A1, B1, SUB1, SECRET1 = "a" * 32, "b" * 32, "c" * 32, "s3cr3t-one"
A2, B2, SUB2, SECRET2 = "d" * 32, "e" * 32, "f" * 32, "s3cr3t-two"


def _recording(a: str, b: str, sub: str, secret: str, port: int) -> dict[str, Any]:
    return {
        "steps": [
            {
                "step": "write",
                "wire": [
                    {
                        "host": "wire_app",
                        "method": "POST",
                        "path": f"/{b}/callbacks/subscriptions/{a}/{sub}",
                        "auth": f"Bearer {secret}",
                        "request": {
                            "subscriptionid": sub,
                            "url": f"http://localhost:{port}/{a}/subscriptions/{b}/{sub}/1",
                            "timestamp": "2026-11-07T10:00:00.123456+00:00",
                        },
                        "children": [],
                    }
                ],
            }
        ]
    }


def _normalise(
    monkeypatch: pytest.MonkeyPatch,
    recording: dict[str, Any],
    a: str,
    b: str,
    secret: str,
    port: int,
) -> dict[str, Any]:
    # The registry of wire hosts is process-wide; restore it afterwards.
    monkeypatch.setattr(_wire, "_WIRE_HOSTS", {f"localhost:{port}": "wire_app"})
    return normalise(recording, {a: "A", b: "B"}, {secret: "trust:A-B"})


# ---------------------------------------------------------------------------
# The normaliser
# ---------------------------------------------------------------------------


def test_two_runs_with_different_actors_normalise_to_the_same_bytes(monkeypatch):
    one = _normalise(
        monkeypatch, _recording(A1, B1, SUB1, SECRET1, 5561), A1, B1, SECRET1, 5561
    )
    two = _normalise(
        monkeypatch, _recording(A2, B2, SUB2, SECRET2, 5571), A2, B2, SECRET2, 5571
    )
    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)
    text = json.dumps(one)
    assert "bearer:trust:A-B" in text
    assert "<wire_app>/<A>/subscriptions/<B>/<sub1>/1" in text


@pytest.mark.parametrize(
    "planted",
    [
        pytest.param("9" * 32, id="an unnamed actor id"),
        pytest.param("localhost:5599", id="a port"),
    ],
)
def test_the_guard_fails_on_anything_left_unnamed(monkeypatch, planted):
    recording = _recording(A1, B1, SUB1, SECRET1, 5561)
    recording["steps"][0]["wire"][0]["request"]["note"] = f"x {planted} y"
    with pytest.raises(AssertionError, match="normaliser left"):
        _normalise(monkeypatch, recording, A1, B1, SECRET1, 5561)


def test_an_unknown_bearer_fails(monkeypatch):
    recording = _recording(A1, B1, SUB1, "not-a-registered-secret", 5561)
    with pytest.raises(AssertionError, match="unknown bearer"):
        _normalise(monkeypatch, recording, A1, B1, SECRET1, 5561)


def _with_trust_creation(secret: str) -> dict[str, Any]:
    recording = _recording(A1, B1, SUB1, secret, 5561)
    recording["steps"][0]["wire"].insert(
        0,
        {
            "host": "wire_app",
            "method": "POST",
            "path": f"/{A1}/trust",
            "auth": None,
            "request": {"secret": secret},
            "children": [],
        },
    )
    return recording


def test_a_secret_nobody_named_fails_the_guard(monkeypatch):
    with pytest.raises(AssertionError, match="unnamed secret"):
        _normalise(
            monkeypatch, _with_trust_creation("fresh-secret"), A1, B1, SECRET1, 5561
        )


def test_a_secret_named_mid_row_is_replaced_and_its_bearer_resolves(monkeypatch):
    monkeypatch.setattr(_wire, "_WIRE_HOSTS", {"localhost:5561": "wire_app"})
    out = normalise(
        _with_trust_creation("fresh-secret"),
        {A1: "A", B1: "B"},
        {SECRET1: "trust:A-B", "fresh-secret": "trust:A-B#2"},
    )
    text = json.dumps(out)
    assert "<secret:trust:A-B#2>" in text
    assert "bearer:trust:A-B#2" in text
    assert "fresh-secret" not in text


@pytest.mark.parametrize("key", ["client_secret", "access_token", "refresh_token"])
def test_an_oauth2_secret_nobody_named_fails_the_guard(monkeypatch, key):
    """The ``wire_oauth`` rows: each OAuth2 secret a response carries is
    named by the row, or the recording fails."""
    recording = _recording(A1, B1, SUB1, SECRET1, 5561)
    recording["steps"][0]["wire"][0]["response"] = {key: "fresh-oauth-value"}
    with pytest.raises(AssertionError, match="unnamed secret"):
        _normalise(monkeypatch, recording, A1, B1, SECRET1, 5561)
    out = normalise(
        recording, {A1: "A", B1: "B"}, {SECRET1: "trust:A-B", "fresh-oauth-value": "x"}
    )
    assert out["steps"][0]["wire"][0]["response"] == {key: "<secret:x>"}


def test_an_unnamed_oauth2_client_id_fails_the_guard(monkeypatch):
    """``mcp_`` and hex is no hex word to ``_HEX32`` (``_`` joins them)."""
    recording = _recording(A1, B1, SUB1, SECRET1, 5561)
    recording["steps"][0]["wire"][0]["request"]["note"] = "mcp_" + "ab" * 16
    with pytest.raises(AssertionError, match="normaliser left"):
        _normalise(monkeypatch, recording, A1, B1, SECRET1, 5561)


def test_a_host_inside_an_encoded_url_is_named(monkeypatch):
    recording = _recording(A1, B1, SUB1, SECRET1, 5561)
    recording["steps"][0]["wire"][0]["request"]["note"] = (
        "redirect_uri=http%3A%2F%2Flocalhost%3A5561%2Foauth%2Fcallback"
    )
    out = _normalise(monkeypatch, recording, A1, B1, SECRET1, 5561)
    assert out["steps"][0]["wire"][0]["request"]["note"] == (
        "redirect_uri=http%3A%2F%2F<wire_app>%2Foauth%2Fcallback"
    )


def test_set_cookie_keeps_name_and_attributes():
    assert (
        _wire._cookie("aw_n=abc123; Path=/; HttpOnly")  # pyright: ignore[reportPrivateUsage]
        == "aw_n=<cookie>; Path=/; HttpOnly"
    )
    assert _wire._cookie("odd") == "odd"  # pyright: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# The comparer
# ---------------------------------------------------------------------------


def test_recording_is_refused_under_ci(monkeypatch, tmp_path):
    monkeypatch.setattr(_wire, "WIRE_DIR", tmp_path)
    monkeypatch.setenv("WIRE_RECORD", "WX1")
    monkeypatch.setenv("CI", "true")
    with pytest.raises(AssertionError, match="refused under CI"):
        _wire.check("WX1", {"steps": []})
    assert not list(tmp_path.iterdir())


def test_only_the_rows_named_are_recorded(monkeypatch, tmp_path):
    monkeypatch.setattr(_wire, "WIRE_DIR", tmp_path)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("WIRE_RECORD", "WX1, WX3")
    (tmp_path / "WX2.json").write_text(json.dumps({"steps": []}) + "\n")
    _wire.check("WX1", {"steps": [{"step": "one"}]})
    assert (tmp_path / "WX1.json").exists()
    with pytest.raises(AssertionError, match="differs from its recording"):
        _wire.check("WX2", {"steps": [{"step": "changed"}]})
    assert json.loads((tmp_path / "WX2.json").read_text()) == {"steps": []}


def test_a_difference_fails_and_leaves_the_actual_file(monkeypatch, tmp_path):
    monkeypatch.setattr(_wire, "WIRE_DIR", tmp_path)
    monkeypatch.delenv("WIRE_RECORD", raising=False)
    (tmp_path / "WX1.json").write_text(json.dumps({"steps": []}) + "\n")
    with pytest.raises(AssertionError, match="differs from its recording"):
        _wire.check("WX1", {"steps": [{"step": "new"}]})
    assert (tmp_path / "WX1.actual.json").exists()


# ---------------------------------------------------------------------------
# The recorder
# ---------------------------------------------------------------------------


def _drive(app: Any, path: str) -> None:
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "query_string": b"",
        "headers": [(b"authorization", b"Bearer s")],
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        return None

    asyncio.run(app(scope, receive, send))


def test_a_handler_exception_is_recorded_as_500():
    async def failing(scope: Any, receive: Any, send: Any) -> None:
        await receive()
        raise RuntimeError("boom")

    start_recording()
    try:
        with pytest.raises(RuntimeError):
            _drive(RecordingMiddleware(failing, host="wire_app"), "/x")
    finally:
        wire = stop_recording()
    assert len(wire) == 1
    assert wire[0]["status"] == 500
    assert wire[0]["exception"] == "RuntimeError"


def test_an_exception_after_the_response_started_keeps_its_status():
    async def late_failure(scope: Any, receive: Any, send: Any) -> None:
        await receive()
        await send({"type": "http.response.start", "status": 204, "headers": []})
        raise RuntimeError("after the answer")

    start_recording()
    try:
        with pytest.raises(RuntimeError):
            _drive(RecordingMiddleware(late_failure, host="wire_app"), "/x")
    finally:
        wire = stop_recording()
    assert wire[0]["status"] == 204
    assert wire[0]["exception"] == "RuntimeError"


def test_a_request_made_while_another_is_open_is_its_child():
    async def inner(scope: Any, receive: Any, send: Any) -> None:
        await receive()
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    inner_app = RecordingMiddleware(inner, host="wire_peer_app")

    async def outer(scope: Any, receive: Any, send: Any) -> None:
        await receive()
        await inner_app(
            {**scope, "path": "/callback"},
            receive,
            lambda message: asyncio.sleep(0),
        )
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    start_recording()
    try:
        _drive(RecordingMiddleware(outer, host="wire_app"), "/write")
    finally:
        wire = stop_recording()
    assert [e["path"] for e in wire] == ["/write"]
    assert wire[0]["status"] == 200
    assert [c["path"] for c in wire[0]["children"]] == ["/callback"]
    assert wire[0]["children"][0]["status"] == 204


def test_a_callback_is_recorded_once_nested_in_the_write_without_the_secret(
    wire_pair,
):
    s = wire_pair("same_host", grant=["*"])
    a = s.publisher
    s.step(
        "put",
        lambda: requests.put(f"{a.url}/properties/p", json={"v": 1}, auth=a.basic),
    )
    wire = s.steps[-1]["wire"]
    assert len(wire) == 1 and wire[0]["method"] == "PUT"
    callbacks = [c for c in wire[0]["children"] if "/callbacks/" in c["path"]]
    assert len(callbacks) == 1
    assert callbacks[0]["status"] == 204
    text = json.dumps(s.recording())
    assert s.trust_secret not in text
    assert "bearer:trust:A-B" in text


# ---------------------------------------------------------------------------
# The registry check in verify_groups.py
# ---------------------------------------------------------------------------


def _verify_groups() -> Any:
    path = Path(__file__).parent / "verify_groups.py"
    spec = importlib.util.spec_from_file_location("verify_groups", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_ENTRY = """
[reserved]
"p" = ["WX1-WX9"]

[rows."WX1"]
test = "test_x.py::test_wx1"
owners = {owners}
exposure = {exposure}
expected = "something"
reason = ["2026-11-07 first recording (p:0)"]
"""


@pytest.mark.parametrize(
    ("owners", "files", "problem", "exposure"),
    [
        ("[]", ["WX1.json"], None, "false"),
        ("[]", [], "no recording WX1.json", "false"),
        ("[]", ["WX1.json", "WX2.json"], "WX2.json: no row", "false"),
        ("[]", ["WX1.json", "WX1.actual.json"], "left over", "false"),
        ('["no-phase"]', ["WX1.json"], "owners must be", "false"),
        ('["q:1"]', ["WX1.json"], "not a [reserved] plan", "false"),
        ("[]", ["WX1.json"], "an exposure row must name an owner", "true"),
        ('["p:1"]', ["WX1.json"], None, "true"),
    ],
)
def test_the_registry_check(tmp_path, owners, files, problem, exposure):
    wire_dir = tmp_path / "wire"
    wire_dir.mkdir()
    (wire_dir / "rows.toml").write_text(_ENTRY.format(owners=owners, exposure=exposure))
    for name in files:
        (wire_dir / name).write_text("{}\n")
    (tmp_path / "test_x.py").write_text("def test_wx1():\n    pass\n")
    problems, _ = _verify_groups().check_wire_rows(wire_dir, tmp_path)
    if problem is None:
        assert problems == []
    else:
        assert any(problem in p for p in problems), problems
