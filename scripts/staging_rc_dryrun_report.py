"""Aggregate staging RC dry-run shard summaries → a hydraflow-find issue body.

Issue #10352 (G2). The RC-required sandbox suite is *advisory* on ``staging``
and only *required* at the ``rc/* → main`` promotion (ADR-0042). A scenario that
breaks on staging therefore stays invisible until the next RC cut — multi-day
feedback dead time that was the root cause of the RC jam. The staging RC
dry-run (``.github/workflows/staging-rc-dryrun.yml``) runs that exact suite
against staging HEAD on a cadence, reusing the sharded ``run-all`` (#10308) so
it finishes in ~one shard's wall-clock. This reporter turns the per-shard run
summaries into a single hydraflow-find issue naming the broken scenario(s) plus
the staging HEAD SHA, so the break surfaces within one dry-run cycle instead of
at promotion.

Pure sensor: it never blocks a PR. It only aggregates results and emits a
report for the workflow to file as an issue.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable
from pathlib import Path


def collect_failures(summary_paths: Iterable[Path]) -> list[str]:
    """Union of failing scenario names across every shard summary file.

    Each file is the payload written by ``sandbox_scenario run-all
    --summary-json`` (see ``_summary_payload``). Missing/malformed files are
    skipped: a shard that died before writing its summary shows up as a red job
    in the Actions tab, and we still report whatever the surviving shards
    captured rather than crashing the reporter.
    """
    failures: set[str] = set()
    for path in summary_paths:
        try:
            payload = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for name in payload.get("failed", []):
            if isinstance(name, str):
                failures.add(name)
    return sorted(failures)


def format_find_issue(failures: list[str], sha: str, run_url: str) -> tuple[str, str]:
    """Render the ``(title, body)`` for the hydraflow-find issue.

    ``failures`` empty is a caller error — an issue is only filed when there are
    failures — but we still render a sane body so a stray call can't produce a
    misleading empty report.
    """
    short_sha = sha[:12] if sha else "unknown"
    scenario_list = "\n".join(f"- `{name}`" for name in failures) or "- (none captured)"
    title = (
        f"Staging RC dry-run: {len(failures)} RC-gate scenario(s) broken at {short_sha}"
    )
    body = (
        "The staging RC dry-run sensor (#10352) ran the RC-required sandbox "
        "suite against **staging HEAD** and found scenario(s) that would fail "
        "the `rc/* → main` promotion gate. These checks are **advisory on "
        "staging** (ADR-0042), so they do not block staging PRs — this issue "
        "surfaces the break now instead of at the next RC cut.\n\n"
        f"**Staging HEAD:** `{sha or 'unknown'}`\n"
        f"**Dry-run:** {run_url or '(local run)'}\n\n"
        f"**Broken RC-gate scenario(s) ({len(failures)}):**\n{scenario_list}\n\n"
        "Bisecting to the exact offending commit is a documented follow-up; for "
        "now, inspect the merges into staging since the last green dry-run "
        "together with the named scenario(s) above."
    )
    return title, body


def _write_github_output(outputs: dict[str, str], path: str | None) -> None:
    """Append ``key=value`` pairs to ``$GITHUB_OUTPUT`` (heredoc for multiline).

    Falls back to stdout when no path is given (local runs / tests).
    """
    if not path:
        for key, value in outputs.items():
            print(f"{key}={value!r}")
        return
    lines: list[str] = []
    for key, value in outputs.items():
        if "\n" in value:
            delim = f"__GH_EOF_{key}__"
            lines.extend([f"{key}<<{delim}", value, delim])
        else:
            lines.append(f"{key}={value}")
    with Path(path).open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="staging_rc_dryrun_report",
        description=(
            "Aggregate staging RC dry-run shard summaries and emit a "
            "hydraflow-find issue body naming any broken RC-gate scenario(s)."
        ),
    )
    parser.add_argument(
        "--results-dir",
        required=True,
        help="Directory holding the downloaded per-shard summary JSON files.",
    )
    parser.add_argument(
        "--sha", default="", help="Staging HEAD SHA the dry-run tested."
    )
    parser.add_argument(
        "--run-url", default="", help="URL of the dry-run workflow run."
    )
    parser.add_argument(
        "--github-output",
        default=os.environ.get("GITHUB_OUTPUT"),
        help="Path to $GITHUB_OUTPUT (defaults to the env var).",
    )
    args = parser.parse_args(argv)

    summary_paths = sorted(Path(args.results_dir).rglob("summary*.json"))
    failures = collect_failures(summary_paths)

    if not failures:
        print(
            f"Staging RC dry-run: all RC-gate scenarios passed "
            f"({len(summary_paths)} shard summaries scanned)."
        )
        _write_github_output({"has_failures": "false"}, args.github_output)
        return 0

    title, body = format_find_issue(failures, args.sha, args.run_url)
    print(
        f"Staging RC dry-run: {len(failures)} broken RC-gate scenario(s): "
        f"{', '.join(failures)}"
    )
    _write_github_output(
        {"has_failures": "true", "title": title, "body": body},
        args.github_output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
