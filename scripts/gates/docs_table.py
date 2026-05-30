"""Render the human-readable gate table for README.md from the contract."""

from __future__ import annotations

from scripts.gates.contract import Contract

HEADER = "| Gate | Dimension | Tier | Required on | Runs on |"
SEP = "|---|---|---|---|---|"


def render_docs_table(contract: Contract) -> str:
    """Markdown table of every active gate, in contract order."""
    rows = [HEADER, SEP]
    for g in contract.gates:
        if g.status != "active":
            continue
        rows.append(
            f"| {g.name} | {g.dimension} | {g.tier} | "
            f"{', '.join(g.required_on)} | {', '.join(g.runs_on)} |"
        )
    return "\n".join(rows)
