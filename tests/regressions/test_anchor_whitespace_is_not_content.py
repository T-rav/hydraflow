"""Review pass three: "non-empty" counted a space as content.

`retro_findings` promises, in prose, that "every finding kind declares
required, non-empty anchor fields, so a vague finding is unconstructable".
`min_length=1` does not deliver that: `" "` has length 1.

A POLICY finding whose entire `rule_text` was a single space constructed,
validated, was KEPT, and would have been filed as a rule for a human to sign —
the exact vagueness the design exists to prevent, walking through the gate.

This is the same failure mode as the two material findings in review passes one
and two: a guarantee stated in prose that the code does not deliver.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

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
    issues=[1],
    evidence=[EvidenceRef(locator="l", excerpt="make: *** [quality] Error 1")],
)

BLANKS = [" ", "\t", "\n", "   \n\t  "]

#: Every required anchor on every kind, with a valid payload for the rest.
ANCHORS = [
    (
        GateFinding,
        "title",
        {
            "kind": "gate",
            "signal_id": SIGNAL.id,
            "title": "t",
            "guard_path": "tests/architecture/x.py",
            "observed": "7",
        },
    ),
    (
        GateFinding,
        "guard_path",
        {
            "kind": "gate",
            "signal_id": SIGNAL.id,
            "title": "t",
            "guard_path": "tests/architecture/x.py",
            "observed": "7",
        },
    ),
    (
        GateFinding,
        "observed",
        {
            "kind": "gate",
            "signal_id": SIGNAL.id,
            "title": "t",
            "guard_path": "tests/architecture/x.py",
            "observed": "7",
        },
    ),
    (
        BugfixFinding,
        "repro_command",
        {
            "kind": "bugfix",
            "signal_id": SIGNAL.id,
            "title": "t",
            "repro_command": "make",
            "repro_file": "CLAUDE.md",
            "error_excerpt": "boom",
        },
    ),
    (
        BugfixFinding,
        "repro_file",
        {
            "kind": "bugfix",
            "signal_id": SIGNAL.id,
            "title": "t",
            "repro_command": "make",
            "repro_file": "CLAUDE.md",
            "error_excerpt": "boom",
        },
    ),
    (
        BugfixFinding,
        "error_excerpt",
        {
            "kind": "bugfix",
            "signal_id": SIGNAL.id,
            "title": "t",
            "repro_command": "make",
            "repro_file": "CLAUDE.md",
            "error_excerpt": "boom",
        },
    ),
    (
        BugfixFinding,
        "title",
        {
            "kind": "bugfix",
            "signal_id": SIGNAL.id,
            "title": "t",
            "repro_command": "make",
            "repro_file": "CLAUDE.md",
            "error_excerpt": "boom",
        },
    ),
    (
        PolicyFinding,
        "title",
        {
            "kind": "policy",
            "signal_id": SIGNAL.id,
            "title": "t",
            "doc_path": "CLAUDE.md",
            "rule_text": "r",
        },
    ),
    (
        PolicyFinding,
        "doc_path",
        {
            "kind": "policy",
            "signal_id": SIGNAL.id,
            "title": "t",
            "doc_path": "CLAUDE.md",
            "rule_text": "r",
        },
    ),
    (
        PolicyFinding,
        "rule_text",
        {
            "kind": "policy",
            "signal_id": SIGNAL.id,
            "title": "t",
            "doc_path": "CLAUDE.md",
            "rule_text": "r",
        },
    ),
]


class TestWhitespaceIsNotContent:
    @pytest.mark.parametrize(
        ("model", "anchor", "payload"),
        ANCHORS,
        ids=[f"{m.__name__}.{a}" for m, a, _ in ANCHORS],
    )
    @pytest.mark.parametrize("blank", BLANKS, ids=["space", "tab", "newline", "mixed"])
    def test_a_whitespace_only_anchor_is_rejected(self, model, anchor, payload, blank):
        with pytest.raises(ValidationError):
            model(**{**payload, anchor: blank})

    def test_the_anchor_table_covers_every_required_field(self):
        """Guard the guard: derived from the models, so a new anchor joins it."""
        for model in (GateFinding, BugfixFinding, PolicyFinding):
            required = {
                name
                for name, f in model.model_fields.items()
                if f.is_required() and name not in {"kind", "signal_id"}
            }
            covered = {a for m, a, _ in ANCHORS if m is model}

            assert required <= covered, (
                f"{model.__name__}: {sorted(required - covered)} is a required "
                "anchor with no whitespace-rejection case"
            )


class TestSurroundingWhitespaceIsTrimmedNotTrusted:
    def test_a_padded_anchor_is_stored_trimmed(self, tmp_path: Path):
        (tmp_path / "CLAUDE.md").write_text("rules")
        finding = PolicyFinding(
            kind="policy",
            signal_id=SIGNAL.id,
            title="t",
            doc_path="  CLAUDE.md  ",
            rule_text="  run make quality  ",
        )

        kept, _ = validate([finding], [SIGNAL], tmp_path)

        assert len(kept) == 1
        assert kept[0].doc_path == "CLAUDE.md"
        assert kept[0].rule_text == "run make quality"
