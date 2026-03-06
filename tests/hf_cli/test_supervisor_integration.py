"""TCP integration tests for the hf supervisor service and client."""

from __future__ import annotations

import asyncio
import contextlib
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from hf_cli import config as cli_config
from hf_cli import supervisor_client, supervisor_service, supervisor_state


@dataclass
class _SupervisorServerHandle:
    loop: asyncio.AbstractEventLoop
    thread: threading.Thread
    task: asyncio.Task[None]

    def stop(self) -> None:
        if not self.task.done():
            self.loop.call_soon_threadsafe(self.task.cancel)
        self.thread.join(timeout=5)


def _wait_for_port(port_hint: int, port_file: Path, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    discovered_port: int | None = None
    while time.time() < deadline:
        if port_file.exists():
            with contextlib.suppress(ValueError):
                discovered_port = int(port_file.read_text().strip())
        target = discovered_port or (port_hint if port_hint > 0 else None)
        if target:
            with (
                contextlib.suppress(OSError),
                socket.create_connection(("127.0.0.1", target), timeout=0.1),
            ):
                return
        time.sleep(0.05)
    raise RuntimeError("supervisor server did not start")


def _start_supervisor_server(port: int) -> _SupervisorServerHandle:
    loop = asyncio.new_event_loop()
    started = threading.Event()
    task_ref: dict[str, asyncio.Task[None]] = {}

    def _runner() -> None:
        asyncio.set_event_loop(loop)
        task = loop.create_task(supervisor_service._serve(port))
        task_ref["task"] = task
        started.set()
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    if not started.wait(timeout=5):
        raise RuntimeError("failed to boot supervisor server thread")
    return _SupervisorServerHandle(loop=loop, thread=thread, task=task_ref["task"])


@pytest.fixture
def supervisor_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state_dir = tmp_path / "hf-home"
    state_dir.mkdir()
    port_file = state_dir / "supervisor-port"
    state_file = state_dir / "supervisor-state.json"
    monkeypatch.setattr(supervisor_service, "STATE_DIR", state_dir)
    monkeypatch.setattr(supervisor_service, "SUPERVISOR_PORT_FILE", port_file)
    monkeypatch.setattr(supervisor_client, "SUPERVISOR_PORT_FILE", port_file)
    monkeypatch.setattr(cli_config, "STATE_DIR", state_dir)
    monkeypatch.setattr(cli_config, "SUPERVISOR_PORT_FILE", port_file)
    monkeypatch.setattr(cli_config, "SUPERVISOR_STATE_FILE", state_file)
    monkeypatch.setattr(supervisor_state, "SUPERVISOR_STATE_FILE", state_file)
    monkeypatch.setenv("HF_SUPERVISOR_PORT_FILE", str(port_file))
    supervisor_service.RUNNERS.clear()

    server: _SupervisorServerHandle | None = None
    chosen_port: int | None = None
    last_error: Exception | None = None
    for _ in range(5):
        port_candidate = supervisor_service._find_free_port()
        handle = _start_supervisor_server(port_candidate)
        try:
            _wait_for_port(port_candidate, port_file)
        except RuntimeError as exc:
            last_error = exc
            handle.stop()
        else:
            server = handle
            chosen_port = port_candidate
            break

    if server is None or chosen_port is None:
        raise RuntimeError("Failed to start supervisor server") from last_error

    monkeypatch.setattr(supervisor_service, "DEFAULT_SUPERVISOR_PORT", chosen_port)
    monkeypatch.setattr(supervisor_client, "DEFAULT_SUPERVISOR_PORT", chosen_port)

    yield server

    server.stop()
    supervisor_service.RUNNERS.clear()


def test_supervisor_client_round_trip(
    supervisor_runtime: _SupervisorServerHandle, tmp_path: Path
) -> None:
    repo_path = tmp_path / "demo-repo"
    repo_path.mkdir()

    assert supervisor_client.ping() is True

    registration = supervisor_client.register_repo(repo_path, repo_slug="demo")
    assert registration["status"] == "ok"
    assert registration["slug"] == "demo"

    repos = supervisor_client.list_repos()
    assert repos and repos[0]["slug"] == "demo"

    supervisor_client.remove_repo(slug="demo")
    assert supervisor_client.list_repos() == []
