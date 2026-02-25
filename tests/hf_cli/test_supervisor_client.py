from __future__ import annotations

import json

import pytest

from hf_cli import supervisor_client


def test_read_port_uses_default_when_file_missing(tmp_path, monkeypatch) -> None:
    missing_file = tmp_path / "missing-port-file"
    monkeypatch.setenv("HF_SUPERVISOR_PORT_FILE", str(missing_file))

    assert supervisor_client._read_port() == supervisor_client.DEFAULT_SUPERVISOR_PORT


def test_read_port_falls_back_to_default_on_invalid_file(tmp_path, monkeypatch) -> None:
    port_file = tmp_path / "port-file"
    port_file.write_text("not-a-port")
    monkeypatch.setenv("HF_SUPERVISOR_PORT_FILE", str(port_file))

    assert supervisor_client._read_port() == supervisor_client.DEFAULT_SUPERVISOR_PORT


def test_ping_returns_false_when_connection_fails(monkeypatch) -> None:
    def _raise(_request):
        raise RuntimeError("boom")

    monkeypatch.setattr(supervisor_client, "_send", _raise)
    assert supervisor_client.ping() is False


def test_list_repos_raises_runtime_error_on_error_response(monkeypatch) -> None:
    monkeypatch.setattr(
        supervisor_client, "_send", lambda _request: {"status": "error", "error": "x"}
    )

    with pytest.raises(RuntimeError, match="x"):
        supervisor_client.list_repos()


def test_send_parses_newline_delimited_json(monkeypatch) -> None:
    class _FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def sendall(self, payload: bytes) -> None:
            request = json.loads(payload.decode().strip())
            assert request["action"] == "ping"

        def recv(self, _size: int) -> bytes:
            return b'{"status":"ok"}\n'

    monkeypatch.setattr(supervisor_client, "_read_port", lambda: 1234)
    monkeypatch.setattr(
        supervisor_client.socket, "create_connection", lambda *_a, **_k: _FakeSocket()
    )

    assert supervisor_client._send({"action": "ping"}) == {"status": "ok"}
