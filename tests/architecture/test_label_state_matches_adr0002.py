"""Drift guard: ADR-0002's Mermaid state diagram vs the generated labels.md.

The canonical transition table (`label_transitions.LABEL_TRANSITIONS`) is the
single source of truth the runtime consults; the architecture extractor reads
it to render `docs/arch/generated/labels.md`. This test diffs that generated
Mermaid edge set against the Mermaid `stateDiagram-v2` block in ADR-0002 and
fails on any drift, so the two representations of the label state machine can
never silently diverge (issue #10621).

Both blocks must exist: an empty extraction (the pre-#10621 state, when no
declarative table existed) is now a failure, not a pass.
"""

import re
from pathlib import Path

_MERMAID_BLOCK = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
_EDGE_RE = re.compile(r"^\s*([\w-]+)\s*-->\s*([\w-]+)(?:\s*:\s*(.+))?$", re.MULTILINE)


def _edges(mermaid_text: str) -> set[tuple[str, str]]:
    return {
        (m.group(1).replace("_", "-"), m.group(2).replace("_", "-"))
        for m in _EDGE_RE.finditer(mermaid_text)
    }


def _first_mermaid_block(md_text: str) -> str:
    m = _MERMAID_BLOCK.search(md_text)
    if not m:
        return ""
    return m.group(1)


def test_label_state_matches_adr0002(real_repo_root: Path):
    adr_path = real_repo_root / "docs/adr/0002-labels-as-state-machine.md"
    gen_path = real_repo_root / "docs/arch/generated/labels.md"
    assert gen_path.exists(), "docs/arch/generated/labels.md must be emitted"

    adr_block = _first_mermaid_block(adr_path.read_text())
    gen_block = _first_mermaid_block(gen_path.read_text())

    assert adr_block, (
        "ADR-0002 has no Mermaid stateDiagram block — it is the source of truth "
        "for the label state machine. Add one (see issue #10621)."
    )
    assert gen_block, (
        "docs/arch/generated/labels.md has no Mermaid block — the canonical "
        "transition table (label_transitions.LABEL_TRANSITIONS) is missing or "
        "empty. Run `make arch-regen`."
    )

    adr_edges = _edges(adr_block)
    gen_edges = _edges(gen_block)
    assert gen_edges, (
        "generated labels.md Mermaid has no parseable edges — the canonical "
        "transition table is empty."
    )

    missing = adr_edges - gen_edges
    extra = gen_edges - adr_edges
    if missing or extra:
        msg = []
        if missing:
            msg.append(f"In ADR-0002 but not in code: {sorted(missing)}")
        if extra:
            msg.append(f"In code but not in ADR-0002: {sorted(extra)}")
        raise AssertionError(
            "Label state machine drift between code and ADR-0002:\n  "
            + "\n  ".join(msg)
            + "\n\nFix: update either src/label_transitions.py:LABEL_TRANSITIONS "
            "or the Mermaid block in ADR-0002 so the edge sets match."
        )
