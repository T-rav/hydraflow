"""Index ``(workflow_file, job_key)`` pairs defined under ``jobs:`` in workflows."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_JOBS_LINE = re.compile(r"^jobs:\s*(#.*)?$")
_KEY_LINE = re.compile(r"^( +)([A-Za-z0-9_.-]+):\s*(#.*)?$")


def _jobs_from_yaml(text: str) -> set[str] | None:
    """Job keys via a real YAML parse, or None if the file will not parse."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    jobs = data.get("jobs", {})
    return set(jobs) if isinstance(jobs, dict) else set()


def _jobs_from_scan(text: str) -> set[str]:
    """Fallback: job keys are the first-indent-level keys under ``jobs:``.

    Resilient to inline ``run:`` scripts that PyYAML's stricter parser rejects
    but GitHub Actions accepts.
    """
    keys: set[str] = set()
    in_jobs = False
    jobs_indent: int | None = None
    for line in text.splitlines():
        if _JOBS_LINE.match(line):
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if line.strip() and not line[0].isspace():
            break  # dedented back to column 0: end of the jobs: block
        m = _KEY_LINE.match(line)
        if not m:
            continue
        indent = len(m.group(1))
        if jobs_indent is None:
            jobs_indent = indent
        if indent == jobs_indent:
            keys.add(m.group(2))
    return keys


def index_workflow_jobs(workflows_dir: Path) -> set[tuple[str, str]]:
    """Every ``(filename, job_key)`` defined under ``jobs:`` across workflows.

    Scans both ``*.yml`` and ``*.yaml`` so a gate whose producer uses the
    ``.yaml`` extension is not a silent false-negative for the gate activator.

    Matching the job KEY (not the expanded check-run name) is deliberate: it is
    robust to matrix ``name:`` interpolation, and it still catches the failure
    mode where a producing workflow file is deleted (the stale ``ADR gate``).
    """
    index: set[tuple[str, str]] = set()
    workflows = sorted(
        wf
        for pattern in ("*.yml", "*.yaml")
        for wf in Path(workflows_dir).glob(pattern)
    )
    for wf in workflows:
        text = wf.read_text()
        keys = _jobs_from_yaml(text)
        if keys is None:
            keys = _jobs_from_scan(text)
        for job_key in keys:
            index.add((wf.name, job_key))
    return index
