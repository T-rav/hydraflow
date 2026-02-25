from __future__ import annotations

from pathlib import Path

import pytest

from hf_cli import supervisor_service


def test_slug_for_repo_replaces_spaces() -> None:
    assert supervisor_service._slug_for_repo(Path("/tmp/my repo")) == "my-repo"


def test_start_repo_raises_for_missing_path() -> None:
    with pytest.raises(FileNotFoundError, match="Repo path not found"):
        supervisor_service._start_repo("/definitely/missing/path")


def test_build_repo_status_payload_marks_running(monkeypatch) -> None:
    monkeypatch.setattr(
        supervisor_service.supervisor_state,
        "list_repos",
        lambda: [
            {"slug": "running-repo", "path": "/tmp/r"},
            {"slug": "stopped-repo", "path": "/tmp/s"},
        ],
    )
    monkeypatch.setattr(
        supervisor_service, "_is_repo_running", lambda slug: slug == "running-repo"
    )

    payload = supervisor_service._build_repo_status_payload()

    assert payload == [
        {"slug": "running-repo", "path": "/tmp/r", "running": True},
        {"slug": "stopped-repo", "path": "/tmp/s", "running": False},
    ]


@pytest.mark.asyncio
async def test_handle_returns_missing_path_error_for_add_repo() -> None:
    class _Reader:
        async def readline(self):
            return b'{"action":"add_repo"}\n'

    class _Writer:
        def __init__(self):
            self.buffer = b""

        def write(self, data: bytes) -> None:
            self.buffer += data

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

    writer = _Writer()
    await supervisor_service._handle(_Reader(), writer)

    assert b'"status": "error"' in writer.buffer
    assert b'"Missing path"' in writer.buffer
