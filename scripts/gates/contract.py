"""Typed records and loader for the branch-protection gate contract (gates.toml)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Gate:
    """One (dimension, binding) pair: a required check context and where it runs."""

    name: str
    dimension: str
    tier: str
    required_on: list[str]
    runs_on: list[str]
    languages: list[str]
    requires_capability: list[str]
    status: str
    workflow: str
    job: str
    make_target: str = ""


@dataclass(frozen=True)
class CodeScanningTool:
    tool: str
    security_alerts_threshold: str
    alerts_threshold: str


@dataclass(frozen=True)
class BranchEnvelope:
    """Per-branch ruleset rules that are not status checks."""

    name: str
    allowed_merge_methods: list[str]
    required_approving_review_count: int = 0
    code_quality_severity: str | None = None
    code_scanning: list[CodeScanningTool] = field(default_factory=list)


@dataclass(frozen=True)
class Contract:
    gates: list[Gate]
    branches: dict[str, BranchEnvelope]


def load_gates(path: Path) -> Contract:
    """Parse gates.toml into a typed Contract."""
    raw = tomllib.loads(Path(path).read_text())
    gates = [
        Gate(
            name=g["name"],
            dimension=g["dimension"],
            tier=g["tier"],
            required_on=list(g["required_on"]),
            runs_on=list(g.get("runs_on", [])),
            languages=list(g.get("languages", [])),
            requires_capability=list(g.get("requires_capability", [])),
            status=g["status"],
            workflow=g["workflow"],
            job=g["job"],
            make_target=g.get("make_target", ""),
        )
        for g in raw.get("gate", [])
    ]
    branches: dict[str, BranchEnvelope] = {}
    for bname, b in raw.get("branch", {}).items():
        branches[bname] = BranchEnvelope(
            name=bname,
            allowed_merge_methods=list(b["allowed_merge_methods"]),
            required_approving_review_count=b.get("required_approving_review_count", 0),
            code_quality_severity=b.get("code_quality_severity"),
            code_scanning=[
                CodeScanningTool(
                    tool=t["tool"],
                    security_alerts_threshold=t["security_alerts_threshold"],
                    alerts_threshold=t["alerts_threshold"],
                )
                for t in b.get("code_scanning", [])
            ],
        )
    return Contract(gates=gates, branches=branches)
