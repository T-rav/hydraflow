"""#11969 — 20 mirrors were pinned to issues that were never theirs.

A sandbox/scenario run of `MemoryBacklogLoop` whose FakeGitHub numbers issues
from a low counter wrote `issue: 25` … `issue: 44` into the REAL repo's
mirrors (#11972 is the containment defect that let it reach a live checkout).
Those numbers resolve to unrelated closed issues and dependabot PRs.

The consequence is silent and permanent: a mirror pinned to a stranger sits at
`status: issue-open` forever, so `pending_entries` never yields it and the
3-strikes escalation never fires. Twenty memory-feedback rules were invisible
to the backlog with nothing red anywhere.

This pins the SHAPE that made them undetectable offline, not the twenty
numbers: a pinned mirror must carry a plausible issue reference, and `null`
when it carries none. Checking that a pin resolves to a real memory-backlog
issue needs the network and belongs to the loop, not to a unit test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_MIRRORS = Path(__file__).resolve().parents[2] / "docs" / "wiki" / "memory-feedback"

#: The memory-feedback system was built long after this repo passed issue #1000,
#: so any pin below it predates the system that would have written it and is
#: therefore evidence of a fake board rather than a real filing. Deliberately
#: far below the real range (#9000+) so an honest low-numbered filing could
#: never trip it — this is a smoke alarm, not a ratchet.
_IMPOSSIBLE_BELOW = 1000


def _front(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, f"{path.name} has no frontmatter"
    return yaml.safe_load(match.group(1)) or {}


def _mirrors() -> list[Path]:
    """Every mirror entry — by SHAPE, not by excluding README by name.

    The directory also holds prose (`README.md`). A mirror is a file whose
    frontmatter declares a `source`, which is what `load_mirror_entry` reads;
    filtering on that keeps this list the same set the loop walks, so a new
    prose file added tomorrow does not fail the guard and a new mirror cannot
    slip past it.
    """
    return [
        path
        for path in sorted(_MIRRORS.glob("*.md"))
        if "source" in (_front_or_none(path) or {})
    ]


def _front_or_none(path: Path) -> dict | None:
    match = re.match(r"^---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.S)
    return yaml.safe_load(match.group(1)) if match else None


def test_the_sweep_finds_the_mirrors() -> None:
    """A guard over an empty directory passes silently and reads as coverage."""
    assert len(_mirrors()) > 20


@pytest.mark.parametrize("path", _mirrors(), ids=lambda p: p.stem)
def test_no_mirror_is_pinned_to_an_issue_that_predates_the_system(
    path: Path,
) -> None:
    issue = _front(path).get("issue")

    assert issue is None or int(issue) >= _IMPOSSIBLE_BELOW, (
        f"{path.name} is pinned to #{issue}, which predates the memory-feedback "
        "system — the signature of a fake board writing into a real checkout "
        "(#11969/#11972). It will sit at issue-open forever and never re-file."
    )


@pytest.mark.parametrize("path", _mirrors(), ids=lambda p: p.stem)
def test_a_pinned_status_and_a_pinned_number_agree(path: Path) -> None:
    """The two halves of one claim, which drifted apart silently.

    `status: issue-open` with `issue: null` is a mirror that says it is being
    worked and cannot say where; `issue: <n>` while still `pending` is one the
    loop will file a second time.
    """
    front = _front(path)
    status, issue = front.get("status"), front.get("issue")

    if status == "issue-open":
        assert issue is not None, f"{path.name}: issue-open with no issue number"
    if status == "pending":
        assert issue is None, f"{path.name}: pending but already pinned to #{issue}"
