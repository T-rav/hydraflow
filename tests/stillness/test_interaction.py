"""Unit tests for the loop-interaction map pure computation (#10823)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from stillness.interaction import (
    FileChurn,
    InteractionMap,
    MergeChurn,
    build_interaction_map,
    contested_surfaces,
    logical_coupling,
    render_report,
)

NOW = datetime(2026, 8, 1, tzinfo=UTC)


def _merge(sha: str, days_ago: int, *files: tuple[str, int, int]) -> MergeChurn:
    return MergeChurn(
        sha=sha,
        merged_at=NOW - timedelta(days=days_ago),
        files=tuple(FileChurn(p, a, d) for p, a, d in files),
    )


# --- contested surfaces -----------------------------------------------------


def test_reversal_churn_is_min_of_added_deleted() -> None:
    merges = [
        _merge("a", 5, ("src/hot.py", 100, 0)),  # grown, not contested
        _merge("b", 3, ("src/hot.py", 40, 60)),  # +40 -60
        _merge("c", 1, ("src/hot.py", 0, 30)),  # removed
    ]
    top = contested_surfaces(merges, now=NOW, weeks=8)
    s = next(x for x in top if x.path == "src/hot.py")
    assert s.added == 140 and s.deleted == 90
    assert s.reversal_churn == 90  # min(140, 90) — the added-AND-removed volume
    assert s.merges == 3


def test_contested_ranked_by_reversal_churn() -> None:
    merges = [
        _merge("a", 2, ("src/fought.py", 50, 50), ("src/grown.py", 200, 1)),
    ]
    top = contested_surfaces(merges, now=NOW, weeks=8)
    # grown.py has more raw churn but min(200,1)=1; fought.py min(50,50)=50 ranks first
    assert top[0].path == "src/fought.py"


def test_contested_excludes_regen_artifacts() -> None:
    merges = [
        _merge("a", 2, ("docs/arch/generated/changelog.md", 50, 50)),
        _merge("b", 1, ("src/real.py", 10, 10)),
    ]
    paths = {s.path for s in contested_surfaces(merges, now=NOW, weeks=8)}
    assert "docs/arch/generated/changelog.md" not in paths
    assert "src/real.py" in paths


def test_contested_excludes_lock_files_and_generated_docs() -> None:
    merges = [
        _merge("a", 2, ("src/ui/package-lock.json", 500, 500)),
        _merge("b", 2, ("uv.lock", 300, 300)),
        _merge("c", 2, ("docs/prompt-audit-2026-04-20.md", 400, 400)),
        _merge("d", 1, ("src/real.py", 10, 10)),
    ]
    paths = {s.path for s in contested_surfaces(merges, now=NOW, weeks=8)}
    assert paths == {"src/real.py"}  # only genuine source contention survives


def test_contested_excludes_out_of_window() -> None:
    merges = [_merge("a", 100, ("src/old.py", 50, 50))]
    assert contested_surfaces(merges, now=NOW, weeks=8) == []


# --- logical coupling -------------------------------------------------------


def test_coupling_counts_co_changed_pairs() -> None:
    # x and y change together in 6 merges (>= min_merges=5); z appears once.
    merges = [_merge(f"m{i}", i + 1, ("x.py", 1, 0), ("y.py", 1, 0)) for i in range(6)]
    merges.append(_merge("z", 1, ("x.py", 1, 0), ("z.py", 1, 0)))
    couplings = logical_coupling(merges, now=NOW, weeks=8, min_merges=5)
    assert couplings[0].file_a == "x.py" and couplings[0].file_b == "y.py"
    assert couplings[0].co_changes == 6


def test_coupling_ignores_infrequent_files() -> None:
    # a and b co-change only twice, below min_merges=5 → not counted.
    merges = [_merge(f"m{i}", i + 1, ("a.py", 1, 0), ("b.py", 1, 0)) for i in range(2)]
    assert logical_coupling(merges, now=NOW, weeks=8, min_merges=5) == []


# --- build + render ---------------------------------------------------------


def test_build_and_render_smoke() -> None:
    merges = [
        _merge(f"m{i}", i + 1, ("src/config.py", 20, 20), ("src/models.py", 10, 10))
        for i in range(6)
    ]
    im = build_interaction_map(merges, now=NOW, weeks=8)
    assert isinstance(im, InteractionMap)
    assert im.total_merges == 6
    report = render_report(im)
    assert "# Loop-Interaction Map (#10823)" in report
    assert "Contested surfaces" in report
    assert "Logical coupling" in report


def test_render_handles_empty() -> None:
    im = build_interaction_map([], now=NOW, weeks=8)
    report = render_report(im)
    assert "No merges in window" in report
