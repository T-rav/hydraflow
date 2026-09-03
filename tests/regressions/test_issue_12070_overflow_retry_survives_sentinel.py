"""#12070: the 0-sentinel retry was defeated by callers spending the keys first.

`file_overflow_summary` honours `create_issue`'s 0-sentinel (the gh call failed
without raising) by withholding its own digest key, so the summary is retried
next tick. That promise only held if the caller had not already spent its
per-subject keys — and all three callers recorded each over-cap subject in the
`not budget.allow()` branch, BEFORE the summary was attempted.

So on a sentinel: the retry tick found every subject already recorded, skipped
them, collected no overflow, and returned early. The batch was lost entirely,
with no issue anywhere.

The fix moves ownership of the subject keys into `file_overflow_summary`, which
records them with its own key only after a confirmed filing. These tests drive
the real function with a failing `create_issue`, then a succeeding one, and
assert the batch survives the round trip.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from filing_budget import FilingBudget, file_overflow_summary, overflow_line  # noqa: E402


class _Dedup:
    """The minimal `_SupportsDedup` surface, with the writes observable."""

    def __init__(self) -> None:
        self._keys: set[str] = set()

    def get(self) -> set[str]:
        return set(self._keys)

    def set_all(self, keys: set[str]) -> None:
        self._keys = set(keys)


def _budget(subjects: list[str]) -> FilingBudget:
    budget = FilingBudget(cap=0)
    for subject in subjects:
        budget.allow()
        budget.note_overflow(overflow_line(subject, "probe"))
    return budget


async def _file(dedup: _Dedup, budget: FilingBudget, *, returns: int) -> int:
    async def create_issue(title: str, body: str, labels: list[str]) -> int:
        return returns

    return await file_overflow_summary(
        create_issue=create_issue,
        dedup=dedup,
        budget=budget,
        key_prefix="probe",
        labels=["hydraflow-find"],
        title="probe overflow",
        intro="probe",
        subject_keys=["subject-a", "subject-b"],
    )


@pytest.mark.asyncio
async def test_a_sentinel_leaves_every_subject_key_unspent() -> None:
    """The defect: a failed filing must not consume the subjects' keys."""
    dedup = _Dedup()

    filed = await _file(dedup, _budget(["a", "b"]), returns=0)

    assert filed == 0
    assert dedup.get() == set(), (
        "the failed summary recorded keys anyway; the retry tick would skip "
        "every subject, collect no overflow, and lose the batch entirely"
    )


@pytest.mark.asyncio
async def test_the_retry_after_a_sentinel_still_files() -> None:
    """End to end: fail, then succeed, and the batch is not lost."""
    dedup = _Dedup()

    assert await _file(dedup, _budget(["a", "b"]), returns=0) == 0
    assert await _file(dedup, _budget(["a", "b"]), returns=4242) == 1

    recorded = dedup.get()
    assert "subject-a" in recorded and "subject-b" in recorded
    assert any(k.startswith("probe:summary:") for k in recorded)


@pytest.mark.asyncio
async def test_a_confirmed_filing_records_subjects_and_summary_together() -> None:
    """The success path must still stop subjects being re-filed individually."""
    dedup = _Dedup()

    assert await _file(dedup, _budget(["a", "b"]), returns=99) == 1

    assert {"subject-a", "subject-b"} <= dedup.get()


@pytest.mark.asyncio
async def test_no_caller_records_over_cap_subjects_before_the_summary() -> None:
    """The ordering the three callers got wrong, pinned at the source.

    A behavioural test cannot see the caller's ordering — it is in a branch
    that runs before the function under test — so this reads the branch.
    """
    src = Path(__file__).parents[2] / "src"
    for name in (
        "gate_health_loop.py",
        "detector_calibration_loop.py",
        "memory_backlog_loop.py",
    ):
        text = (src / name).read_text(encoding="utf-8")
        branch = text[text.index("if not budget.allow():") :][:400]
        assert "set_all" not in branch, (
            f"{name} records dedup keys inside the over-cap branch, before the "
            f"summary is attempted — the #12070 ordering defect"
        )
        assert "overflow_keys.append" in branch, (
            f"{name} does not collect its over-cap subjects for the summary"
        )
