"""The adoption plan includes the branch-protection gates section when provided."""

from scripts.hydraflow_init.modes import Mode
from scripts.hydraflow_init.prompt import render


def test_render_includes_gates_section_when_provided() -> None:
    out = render(
        target="x",
        findings=[],
        summary={},
        mode=Mode.INCREMENTAL,
        principle_filter=None,
        skip_brainstorm=False,
        gates_section=["## Branch-protection gates (ADR-0082)", "", "detected: python"],
    )
    assert "Branch-protection gates (ADR-0082)" in out
    assert "detected: python" in out


def test_render_omits_gates_section_when_none() -> None:
    out = render(
        target="x",
        findings=[],
        summary={},
        mode=Mode.INCREMENTAL,
        principle_filter=None,
        skip_brainstorm=False,
        gates_section=None,
    )
    assert "Branch-protection gates" not in out
