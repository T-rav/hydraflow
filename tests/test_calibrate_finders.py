"""Tests for the finder-calibration runner I/O shell (#10826).

Covers the ``WorktreeFinderRunner`` materialize→detect→count path with an
injected worktree factory + fake detector (no real git), the unsupported /
detection-failure skip contracts (never a fabricated 0), the read-only ledger
population, and a REAL deterministic-detection integration case for wiki_rot
and wiki_rot against tiny fixture trees.

The shell shares no basename with a src module, but is still loaded via
``importlib`` (like ``tests/mutation/test_shell_integration.py``) so it works
regardless of whether ``scripts`` is on ``sys.path``.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from finder_calibration import (  # noqa: E402
    CalibrationLedger,
    GoldenBaseline,
    calibration_ledger_path,
    collect_samples,
)
from finder_faceplate import BaselineLedger, baseline_ledger_path  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
_SHELL_PATH = REPO / "scripts" / "calibrate_finders.py"
_NOW = datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC)


def _load_shell():
    spec = importlib.util.spec_from_file_location(
        "calibrate_finders_shell", _SHELL_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


shell = _load_shell()


def _fake_factory(worktree: Path, *, calls: list[str] | None = None):
    """A worktree factory that yields *worktree* without touching git."""

    @contextmanager
    def factory(repo_root: Path, sha: str) -> Iterator[Path]:
        if calls is not None:
            calls.append(sha)
        yield worktree

    return factory


def _baseline(sha: str = "cafebabe") -> GoldenBaseline:
    return GoldenBaseline(
        sha=sha,
        vetted_at=_NOW,
        vetted_by="operator-supplied",
        signal_class="wiki-rot",
    )


# -- runner: materialize → detect → count --------------------------------------


def test_runner_materializes_once_and_counts_per_sample(tmp_path: Path) -> None:
    detected: list[Path] = []
    factory_calls: list[str] = []

    def detector(worktree: Path) -> int:
        detected.append(worktree)
        return 3

    wt = tmp_path / "wt"
    runner = shell.WorktreeFinderRunner(
        tmp_path,
        {"wiki_rot": detector},
        worktree_factory=_fake_factory(wt, calls=factory_calls),
    )
    with runner:
        samples = collect_samples(runner, "wiki_rot", _baseline(), runs=2, ran_at=_NOW)

    assert [s.flagged_count for s in samples] == [3, 3]
    # Detection ran against the materialized worktree, twice…
    assert detected == [wt, wt]
    # …but the checkout was materialized only ONCE and reused across samples.
    assert factory_calls == ["cafebabe"]


def test_runner_raises_for_unsupported_finder(tmp_path: Path) -> None:
    runner = shell.WorktreeFinderRunner(
        tmp_path, {}, worktree_factory=_fake_factory(tmp_path)
    )
    with runner, pytest.raises(shell.UnsupportedFinderError):
        runner.run_against_baseline("erosion_metrics", _baseline())


# -- calibrate_finders: ledger population + skip contracts ---------------------


def test_calibrate_finders_populates_both_ledgers(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    detectors = {"wiki_rot": lambda _wt: 2, "edge_proposer": lambda _wt: 0}
    runner = shell.WorktreeFinderRunner(
        tmp_path, detectors, worktree_factory=_fake_factory(tmp_path)
    )
    with runner:
        calibrated, skipped = shell.calibrate_finders(
            runner=runner,
            finder_ids=["wiki_rot", "edge_proposer", "erosion_metrics"],
            baseline_sha="cafe1234",
            samples=3,
            data_root=data_root,
            vetted_by="operator-supplied",
            vetted_at=_NOW,
            note="fixture",
            now=_NOW,
        )

    assert set(calibrated) == {"wiki_rot", "edge_proposer"}
    # The LLM finder is skipped with a reason, NOT recorded as a fabricated 0.
    assert [fid for fid, _reason in skipped] == ["erosion_metrics"]

    floors = CalibrationLedger(calibration_ledger_path(data_root)).latest_by_finder()
    assert set(floors) == {"wiki_rot", "edge_proposer"}
    assert floors["wiki_rot"].floor_mean == 2.0
    assert floors["wiki_rot"].sample_count == 3
    assert floors["wiki_rot"].floor_sigma == 0.0  # deterministic ⇒ zero spread
    assert "erosion_metrics" not in floors

    baselines = BaselineLedger(baseline_ledger_path(data_root)).latest_by_finder()
    assert baselines["wiki_rot"].sha == "cafe1234"
    assert baselines["wiki_rot"].vetted is True


def test_calibrate_finders_records_unvouched_baseline(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    runner = shell.WorktreeFinderRunner(
        tmp_path, {"wiki_rot": lambda _wt: 1}, worktree_factory=_fake_factory(tmp_path)
    )
    with runner:
        shell.calibrate_finders(
            runner=runner,
            finder_ids=["wiki_rot"],
            baseline_sha="cafe",
            samples=2,
            data_root=data_root,
            vetted_by="operator-supplied",
            vetted_at=None,  # operator could not vouch
            note="",
            now=_NOW,
        )

    baselines = BaselineLedger(baseline_ledger_path(data_root)).latest_by_finder()
    assert baselines["wiki_rot"].vetted is False
    assert baselines["wiki_rot"].to_golden_baseline() is None


def test_detection_failure_skips_without_faking_zero(tmp_path: Path) -> None:
    data_root = tmp_path / "data"

    def boom(_wt: Path) -> int:
        raise RuntimeError("kaboom")

    runner = shell.WorktreeFinderRunner(
        tmp_path, {"wiki_rot": boom}, worktree_factory=_fake_factory(tmp_path)
    )
    with runner:
        calibrated, skipped = shell.calibrate_finders(
            runner=runner,
            finder_ids=["wiki_rot"],
            baseline_sha="cafe",
            samples=2,
            data_root=data_root,
            vetted_by="operator-supplied",
            vetted_at=_NOW,
            note="",
            now=_NOW,
        )

    assert calibrated == []
    assert skipped[0][0] == "wiki_rot"
    assert "detection failed" in skipped[0][1]
    # Nothing recorded — a failed detection must not poison the floor with a 0.
    assert (
        CalibrationLedger(calibration_ledger_path(data_root)).latest_by_finder() == {}
    )


# -- real deterministic detection against tiny fixtures ------------------------


def test_real_wiki_rot_detection_counts_broken_cite(tmp_path: Path) -> None:
    (tmp_path / "docs" / "wiki").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text(
        "class Real:\n    pass\n", encoding="utf-8"
    )
    (tmp_path / "docs" / "wiki" / "entry.md").write_text(
        "# Entry\n\nThe handler lives at `src/foo.py:Missing` in the tree.\n",
        encoding="utf-8",
    )

    runner = shell.WorktreeFinderRunner(
        tmp_path,
        {"wiki_rot": shell._detect_wiki_rot},
        worktree_factory=_fake_factory(tmp_path),
    )
    with runner:
        shell.calibrate_finders(
            runner=runner,
            finder_ids=["wiki_rot"],
            baseline_sha="cafe",
            samples=2,
            data_root=tmp_path / "data",
            vetted_by="operator-supplied",
            vetted_at=_NOW,
            note="",
            now=_NOW,
        )

    floors = CalibrationLedger(
        calibration_ledger_path(tmp_path / "data")
    ).latest_by_finder()
    assert floors["wiki_rot"].floor_mean == 1.0


def test_list_flag_returns_zero() -> None:
    assert shell.main(["--list"]) == 0
