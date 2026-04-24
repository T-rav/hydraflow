"""Temporal annotator — turns created_at + corroboration counts into
short stability tags the planner/reviewer can read alongside the entry
body. Pure function, no I/O, no LLM calls."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from repo_wiki import WikiEntry, annotate_entries_with_temporal_tags


def _entry(
    *,
    title: str,
    created_at: datetime,
    corroborations: int = 1,
) -> WikiEntry:
    return WikiEntry(
        title=title,
        content="body",
        source_type="review",
        created_at=created_at.isoformat(),
        corroborations=corroborations,
    )


def test_recently_created_entry_is_tagged_recent() -> None:
    now = datetime.now(UTC)
    young = _entry(title="x", created_at=now - timedelta(days=3))

    [(entry, tag)] = annotate_entries_with_temporal_tags([young], now=now)

    assert entry.title == "x"
    assert tag == "recently added"


def test_months_old_entry_is_tagged_stable_for_n_months() -> None:
    now = datetime.now(UTC)
    old = _entry(title="y", created_at=now - timedelta(days=200))

    [(_e, tag)] = annotate_entries_with_temporal_tags([old], now=now)

    assert tag == "stable for 6 months"


def test_year_old_entry_is_tagged_stable_for_one_year() -> None:
    now = datetime.now(UTC)
    ancient = _entry(title="z", created_at=now - timedelta(days=400))

    [(_e, tag)] = annotate_entries_with_temporal_tags([ancient], now=now)

    assert tag == "stable for 1 year"


def test_multi_year_old_entry_uses_years_plural() -> None:
    now = datetime.now(UTC)
    ancient = _entry(title="z", created_at=now - timedelta(days=800))

    [(_e, tag)] = annotate_entries_with_temporal_tags([ancient], now=now)

    assert tag == "stable for 2 years"


def test_high_corroboration_is_reflected_in_tag() -> None:
    """Entries with many corroborations get a (+N) suffix so the reader
    can see how independently-re-discovered the claim is at a glance."""
    now = datetime.now(UTC)
    e = _entry(title="q", created_at=now - timedelta(days=200), corroborations=12)

    [(_e, tag)] = annotate_entries_with_temporal_tags([e], now=now)

    assert tag == "stable for 6 months (+12)"


def test_single_corroboration_does_not_add_suffix() -> None:
    """(+1) would be noise on every entry — skip the suffix until >=2."""
    now = datetime.now(UTC)
    e = _entry(title="q", created_at=now - timedelta(days=200), corroborations=1)

    [(_e, tag)] = annotate_entries_with_temporal_tags([e], now=now)

    assert tag == "stable for 6 months"


def test_empty_input_returns_empty_list() -> None:
    now = datetime.now(UTC)

    assert annotate_entries_with_temporal_tags([], now=now) == []


def test_malformed_created_at_tags_as_age_unknown() -> None:
    """Never crash on bad timestamps — entry passes through with a
    placeholder tag."""
    e = WikiEntry(
        title="w",
        content="body",
        source_type="review",
        created_at="not a date",
    )

    [(_e, tag)] = annotate_entries_with_temporal_tags([e], now=datetime.now(UTC))

    assert tag == "age unknown"
