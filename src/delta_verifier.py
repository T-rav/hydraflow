"""Delta verification — compare planned file changes against actual git diff."""

from __future__ import annotations

import logging
import re

from models import DeltaReport

logger = logging.getLogger("hydraflow.delta_verifier")

# Task-type markers signalling that zero relevant code diff is an expected,
# valid terminal state — e.g. landing an already-reviewed PR, verifying a
# precondition, or closing out administrative work. These tasks legitimately
# produce no changes to their planned files, so leftover unrelated branch
# residue must not be flagged as scope creep (issue #10271). Values are
# compared in a hyphen-normalised, lowercase form.
LANDING_ONLY_TASK_TYPES: frozenset[str] = frozenset(
    {
        "landing-only",
        "landing",
        "verification-only",
        "verification",
        "verify-only",
        "no-op",
        "noop",
        "no-code-change",
        "no-change",
    }
)


def parse_task_type(plan_text: str) -> str | None:
    """Extract the declared task type from a plan, if any.

    Recognises either a ``## Task Type`` section (its first non-empty body line
    is the value) or an inline ``TASK_TYPE: <value>`` marker. Returns the
    lowercased value, or ``None`` when no task-type marker is present.
    """
    section_match = re.search(
        r"## Task Type\s*\n(.*?)(?=\n## |\Z)",
        plan_text,
        re.DOTALL | re.IGNORECASE,
    )
    if section_match:
        for line in section_match.group(1).splitlines():
            value = line.strip().lstrip("-").strip().strip("`").strip()
            if value:
                return value.lower()

    inline_match = re.search(r"TASK_TYPE\s*:\s*(.+)", plan_text, re.IGNORECASE)
    if inline_match:
        value = inline_match.group(1).strip().strip("`").strip()
        if value:
            return value.lower()

    return None


def is_landing_only_plan(plan_text: str) -> bool:
    """Return True if the plan declares a landing-only / verification-only task.

    Such tasks legitimately expect zero relevant code diff as their terminal
    state, so scope-check must not flag pre-existing/unrelated branch residue
    as scope creep (issue #10271).
    """
    task_type = parse_task_type(plan_text)
    if task_type is None:
        return False
    normalised = task_type.replace("_", "-").replace(" ", "-")
    return normalised in LANDING_ONLY_TASK_TYPES


def parse_file_delta(plan_text: str) -> list[str]:
    """Extract file paths from the ``## File Delta`` section of a plan.

    Recognises lines starting with ``MODIFIED:``, ``ADDED:``, or ``REMOVED:``.
    Returns a sorted, deduplicated list of file paths.
    """
    section_match = re.search(
        r"## File Delta\s*\n(.*?)(?=\n## |\Z)",
        plan_text,
        re.DOTALL | re.IGNORECASE,
    )
    if not section_match:
        return []

    body = section_match.group(1)
    paths: set[str] = set()
    for line in body.splitlines():
        stripped = line.strip()
        match = re.match(
            r"(?:MODIFIED|ADDED|REMOVED)\s*:\s*(.+)", stripped, re.IGNORECASE
        )
        if match:
            path = match.group(1).strip().strip("`")
            if path:
                paths.add(path)
    return sorted(paths)


def verify_delta(planned_files: list[str], actual_files: list[str]) -> DeltaReport:
    """Compare planned file paths against actual changed files.

    *planned_files* comes from :func:`parse_file_delta`.
    *actual_files* comes from ``git diff --name-only`` against the base branch.

    Returns a :class:`DeltaReport` with planned, actual, missing, and unexpected.
    """
    planned_set = set(planned_files)
    actual_set = set(actual_files)

    missing = sorted(planned_set - actual_set)
    unexpected = sorted(actual_set - planned_set)

    report = DeltaReport(
        planned=sorted(planned_set),
        actual=sorted(actual_set),
        missing=missing,
        unexpected=unexpected,
    )

    if report.has_drift:
        logger.warning(
            "Delta drift detected: %d missing, %d unexpected",
            len(missing),
            len(unexpected),
        )
    else:
        logger.info(
            "Delta verification passed: %d planned == %d actual",
            len(planned_set),
            len(actual_set),
        )

    return report
