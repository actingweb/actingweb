"""The demo's README first-run sequence, on a store of its own.

``examples/demo/README.md`` ("Local QA account") gives the sequence for
every fresh deployment: start (the tables are created and the start stops
with ``UniqueCreatorNotReady``), ``actingweb-unique-creators enable
--apply``, start again. Every other demo test stubs the readiness check, so
nothing ran the sequence as written (release validation, 2026-11-18).

Each step is its own process, as an operator runs it: the DynamoDB models
bind their table names at import, so one process cannot play a fresh store
beside the suite's.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import warnings
from pathlib import Path

import pytest
import requests

REPO = Path(__file__).resolve().parent.parent.parent
DEMO = REPO / "examples" / "demo"

DROP = """
import sys
from pynamodb.connection import Connection
connection = Connection(region=sys.argv[2], host=sys.argv[3])
names, start = [], None
while True:
    page = connection.list_tables(exclusive_start_table_name=start)
    names.extend(page.get("TableNames", []))
    start = page.get("LastEvaluatedTableName")
    if not start:
        break
for name in names:
    if name.startswith(sys.argv[1]):
        connection.delete_table(name)
"""


def _stop(server: subprocess.Popen[bytes]) -> None:
    """Stop the development server and its reloader child (one process
    group), killing it if it does not exit."""
    try:
        os.killpg(server.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        server.wait(timeout=20)
    except subprocess.TimeoutExpired:
        os.killpg(server.pid, signal.SIGKILL)
        server.wait(timeout=20)


@pytest.mark.usefixtures("docker_services")
def test_readme_first_run_sequence() -> None:
    prefix = f"demofirst_{uuid.uuid4().hex[:8]}"
    host = os.environ.get("AWS_DB_HOST", "http://localhost:8001")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://localhost:{port}"
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("PG_", "DATABASE_")) and k not in ("NUKE_SECRET",)
    }
    env.update(
        {
            "DATABASE_BACKEND": "dynamodb",
            "AWS_DB_HOST": host,
            "AWS_DB_PREFIX": prefix,
            "AWS_ACCESS_KEY_ID": "local",
            "AWS_SECRET_ACCESS_KEY": "local",
            "AWS_DEFAULT_REGION": "us-east-1",
            "PORT": str(port),
            "APP_HOST_FQDN": f"localhost:{port}",
            "APP_HOST_PROTOCOL": "http://",
            "DEMO_QA_BASIC_AUTH": "true",
            "ENABLE_DEVTEST": "false",
        }
    )

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *args],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    try:
        first = run(str(DEMO / "application.py"))
        assert first.returncode != 0, "the first start served; it must stop"
        assert "UniqueCreatorNotReady" in first.stderr, first.stderr[-2000:]
        assert "actingweb-unique-creators enable --apply" in first.stderr

        enable = run("-m", "actingweb.maintenance.unique_creators", "enable", "--apply")
        assert enable.returncode == 0, enable.stderr[-2000:]

        # The second start serves (QA mode runs as the development server
        # only, so it is started as the README starts it).
        # stderr goes to a file: a pipe nobody reads fills and stalls the
        # server. Its own process group, so the reloader child stops with it.
        log = tempfile.TemporaryFile()
        server = subprocess.Popen(
            [sys.executable, str(DEMO / "application.py")],
            cwd=REPO,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=log,
            start_new_session=True,
        )

        def server_log() -> str:
            log.seek(0)
            return log.read().decode(errors="replace")[-2000:]

        try:
            deadline = time.monotonic() + 60
            while True:
                assert server.poll() is None, server_log()
                try:
                    if requests.get(f"{url}/health", timeout=2).status_code == 200:
                        break
                except requests.exceptions.ConnectionError:
                    pass
                assert time.monotonic() < deadline, "the second start did not serve"
                time.sleep(0.5)
            created = requests.post(
                f"{url}/", json={"creator": "qa@example.test"}, timeout=30
            )
            assert created.status_code == 201, created.text
            record = created.json()
            auth = (record["creator"], record["passphrase"])
            assert requests.get(f"{url}/{record['id']}/meta", timeout=30).ok
            page = requests.get(f"{url}/{record['id']}/www", auth=auth, timeout=30)
            assert page.status_code == 200, page.text[:500]
            gone = requests.delete(f"{url}/{record['id']}", auth=auth, timeout=30)
            assert gone.status_code == 204
        finally:
            _stop(server)
            log.close()
    finally:
        dropped = run("-c", DROP, prefix, "us-east-1", host)
        if dropped.returncode != 0:
            message = f"the {prefix} tables were not dropped: {dropped.stderr[-2000:]}"
            if sys.exc_info()[1] is None:
                pytest.fail(message)
            # The test already failed: say so without hiding why.
            warnings.warn(message, stacklevel=1)
