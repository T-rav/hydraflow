"""ADR-0136 enforcement: the activity-based ADR-drift loops stay removed.

ADR-0136 supersedes ADR-0056 and deletes ``AdrTouchpointAuditorLoop`` +
``AdrDriftResolverLoop`` (Decision §2), keeping only the pieces §3 names: the
authoring nudge in ``adr_drift`` (live consumer:
``src/arch/generators/adr_cross_reference.py``), the ADR-0100 half of
``src/state/_adr_audit.py``, and the replacement gate itself.

Same shape as ``test_adr0065_code_grooming_removed.py``: the "no live
references" scan walks the AST for *identifiers and imports only*, so ADR
prose in comments and docstrings (ADR-0056 and ADR-0136 are cited by name in
several) is correctly ignored while any real code reference fails the check.

The second half is the load-bearing complement: a removal test that only
asserted absence would also pass if the *replacement* were deleted, so the
positive assertions pin the surviving gate and the surviving nudge.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

# Class names deleted by ADR-0136 §2. ``AdrDrift`` also matches the deleted
# ``AdrDriftTriageLLM`` / ``AdrDriftResolverLLMClient`` collaborators.
_CAMEL = ("AdrTouchpointAuditor", "AdrDrift")

# Modules deleted by ADR-0136 §2. ``adr_drift`` itself is NOT here: §3 keeps it
# for ``bare_infra_citation_nudges``.
_MODULES = (
    "adr_touchpoint_auditor_loop",
    "adr_drift_resolver_loop",
    "adr_drift_resolver_runtime",
    "adr_drift_triage",
    "adr_drift_triage_llm",
)

# Loop-only symbols removed from the surviving ``adr_drift`` module (§3): the
# drift engine went with the loops; the nudge stayed.
_REMOVED_DRIFT_SYMBOLS = (
    "compute_drift",
    "compute_drift_by_adr",
    "partition_fleet_drift",
    "FleetDriftBatch",
    "AdrRollupEntry",
    "DriftFinding",
)


def _matches_module(name: str) -> bool:
    """True iff *name* is a deleted module (exact, or a dotted component of one).

    Exact per-component matching, not substring: ``adr_drift`` — the module §3
    keeps — is a *prefix* of every deleted module name, so a substring test
    would flag every legitimate ``import adr_drift`` as a violation.
    """
    return any(part in _MODULES for part in name.split("."))


def _live_references(base: Path) -> list[str]:
    """Return ``path::symbol`` for every *executable* reference to the removed
    loops under *base* — AST identifiers/imports only, never comments/strings."""
    offenders: list[str] = []
    for path in base.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        rel = path.name
        for node in ast.walk(tree):
            if isinstance(
                node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            ) and node.name.startswith(_CAMEL):
                offenders.append(f"{rel}::def {node.name}")
            elif isinstance(node, ast.Name) and node.id.startswith(_CAMEL):
                offenders.append(f"{rel}::name {node.id}")
            elif isinstance(node, ast.Attribute) and node.attr.startswith(_CAMEL):
                offenders.append(f"{rel}::attr {node.attr}")
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and _matches_module(node.module)
            ):
                offenders.append(f"{rel}::from {node.module}")
            elif isinstance(node, ast.Import):
                offenders.extend(
                    f"{rel}::import {alias.name}"
                    for alias in node.names
                    if _matches_module(alias.name)
                )
    return offenders


def test_adr_drift_loop_modules_are_deleted(real_repo_root: Path) -> None:
    """ADR-0136 §2: every deleted module is gone and not importable (no shim)."""
    for module in _MODULES:
        assert not (real_repo_root / "src" / f"{module}.py").exists(), (
            f"src/{module}.py still exists — ADR-0136 §2 deletes it"
        )
        assert importlib.util.find_spec(module) is None, (
            f"{module} is still importable — a re-export shim would let the "
            "removed machinery come back under the old name"
        )


def test_no_live_adr_drift_loop_references(real_repo_root: Path) -> None:
    """ADR-0136 §2: no executable code under src/ or tests/ defines, imports,
    or references the removed loops (comments and docstrings are exempt)."""
    offenders = _live_references(real_repo_root / "src")
    offenders += _live_references(real_repo_root / "tests")
    assert not offenders, (
        "live references to the retired ADR-drift loops remain "
        f"(ADR-0136 §2 requires full removal): {sorted(offenders)}"
    )


def test_adr_drift_kill_switches_are_gone() -> None:
    """ADR-0136 §2: both flags left ``HydraFlowConfig`` with their machinery.

    A default-OFF flag guarding deleted code is the exact rot #11600 filed.
    """
    from config import HydraFlowConfig  # noqa: PLC0415

    fields = set(HydraFlowConfig.model_fields)
    assert "adr_touchpoint_auditor_loop_enabled" not in fields
    assert "adr_drift_resolver_loop_enabled" not in fields
    assert not [f for f in fields if f.startswith("adr_drift_resolver_")]


def test_drift_engine_removed_but_authoring_nudge_survives() -> None:
    """ADR-0136 §3: ``adr_drift`` keeps the nudge and loses the drift engine.

    The module is not deleted — ``src/arch/generators/adr_cross_reference.py``
    is a live non-loop consumer of ``bare_infra_citation_nudges``.
    """
    import adr_drift  # noqa: PLC0415

    assert callable(adr_drift.bare_infra_citation_nudges)
    for symbol in _REMOVED_DRIFT_SYMBOLS:
        assert not hasattr(adr_drift, symbol), (
            f"adr_drift.{symbol} is loop-only machinery ADR-0136 §3 removes"
        )


def test_the_replacement_gate_is_the_live_enforcement() -> None:
    """ADR-0136 §1: the deterministic cited-symbol resolver is what enforces now.

    Pins the replacement so this file cannot pass by everything being deleted.
    """
    from adr_citation_resolve import unresolved_citations  # noqa: PLC0415
    from adr_index import ADRIndex  # noqa: PLC0415

    assert callable(unresolved_citations)
    assert callable(ADRIndex)
