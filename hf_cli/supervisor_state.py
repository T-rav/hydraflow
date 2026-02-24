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


def upsert_repo(path: str, slug: str, port: int, log_file: str) -> None:
    state = _load_state()
    repos = state.setdefault("repos", [])
    dashboard_url = f"http://localhost:{port}"
    for repo in repos:
        if repo.get("path") == path:
            repo.update(
                {
                    "slug": slug,
                    "port": port,
                    "dashboard_url": dashboard_url,
                    "log_file": log_file,
                }
            )
            _save_state(state)
            return
    repos.append(
        {
            "path": path,
            "slug": slug,
            "port": port,
            "dashboard_url": dashboard_url,
            "log_file": log_file,
        }
    )
    _save_state(state)


def remove_repo(path: str) -> bool:
    state = _load_state()
    repos = state.setdefault("repos", [])
    for idx, repo in enumerate(repos):
        if repo.get("path") == path:
            repos.pop(idx)
            _save_state(state)
            return True
    return False
