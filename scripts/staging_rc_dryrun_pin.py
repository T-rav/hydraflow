"""Assert a staging RC dry-run shard is standing on the SHA the report names.

Issue #11518. The dry-run sensor (#10352) resolves ``staging`` HEAD once in the
``resolve`` job and every shard runs against that one SHA, so the aggregated
hydraflow-find issue can name a single exact commit. The original wiring got
that by checking out ``ref: ${{ needs.resolve.outputs.sha }}`` in each shard —
which CodeQL reports as ``actions/cache-poisoning/poisonable-step`` (alert
#108): a job output is opaque to the analysis, so a privileged, cache-writing
job appears to be checking out attacker-influenced code.

The shard now checks out the literal protected branch (``staging``) and calls
this script to *prove* the checkout landed on the resolved SHA before any
cache-writing or code-executing step runs:

* match     → ``matched=true``; the shard proceeds.
* mismatch  → ``matched=false`` + a ``::notice``; every later step is skipped
  and a **skip marker** is written where the shard summary would have gone, so
  the reporter still sees a well-formed (zero-failure) summary for the shard.
  Staging advancing mid-run is a benign race — the next 6-hourly tick re-runs.
* unusable input (no resolved SHA, or HEAD cannot be resolved) → ``matched=
  false`` and a **non-zero exit**: that is a wiring bug, not a race, and it
  should be loud.

Living here rather than as inline YAML bash is deliberate: the comparison is
the safety property of the whole workflow, and YAML bash can only be shape-
tested. ``tests/test_staging_rc_dryrun_pin.py`` executes every branch below.

Standard library only, and runnable as a bare file path — the shard invokes it
before ``actions/setup-python`` has run, using the runner's system ``python3``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Recorded in the skip marker so a reader knows *why* the shard produced no
#: scenario results. Kept short — it also titles the ``::notice``.
SKIP_REASON = "staging-advanced"


@dataclass(frozen=True)
class PinVerdict:
    """Outcome of comparing the checked-out HEAD against the resolved SHA."""

    matched: bool
    expected: str
    actual: str


def verify_pin(expected: str, actual: str) -> PinVerdict:
    """Compare a resolved SHA against the checked-out HEAD.

    Whitespace- and case-insensitive (``$GITHUB_OUTPUT`` round-trips add
    neither, but a hand-dispatched value might), and *exact* — an abbreviated
    SHA is not a match, because a prefix can name a different commit. A blank
    on either side never matches: two empty strings are equal, and treating
    that as a pass would wave the shard through when ``resolve`` broke.
    """
    left = expected.strip().lower()
    right = actual.strip().lower()
    matched = bool(left) and bool(right) and left == right
    return PinVerdict(matched=matched, expected=expected.strip(), actual=right)


def resolve_head_sha() -> str:
    """``git rev-parse HEAD`` in the current directory, or ``""`` if it fails."""
    try:
        # Fixed argv, no shell, no untrusted input: reads the local checkout.
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def skip_marker_payload(shard: str, expected: str, actual: str) -> dict:
    """A zero-result stand-in for the summary the skipped shard never wrote.

    Shape-compatible with ``sandbox_scenario._summary_payload`` so the
    reporter's ``collect_failures`` reads it as "this shard broke nothing"
    rather than choking on an absent artifact, plus a ``skipped`` block that
    records the race for whoever reads the artifact later.
    """
    return {
        "shard": shard or None,
        "scenarios": [],
        "failed": [],
        "skipped": {
            "reason": SKIP_REASON,
            "expected_sha": expected,
            "actual_sha": actual,
        },
    }


def _write_github_output(outputs: dict[str, str], path: str | None) -> None:
    """Append ``key=value`` lines to ``$GITHUB_OUTPUT`` (stdout when unset)."""
    lines = [f"{key}={value}" for key, value in outputs.items()]
    if not path:
        for line in lines:
            print(line)
        return
    with Path(path).open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="staging_rc_dryrun_pin",
        description=(
            "Assert the checked-out HEAD is the staging SHA the dry-run "
            "resolved, and emit the matched=true|false gate output."
        ),
    )
    parser.add_argument(
        "--expected-sha",
        required=True,
        help="SHA the resolve job named (needs.resolve.outputs.sha).",
    )
    parser.add_argument(
        "--actual-sha",
        default="",
        help="Checked-out HEAD (defaults to `git rev-parse HEAD`).",
    )
    parser.add_argument(
        "--shard", default="", help="Shard label, e.g. 3/6, for the skip marker."
    )
    parser.add_argument(
        "--skip-summary-json",
        default="",
        help="Where to write the skip marker when the shard is skipped.",
    )
    parser.add_argument(
        "--github-output",
        default=os.environ.get("GITHUB_OUTPUT"),
        help="Path to $GITHUB_OUTPUT (defaults to the env var).",
    )
    args = parser.parse_args(argv)

    actual = args.actual_sha.strip() or resolve_head_sha()
    verdict = verify_pin(args.expected_sha, actual)

    _write_github_output(
        {"matched": "true" if verdict.matched else "false"}, args.github_output
    )

    if verdict.matched:
        print(f"Shard pinned to resolved staging HEAD {verdict.actual}.")
        return 0

    if not verdict.expected or not verdict.actual:
        # Not the benign race: either `resolve` handed us nothing, or the
        # checkout produced no HEAD. Fail loudly rather than skip silently.
        print(
            "::error title=staging-rc-dryrun pin::cannot verify shard SHA "
            f"(resolved={verdict.expected or '<empty>'}, "
            f"head={verdict.actual or '<empty>'})"
        )
        return 2

    print(
        f"::notice title={SKIP_REASON}::staging advanced during the dry-run "
        f"(resolved {verdict.expected[:12]}, checked out {verdict.actual[:12]}); "
        "skipping this shard — the next scheduled tick re-runs it."
    )
    if args.skip_summary_json:
        marker = Path(args.skip_summary_json)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps(
                skip_marker_payload(args.shard, verdict.expected, verdict.actual),
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
