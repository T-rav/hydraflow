"""Tests for per-branch context resolution and ruleset rendering."""

import json
from pathlib import Path

from scripts.gates.contract import load_gates
from scripts.gates.resolve import render_ruleset, resolve_contexts

CONTRACT = Path("docs/standards/branch_protection/gates.toml")
BP = Path("docs/standards/branch_protection")


def test_resolve_main_contexts_excludes_staging_only() -> None:
    contract = load_gates(CONTRACT)
    ctx = resolve_contexts(contract, "main")
    # `CI Gate` replaced ten individually-enumerated lanes on main (#11727);
    # it fans them in via `needs:` plus five more main never required. The
    # staging-only baseline must still be absent.
    assert "CI Gate" in ctx
    assert "Detect Changes" not in ctx
    assert "ADR gate" not in ctx
    assert "quality (.)" not in ctx, (
        "the no-op matrix legs are declared on staging, not main (#11727)"
    )
    assert len(ctx) == 5


def test_resolve_staging_contexts() -> None:
    contract = load_gates(CONTRACT)
    ctx = resolve_contexts(contract, "staging")
    assert ctx == [
        "quality (.)",
        "quality (src/ui)",
        "Detect Changes",
        "discover-projects",
        "CI Gate",
    ]


def test_render_main_matches_committed_json() -> None:
    contract = load_gates(CONTRACT)
    rendered = render_ruleset(contract, "main")
    committed = json.loads((BP / "main_ruleset.json").read_text())
    assert rendered == committed


def test_render_staging_matches_committed_json() -> None:
    contract = load_gates(CONTRACT)
    rendered = render_ruleset(contract, "staging")
    committed = json.loads((BP / "staging_ruleset.json").read_text())
    assert rendered == committed
