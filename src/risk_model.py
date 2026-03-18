"""Risk model — rule-based blast-radius and risk scoring.

Pure-function module. Risk tolerance is organizational policy, not prediction.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field

BlastRadius = Literal["isolated", "module", "cross-cutting", "infrastructure"]
RiskLevel = Literal["low", "medium", "high", "critical"]

_INFRA_PATTERNS = frozenset(
    {
        "dockerfile",
        "docker-compose",
        ".github/workflows",
        "makefile",
        "terraform",
        "ansible",
        "k8s/",
        "helm/",
        "ci/",
        ".circleci",
        "jenkinsfile",
    }
)

_CONFIG_PATTERNS = frozenset(
    {
        ".env",
        "config.json",
        "config.yaml",
        "config.yml",
        "settings.py",
        "pyproject.toml",
        "package.json",
        ".toml",
        ".ini",
        ".cfg",
    }
)


class RiskDimensions(BaseModel):
    """Raw inputs for risk assessment."""

    files_changed: list[str] = Field(default_factory=list)
    diff_line_count: int = Field(default=0, ge=0)
    high_risk_paths_touched: bool = False
    issue_type: str = "feature"
    touches_config: bool = False
    touches_tests_only: bool = False
    is_epic_child: bool = False
    visual_triggers: list[str] = Field(default_factory=list)
    code_scanning_severity_max: str = ""


class RiskScore(BaseModel):
    """Computed risk score with breakdown."""

    score: float = Field(ge=0.0, le=1.0)
    level: RiskLevel
    factors: list[str]
    blast_radius: BlastRadius


def _level_from_score(score: float) -> RiskLevel:
    if score >= 0.75:
        return "critical"
    if score >= 0.50:
        return "high"
    if score >= 0.25:
        return "medium"
    return "low"


def _compute_blast_radius(files: list[str]) -> BlastRadius:
    if not files:
        return "isolated"

    lower_files = [f.lower() for f in files]
    for f in lower_files:
        for pat in _INFRA_PATTERNS:
            if pat in f:
                return "infrastructure"

    top_dirs: set[str] = set()
    for f in files:
        parts = f.split(os.sep)
        if not parts:
            parts = f.split("/")
        if len(parts) > 1:
            top_dirs.add(parts[0])
        else:
            top_dirs.add(".")

    if len(top_dirs) >= 4:
        return "cross-cutting"
    if len(top_dirs) >= 2:
        return "module"
    return "isolated"


def _detect_config_touch(files: list[str]) -> bool:
    for f in files:
        lower = f.lower()
        for pat in _CONFIG_PATTERNS:
            if lower.endswith(pat) or pat in lower:
                return True
    return False


def assess_risk(dims: RiskDimensions) -> RiskScore:
    """Assess risk from structural dimensions.

    Returns a :class:`RiskScore` with a 0.0–1.0 score, a level
    (low/medium/high/critical), human-readable factors, and blast radius.
    """
    score = 0.0
    factors: list[str] = []

    # High-risk paths
    if dims.high_risk_paths_touched:
        score += 0.25
        factors.append("high-risk paths touched (+0.25)")

    # Diff size
    if dims.diff_line_count > 1000:
        score += 0.20
        factors.append(f"large diff {dims.diff_line_count} lines (+0.20)")
    elif dims.diff_line_count > 500:
        score += 0.10
        factors.append(f"medium diff {dims.diff_line_count} lines (+0.10)")

    # File count
    file_count = len(dims.files_changed)
    if file_count > 25:
        score += 0.20
        factors.append(f"{file_count} files changed (+0.20)")
    elif file_count > 10:
        score += 0.10
        factors.append(f"{file_count} files changed (+0.10)")

    # Config/infra touch
    touches_config = dims.touches_config or _detect_config_touch(dims.files_changed)
    if touches_config:
        score += 0.15
        factors.append("config/infra files touched (+0.15)")

    # Tests-only (risk reduction)
    if dims.touches_tests_only:
        score -= 0.30
        factors.append("tests-only change (-0.30)")

    # Epic child
    if dims.is_epic_child:
        score += 0.05
        factors.append("epic child (+0.05)")

    # Code scanning severity
    sev = dims.code_scanning_severity_max.lower()
    if sev == "critical":
        score += 0.30
        factors.append("critical code scanning alert (+0.30)")
    elif sev == "high":
        score += 0.15
        factors.append("high code scanning alert (+0.15)")

    # Visual triggers
    visual_count = len(dims.visual_triggers)
    if visual_count > 0:
        visual_risk = min(visual_count * 0.05, 0.15)
        score += visual_risk
        factors.append(f"{visual_count} visual trigger(s) (+{visual_risk:.2f})")

    # Issue type
    issue_risk = {"feature": 0.10, "refactor": 0.10, "bugfix": 0.05, "chore": 0.00}
    type_risk = issue_risk.get(dims.issue_type, 0.05)
    if type_risk > 0:
        score += type_risk
        factors.append(f"issue type '{dims.issue_type}' (+{type_risk:.2f})")

    score = max(0.0, min(1.0, score))
    level = _level_from_score(score)
    blast_radius = _compute_blast_radius(dims.files_changed)

    return RiskScore(
        score=score,
        level=level,
        factors=factors,
        blast_radius=blast_radius,
    )
