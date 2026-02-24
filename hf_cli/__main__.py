"""Entry point module for the `hf` console script."""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from cli import main as hydraflow_main

from .init_cmd import run_init
from .supervisor_client import add_repo, list_repos, remove_repo
from .supervisor_manager import ensure_running

_FLAG_COMMANDS = {
    "prep": "--prep",
    "scaffold": "--scaffold",
    "audit": "--audit",
    "clean": "--clean",
    "dry-run": "--dry-run",
}


def _dispatch_flag_command(flag: str, rest: Iterable[str]) -> None:
    hydraflow_main([flag, *rest])


def _handle_run(rest: Iterable[str]) -> None:
    ensure_running()
    repo_path = Path.cwd()
    info = add_repo(repo_path)
    url = info.get("dashboard_url")
    print(f"Registered repo {repo_path} with hf supervisor")
    if url:
        print(f"Dashboard: {url}")
    if info.get("log_file"):
        print(f"Logs: {info['log_file']}")


def _handle_view() -> None:
    repos = list_repos()
    if not repos:
        print("No repos registered. Run `hf run` inside a repo first.")
        return
    print("Registered repos:")
    for repo in repos:
        path = repo.get("path")
        url = repo.get("dashboard_url")
        port = repo.get("port")
        slug = repo.get("slug")
        log_file = repo.get("log_file")
        line = f"- {path}"
        if slug:
            line += f" [{slug}]"
        if port:
            line += f" port={port}"
        if url:
            line += f" -> {url}"
        print(line)
        if log_file:
            print(f"    logs: {log_file}")


def _handle_stop() -> None:
    repo_path = Path.cwd()
    try:
        remove_repo(repo_path)
        print(f"Removed repo {repo_path} from hf supervisor")
    except RuntimeError as exc:
        print(f"{exc}")


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

    command_map = {
        "view": _handle_view,
        "status": _handle_view,
        "stop": _handle_stop,
        "run": lambda: _handle_run(rest),
        "start": lambda: hydraflow_main(rest),
    }
    if cmd in command_map:
        command_map[cmd]()
        return

    if cmd in _FLAG_COMMANDS:
        _dispatch_flag_command(_FLAG_COMMANDS[cmd], rest)
        return

    hydraflow_main(args)


if __name__ == "__main__":
    entrypoint(sys.argv[1:])
