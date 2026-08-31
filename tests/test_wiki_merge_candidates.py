"""Unit tests for the compaction pre-check (#11898).

Measured on the live wiki: ``patterns`` holds 162 active entries with ZERO
duplicate titles and ZERO near-duplicate bodies — 3878 entries are already
superseded, a ~24x compaction that already happened. Asking a model to
synthesize a set with nothing to merge produced platitudes for eleven days
(552 anchor-gate drops, ``entries_compiled: 0`` on all 27 runs). The prompt
even lists the exact titles it kept emitting as DROP examples.

So the question the loop should ask BEFORE spending a spawn is local and
cheap: is there anything here for synthesis to do?
"""

from __future__ import annotations

import pytest

from wiki_merge_candidates import has_compaction_work, near_duplicate_pairs


def _e(title: str, body: str) -> str:
    """Only the body matters — the predicate takes plain strings by design."""
    del title
    return body


def test_identical_bodies_are_a_merge_candidate() -> None:
    entries = [
        _e("A", "Route git reads through `WorkspacePort` so the fake can answer."),
        _e("B", "Route git reads through `WorkspacePort` so the fake can answer."),
    ]
    assert near_duplicate_pairs(entries, threshold=0.8)


def test_cosmetically_different_bodies_are_still_a_candidate() -> None:
    entries = [
        _e("A", "Route git reads through `WorkspacePort` so the fake can answer."),
        _e("B", "Route  git   reads through `WorkspacePort`, so the fake can answer!"),
    ]
    assert near_duplicate_pairs(entries, threshold=0.8)


def test_distinct_entries_are_not_candidates() -> None:
    entries = [
        _e("A", "Route git reads through `WorkspacePort` so the fake can answer."),
        _e("B", "`StagingPromotionLoop` cuts an rc branch every `rc_cadence_hours`."),
        _e("C", "ADR-0042 makes `staging` the default base for every new PR."),
    ]
    assert near_duplicate_pairs(entries, threshold=0.8) == []


def test_a_compacted_topic_has_no_work() -> None:
    """The measured shape: distinct, anchored, nothing to do."""
    entries = [
        _e("A", "Route git reads through `WorkspacePort` (`src/ports.py`)."),
        _e("B", "`StagingPromotionLoop` cuts rc every `rc_cadence_hours`."),
        _e("C", "ADR-0042 makes `staging` the default base for new PRs."),
    ]
    assert has_compaction_work(entries, threshold=0.8) is False


def test_a_duplicate_pair_is_work() -> None:
    entries = [
        _e("A", "Route git reads through `WorkspacePort` (`src/ports.py`)."),
        _e("B", "Route git reads through `WorkspacePort` (`src/ports.py`)."),
        _e("C", "ADR-0042 makes `staging` the default base for new PRs."),
    ]
    assert has_compaction_work(entries, threshold=0.8) is True


def test_an_anchorless_entry_alone_is_not_work() -> None:
    """Platitude removal is Phase 1's job, done deterministically without a model.

    ``repo_wiki.flag_generic_entries_stale`` scores every active entry with the
    SAME ``has_repo_anchor`` heuristic and flips the failures to stale before
    the compile phase runs. Counting an anchor-less entry as work here would
    buy a synthesis spawn to repeat a pure function — and on the live wiki it
    would have kept this gate returning True for four of five topics, which is
    a gate that cannot fire.
    """
    entries = [
        _e("A", "Route git reads through `WorkspacePort` (`src/ports.py`)."),
        _e("B", "Prefer small functions that each do one job."),
    ]
    assert has_compaction_work(entries, threshold=0.8) is False


def test_fewer_than_two_entries_is_never_work() -> None:
    assert has_compaction_work([], threshold=0.8) is False
    assert (
        has_compaction_work(
            [_e("A", "Route git reads through `WorkspacePort` (`src/ports.py`).")],
            threshold=0.8,
        )
        is False
    )


def test_threshold_of_zero_treats_everything_as_work() -> None:
    """The documented escape hatch: 0 restores the pre-#11898 behaviour."""
    entries = [
        _e("A", "Route git reads through `WorkspacePort` (`src/ports.py`)."),
        _e("B", "ADR-0042 makes `staging` the default base for new PRs."),
    ]
    assert has_compaction_work(entries, threshold=0.0) is True


def test_pairs_are_reported_with_their_score_for_the_log() -> None:
    entries = [
        _e("A", "Route git reads through `WorkspacePort` so the fake can answer."),
        _e("B", "Route git reads through `WorkspacePort` so the fake can answer."),
    ]
    pairs = near_duplicate_pairs(entries, threshold=0.8)
    assert len(pairs) == 1
    i, j, score = pairs[0]
    assert (i, j) == (0, 1)
    assert score >= 0.8


def test_empty_bodies_do_not_all_match_each_other() -> None:
    """An empty sketch must not read as 'identical to every other empty one'."""
    entries = [_e("A", ""), _e("B", ""), _e("C", "")]
    assert near_duplicate_pairs(entries, threshold=0.8) == []


@pytest.mark.parametrize("count", [50, 200])
def test_scales_to_a_real_topic_without_quadratic_blowup(count: int) -> None:
    """gotchas holds 391 active entries; this must stay cheap enough to run
    on every tick before deciding to spend a spawn."""
    import time

    entries = [
        _e(f"Entry {i}", f"`src/mod_{i}.py:Thing{i}` does the {i}th distinct thing.")
        for i in range(count)
    ]
    start = time.monotonic()
    assert near_duplicate_pairs(entries, threshold=0.8) == []
    assert time.monotonic() - start < 2.0
