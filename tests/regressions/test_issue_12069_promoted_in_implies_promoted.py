"""#12069: three rows carried `promoted_in` while still claiming `issue-open`.

`docs/wiki/memory-feedback/README.md` defines `promoted` as "enforcement
landed. `promoted_in` carries the PR / commit SHA." But only
`pending -> issue-open` is automated in `src/memory_backlog_loop.py`; the
terminal transition is manual, so it drifted.

All three rows' PRs had merged and all three issues were closed:

| row | PR | issue |
|---|---|---|
| feedback-check-existing-before-building | #12016 merged | #11947 closed |
| feedback-merge-only-on-author-convergence-report | #12017 merged | #11948 closed |
| feedback-scratchpad-shared-between-sibling-subagents | #12015 merged | #11949 closed |

So the board disagreed with the state machine, silently, on rows whose whole
job is to record whether an enforcement landed.

`load_mirror_entry` now refuses the pair. That is the cheaper of the two fixes
the issue offered — the other, advancing rows whose linked PR merged, needs the
loop to poll GitHub for PR state it does not currently read.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from memory_backlog_mirror import load_mirror_entry  # noqa: E402

_MIRROR = Path(__file__).parents[2] / "docs" / "wiki" / "memory-feedback"

_FRONT = """---
name: probe
description: a probe row
source: test
status: {status}
issue: 1
{promoted}
---

body
"""


def _write(tmp_path: Path, *, status: str, promoted_in: str | None) -> Path:
    path = tmp_path / "probe.md"
    path.write_text(
        _FRONT.format(
            status=status,
            promoted=f"promoted_in: {promoted_in}" if promoted_in else "",
        ),
        encoding="utf-8",
    )
    return path


def test_promoted_in_with_an_earlier_status_is_refused(tmp_path: Path) -> None:
    """The contradiction itself — a row cannot cite evidence it has not reached."""
    path = _write(tmp_path, status="issue-open", promoted_in="12016")

    with pytest.raises(ValueError, match="promoted_in"):
        load_mirror_entry(path)


def test_promoted_in_with_status_promoted_is_accepted(tmp_path: Path) -> None:
    """The valid pairing must still load, or the guard is just a wall."""
    entry = load_mirror_entry(_write(tmp_path, status="promoted", promoted_in="12016"))

    assert entry.status == "promoted"
    assert entry.promoted_in == 12016


def test_a_row_without_promoted_in_is_unaffected(tmp_path: Path) -> None:
    """The overwhelmingly common shape — pending/issue-open rows still load."""
    entry = load_mirror_entry(_write(tmp_path, status="issue-open", promoted_in=None))

    assert entry.status == "issue-open"
    assert entry.promoted_in is None


def test_every_row_on_disk_satisfies_the_invariant() -> None:
    """The three that drifted, and any that drift next, fail here.

    Loading the real mirror rather than a fixture: the defect was in committed
    data, and a guard that only ever sees synthetic rows would not have caught
    it.
    """
    offenders = []
    for path in sorted(_MIRROR.glob("*.md")):
        if path.name == "README.md":
            continue
        try:
            load_mirror_entry(path)
        except ValueError as exc:  # noqa: PERF203
            offenders.append(f"{path.name}: {exc}")

    assert not offenders, "\n".join(offenders)
