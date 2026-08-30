"""Regression: `docs/standards/**` is machine-read, so it must trigger the tests.

`docs/standards/` is not prose. `branch_protection/gates.toml` is the source
`scripts/setup_branch_protection.py` PUTs rulesets from, and every
`<standard>/standard.yaml` is consumed by the drift guards in
`tests/architecture/`. Tests read these files as DATA.

The CI `core_python` path filter listed `docs/wiki/**` but not
`docs/standards/**`, so a PR touching only a standard ran no pytest lane at
all. Measured on #11784, which changed `gates.toml`: `Scenario Tests` reported
`skipping`, and a stale fixture in
`tests/test_branch_protection_audit.py` plus one scenario broke on staging
instead of on the PR — four tests, none of which CI was asked to run.

Under-inclusive is the dangerous direction for a filter that decides whether
to TEST: the PR goes green because nothing looked, not because nothing broke.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github/workflows/ci.yml"

#: Directories whose contents tests read as data, and which must therefore be
#: inside the filter that decides whether the pytest lanes run at all.
MACHINE_READ_DOC_TREES = ("docs/wiki/**", "docs/standards/**")


def _core_python_filter() -> str:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"^\s+core_python:\n\s+- '(?P<pattern>\{.*\})'", text, re.M)
    assert match, "could not find the core_python path filter in ci.yml"
    return match.group("pattern")


def test_machine_read_doc_trees_are_inside_the_core_python_filter() -> None:
    pattern = _core_python_filter()

    # Anti-vacuity: a pattern that failed to parse would make every `in` below
    # trivially false, and this test would fail loudly rather than pass empty.
    assert pattern.startswith("{") and "src/**/*.py" in pattern, (
        f"core_python filter does not look like the expected brace list: {pattern}"
    )

    missing = [tree for tree in MACHINE_READ_DOC_TREES if tree not in pattern]
    assert not missing, (
        f"{missing} are read by tests as data but are outside the core_python "
        "filter, so a PR touching only them runs NO pytest lane and goes green "
        "because nothing looked. Add them to the filter in ci.yml."
    )
