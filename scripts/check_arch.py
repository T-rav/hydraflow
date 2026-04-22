#!/usr/bin/env python3
"""Pluggable architecture checker.

Locates `.hydraflow/arch_rules.py` in the target repo, spawns a subprocess
that loads and validates it, and prints a human-readable report.

Exit codes:
  0 — pass or skipped (no rules configured)
  1 — one or more violations
  2 — rule module error (bad syntax, missing fields, subprocess crash)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "repo", nargs="?", default=".", help="path to repo (default: cwd)"
    )
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()

    # Ensure the spawned subprocess can import `arch` from src/.
    env = dict(os.environ)
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    src_dir = repo_root / "src"
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{existing}" if existing else str(src_dir)

    proc = subprocess.run(
        [sys.executable, "-m", "arch.subprocess_entry", str(repo)],
        capture_output=True,
        text=True,
        timeout=args.timeout,
        env=env,
        check=False,
    )

    sys.stderr.write(proc.stderr)

    if proc.returncode == 2:
        return 2
    if proc.returncode == 0:
        if "SKIPPED" not in proc.stderr:
            print("OK: no architecture violations")
        else:
            print("SKIPPED: no .hydraflow/arch_rules.py")
        return 0

    violations = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    print(f"Architecture violations ({len(violations)}):")
    for v in violations:
        print(f"  [{v['rule']}] {v['source']} → {v['target']}  {v['detail']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
