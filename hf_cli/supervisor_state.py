"""Persistent supervisor state management."""

from __future__ import annotations

import json
from typing import Any

from .config import SUPERVISOR_STATE_FILE


def _load_state() -> dict[str, Any]:
    if SUPERVISOR_STATE_FILE.is_file():
        try:
            return json.loads(SUPERVISOR_STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"repos": []}


def _save_state(state: dict[str, Any]) -> None:
    SUPERVISOR_STATE_FILE.write_text(json.dumps(state, indent=2))


def list_repos() -> list[dict[str, Any]]:
    return list(_load_state().get("repos", []))


def add_repo(path: str, dashboard_url: str) -> None:
    state = _load_state()
    repos = state.setdefault("repos", [])
    for repo in repos:
        if repo.get("path") == path:
            repo["dashboard_url"] = dashboard_url
            _save_state(state)
            return
    repos.append({"path": path, "dashboard_url": dashboard_url})
    _save_state(state)
