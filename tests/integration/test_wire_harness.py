"""Tests of the wire harness itself: recorder, normaliser, comparer, registry.

Most need no server; the last one records a real write between two wire apps.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import types
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


@pytest.mark.parametrize(
    ("second", "problem"),
    [
        ('{ file = "WX1.postgresql.json", why = "a backend difference" }', None),
        ('{ file = "WX1.postgresql.json" }', "second must be"),
        ('{ file = "WY1.postgresql.json", why = "x" }', "second must be"),
        ('"WX1.postgresql.json"', "second must be"),
    ],
)
def test_a_second_file_needs_its_reason(tmp_path, second, problem):
    wire_dir = tmp_path / "wire"
    wire_dir.mkdir()
    entry = _ENTRY.format(owners="[]", exposure="false") + f"second = {second}\n"
    (wire_dir / "rows.toml").write_text(entry)
    for name in ("WX1.json", "WX1.postgresql.json"):
        (wire_dir / name).write_text("{}\n")
    (tmp_path / "test_x.py").write_text("def test_wx1():\n    pass\n")
    problems, _ = _verify_groups().check_wire_rows(wire_dir, tmp_path)
    if problem is None:
        assert problems == []
    else:
        assert any(problem in p for p in problems), problems


_PHASE_ROWS: dict[str, dict[str, Any]] = {
    "WX1": {"owners": ["p:2"]},
    "WX2": {"owners": [], "topologies": ["same_host", "two_hosts"]},
}


_BASE_FILES = {"WX1.json", "WX2.same_host.json", "WX2.two_hosts.json", "WZ9.json"}


@pytest.mark.parametrize(
    ("changes", "trailers", "problem"),
    [
        # A new recording is the first: no owner needed.
        ([("A", "WX1.json")], [], None),
        # Re-recorded by its owner.
        ([("M", "WX1.json")], ["p:2"], None),
        # Re-recorded by a phase that does not own it.
        ([("M", "WX1.json")], ["p:3"], "not among its owners"),
        # Re-recorded with no trailer, or two.
        ([("M", "WX1.json")], [], "exactly one"),
        ([("M", "WX1.json")], ["p:2", "p:3"], "exactly one"),
        # A row nobody owns is changed by nobody.
        ([("M", "WX2.two_hosts.json")], ["p:2"], "not among its owners"),
        # A deletion needs an owner too.
        ([("D", "WX1.json")], ["p:2"], None),
        ([("D", "WX1.json")], ["p:3"], "not among its owners"),
        # A file at the merge base that no row names.
        ([("M", "WZ9.json")], ["p:2"], "belongs to no row"),
        # A recording added on this branch may change on this branch.
        ([("M", "WX7.json")], [], None),
        ([("D", "WX7.json")], [], None),
    ],
)
def test_the_wire_phase_check(changes, trailers, problem):
    problems = _verify_groups().wire_phase_problems(
        "0123456789abcdef", changes, trailers, _PHASE_ROWS, _BASE_FILES
    )
    if problem is None:
        assert problems == []
    else:
        assert any(problem in p for p in problems), problems


def test_an_async_step_waits_for_the_tasks_it_left_on_the_loop():
    """An asynchronous step settles only when the fire-and-forget tasks it
    started, and the tasks those started, have finished."""
    done: list[str] = []

    async def later(name: str, then: str | None = None) -> None:
        await asyncio.sleep(0.01)
        done.append(name)
        if then:
            asyncio.get_running_loop().create_task(later(then))

    async def action() -> str:
        asyncio.get_running_loop().create_task(later("first", then="second"))
        return "returned before either"

    assert asyncio.run(_wire._run_and_drain(action)) == "returned before either"
    assert done == ["first", "second"]


def test_sibling_callbacks_sort_by_the_receivers_name_and_nothing_else_moves():
    b, c = "b" * 32, "c" * 32

    def cb(actor: str, children: list[Any] | None = None) -> dict[str, Any]:
        return {
            "path": f"/{actor}/callbacks/subscriptions/x/y",
            "children": children or [],
        }

    write = {
        "path": "/a/properties/x",
        "children": [cb(c, [cb(c)]), cb(b), {"event": "e"}, cb(c), cb(b)],
    }
    out = _wire._sort_callback_runs([write], {b: "B", c: "C"})
    paths = [e.get("path", e.get("event"))[:2] for e in out[0]["children"]]
    assert paths == ["/b", "/c", "e", "/b", "/c"]
    assert out[0]["children"][1]["children"] == [cb(c)]


def test_an_owner_added_on_the_branch_does_not_count():
    """Owners are read at the merge base: a branch that adds its own phase to
    a row's owners (in that commit or an earlier one) and re-records the row
    fails, so an ownership change lands on master first."""
    at_base = {"WX1": {"owners": []}}
    problems = _verify_groups().wire_phase_problems(
        "0123456789abcdef", [("M", "WX1.json")], ["p:3"], at_base, {"WX1.json"}
    )
    assert any("not among its owners" in p for p in problems), problems


def _git_repo(path: Path) -> Any:
    import subprocess

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(path), *args],
            check=True,
            capture_output=True,
            text=True,
            env={
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@example.test",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@example.test",
                "PATH": __import__("os").environ["PATH"],
                "HOME": str(path),
            },
        ).stdout

    return git


def test_the_wire_phase_check_reads_merges_and_runs_from_anywhere(
    tmp_path, monkeypatch
):
    """End to end on a scratch repository: a merge commit that re-records a
    row is checked against its first parent, an owner added on the branch
    does not count, and the result does not depend on the working
    directory."""
    vg = _verify_groups()
    git = _git_repo(tmp_path)
    wire = tmp_path / "tests/integration/wire"
    wire.mkdir(parents=True)
    git("init", "-q", "-b", "master")
    (wire / "rows.toml").write_text('[rows."WX1"]\nowners = ["p:2"]\n')
    (wire / "WX1.json").write_text("{}\n")
    git("add", "-A")
    git("commit", "-qm", "base")
    git("checkout", "-qb", "branch")
    (wire / "rows.toml").write_text('[rows."WX1"]\nowners = ["p:2", "p:3"]\n')
    git("commit", "-qam", "make p:3 an owner on the branch")
    git("checkout", "-qb", "side")
    (wire / "WX1.json").write_text('{"x": 1}\n')
    git("commit", "-qam", "side change\n\nWire-Phase: p:2")
    git("checkout", "-q", "branch")
    # The merge re-records the row itself (as a conflict resolution would):
    # its content matches neither parent.
    git("merge", "-q", "--no-ff", "--no-commit", "side")
    (wire / "WX1.json").write_text('{"x": 2}\n')
    git("commit", "-qam", "merge\n\nWire-Phase: p:3")
    monkeypatch.setattr(vg, "_REPO", tmp_path)
    monkeypatch.chdir(tmp_path / "tests")
    problems, skipped = vg.check_wire_phase(("master",))
    assert skipped is None
    # The side commit (p:2) passes; the merge's own re-recording is under
    # p:3, an owner only on the branch.
    assert any("not among its owners" in p and "p:3" in p for p in problems), problems
    assert len(problems) == 1, problems


def test_merging_master_in_does_not_need_master_s_trailers(tmp_path, monkeypatch):
    """master re-records a row under its owner; a branch that merges master
    in took that file unchanged, so the merge needs no trailer for it."""
    vg = _verify_groups()
    git = _git_repo(tmp_path)
    wire = tmp_path / "tests/integration/wire"
    wire.mkdir(parents=True)
    git("init", "-q", "-b", "master")
    (wire / "rows.toml").write_text('[rows."WX1"]\nowners = ["p:1"]\n')
    (wire / "WX1.json").write_text("{}\n")
    git("add", "-A")
    git("commit", "-qm", "base")
    git("checkout", "-qb", "branch")
    (tmp_path / "other.txt").write_text("branch work\n")
    git("add", "-A")
    git("commit", "-qm", "branch work")
    git("checkout", "-q", "master")
    (wire / "WX1.json").write_text('{"x": 1}\n')
    git("commit", "-qam", "re-record\n\nWire-Phase: p:1")
    git("checkout", "-q", "branch")
    git("merge", "-q", "--no-edit", "master")
    monkeypatch.setattr(vg, "_REPO", tmp_path)
    assert vg.check_wire_phase(("master",)) == ([], None)


def test_an_unparsable_registry_at_the_merge_base_is_a_problem(tmp_path, monkeypatch):
    vg = _verify_groups()
    git = _git_repo(tmp_path)
    wire = tmp_path / "tests/integration/wire"
    wire.mkdir(parents=True)
    git("init", "-q", "-b", "master")
    (wire / "rows.toml").write_text("[rows.\n")
    git("add", "-A")
    git("commit", "-qm", "base")
    monkeypatch.setattr(vg, "_REPO", tmp_path)
    problems, _ = vg.check_wire_phase(("master",))
    assert any("does not parse" in p for p in problems), problems


def test_a_callback_nested_under_a_method_is_hoisted_to_follow_it():
    """The race an async method's callback can win: recorded under the
    method or after it, the hoisted recording is the same."""
    a, b = "a" * 32, "b" * 32
    callback = {"path": f"/{b}/callbacks/subscriptions/{a}/x", "children": []}
    other = {"path": f"/{a}/properties/y", "children": []}
    method = {"path": f"/{a}/methods/wire_import", "children": []}
    nested = [{**method, "children": [other, callback]}]
    sibling = [{**method, "children": [other]}, callback]
    hoisted = _wire._hoist_callbacks(nested, ("/methods/",))
    assert hoisted == sibling
    assert _wire._hoist_callbacks(sibling, ("/methods/",)) == sibling


def test_an_async_steps_failing_task_is_recorded_not_raised():
    async def boom() -> None:
        raise ValueError("peer gone")

    async def action() -> str:
        asyncio.get_running_loop().create_task(boom())
        return "returned"

    assert asyncio.run(_wire._run_and_drain(action)) == {
        "result": "returned",
        "task_errors": ["ValueError"],
    }


def test_a_task_that_failed_before_the_action_returned_is_recorded():
    """The action awaits after starting the task, so the task has already
    failed (and left ``all_tasks``) when the drain begins."""

    async def boom() -> None:
        raise ValueError("peer gone")

    async def action() -> str:
        asyncio.get_running_loop().create_task(boom())
        await asyncio.sleep(0.01)
        return "returned"

    assert asyncio.run(_wire._run_and_drain(action)) == {
        "result": "returned",
        "task_errors": ["ValueError"],
    }


def test_the_drain_does_not_depend_on_wait_for_running_it_in_a_task(monkeypatch):
    """Python 3.11's ``asyncio.wait_for`` runs its coroutine in a task of its
    own; a drain run that way finds itself among the pending tasks and
    waits for itself. Here ``wait_for`` is given 3.11's shape: the drain
    must still settle."""
    real_wait_for = asyncio.wait_for

    async def wait_for_311(aw: Any, timeout: float | None) -> Any:
        return await real_wait_for(asyncio.ensure_future(aw), timeout)

    monkeypatch.setattr(asyncio, "wait_for", wait_for_311)
    monkeypatch.setattr(_wire, "_DRAIN_TIMEOUT", 2.0)
    done: list[str] = []

    async def later() -> None:
        await asyncio.sleep(0.01)
        done.append("later")

    async def action() -> str:
        asyncio.get_running_loop().create_task(later())
        return "returned"

    assert asyncio.run(_wire._run_and_drain(action)) == "returned"
    assert done == ["later"]


def test_an_async_step_that_never_settles_times_out(monkeypatch):
    monkeypatch.setattr(_wire, "_DRAIN_TIMEOUT", 0.05)

    async def action() -> None:
        asyncio.get_running_loop().create_task(asyncio.sleep(10))

    with pytest.raises(TimeoutError):
        asyncio.run(_wire._run_and_drain(action))


def test_failures_the_action_handled_are_not_task_errors():
    """A failure the step's code handled is not a task error: gathered with
    ``return_exceptions`` (fanout's deliveries), or awaited and caught."""

    async def boom() -> None:
        raise ValueError("delivery failed")

    async def action() -> str:
        outcomes = await asyncio.gather(boom(), return_exceptions=True)
        task = asyncio.get_running_loop().create_task(boom())
        try:
            await task
        except ValueError:
            pass
        return f"handled {len(outcomes)}"

    assert asyncio.run(_wire._run_and_drain(action)) == "handled 1"


def test_a_timed_out_drain_cancels_what_is_still_running(monkeypatch):
    """When the drain gives up, the tasks it was waiting for are cancelled
    before the error goes up, not left to run into a later step."""
    monkeypatch.setattr(_wire, "_DRAIN_TIMEOUT", 0.05)
    started: list[asyncio.Task[Any]] = []

    async def action() -> None:
        started.append(asyncio.get_running_loop().create_task(asyncio.sleep(10)))

    async def run() -> bool:
        with pytest.raises(TimeoutError):
            await _wire._run_and_drain(action)
        return started[0].cancelled()

    assert asyncio.run(run()) is True


def test_store_leftovers_keep_their_order_whatever_their_ids(monkeypatch):
    """Two leftover diffs and two callback-state entries are ordered by
    content and peer name, not by their random subscription ids."""
    import actingweb.db as db

    def stores(sub_x: str, sub_y: str) -> dict[str, Any]:
        diffs = [
            {
                "subscriptionid": sub_y,
                "sequence": 1,
                "diff": '{"timestamp": "2026-01-01", "y": 1}',
            },
            {
                "subscriptionid": sub_x,
                "sequence": 1,
                "diff": '{"timestamp": "2026-02-02", "x": 1}',
            },
        ]
        # The clock fields run opposite to the content: X was claimed and
        # its diff stored later than Y's, yet X still sorts first.
        bucket = {
            f"state:{'p' * 32}:{sub_y}": {
                "data": {"claimed_at": 1.0, "last": "y", "_received_at": 1.0}
            },
            f"state:{'p' * 32}:{sub_x}": {
                "data": {"claimed_at": 2.0, "last": "x", "_received_at": 2.0}
            },
        }

        class Diffs:
            def fetch(self, actor_id: str) -> list[dict[str, Any]]:
                return diffs

        class Bucket:
            def __init__(self, **_: Any) -> None:
                pass

            def get_bucket(self) -> dict[str, Any]:
                return bucket

        monkeypatch.setattr(db, "get_subscription_diff_list", lambda config: Diffs())
        monkeypatch.setattr(_wire, "Attributes", Bucket)
        actor = types.SimpleNamespace(
            id="a" * 32, host=types.SimpleNamespace(config=None)
        )
        out = _wire._snapshot_stores(actor, {"p" * 32: "B"})  # type: ignore[arg-type]
        named = {sub_x: "X", sub_y: "Y"}
        return {
            "diffs": [named[d["subscriptionid"]] for d in out["diffs"]],
            "callback_state": [
                named[e["subscriptionid"]] for e in out["callback_state"]
            ],
        }

    assert stores("1" * 32, "9" * 32) == stores("9" * 32, "1" * 32)
    assert stores("1" * 32, "9" * 32) == {
        "diffs": ["X", "Y"],
        "callback_state": ["X", "Y"],
    }
