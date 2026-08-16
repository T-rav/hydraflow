#!/usr/bin/env python3
"""Class-key fold check — agent-facing I/O shell (#11292).

Thin ``gh`` shell mirroring ``scripts/calibrate_finders.py``: the pure
matching engine lives in ``src/find_class_key.py`` and is never
re-implemented here. ``/hf.issue`` Phase 3 runs this BEFORE filing a
pattern-shaped finding so the fold decision is mechanical (a plain
marker/token match), not an agent's own keyword-search judgment call.

    python scripts/find_class_check.py --check --source branch-parser \\
        --needle "branch-name parser missing agent/auto-agent-<N>" \\
        --title "pr_manager misses agent/auto-agent-<N>"

    python scripts/find_class_check.py --emit-marker --source branch-parser \\
        --needle "branch-name parser missing agent/auto-agent-<N>"

Exit codes for ``--check``:

* ``0`` — an open class issue was found; its number is printed as
  ``FOLD <number>`` on stdout. The caller folds into it (comment + site
  line) instead of filing a new issue.
* ``1`` — no open class issue matches; ``FILE-NEW`` is printed on stdout.
  The caller proceeds to create a new issue, embedding
  ``--emit-marker``'s output in its body.
* ``2`` — the ``gh`` call itself failed (auth, network, rate limit). NEVER
  treated as ``FILE-NEW`` — a transient ``gh`` failure misread as "no
  matches" would file an avoidable duplicate. The caller must retry or
  escalate, not fall back to filing.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from find_class_key import (  # noqa: E402
    DEFAULT_FIND_LABEL,
    compute_class_key,
    match_class,
    render_marker,
)

if TYPE_CHECKING:
    from models import GitHubIssueSummary  # noqa: E402


class GhCommandError(RuntimeError):
    """Raised when the underlying ``gh`` call fails.

    Caught only at the CLI boundary (``main``), where it maps to exit code
    ``2`` — distinct from the ``FILE-NEW`` (exit ``1``) outcome so a caller
    can never confuse "gh failed" with "no fold target".
    """


def _resolve_repo(explicit: str | None) -> str:
    if explicit:
        return explicit
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GhCommandError(
            f"could not resolve repo: git remote get-url origin failed: {result.stderr.strip()}"
        )
    url = result.stdout.strip()
    slug = url.removeprefix("https://github.com/").removesuffix(".git")
    slug = slug.split("git@github.com:")[-1]
    if "/" not in slug:
        raise GhCommandError(f"could not parse owner/repo from remote url: {url!r}")
    return slug


def list_open_issues(repo: str, label: str) -> list[GitHubIssueSummary]:
    """Return open issues carrying *label* as ``{number, title, body}`` dicts.

    Raises :class:`GhCommandError` on any ``gh`` failure — NEVER returns an
    empty list on failure, since an empty list is indistinguishable from
    "genuinely no open issues" and would silently let a caller file a
    duplicate.
    """
    result = subprocess.run(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            repo,
            "--label",
            label,
            "--state",
            "open",
            "--json",
            "number,title,body",
            "--limit",
            "100",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GhCommandError(f"gh issue list failed: {result.stderr.strip()}")
    try:
        return json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise GhCommandError(f"gh issue list returned invalid JSON: {exc}") from exc


def run_check(
    *, source: str, needle: str, title: str, repo: str, label: str
) -> tuple[int, str]:
    """Return ``(exit_code, message)`` for the ``--check`` outcome."""
    class_key = compute_class_key(source, needle)
    open_issues = list_open_issues(repo, label)
    target = match_class(class_key, needle, title, open_issues)
    if target:
        return 0, f"FOLD {target}"
    return 1, "FILE-NEW"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Class-key fold check for pattern-shaped find-issues (#11292)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="check whether an open class issue already covers --source/--needle",
    )
    parser.add_argument(
        "--emit-marker",
        action="store_true",
        help="print the body marker line for --source/--needle and exit",
    )
    parser.add_argument("--source", default=None, help="finder/tool identity")
    parser.add_argument("--needle", default=None, help="the pattern/defect needle")
    parser.add_argument(
        "--title", default=None, help="candidate issue title (required for --check)"
    )
    parser.add_argument("--repo", default=None, help="owner/repo (default: origin)")
    parser.add_argument("--label", default=DEFAULT_FIND_LABEL)
    args = parser.parse_args(argv)

    if not args.check and not args.emit_marker:
        parser.error("one of --check or --emit-marker is required")
    if args.check and args.emit_marker:
        parser.error("--check and --emit-marker are mutually exclusive")
    if not args.source or not args.needle:
        parser.error("--source and --needle are required")

    if args.emit_marker:
        class_key = compute_class_key(args.source, args.needle)
        print(render_marker(class_key))
        return 0

    if not args.title:
        parser.error("--title is required with --check")

    try:
        repo = _resolve_repo(args.repo)
        exit_code, message = run_check(
            source=args.source,
            needle=args.needle,
            title=args.title,
            repo=repo,
            label=args.label,
        )
    except GhCommandError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(message)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
