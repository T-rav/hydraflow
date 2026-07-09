"""Tests for disturbance.detectors.traceability — the untraced-fraction ratchet (CH-5).

The detector reads the committed traceability matrix artifact (pure file
read, like every detector) and emits one finding per untraced percentage
point, so the standard {signature: count} baseline ratchets the fraction:
it may only shrink.
"""

from __future__ import annotations

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


class TestTraceabilityDetector:
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

    def test_pct_clamped_to_100(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "<!-- untraced-pct: 250 -->\n")
        assert len(TraceabilityDetector().detect(tmp_path)) == 100

    def test_message_names_the_fraction(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "<!-- untraced-pct: 42 -->\n")
        findings = TraceabilityDetector().detect(tmp_path)
        assert "42%" in findings[0].message


class TestSyncTraceabilityBaseline:
    def test_lower_marker_rewrites_baseline_count(self, tmp_path: Path) -> None:
        # Regen PRs (make arch-regen, DiagramLoop) must ship the pruned
        # baseline alongside the lower matrix pct, or the ratchet's
        # `resolved` assertion fails on the NEXT unrelated PR.
        _write_artifact(tmp_path, "<!-- untraced-pct: 87 -->\n")
        baseline_path = _write_baseline(tmp_path, 100)

        assert sync_traceability_baseline(tmp_path) is True
        assert load_baseline(baseline_path) == {_SIGNATURE: 87}

    def test_sync_preserves_baseline_comment(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "<!-- untraced-pct: 87 -->\n")
        baseline_path = _write_baseline(tmp_path, 100)

        sync_traceability_baseline(tmp_path)

        assert "traceability baseline" in baseline_path.read_text(encoding="utf-8")

    def test_equal_marker_is_a_noop(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "<!-- untraced-pct: 100 -->\n")
        baseline_path = _write_baseline(tmp_path, 100)
        before = baseline_path.read_text(encoding="utf-8")

        assert sync_traceability_baseline(tmp_path) is False
        assert baseline_path.read_text(encoding="utf-8") == before

    def test_higher_marker_never_raises_the_baseline(self, tmp_path: Path) -> None:
        # The ratchet only shrinks: growth must fail the gate as `new`,
        # not be silently legitimized by an auto-raised baseline.
        _write_artifact(tmp_path, "<!-- untraced-pct: 60 -->\n")
        baseline_path = _write_baseline(tmp_path, 40)

        assert sync_traceability_baseline(tmp_path) is False
        assert load_baseline(baseline_path) == {_SIGNATURE: 40}

    def test_zero_marker_prunes_the_entry(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "<!-- untraced-pct: 0 -->\n")
        baseline_path = _write_baseline(tmp_path, 12)

        assert sync_traceability_baseline(tmp_path) is True
        assert load_baseline(baseline_path) == {}

    def test_missing_artifact_is_inert(self, tmp_path: Path) -> None:
        baseline_path = _write_baseline(tmp_path, 100)
        before = baseline_path.read_text(encoding="utf-8")

        assert sync_traceability_baseline(tmp_path) is False
        assert baseline_path.read_text(encoding="utf-8") == before

    def test_missing_baseline_is_inert(self, tmp_path: Path) -> None:
        # Repos without the dimension adopted must not grow a baseline file.
        _write_artifact(tmp_path, "<!-- untraced-pct: 5 -->\n")

        assert sync_traceability_baseline(tmp_path) is False
        assert not (tmp_path / _BASELINE_REL).exists()

    def test_marker_clamped_to_100(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "<!-- untraced-pct: 250 -->\n")
        baseline_path = _write_baseline(tmp_path, 100)
        before = baseline_path.read_text(encoding="utf-8")

        assert sync_traceability_baseline(tmp_path) is False
        assert baseline_path.read_text(encoding="utf-8") == before


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
