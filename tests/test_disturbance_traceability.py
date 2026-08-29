"""Tests for disturbance.detectors.traceability — the untraced-fraction ratchet (CH-5).

The detector reads the committed traceability matrix artifact and emits one
finding per untraced percentage point, so the standard {signature: count}
baseline ratchets the fraction: it may only shrink.

The committed ``<!-- untraced-pct: NN -->`` marker is display-only (CH-5
convergence review finding 3): both the baseline sync and the detector's
verification recompute the fraction from git history through the SAME code
path the generator uses (``collect_trace_commits`` + ``untraced_pct``). A
hand-edited marker can therefore never lower the baseline, and a deviation
beyond rounding tolerance raises a ``marker-mismatch`` finding. Where git
history is unavailable (non-repo tmp dirs, shallow CI clones) the recompute
degrades to marker-only mode — the ratchet still applies, verification is
simply skipped.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from disturbance.baseline import load_baseline
from disturbance.detectors.traceability import (
    TraceabilityDetector,
    sync_traceability_baseline,
)
from disturbance.registry import DIMENSIONS

_ARTIFACT_REL = "docs/arch/generated/traceability_matrix.md"
_BASELINE_REL = "disturbance/baselines/traceability.yaml"
_SIGNATURE = f"{_ARTIFACT_REL}::untraced-pct"
_MISMATCH_SIGNATURE = f"{_ARTIFACT_REL}::marker-mismatch"
_REGRESSION_SIGNATURE = f"{_ARTIFACT_REL}::generation-regression"


def _write_artifact(repo_root: Path, content: str) -> None:
    path = repo_root / _ARTIFACT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_baseline(repo_root: Path, count: int) -> Path:
    path = repo_root / _BASELINE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"comment: traceability baseline\nentries:\n  {_SIGNATURE}: {count}\n",
        encoding="utf-8",
    )
    return path


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _init_git_repo(
    repo_root: Path, *, traced: int = 0, untraced: int = 0, plain: int = 0
) -> None:
    """Init a repo whose PR-merge population yields a known untraced pct.

    *traced*/*untraced* commits carry the ``(#N)`` PR-squash suffix (with /
    without a ``Req-ID:`` trailer); *plain* commits carry neither, so they
    are not population. CI has no global git config, so user.email/name are
    persisted per-repo, not passed inline on a single commit.
    """
    repo_root.mkdir(parents=True, exist_ok=True)
    _git(repo_root, "init", "-q")
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test")
    n = 0
    for i in range(traced):
        n += 1
        _git(
            repo_root,
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            f"feat: traced {i} (#{n})\n\nReq-ID: REQ-{i}",
        )
    for i in range(untraced):
        n += 1
        _git(
            repo_root,
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            f"feat: untraced {i} (#{n})",
        )
    for i in range(plain):
        _git(
            repo_root,
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            f"chore: branch wip {i} with no pr suffix",
        )


class TestTraceabilityDetector:
    """Marker-only mode: tmp_path has no git history, so the ratchet counts
    come straight from the committed marker and verification is skipped."""

    def test_emits_one_finding_per_untraced_percentage_point(
        self, tmp_path: Path
    ) -> None:
        _write_artifact(tmp_path, "# Matrix\n\n<!-- untraced-pct: 37 -->\n")
        findings = TraceabilityDetector().detect(tmp_path)
        assert len(findings) == 37
        assert {f.signature for f in findings} == {f"{_ARTIFACT_REL}::untraced-pct"}
        assert {f.dimension for f in findings} == {"traceability"}
        assert {f.path for f in findings} == {_ARTIFACT_REL}

    def test_zero_pct_emits_no_findings(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "<!-- untraced-pct: 0 -->\n")
        assert TraceabilityDetector().detect(tmp_path) == []

    def test_missing_artifact_is_inert(self, tmp_path: Path) -> None:
        assert TraceabilityDetector().detect(tmp_path) == []

    def test_missing_marker_is_inert(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "# Matrix without a marker\n")
        assert TraceabilityDetector().detect(tmp_path) == []

    def test_an_out_of_domain_marker_is_reported_not_normalised(
        self, tmp_path: Path
    ) -> None:
        """This test used to pin ``== 100`` — the clamp that killed the arm.

        Clamping to 100 against a baseline of 100 made ``cur > base``
        unsatisfiable, so a marker of 250 (or 150, or any value at all) left
        the gate green. What survives is the materialisation bound, which is
        an order of magnitude above the metric's legitimate domain; see
        ``TestReachableRange``.
        """
        _write_artifact(tmp_path, "<!-- untraced-pct: 250 -->\n")
        assert len(TraceabilityDetector().detect(tmp_path)) == 250

    def test_message_names_the_fraction(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "<!-- untraced-pct: 42 -->\n")
        findings = TraceabilityDetector().detect(tmp_path)
        assert "42%" in findings[0].message


class TestMarkerVerification:
    """The committed marker is verified against a recompute from git history
    (same code path as the generator) — CH-5 convergence review finding 3."""

    def test_hand_lowered_marker_emits_mismatch_finding(self, tmp_path: Path) -> None:
        # Recomputed: 4/4 untraced = 100%. Marker forged down to 5%.
        _init_git_repo(tmp_path, untraced=4)
        _write_artifact(tmp_path, "<!-- untraced-pct: 5 -->\n")
        _write_baseline(tmp_path, 100)

        findings = TraceabilityDetector().detect(tmp_path)

        mismatch = [f for f in findings if f.signature == _MISMATCH_SIGNATURE]
        assert len(mismatch) == 1
        assert "stale or tampered" in mismatch[0].message
        assert "make arch-regen" in mismatch[0].message
        # The ratchet findings still reflect the committed marker.
        assert len([f for f in findings if f.signature == _SIGNATURE]) == 5

    def test_regenerated_matrix_stays_quiet(self, tmp_path: Path) -> None:
        # Recomputed: 2/4 untraced = 50%; marker matches → no mismatch.
        _init_git_repo(tmp_path, traced=2, untraced=2)
        _write_artifact(tmp_path, "<!-- untraced-pct: 50 -->\n")
        _write_baseline(tmp_path, 50)

        findings = TraceabilityDetector().detect(tmp_path)

        assert {f.signature for f in findings} == {_SIGNATURE}
        assert len(findings) == 50

    def test_one_point_rounding_drift_is_tolerated(self, tmp_path: Path) -> None:
        # ceil-rounding jitter as the window shifts between the author's
        # regen and the gate run must not false-alarm.
        _init_git_repo(tmp_path, traced=2, untraced=2)  # recomputed 50
        _write_artifact(tmp_path, "<!-- untraced-pct: 49 -->\n")

        findings = TraceabilityDetector().detect(tmp_path)

        assert not [f for f in findings if f.signature == _MISMATCH_SIGNATURE]

    def test_empty_recompute_with_nonzero_baseline_is_generation_regression(
        self, tmp_path: Path
    ) -> None:
        # History exists but parses to ZERO PR-merge commits while the
        # baseline pins a nonzero fraction: the generator regressed to
        # matching nothing. Must NOT read as 0%-untraced success.
        _init_git_repo(tmp_path, plain=1)
        _write_artifact(tmp_path, "<!-- untraced-pct: 0 -->\n")
        _write_baseline(tmp_path, 12)

        findings = TraceabilityDetector().detect(tmp_path)

        regression = [f for f in findings if f.signature == _REGRESSION_SIGNATURE]
        assert len(regression) == 1
        assert "generation regression" in regression[0].message
        assert not [f for f in findings if f.signature == _SIGNATURE]

    def test_legitimate_all_traced_zero_is_not_a_regression(
        self, tmp_path: Path
    ) -> None:
        # Real PR-merge commits, all carrying Req-IDs: 0% is genuine.
        _init_git_repo(tmp_path, traced=2)
        _write_artifact(tmp_path, "<!-- untraced-pct: 0 -->\n")
        _write_baseline(tmp_path, 12)

        assert TraceabilityDetector().detect(tmp_path) == []

    def test_shallow_clone_degrades_to_marker_only_mode(self, tmp_path: Path) -> None:
        # CI test checkouts are shallow (fetch-depth 1): a truncated window
        # would misreport the fraction, so verification is skipped there.
        origin = tmp_path / "origin"
        _init_git_repo(origin, untraced=4)
        clone = tmp_path / "clone"
        subprocess.run(
            ["git", "clone", "-q", "--depth", "1", origin.as_uri(), str(clone)],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        _write_artifact(clone, "<!-- untraced-pct: 5 -->\n")
        _write_baseline(clone, 100)

        findings = TraceabilityDetector().detect(clone)

        assert {f.signature for f in findings} == {_SIGNATURE}
        assert len(findings) == 5
        assert sync_traceability_baseline(clone) is False


class TestSyncTraceabilityBaseline:
    """The baseline only ever lowers from the RECOMPUTED fraction — the
    committed marker is display-only and cannot ratchet a forgery in."""

    def test_lower_recomputed_pct_rewrites_baseline_count(self, tmp_path: Path) -> None:
        # Regen PRs (make arch-regen, DiagramLoop) must ship the pruned
        # baseline alongside the lower matrix pct, or the ratchet's
        # `resolved` assertion fails on the NEXT unrelated PR.
        _init_git_repo(tmp_path, traced=2, untraced=2)  # recomputed 50
        _write_artifact(tmp_path, "<!-- untraced-pct: 50 -->\n")
        baseline_path = _write_baseline(tmp_path, 100)

        assert sync_traceability_baseline(tmp_path) is True
        assert load_baseline(baseline_path) == {_SIGNATURE: 50}

    def test_hand_lowered_marker_does_not_lower_baseline(self, tmp_path: Path) -> None:
        # Recomputed 100%; marker forged to 5. The forgery must not be
        # ratcheted in via an auto-pruned baseline.
        _init_git_repo(tmp_path, untraced=4)
        _write_artifact(tmp_path, "<!-- untraced-pct: 5 -->\n")
        baseline_path = _write_baseline(tmp_path, 100)

        assert sync_traceability_baseline(tmp_path) is False
        assert load_baseline(baseline_path) == {_SIGNATURE: 100}

    def test_lowers_from_recomputed_value_not_the_marker(self, tmp_path: Path) -> None:
        # Recomputed 50%, marker forged to 5, baseline 80: the baseline
        # follows the true number, never the marker.
        _init_git_repo(tmp_path, traced=2, untraced=2)
        _write_artifact(tmp_path, "<!-- untraced-pct: 5 -->\n")
        baseline_path = _write_baseline(tmp_path, 80)

        assert sync_traceability_baseline(tmp_path) is True
        assert load_baseline(baseline_path) == {_SIGNATURE: 50}

    def test_sync_preserves_baseline_comment(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path, traced=2, untraced=2)
        _write_artifact(tmp_path, "<!-- untraced-pct: 50 -->\n")
        baseline_path = _write_baseline(tmp_path, 100)

        sync_traceability_baseline(tmp_path)

        assert "traceability baseline" in baseline_path.read_text(encoding="utf-8")

    def test_equal_recomputed_pct_is_a_noop(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path, untraced=3)  # recomputed 100
        _write_artifact(tmp_path, "<!-- untraced-pct: 100 -->\n")
        baseline_path = _write_baseline(tmp_path, 100)
        before = baseline_path.read_text(encoding="utf-8")

        assert sync_traceability_baseline(tmp_path) is False
        assert baseline_path.read_text(encoding="utf-8") == before

    def test_higher_recomputed_pct_never_raises_the_baseline(
        self, tmp_path: Path
    ) -> None:
        # The ratchet only shrinks: growth must fail the gate as `new`,
        # not be silently legitimized by an auto-raised baseline.
        _init_git_repo(tmp_path, traced=2, untraced=3)  # recomputed 60
        _write_artifact(tmp_path, "<!-- untraced-pct: 60 -->\n")
        baseline_path = _write_baseline(tmp_path, 40)

        assert sync_traceability_baseline(tmp_path) is False
        assert load_baseline(baseline_path) == {_SIGNATURE: 40}

    def test_zero_recomputed_pct_prunes_the_entry(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path, traced=2)  # recomputed 0
        _write_artifact(tmp_path, "<!-- untraced-pct: 0 -->\n")
        baseline_path = _write_baseline(tmp_path, 12)

        assert sync_traceability_baseline(tmp_path) is True
        assert load_baseline(baseline_path) == {}

    def test_empty_recompute_never_prunes_the_baseline(self, tmp_path: Path) -> None:
        # Generation regression: history parses to zero PR-merge commits.
        # An empty population must not read as "0% untraced" success.
        _init_git_repo(tmp_path, plain=1)
        _write_artifact(tmp_path, "<!-- untraced-pct: 0 -->\n")
        baseline_path = _write_baseline(tmp_path, 12)

        assert sync_traceability_baseline(tmp_path) is False
        assert load_baseline(baseline_path) == {_SIGNATURE: 12}

    def test_without_git_history_is_inert(self, tmp_path: Path) -> None:
        # No recompute possible → never lower on the marker's word alone.
        _write_artifact(tmp_path, "<!-- untraced-pct: 5 -->\n")
        baseline_path = _write_baseline(tmp_path, 100)

        assert sync_traceability_baseline(tmp_path) is False
        assert load_baseline(baseline_path) == {_SIGNATURE: 100}

    def test_missing_artifact_is_inert(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path, traced=2, untraced=2)
        baseline_path = _write_baseline(tmp_path, 100)
        before = baseline_path.read_text(encoding="utf-8")

        assert sync_traceability_baseline(tmp_path) is False
        assert baseline_path.read_text(encoding="utf-8") == before

    def test_missing_baseline_is_inert(self, tmp_path: Path) -> None:
        # Repos without the dimension adopted must not grow a baseline file.
        _init_git_repo(tmp_path, traced=2, untraced=2)
        _write_artifact(tmp_path, "<!-- untraced-pct: 50 -->\n")

        assert sync_traceability_baseline(tmp_path) is False
        assert not (tmp_path / _BASELINE_REL).exists()


class TestRegistryEntry:
    def test_traceability_dimension_registered(self) -> None:
        spec = next(s for s in DIMENSIONS if s.name == "traceability")
        assert isinstance(spec.detector, TraceabilityDetector)
        assert (
            spec.baseline_path.as_posix() == "disturbance/baselines/traceability.yaml"
        )
        assert spec.fix_prompt

    def test_traceability_is_excluded_from_burn_down(self) -> None:
        # Adoption of requirement IDs happens in future work, not by an agent
        # editing a generated artifact — the dampener must not dispatch here.
        spec = next(s for s in DIMENSIONS if s.name == "traceability")
        assert spec.burn_down is False

    def test_other_dimensions_default_to_burn_down(self) -> None:
        assert all(s.burn_down for s in DIMENSIONS if s.name != "traceability")


class TestReachableRange:
    """The block-new arm shipped with an EMPTY failing region.

    ``min(pct, 100)`` capped the emitted count at exactly the baseline
    (#9733 landed grandfathered at 100), so ``cur > base`` could not hold for
    any marker value — doubling the committed debt to 150 left the gate
    green. The clamp also ran BEFORE the marker cross-check, so the forged
    150 was normalised into a 100 that agreed with the recompute and the
    tamper arm saw nothing either. One clamp, two blinded arms.
    """

    def test_a_marker_above_the_legitimate_domain_exceeds_the_baseline(
        self, tmp_path: Path
    ) -> None:
        """The value that used to pass. 150 > baseline 100 must now be `new`."""
        _init_git_repo(tmp_path, untraced=4)  # recomputed 100
        _write_artifact(tmp_path, "<!-- untraced-pct: 150 -->\n")

        findings = TraceabilityDetector().detect(tmp_path)

        assert len([f for f in findings if f.signature == _SIGNATURE]) == 150

    def test_a_forged_marker_no_longer_slips_past_the_mismatch_check(
        self, tmp_path: Path
    ) -> None:
        """The clamp laundered 150 into a 100 that matched the recompute."""
        _init_git_repo(tmp_path, untraced=4)  # recomputed 100
        _write_artifact(tmp_path, "<!-- untraced-pct: 150 -->\n")
        _write_baseline(tmp_path, 100)

        findings = TraceabilityDetector().detect(tmp_path)

        mismatch = [f for f in findings if f.signature == _MISMATCH_SIGNATURE]
        assert len(mismatch) == 1
        assert "150%" in mismatch[0].message

    def test_an_honest_marker_still_says_nothing(self, tmp_path: Path) -> None:
        """The other direction: 100 against a recomputed 100 stays quiet."""
        _init_git_repo(tmp_path, untraced=4)
        _write_artifact(tmp_path, "<!-- untraced-pct: 100 -->\n")

        findings = TraceabilityDetector().detect(tmp_path)

        assert {f.signature for f in findings} == {_SIGNATURE}
        assert len(findings) == 100

    def test_an_absurd_marker_is_bounded_without_hiding_its_value(
        self, tmp_path: Path
    ) -> None:
        """One Finding per point makes an unbounded marker an OOM vector.

        The remaining bound is a materialisation bound: it caps the LIST, not
        what the detector reports, so the message and the mismatch arm still
        carry the number the artifact actually claims.
        """
        _init_git_repo(tmp_path, untraced=4)
        _write_artifact(tmp_path, "<!-- untraced-pct: 1000000000 -->\n")
        ceiling = TraceabilityDetector().reachable_ceilings()[_SIGNATURE]

        findings = TraceabilityDetector().detect(tmp_path)

        ratchet = [f for f in findings if f.signature == _SIGNATURE]
        assert len(ratchet) == ceiling
        assert "1000000000%" in ratchet[0].message

    def test_the_live_baseline_sits_strictly_below_the_declared_ceiling(self) -> None:
        """The property that makes the arm live, read off the shipped files.

        This is the assertion whose failure IS the #9733 defect: baseline 100
        against a ceiling of 100.
        """
        repo_root = Path(__file__).resolve().parent.parent
        baseline = load_baseline(repo_root / _BASELINE_REL)
        ceilings = TraceabilityDetector().reachable_ceilings()

        assert baseline, "traceability baseline is empty; this asserts nothing"
        for signature, count in baseline.items():
            assert count < ceilings[signature], (
                f"{signature} baseline {count} is at or above its detector's "
                f"reachable ceiling {ceilings[signature]} — the block-new arm "
                "cannot fire"
            )

    def test_every_declared_ceiling_names_a_signature_the_detector_emits(
        self, tmp_path: Path
    ) -> None:
        """A ceiling for a signature nothing produces would guard nothing.

        Driven through the detector rather than read off the source, so the
        declaration cannot drift away from what ``detect`` actually emits.
        """
        emitted: set[str] = set()

        normal = tmp_path / "normal"
        _init_git_repo(normal, untraced=4)
        _write_artifact(normal, "<!-- untraced-pct: 100 -->\n")
        emitted |= {f.signature for f in TraceabilityDetector().detect(normal)}

        forged = tmp_path / "forged"
        _init_git_repo(forged, untraced=4)
        _write_artifact(forged, "<!-- untraced-pct: 5 -->\n")
        _write_baseline(forged, 100)
        emitted |= {f.signature for f in TraceabilityDetector().detect(forged)}

        regressed = tmp_path / "regressed"
        _init_git_repo(regressed, plain=1)
        _write_artifact(regressed, "<!-- untraced-pct: 0 -->\n")
        _write_baseline(regressed, 12)
        emitted |= {f.signature for f in TraceabilityDetector().detect(regressed)}

        assert emitted == set(TraceabilityDetector().reachable_ceilings())
