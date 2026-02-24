"""Client helpers for talking to the hf supervisor."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

from .config import DEFAULT_SUPERVISOR_PORT, SUPERVISOR_PORT_FILE


def _read_port() -> int:
    if SUPERVISOR_PORT_FILE.is_file():
        try:
            return int(SUPERVISOR_PORT_FILE.read_text().strip())
        except ValueError:
            pass
    return DEFAULT_SUPERVISOR_PORT


def _send(request: dict[str, Any]) -> dict[str, Any]:
    port = _read_port()
    with socket.create_connection(("127.0.0.1", port), timeout=1) as sock:
        sock.sendall((json.dumps(request) + "\n").encode())
        data = sock.recv(65535).decode()
    return json.loads(data)


def ping() -> bool:
    try:
        resp = _send({"action": "ping"})
        return resp.get("status") == "ok"
    except OSError:
        return False


def list_repos() -> list[dict[str, Any]]:
    resp = _send({"action": "list_repos"})
    if resp.get("status") == "ok":
        return list(resp.get("repos", []))
    raise RuntimeError(resp.get("error", "unknown error"))


def add_repo(path: Path, dashboard_url: str) -> str:
    resp = _send(
        {
            "action": "add_repo",
            "path": str(path.resolve()),
            "dashboard_url": dashboard_url,
        }
    )
    if resp.get("status") != "ok":
        raise RuntimeError(resp.get("error", "unknown error"))
    return resp.get("dashboard_url", dashboard_url)
