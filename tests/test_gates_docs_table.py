"""Tests for rendering the README gate table from the contract."""

from pathlib import Path

from scripts.gates.contract import load_gates
from scripts.gates.docs_table import render_docs_table

CONTRACT = Path("docs/standards/branch_protection/gates.toml")


def test_table_has_header_and_all_active_gates() -> None:
    contract = load_gates(CONTRACT)
    table = render_docs_table(contract)
    assert "| Gate | Dimension | Tier | Required on | Runs on |" in table
    for g in contract.gates:
        if g.status == "active":
            assert f"| {g.name} |" in table
    assert "ADR gate" not in table


def test_table_is_deterministic() -> None:
    contract = load_gates(CONTRACT)
    assert render_docs_table(contract) == render_docs_table(contract)
