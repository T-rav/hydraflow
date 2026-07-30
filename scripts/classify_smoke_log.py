#!/usr/bin/env python3
"""CLI seam for the post-merge-smoke infra-flake classifier (#10776).

The ``post-merge-smoke`` job in ``.github/workflows/ci.yml`` cannot itself
contain the classification logic — the ADR-0050 auto-agent tool contract
forbids the factory from editing ``.github/workflows/`` (recursion guard). So
the reusable classifier lives in ``src/smoke_infra_flake.py`` and this thin
CLI is what the workflow shells out to.

It reads a build/smoke log, decides the disposition, and emits it as both
JSON (stdout) and GitHub Actions ``name=value`` output pairs (to ``--out`` /
``$GITHUB_OUTPUT``) so the workflow can branch with ``steps.<id>.outputs.*``:

    action        one of retry | file_targeted | file_generic
    signature_id  the matched signature id (empty for file_generic)
    dependency    the specific flaky dependency/step (empty for file_generic)
    issue_title   targeted-issue title  (only for file_targeted)
    issue_body    targeted-issue body   (only for file_targeted)

Exit code is always 0 on a successful classification — the *action* is the
signal, not the exit status.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from smoke_infra_flake import decide_smoke_disposition  # noqa: E402


def _read_log(path: str | None) -> str:
    if path in (None, "", "-"):
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8", errors="replace")


def _emit_github_output(out_path: str, values: dict[str, str]) -> None:
    """Append ``name=value`` pairs to a GitHub Actions output file.

    Multi-line values (the issue body) use the heredoc form GitHub Actions
    requires; single-line values use the plain ``name=value`` form.
    """
    lines: list[str] = []
    for key, value in values.items():
        if "\n" in value:
            delim = f"__EOF_{key.upper()}__"
            lines.append(f"{key}<<{delim}")
            lines.append(value)
            lines.append(delim)
        else:
            lines.append(f"{key}={value}")
    with Path(out_path).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log",
        default="-",
        help="Path to the build/smoke log (default: '-' reads stdin).",
    )
    parser.add_argument(
        "--prior-attempts",
        type=int,
        default=int(os.environ.get("SMOKE_PRIOR_ATTEMPTS", "0") or "0"),
        help="Times this push already failed (e.g. github.run_attempt - 1).",
    )
    parser.add_argument("--ref-name", default=os.environ.get("GITHUB_REF_NAME", ""))
    parser.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--run-url", default=os.environ.get("SMOKE_RUN_URL", ""))
    parser.add_argument(
        "--out",
        default=os.environ.get("GITHUB_OUTPUT", ""),
        help="GitHub Actions output file to append name=value pairs to.",
    )
    args = parser.parse_args(argv)

    disposition = decide_smoke_disposition(
        _read_log(args.log),
        ref_name=args.ref_name,
        sha=args.sha,
        run_url=args.run_url,
        prior_attempts=args.prior_attempts,
    )

    payload = asdict(disposition)
    print(json.dumps(payload, indent=2))

    if args.out:
        _emit_github_output(
            args.out,
            {
                key: ("" if value is None else str(value))
                for key, value in payload.items()
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
