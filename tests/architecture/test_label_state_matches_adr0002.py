"""Drift guard: ADR-0002's Mermaid state diagram vs the generated labels.md.

HydraFlow does not yet expose a canonical transition table. Until that source
exists, this test asserts that the generated labels page is present and
explicitly documents the empty transition extraction instead of being skipped.
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
    if not gen_block:
        gen_text = gen_path.read_text()
        assert "_(no transitions discovered)_" in gen_text
        return
    if not adr_block:
        raise AssertionError("ADR-0002 has no Mermaid block — add one.")

    adr_edges = _edges(adr_block)
    gen_edges = _edges(gen_block)
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
            + "\n\nFix: update either the source transition table or ADR-0002."
        )
