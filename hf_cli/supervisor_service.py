"""Simple TCP supervisor for hf CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
import signal

from . import supervisor_state
from .config import DEFAULT_SUPERVISOR_PORT, SUPERVISOR_PORT_FILE


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        raw = await reader.readline()
        if not raw:
            return
        request = json.loads(raw.decode())
        action = request.get("action")
        if action == "ping":
            response = {"status": "ok"}
        elif action == "list_repos":
            response = {"status": "ok", "repos": supervisor_state.list_repos()}
        elif action == "add_repo":
            path = request.get("path")
            dashboard_url = request.get("dashboard_url", "http://localhost:5556")
            if not path:
                response = {"status": "error", "error": "Missing path"}
            else:
                supervisor_state.add_repo(path, dashboard_url)
                response = {"status": "ok", "dashboard_url": dashboard_url}
        elif action == "remove_repo":
            path = request.get("path")
            if not path:
                response = {"status": "error", "error": "Missing path"}
            elif supervisor_state.remove_repo(path):
                response = {"status": "ok"}
            else:
                response = {"status": "error", "error": "Repo not found"}
        else:
            response = {"status": "error", "error": "unknown action"}
    except Exception as exc:  # noqa: BLE001
        response = {"status": "error", "error": str(exc)}
    writer.write((json.dumps(response) + "\n").encode())
    await writer.drain()
    writer.close()


async def _serve(port: int) -> None:
    server = await asyncio.start_server(_handle, "127.0.0.1", port)
    SUPERVISOR_PORT_FILE.write_text(str(port))
    async with server:
        await server.serve_forever()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="hf supervisor")
    parser.add_argument("serve", nargs="?", default="serve")
    parser.add_argument("--port", type=int, default=DEFAULT_SUPERVISOR_PORT)
    args = parser.parse_args(argv)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, loop.stop)
    try:
        loop.run_until_complete(_serve(args.port))
    finally:
        loop.close()
        if SUPERVISOR_PORT_FILE.exists():
            SUPERVISOR_PORT_FILE.unlink()


if __name__ == "__main__":
    main()
