"""Regression test for issue #10621.

The label state machine gained a canonical, machine-readable transition table
(`label_transitions.LABEL_TRANSITIONS`) that the runtime consults and the
architecture extractor reads. This locks in three properties:

* `docs/arch/generated/labels.md` now lists real transitions (not the old
  ``_(no transitions discovered)_`` placeholder);
* the canonical table, ADR-0002's Mermaid diagram, and the generated artifact
  all declare the *same* edge set (single source of truth);
* the ADR-0002 drift gate is no longer neutered — it FAILS when the code table
  and ADR-0002's Mermaid disagree, and passes when they match.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import label_transitions
from tests.architecture.test_label_state_matches_adr0002 import (
    _edges,
    _first_mermaid_block,
)
from tests.architecture.test_label_state_matches_adr0002 import (
    test_label_state_matches_adr0002 as run_drift_gate,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LABELS_MD = REPO_ROOT / "docs/arch/generated/labels.md"
ADR0002 = REPO_ROOT / "docs/adr/0002-labels-as-state-machine.md"


def _canonical_edges() -> set[tuple[str, str]]:
    return {(src, dst) for src, dst, _trigger in label_transitions.LABEL_TRANSITIONS}


def test_canonical_transition_table_is_non_empty() -> None:
    assert label_transitions.LABEL_TRANSITIONS, (
        "LABEL_TRANSITIONS must declare the canonical label state machine"
    )
    for edge in label_transitions.LABEL_TRANSITIONS:
        src, dst, _trigger = edge
        assert src.startswith("hydraflow-"), edge
        assert dst.startswith("hydraflow-"), edge


def test_generated_labels_md_lists_real_transitions() -> None:
    text = LABELS_MD.read_text()
    assert "_(no transitions discovered)_" not in text, (
        "labels.md must no longer render the empty-extraction placeholder"
    )
    block = _first_mermaid_block(text)
    assert block, "labels.md must contain a Mermaid state diagram"
    gen_edges = _edges(block)
    assert gen_edges, "labels.md Mermaid must contain real edges"
    # The generated artifact is derived verbatim from the canonical table.
    assert gen_edges == _canonical_edges()


def test_adr0002_mermaid_matches_canonical_table() -> None:
    adr_edges = _edges(_first_mermaid_block(ADR0002.read_text()))
    assert adr_edges, "ADR-0002 must contain a Mermaid state diagram"
    assert adr_edges == _canonical_edges(), (
        "ADR-0002 Mermaid and LABEL_TRANSITIONS must declare the same edge set"
    )


def test_drift_gate_passes_on_real_repo() -> None:
    # No exception raised == the gate passes on the synced repo.
    run_drift_gate(REPO_ROOT)


def _mermaid(edges: list[tuple[str, str]]) -> str:
    lines = ["```mermaid", "stateDiagram-v2"]
    for a, b in edges:
        lines.append(f"    {a.replace('-', '_')} --> {b.replace('-', '_')}")
    lines.append("```")
    return "\n".join(lines)


def _write_synthetic_repo(
    tmp: Path,
    *,
    adr_edges: list[tuple[str, str]],
    gen_edges: list[tuple[str, str]],
) -> None:
    adr = tmp / "docs/adr/0002-labels-as-state-machine.md"
    gen = tmp / "docs/arch/generated/labels.md"
    adr.parent.mkdir(parents=True, exist_ok=True)
    gen.parent.mkdir(parents=True, exist_ok=True)
    adr.write_text("# ADR-0002\n\n" + _mermaid(adr_edges) + "\n")
    gen.write_text("# Label State Machine\n\n" + _mermaid(gen_edges) + "\n")


def test_drift_gate_fails_on_desync(tmp_path: Path) -> None:
    # ADR-0002 declares an edge the code table lacks: the gate must FAIL,
    # proving it is no longer neutered.
    _write_synthetic_repo(
        tmp_path,
        adr_edges=[
            ("hydraflow-find", "hydraflow-plan"),
            ("hydraflow-plan", "hydraflow-ready"),
        ],
        gen_edges=[("hydraflow-find", "hydraflow-plan")],  # missing plan->ready
    )
    with pytest.raises(AssertionError):
        run_drift_gate(tmp_path)


def test_drift_gate_fails_on_empty_generated(tmp_path: Path) -> None:
    # The old escape hatch: an empty extraction used to PASS. It must now FAIL.
    adr = tmp_path / "docs/adr/0002-labels-as-state-machine.md"
    gen = tmp_path / "docs/arch/generated/labels.md"
    adr.parent.mkdir(parents=True, exist_ok=True)
    gen.parent.mkdir(parents=True, exist_ok=True)
    adr.write_text(
        "# ADR-0002\n\n" + _mermaid([("hydraflow-find", "hydraflow-plan")]) + "\n"
    )
    gen.write_text("# Label State Machine\n\n_(no transitions discovered)_\n")
    with pytest.raises(AssertionError):
        run_drift_gate(tmp_path)


def test_drift_gate_passes_on_synced_synthetic(tmp_path: Path) -> None:
    edges = [
        ("hydraflow-find", "hydraflow-plan"),
        ("hydraflow-plan", "hydraflow-ready"),
    ]
    _write_synthetic_repo(tmp_path, adr_edges=edges, gen_edges=edges)
    run_drift_gate(tmp_path)  # no exception == pass
