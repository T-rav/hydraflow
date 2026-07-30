"""Unit tests for the shared per-tick issue-filing budget (#10767, #10777).

``filing_budget`` is the abstraction extracted from ``wiki_rot_detector_loop``
so every issue-filing loop bounds its per-tick blast radius through one gate
instead of copy-pasting the pattern.
"""

from __future__ import annotations

from filing_budget import (
    FilingBudget,
    file_overflow_summary,
    overflow_digest,
    overflow_line,
)


class _FakeDedup:
    """Minimal DedupStore stand-in: an in-memory ``get``/``set_all`` set."""

    def __init__(self, initial: set[str] | None = None) -> None:
        self._store: set[str] = set(initial or set())

    def get(self) -> set[str]:
        return set(self._store)

    def set_all(self, values: set[str]) -> None:
        self._store = set(values)


class _RecordingFiler:
    """Records every ``create_issue`` call; returns a configurable issue number."""

    def __init__(self, issue_number: int = 101) -> None:
        self.issue_number = issue_number
        self.calls: list[tuple[str, str, list[str]]] = []

    async def create_issue(self, title: str, body: str, labels: list[str]) -> int:
        self.calls.append((title, body, labels))
        return self.issue_number


def test_budget_allows_up_to_cap_then_blocks() -> None:
    budget = FilingBudget(cap=2)
    assert budget.allow()
    budget.note_filed()
    assert budget.allow()
    budget.note_filed()
    assert not budget.allow()
    assert budget.filed == 2


def test_note_overflow_collects_lines() -> None:
    budget = FilingBudget(cap=1)
    budget.note_overflow("- `a`")
    budget.note_overflow("- `b`")
    assert budget.overflow == ["- `a`", "- `b`"]


def test_overflow_line_with_and_without_detail() -> None:
    assert overflow_line("subject") == "- `subject`"
    assert overflow_line("subject", "3x/30d") == "- `subject` — 3x/30d"


def test_overflow_digest_is_stable_and_order_independent() -> None:
    a = overflow_digest(["x", "y", "z"])
    b = overflow_digest(["z", "y", "x"])
    assert a == b
    assert a != overflow_digest(["x", "y"])
    assert len(a) == 12


async def test_summary_no_overflow_files_nothing() -> None:
    filer = _RecordingFiler()
    dedup = _FakeDedup()
    budget = FilingBudget(cap=3)  # nothing overflowed
    filed = await file_overflow_summary(
        create_issue=filer.create_issue,
        dedup=dedup,
        budget=budget,
        key_prefix="demo",
        labels=["hydraflow-find"],
        title="t",
        intro="i",
    )
    assert filed == 0
    assert filer.calls == []


async def test_summary_files_one_issue_listing_every_overflow_line() -> None:
    filer = _RecordingFiler()
    dedup = _FakeDedup()
    budget = FilingBudget(cap=1)
    budget.note_filed()
    for i in range(4):
        budget.note_overflow(overflow_line(f"subj-{i}"))

    filed = await file_overflow_summary(
        create_issue=filer.create_issue,
        dedup=dedup,
        budget=budget,
        key_prefix="demo",
        labels=["hydraflow-find", "wiki-rot"],
        title="Over cap",
        intro="**Automated.**",
    )

    assert filed == 1
    assert len(filer.calls) == 1
    title, body, labels = filer.calls[0]
    assert title == "Over cap"
    assert labels == ["hydraflow-find", "wiki-rot"]
    # Body states the true count and lists each overflowed subject.
    assert "4 finding(s) exceeded the per-tick filing cap of `1`" in body
    for i in range(4):
        assert f"subj-{i}" in body


async def test_summary_is_idempotent_for_an_unchanged_overflow_set() -> None:
    filer = _RecordingFiler()
    dedup = _FakeDedup()

    def _budget() -> FilingBudget:
        b = FilingBudget(cap=1)
        b.note_overflow(overflow_line("subj-a"))
        b.note_overflow(overflow_line("subj-b"))
        return b

    first = await file_overflow_summary(
        create_issue=filer.create_issue,
        dedup=dedup,
        budget=_budget(),
        key_prefix="demo",
        labels=["hydraflow-find"],
        title="t",
        intro="i",
    )
    second = await file_overflow_summary(
        create_issue=filer.create_issue,
        dedup=dedup,
        budget=_budget(),
        key_prefix="demo",
        labels=["hydraflow-find"],
        title="t",
        intro="i",
    )
    assert first == 1
    assert second == 0  # same digest already recorded
    assert len(filer.calls) == 1


async def test_summary_truncates_body_but_reports_full_count() -> None:
    filer = _RecordingFiler()
    dedup = _FakeDedup()
    budget = FilingBudget(cap=1)
    for i in range(60):
        budget.note_overflow(overflow_line(f"s{i:03d}"))

    filed = await file_overflow_summary(
        create_issue=filer.create_issue,
        dedup=dedup,
        budget=budget,
        key_prefix="demo",
        labels=["hydraflow-find"],
        title="t",
        intro="i",
    )

    assert filed == 1
    _, body, _ = filer.calls[0]
    assert "60 finding(s) exceeded" in body
    assert "…and 10 more." in body  # 60 - 50 rendered


async def test_summary_zero_sentinel_leaves_dedup_unrecorded_for_retry() -> None:
    filer = _RecordingFiler(issue_number=0)  # gh failed without raising
    dedup = _FakeDedup()
    budget = FilingBudget(cap=1)
    budget.note_overflow(overflow_line("subj"))

    filed = await file_overflow_summary(
        create_issue=filer.create_issue,
        dedup=dedup,
        budget=budget,
        key_prefix="demo",
        labels=["hydraflow-find"],
        title="t",
        intro="i",
    )

    assert filed == 0
    # Nothing recorded — the summary is retried on the next tick.
    assert dedup.get() == set()
