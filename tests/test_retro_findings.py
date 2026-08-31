"""Typed findings and the validator that is the actual quality gate (§4).

The retro's old output was prose ("consider strengthening the implementation
prompt"). The fix is structural: a finding without a concrete, resolvable
anchor cannot be constructed, and one whose anchor does not resolve against the
real tree is dropped and counted rather than filed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from retro_findings import (  # noqa: E402
    BugfixFinding,
    GateFinding,
    PolicyFinding,
    validate,
)
from retro_signals import EvidenceRef, RetroSignal  # noqa: E402

SIGNAL = RetroSignal(
    id="tool_error-abc1234567",
    family="tool_error",
    signature="Bash: make quality failed",
    count=7,
    issues=[1, 2],
    evidence=[
        EvidenceRef(
            locator="traces/1/implement/run-1/subprocess-0.json#Bash",
            excerpt="make: *** [quality] Error 1",
        )
    ],
)


def _gate(**over):
    base = {
        "kind": "gate",
        "signal_id": SIGNAL.id,
        "title": "Guard against repeated quality failures",
        "guard_path": "tests/architecture/test_quality_guard.py",
        "observed": "7 occurrences across 2 issues",
    }
    base.update(over)
    return GateFinding(**base)


def _bugfix(**over):
    base = {
        "kind": "bugfix",
        "signal_id": SIGNAL.id,
        "title": "make quality fails on a clean tree",
        "repro_command": "make quality",
        "repro_file": "src/retro_findings.py",
        "error_excerpt": "make: *** [quality] Error 1",
    }
    base.update(over)
    return BugfixFinding(**base)


def _policy(**over):
    base = {
        "kind": "policy",
        "signal_id": SIGNAL.id,
        "title": "Require quality before finishing",
        "doc_path": "CLAUDE.md",
        "rule_text": "Run make quality before declaring work complete.",
    }
    base.update(over)
    return PolicyFinding(**base)


class TestAnchorsAreMandatoryByConstruction:
    """Derived from the models, so a new anchor field cannot dodge its guard."""

    @pytest.mark.parametrize(
        ("model", "builder"),
        [(GateFinding, _gate), (BugfixFinding, _bugfix), (PolicyFinding, _policy)],
        ids=["gate", "bugfix", "policy"],
    )
    def test_every_anchor_field_rejects_blank(self, model, builder):
        anchors = [
            name
            for name, f in model.model_fields.items()
            if name not in {"kind", "rationale"} and f.is_required()
        ]
        assert anchors, "model declares no required anchors"

        for name in anchors:
            with pytest.raises(ValidationError):
                builder(**{name: ""})


class TestGateResolution:
    def test_guard_outside_the_allowlist_is_dropped(self, tmp_path: Path):
        kept, dropped = validate(
            [_gate(guard_path="src/whatever.py")], [SIGNAL], tmp_path
        )

        assert kept == []
        assert "allowlist" in dropped[0].reason

    def test_guard_inside_the_allowlist_is_kept(self, tmp_path: Path):
        kept, _ = validate([_gate()], [SIGNAL], tmp_path)

        assert len(kept) == 1

    def test_observed_must_restate_the_signal_count(self, tmp_path: Path):
        kept, dropped = validate(
            [_gate(observed="this happens rather a lot")], [SIGNAL], tmp_path
        )

        assert kept == []
        assert "count" in dropped[0].reason

    def test_unknown_signal_id_is_dropped(self, tmp_path: Path):
        kept, dropped = validate(
            [_gate(signal_id="tool_error-deadbeef00")], [SIGNAL], tmp_path
        )

        assert kept == []
        assert "signal" in dropped[0].reason


class TestBugfixResolution:
    def test_nonexistent_repro_file_is_dropped(self, tmp_path: Path):
        kept, dropped = validate(
            [_bugfix(repro_file="src/does_not_exist.py")], [SIGNAL], tmp_path
        )

        assert kept == []
        assert "repro_file" in dropped[0].reason

    def test_existing_repro_file_with_grounded_excerpt_is_kept(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "retro_findings.py").write_text("x")

        kept, _ = validate([_bugfix()], [SIGNAL], tmp_path)

        assert len(kept) == 1

    def test_excerpt_absent_from_the_evidence_is_dropped(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "retro_findings.py").write_text("x")

        kept, dropped = validate(
            [_bugfix(error_excerpt="a failure nobody observed")], [SIGNAL], tmp_path
        )

        assert kept == []
        assert "excerpt" in dropped[0].reason

    def test_a_signal_without_evidence_cannot_ground_a_bugfix(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "retro_findings.py").write_text("x")
        skill_signal = RetroSignal(
            id="skill_failure-0000000000",
            family="skill_failure",
            signature="tdd failed",
            count=3,
            issues=[1],
            evidence=[],
        )

        kept, dropped = validate(
            [_bugfix(signal_id=skill_signal.id)], [skill_signal], tmp_path
        )

        assert kept == []
        assert "excerpt" in dropped[0].reason


class TestPolicyResolution:
    def test_nonexistent_doc_is_dropped(self, tmp_path: Path):
        kept, dropped = validate([_policy(doc_path="docs/nope.md")], [SIGNAL], tmp_path)

        assert kept == []
        assert "doc_path" in dropped[0].reason

    def test_existing_doc_is_kept(self, tmp_path: Path):
        (tmp_path / "CLAUDE.md").write_text("rules")

        kept, _ = validate([_policy()], [SIGNAL], tmp_path)

        assert len(kept) == 1


class TestPathSafety:
    @pytest.mark.parametrize(
        "hostile", ["/etc/passwd", "../../../etc/passwd", "docs/../../secrets.md"]
    )
    def test_traversal_and_absolute_paths_are_dropped(self, tmp_path: Path, hostile):
        kept, dropped = validate([_policy(doc_path=hostile)], [SIGNAL], tmp_path)

        assert kept == []
        assert "path" in dropped[0].reason


class TestCounting:
    def test_dropped_findings_are_reported_not_silently_discarded(self, tmp_path: Path):
        kept, dropped = validate(
            [_gate(), _gate(guard_path="src/nope.py"), _policy(doc_path="gone.md")],
            [SIGNAL],
            tmp_path,
        )

        assert len(kept) == 1
        assert len(dropped) == 2
        assert all(d.reason for d in dropped)
