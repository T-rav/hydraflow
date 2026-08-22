#!/usr/bin/env python3
"""Finder calibration runner — I/O shell (#10826).

On-demand instrument that measures each DETERMINISTIC generative finder's
false-positive noise floor against a golden-baseline sha and populates the
#10821 :class:`~finder_calibration.CalibrationLedger` with the real floors. It is
the missing half of that engine: #10821 shipped the pure math + ledger but
NOTHING populated it — this does, honestly, against a frozen known-clean commit.

Shape mirrors ``scripts/mutation_gauntlet.py``: a thin I/O shell (git-worktree +
argparse plumbing) around a real ``FinderRunner``. For each supported finder it
materializes a **read-only** git worktree at ``--baseline-sha``, invokes THAT
finder's existing detection module against the checked-out tree (never
re-implemented, never filing issues / mutating config / touching the real repo),
and returns the flagged-count. Repeated ``--samples`` runs feed
:func:`~finder_calibration.measure_floor`; the resulting
:class:`~finder_calibration.FinderFloor` + a :class:`~finder_faceplate.BaselineProvenance`
row land in the calibration ledgers under ``<data_root>/calibration/``.

Only the deterministic finders are supported — their detection already
lives in reusable, LLM-free modules:

* ``wiki_rot``    → :func:`wiki_rot_citations.count_broken_cites`
* ``edge_proposer`` → :func:`edge_proposer_loop.count_edge_proposals`

(``adr_drift`` was a third until ADR-0136 deleted the loop it measured; a floor
only means something for a generative finder, and its stand-in detector was the
citation gate CI already runs on every PR.)

The LLM finders (``erosion_metrics``, ``term_proposer``, ``entry_evidence``) are
DEFERRED: they are skipped with a logged reason, NEVER a fabricated ``0``.

    python scripts/calibrate_finders.py --list
    python scripts/calibrate_finders.py --baseline-sha <sha> --samples 3
    python scripts/calibrate_finders.py --baseline-sha <sha> --vetted-at 2026-08-03T00:00:00+00:00

Baseline honesty: pass ``--vetted-at`` only when an operator has actually vouched
the sha defect-free for the finder's signal class. Omit it and the baseline is
recorded as unvouched (``vetted_at=None``) — surfaced downstream as a
low-confidence flag rather than pretended-vetted.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from finder_calibration import (  # noqa: E402
    FINDERS_BY_ID,
    GENERATIVE_FINDERS,
    GoldenBaseline,
)

logger = logging.getLogger("hydraflow.calibrate_finders")


#: A finder detector: given a checked-out worktree path, return its flagged-count.
Detector = Callable[[Path], int]

#: A worktree factory: given (repo_root, sha) yield a checkout of the repo at sha.
WorktreeFactory = Callable[[Path, str], AbstractContextManager[Path]]


class UnsupportedFinderError(RuntimeError):
    """Raised when a runner is asked for a finder it has no detector for.

    Surfaced (logged + skipped) by :func:`main` — a finder with no deterministic
    detection is NEVER recorded as a fabricated ``0`` sample.
    """


# --- deterministic detectors (reuse each finder's real detection module) -------


def _detect_wiki_rot(worktree: Path) -> int:
    from wiki_rot_citations import count_broken_cites  # noqa: PLC0415

    return count_broken_cites(worktree)


def _detect_edge_proposer(worktree: Path) -> int:
    from edge_proposer_loop import count_edge_proposals  # noqa: PLC0415

    return count_edge_proposals(worktree)


#: ``finder_id`` -> deterministic, read-only detector. Only these are
#: supported; everything else in the catalog is deferred (LLM-driven).
DETERMINISTIC_DETECTORS: dict[str, Detector] = {
    "wiki_rot": _detect_wiki_rot,
    "edge_proposer": _detect_edge_proposer,
}

#: Why each non-deterministic catalog finder is skipped — logged, never faked.
DEFERRED_REASON: dict[str, str] = {
    "erosion_metrics": (
        "LLM finder (ErosionMetricsLoop) — deferred; no deterministic detection "
        "to run read-only against a baseline"
    ),
    "term_proposer": (
        "LLM finder (TermProposerLoop) — deferred; proposal generation needs an "
        "LLM, so it has no reproducible clean-tree floor here"
    ),
    "entry_evidence": (
        "LLM finder (EntryEvidenceLoop) — deferred; evidence matching needs an "
        "LLM, so it has no reproducible clean-tree floor here"
    ),
}


# --- worktree materialization (real git; injectable for tests) -----------------


@contextmanager
def git_worktree_at(repo_root: Path, sha: str) -> Iterator[Path]:
    """Materialize a detached read-only checkout of *repo_root* at *sha*.

    Always removed on exit (even on failure), so a calibration run leaves no
    stray worktrees behind. The detection modules only READ the tree.
    """
    scratch = Path(tempfile.mkdtemp(prefix="findercal-"))
    worktree = scratch / "wt"
    subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "worktree",
            "add",
            "--detach",
            str(worktree),
            sha,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        yield worktree
    finally:
        subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "worktree",
                "remove",
                "--force",
                str(worktree),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        shutil.rmtree(scratch, ignore_errors=True)


class WorktreeFinderRunner:
    """Concrete :class:`~finder_calibration.FinderRunner`.

    Materializes a read-only git worktree at ``baseline.sha`` (once per sha,
    reused across samples), invokes the finder's real detection module against
    it, and returns the flagged-count. Only the finders in *detectors* are
    supported — any other id raises :class:`UnsupportedFinderError`. The
    ``worktree_factory`` seam is injected so tests exercise the
    materialize→detect→count path without real git.
    """

    def __init__(
        self,
        repo_root: Path,
        detectors: dict[str, Detector],
        *,
        worktree_factory: WorktreeFactory = git_worktree_at,
    ) -> None:
        self._repo_root = repo_root
        self._detectors = detectors
        self._worktree_factory = worktree_factory
        self._stack = ExitStack()
        self._worktrees: dict[str, Path] = {}

    def supports(self, finder_id: str) -> bool:
        """True iff this runner has a deterministic detector for *finder_id*."""
        return finder_id in self._detectors

    def _worktree_for(self, sha: str) -> Path:
        if sha not in self._worktrees:
            self._worktrees[sha] = self._stack.enter_context(
                self._worktree_factory(self._repo_root, sha)
            )
        return self._worktrees[sha]

    def run_against_baseline(self, finder_id: str, baseline: GoldenBaseline) -> int:
        detector = self._detectors.get(finder_id)
        if detector is None:
            raise UnsupportedFinderError(finder_id)
        worktree = self._worktree_for(baseline.sha)
        return int(detector(worktree))

    def close(self) -> None:
        self._stack.close()
        self._worktrees.clear()

    def __enter__(self) -> WorktreeFinderRunner:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


# --- calibration driver --------------------------------------------------------


def _default_data_root() -> Path:
    """Resolve the data root from config, falling back to a repo-local dir."""
    try:
        from config import HydraFlowConfig  # noqa: PLC0415

        return HydraFlowConfig().data_root
    except Exception:  # the instrument must run without full config present
        return REPO / "data"


def calibrate_finders(
    *,
    runner: WorktreeFinderRunner,
    finder_ids: list[str],
    baseline_sha: str,
    samples: int,
    data_root: Path,
    vetted_by: str,
    vetted_at: datetime | None,
    note: str,
    now: datetime,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Calibrate *finder_ids* against *baseline_sha*; write floors + provenance.

    Returns ``(calibrated_ids, skipped)`` where ``skipped`` is a list of
    ``(finder_id, reason)``. A finder whose detection raises, or that has no
    deterministic detector, is SKIPPED with a reason — never recorded as a
    fabricated ``0``.
    """
    from finder_calibration import CalibrationLedger as _Ledger  # noqa: PLC0415
    from finder_calibration import (  # noqa: PLC0415
        calibrate_finder,
        calibration_ledger_path,
        collect_samples,
    )
    from finder_faceplate import (  # noqa: PLC0415
        BaselineLedger,
        BaselineProvenance,
        baseline_ledger_path,
    )

    floor_ledger = _Ledger(calibration_ledger_path(data_root))
    baseline_ledger = BaselineLedger(baseline_ledger_path(data_root))
    priors = floor_ledger.latest_by_finder()

    calibrated: list[str] = []
    skipped: list[tuple[str, str]] = []

    for finder_id in finder_ids:
        finder = FINDERS_BY_ID.get(finder_id)
        if finder is None:
            skipped.append((finder_id, "unknown finder id (not in catalog)"))
            continue
        if not runner.supports(finder_id):
            reason = DEFERRED_REASON.get(finder_id, "no deterministic detector")
            logger.info("skip %s: %s", finder_id, reason)
            skipped.append((finder_id, reason))
            continue

        # GoldenBaseline requires a concrete vetted_at (the runner only reads
        # ``.sha``); the honest optional vetted_at is persisted in the provenance
        # sidecar below, NOT smuggled into the floor.
        baseline = GoldenBaseline(
            sha=baseline_sha,
            vetted_at=vetted_at or now,
            vetted_by=vetted_by,
            signal_class=finder.signal_class,
            note=note,
        )
        try:
            noise = collect_samples(
                runner, finder_id, baseline, runs=samples, ran_at=now
            )
        except UnsupportedFinderError:
            reason = DEFERRED_REASON.get(finder_id, "unsupported finder")
            skipped.append((finder_id, reason))
            continue
        except Exception as exc:  # noqa: BLE001 — a detection failure must skip, not fake a 0
            logger.warning("skip %s: detection failed: %s", finder_id, exc)
            skipped.append((finder_id, f"detection failed: {exc}"))
            continue

        floor = calibrate_finder(finder_id, noise, now, prior=priors.get(finder_id))
        floor_ledger.record(floor)
        baseline_ledger.record(
            BaselineProvenance(
                finder_id=finder_id,
                sha=baseline_sha,
                vetted_by=vetted_by,
                signal_class=finder.signal_class,
                vetted_at=vetted_at,
                note=note,
            )
        )
        calibrated.append(finder_id)
        print(
            f"  {finder_id:<16} mean={floor.floor_mean:.2f} "
            f"sigma={floor.floor_sigma:.2f} threshold={floor.threshold} "
            f"n={floor.sample_count} "
            f"{'low-confidence' if floor.low_confidence else 'ok'}"
        )

    return calibrated, skipped


def _print_catalog() -> None:
    for finder in GENERATIVE_FINDERS:
        if finder.finder_id in DETERMINISTIC_DETECTORS:
            status = "SUPPORTED (deterministic)"
        else:
            status = "DEFERRED — " + DEFERRED_REASON.get(finder.finder_id, "LLM finder")
        print(f"{finder.finder_id:<16} [{finder.signal_class}]  {status}")


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: measure noise floors + write the calibration ledgers."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Finder calibration runner (#10826)")
    parser.add_argument(
        "--baseline-sha",
        dest="baseline_sha",
        default=None,
        help="frozen known-clean commit to measure the noise floor against",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=2,
        help="runs per finder against the baseline (>=2 gives the ledger a sigma)",
    )
    parser.add_argument("--data-root", dest="data_root", default=None)
    parser.add_argument(
        "--finder",
        dest="finders",
        action="append",
        default=[],
        help="restrict to these finder id(s); default = all deterministic finders",
    )
    parser.add_argument("--vetted-by", dest="vetted_by", default="operator-supplied")
    parser.add_argument(
        "--vetted-at",
        dest="vetted_at",
        default=None,
        help="ISO-8601 time an operator vouched the sha clean; omit if unvouched",
    )
    parser.add_argument("--note", dest="note", default="")
    parser.add_argument(
        "--list",
        action="store_true",
        help="list catalog finders (supported vs deferred) and exit",
    )
    args = parser.parse_args(argv)

    if args.list:
        _print_catalog()
        return 0

    if not args.baseline_sha:
        parser.error("--baseline-sha is required (or use --list)")

    if args.samples < 1:
        parser.error("--samples must be >= 1")

    vetted_at: datetime | None = None
    if args.vetted_at:
        try:
            vetted_at = datetime.fromisoformat(args.vetted_at)
        except ValueError:
            parser.error(f"--vetted-at is not ISO-8601: {args.vetted_at!r}")

    target_ids = args.finders or list(DETERMINISTIC_DETECTORS)
    now = datetime.now(UTC)
    data_root = Path(args.data_root) if args.data_root else _default_data_root()

    if vetted_at is None:
        logger.info(
            "note: baseline %s is UNVOUCHED (no --vetted-at) — floors will carry a "
            "low-confidence flag downstream",
            args.baseline_sha,
        )

    print(
        f"calibrating {len(target_ids)} finder(s) against baseline "
        f"{args.baseline_sha} ({args.samples} sample(s) each):"
    )

    runner = WorktreeFinderRunner(REPO, DETERMINISTIC_DETECTORS)
    with runner:
        calibrated, skipped = calibrate_finders(
            runner=runner,
            finder_ids=target_ids,
            baseline_sha=args.baseline_sha,
            samples=args.samples,
            data_root=data_root,
            vetted_by=args.vetted_by,
            vetted_at=vetted_at,
            note=args.note,
            now=now,
        )

    print(f"\ncalibrated {len(calibrated)}: {', '.join(calibrated) or '(none)'}")
    if skipped:
        print("skipped:")
        for finder_id, reason in skipped:
            print(f"  {finder_id}: {reason}")
    print(f"\nledgers written under -> {data_root / 'calibration'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
