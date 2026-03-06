"""Integration tests for hf_cli.update_check using a live HTTP server."""

from __future__ import annotations

import http.server
import json
import socketserver
import threading
from pathlib import Path

import pytest

from hf_cli import update_check


class _PyPIServer:
    def __init__(self, payload: dict[str, object]):
        self._payload = payload
        self._thread: threading.Thread | None = None
        self._server: socketserver.TCPServer | None = None
        self.url: str = ""
        self.requests = 0

    def __enter__(self) -> _PyPIServer:
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                outer.requests += 1
                body = json.dumps(outer._payload).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args, **_kwargs) -> None:  # pragma: no cover
                return

        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        self._server = server
        self._thread = thread
        self.url = f"http://127.0.0.1:{server.server_address[1]}/json"
        return self

    def __exit__(self, *_exc) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)


def _patch_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    cache_path = tmp_path / "update-cache.json"
    monkeypatch.setattr(update_check, "_CACHE_PATH", cache_path)
    return cache_path


def test_check_for_updates_fetches_live_http(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(update_check, "get_app_version", lambda: "1.0.0")
    _patch_cache(monkeypatch, tmp_path)

    payload = {"info": {"version": "9.9.9"}}
    with _PyPIServer(payload) as server:
        monkeypatch.setattr(update_check, "_PYPI_JSON_URL", server.url)
        result = update_check.check_for_updates(timeout_seconds=2.0)

    assert server.requests == 1
    assert result.latest_version == "9.9.9"
    assert result.update_available is True
    assert result.error is None


def test_check_for_updates_cached_reads_disk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(update_check, "get_app_version", lambda: "1.2.3")
    cache_path = _patch_cache(monkeypatch, tmp_path)

    payload = {"info": {"version": "2.0.0"}}
    with _PyPIServer(payload) as server:
        monkeypatch.setattr(update_check, "_PYPI_JSON_URL", server.url)
        fresh = update_check.check_for_updates_cached(
            timeout_seconds=2.0, max_age_seconds=60, path=cache_path
        )
        assert server.requests == 1
        assert fresh.latest_version == "2.0.0"

    def _boom(*_args, **_kwargs):
        raise AssertionError("network should not be called")

    monkeypatch.setattr(update_check, "check_for_updates", _boom)
    cached = update_check.check_for_updates_cached(
        timeout_seconds=2.0, max_age_seconds=60, path=cache_path
    )

    assert cached.latest_version == "2.0.0"
    assert cached.update_available is True
