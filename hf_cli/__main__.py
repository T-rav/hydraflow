"""Entry point module for the `hf` console script."""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from cli import main as hydraflow_main

from .init_cmd import run_init
from .supervisor_client import add_repo, list_repos
from .supervisor_manager import ensure_running

_FLAG_COMMANDS = {
    "prep": "--prep",
    "scaffold": "--scaffold",
    "audit": "--audit",
    "clean": "--clean",
    "dry-run": "--dry-run",
}

_DASHBOARD_URL = "http://localhost:5556"


def _dispatch_flag_command(flag: str, rest: Iterable[str]) -> None:
    hydraflow_main([flag, *rest])


def _handle_run(rest: Iterable[str]) -> None:
    ensure_running()
    repo_path = Path.cwd()
    url = add_repo(repo_path, _DASHBOARD_URL)
    print(f"Registered repo {repo_path} with hf supervisor")
    print(f"Dashboard: {url}")


def _handle_view() -> None:
    repos = list_repos()
    if not repos:
        print("No repos registered. Run `hf run` inside a repo first.")
        return
    print("Registered repos:")
    for repo in repos:
        print(f"- {repo['path']} -> {repo.get('dashboard_url', _DASHBOARD_URL)}")


def entrypoint(argv: Sequence[str] | None = None) -> None:
    args = list(argv) if argv is not None else []
    if not args:
        hydraflow_main(None)
        return

    cmd, rest = args[0], args[1:]
    if cmd in ("-h", "--help"):
        hydraflow_main([cmd, *rest])
        return

    if cmd == "init":
        raise SystemExit(run_init(rest))

    if cmd == "view":
        _handle_view()
        return

    if cmd == "run":
        _handle_run(rest)
        return

    if cmd in _FLAG_COMMANDS:
        _dispatch_flag_command(_FLAG_COMMANDS[cmd], rest)
        return

    if cmd == "start":
        hydraflow_main(rest)
        return

    hydraflow_main(args)


if __name__ == "__main__":
    entrypoint(sys.argv[1:])
