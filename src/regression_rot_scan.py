"""Pure scan/classify engine for regression-test rot (#9597).

Detects two decay patterns in ``tests/regressions/*.py`` contract files:

- **false-close rot** — the linked GitHub issue is CLOSED but its regression
  pin is still ``xfail`` RED, meaning the close likely happened before the
  fix actually landed (or the fix regressed after close).
- **orphaned-RED** — the linked issue is still OPEN and the regression pin
  has been RED for more than a configurable number of days with no fix
  landing, meaning the written-but-unimplemented contract is rotting.

This module does no I/O beyond reading the files handed to it — no
``pytest``, no ``git``, no GitHub. RED-ness is inferred *statically* from the
``xfail(..., reason="... fix not yet landed")`` marker convention used by
``scripts/triage_regressions.py``; running pytest over ~200 files every tick
would be slow, flaky, and ``xfail(strict=False)`` masks the exit code anyway.

An explicit ``# hydraflow-regression-rot: blocked-on #<N>`` annotation (placed
anywhere in the file, e.g. as a comment near the marker) exempts a file from
both classifications — the "legitimately held back pending another issue"
case.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from issue_state import issue_state_is_resolved

# Matches `test_issue_9836`, `regression_issue_6709`, and multi-number slugs
# like `test_issue_9419_9421_adr_drift` (first run of digit groups only).
_ISSUE_NUMBERS_RE = re.compile(r"^(?:test|regression)_issue_((?:\d+_)*\d+)")

# `@pytest.mark.xfail(reason="... fix not yet landed", ...)` — DOTALL so a
# marker split across lines (common when the reason string is long) is still
# matched; non-greedy so it doesn't reach past the marker into unrelated text.
_HELD_BACK_RE = re.compile(r"xfail\(.*?fix not yet landed", re.DOTALL)

# `# hydraflow-regression-rot: blocked-on #9080` (case-insensitive, `#`
# optional so `blocked-on 9080` also matches).
_BLOCKED_RE = re.compile(
    r"hydraflow-regression-rot:\s*blocked-on\s*#?(\d+)", re.IGNORECASE
)

_SKIP_NAMES = {"__init__.py"}

RegressionRotKind = Literal["false_close", "orphaned_red"]


def parse_issue_numbers(stem: str) -> list[int]:
    """Extract issue number(s) from a regression-test filename stem.

    ``test_issue_9836`` -> ``[9836]``; ``test_issue_9419_9421_adr_drift`` ->
    ``[9419, 9421]``; ``regression_issue_6709`` -> ``[6709]``; anything not
    matching the ``{test,regression}_issue_<N>`` convention -> ``[]`` (e.g.
    descriptively-named files, which are deliberately not covered — see
    docs/wiki/testing.md).
    """
    match = _ISSUE_NUMBERS_RE.match(stem)
    if not match:
        return []
    return [int(n) for n in match.group(1).split("_")]


@dataclass(frozen=True)
class RegressionRotFile:
    """One scanned ``tests/regressions/*.py`` file."""

    path: Path
    issue_numbers: tuple[int, ...]
    is_xfail_red: bool
    blocked_on: int | None


@dataclass(frozen=True)
class RegressionRotFinding:
    """One classified rot finding for a single GitHub issue."""

    issue_number: int
    kind: RegressionRotKind
    paths: tuple[str, ...]


def scan_regression_dir(regressions_dir: Path) -> list[RegressionRotFile]:
    """Scan *regressions_dir* for regression-test contract files.

    Returns ``[]`` when the directory does not exist (most unit-test repos
    and MockWorld scenarios have no ``tests/regressions/`` tree — that is
    not an error, just nothing to scan).
    """
    if not regressions_dir.is_dir():
        return []

    files: list[RegressionRotFile] = []
    for path in sorted(regressions_dir.glob("*.py")):
        if path.name in _SKIP_NAMES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        issue_numbers = tuple(parse_issue_numbers(path.stem))
        blocked_match = _BLOCKED_RE.search(text)
        blocked_on = int(blocked_match.group(1)) if blocked_match else None
        files.append(
            RegressionRotFile(
                path=path,
                issue_numbers=issue_numbers,
                is_xfail_red=bool(_HELD_BACK_RE.search(text)),
                blocked_on=blocked_on,
            )
        )
    return files


def classify_regression_rot(
    files: list[RegressionRotFile],
    issue_states: dict[int, str],
    ages_days: dict[int, int],
    *,
    stale_days: int,
) -> list[RegressionRotFinding]:
    """Classify RED regression files against resolved issue states.

    An orphan candidate is a file that is ``is_xfail_red`` and carries no
    blocked-on exemption. Files sharing an issue number are grouped into one
    finding per issue (a single issue can be guarded by more than one
    regression file).

    - Issue state resolved per :func:`issue_state.issue_state_is_resolved`
      (``COMPLETED`` / ``NOT_PLANNED``) -> ``"false_close"`` (fires
      immediately — a closed issue with a still-RED pin is a contradiction
      regardless of how long it's been that way).
    - Issue state ``"OPEN"`` and ``ages_days[issue] > stale_days`` ->
      ``"orphaned_red"``. Fresh (not-yet-stale) OPEN issues yield nothing.
    - Any other state (``"UNKNOWN"``, missing) yields nothing — a transient
      lookup failure must never manufacture a false alarm.
    """
    candidates_by_issue: dict[int, list[RegressionRotFile]] = {}
    for file in files:
        if not file.is_xfail_red or file.blocked_on is not None:
            continue
        for number in file.issue_numbers:
            candidates_by_issue.setdefault(number, []).append(file)

    findings: list[RegressionRotFinding] = []
    for number in sorted(candidates_by_issue):
        state = issue_states.get(number, "UNKNOWN")
        kind: RegressionRotKind | None = None
        if issue_state_is_resolved(state):
            kind = "false_close"
        elif state == "OPEN" and ages_days.get(number, 0) > stale_days:
            kind = "orphaned_red"
        if kind is None:
            continue
        paths = tuple(sorted(str(f.path) for f in candidates_by_issue[number]))
        findings.append(
            RegressionRotFinding(issue_number=number, kind=kind, paths=paths)
        )
    return findings


def build_rollup_body(findings: list[RegressionRotFinding]) -> str:
    """Render the single rollup issue body for the given findings.

    Grouped into the two classifications so a reviewer can tell at a glance
    whether a close needs reverting (false-close) or a fix still needs
    writing (orphaned-RED). Deterministic ordering (sorted by issue number)
    so the content hash only changes when the finding set actually changes.
    """
    false_close = sorted(
        (f for f in findings if f.kind == "false_close"), key=lambda f: f.issue_number
    )
    orphaned = sorted(
        (f for f in findings if f.kind == "orphaned_red"),
        key=lambda f: f.issue_number,
    )

    lines = [
        "Regression tests in `tests/regressions/` whose `xfail` RED pin no "
        "longer matches their linked issue's state (#9597). One rolling "
        "issue for both classifications — no per-finding spam.",
        "",
        "## False-close rot — issue closed, pin still RED",
        "",
    ]
    if false_close:
        lines += [f"- #{f.issue_number}: `{', '.join(f.paths)}`" for f in false_close]
    else:
        lines.append("None currently.")

    lines += [
        "",
        "## Orphaned-RED — issue open, pin RED past the stale threshold",
        "",
    ]
    if orphaned:
        lines += [f"- #{f.issue_number}: `{', '.join(f.paths)}`" for f in orphaned]
    else:
        lines.append("None currently.")

    lines += [
        "",
        "*Filed by StaleIssueLoop's regression-rot check. Reopen the issue "
        "(false-close) or implement the fix / add a "
        "`# hydraflow-regression-rot: blocked-on #N` annotation "
        "(orphaned-RED) to clear an entry.*",
    ]
    return "\n".join(lines)
