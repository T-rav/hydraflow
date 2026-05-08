"""Advisor-pattern self-repairing review.

Per docs/superpowers/specs/2026-05-08-advisor-pattern-self-repairing-review-design.md.
All model invocations go through Claude Code subagent dispatch — no direct
Anthropic SDK calls in this module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field


class FocusArea(BaseModel):
    description: str
    files: list[str]
    rationale: str


class ReviewPlan(BaseModel):
    risk_summary: str
    focus_areas: list[FocusArea] = Field(default_factory=list)
    rubric: list[str] = Field(default_factory=list)
    escalation_signals: list[str] = Field(default_factory=list)


class PreFlightInput(BaseModel):
    surface: str
    diff: str
    spec: str | None = None
    related_paths: list[str] = Field(default_factory=list)
    prior_attempts: int = 0


class Disagreement(BaseModel):
    executor_claim: str
    advisor_assessment: str
    severity: Literal["blocking", "concern"]


class PostVerifyResult(BaseModel):
    verdict: Literal["APPROVE", "VETO"]
    reasoning: str
    disagreements: list[Disagreement] = Field(default_factory=list)
    suggested_fix_direction: str | None = None


class PostVerifyInput(BaseModel):
    surface: str
    diff: str
    spec: str | None = None
    executor_verdict_summary: str
    executor_fix_diff: str | None = None
    pre_flight_plan: ReviewPlan | None = None
    attempt_number: int = 0


def _env_truthy(value: str | None) -> bool | None:
    """Tri-state: True/False if value is set and parses; None if unset."""
    if value is None:
        return None
    return value.strip().lower() not in {"false", "0", "no", "off", ""}


def is_advisor_enabled(surface: str, role: str) -> bool:
    """AND across master, per-role, per-surface kill-switches.

    Defaults to True when env unset.
    """
    if _env_truthy(os.environ.get("HYDRAFLOW_REVIEW_ADVISOR_ENABLED")) is False:
        return False
    role_token = role.replace("_", "").upper()
    role_env = f"HYDRAFLOW_REVIEW_{role_token}_ENABLED"
    if _env_truthy(os.environ.get(role_env)) is False:
        return False
    surface_env = f"HYDRAFLOW_{surface.upper()}_ADVISOR_ENABLED"
    return _env_truthy(os.environ.get(surface_env)) is not False


def resolve_model(surface: str, role: str, default: str) -> str:
    """Per-surface > global > default."""
    per_surface = os.environ.get(f"HYDRAFLOW_{surface.upper()}_{role.upper()}_MODEL")
    if per_surface:
        return per_surface
    global_val = os.environ.get(f"HYDRAFLOW_REVIEW_{role.upper()}_MODEL")
    if global_val:
        return global_val
    return default


class PreFlightTrigger:
    """Strategy for whether to run pre-flight on a given review."""

    def should_run(
        self, diff_stats: object, pr: object
    ) -> bool:  # pragma: no cover - abstract
        raise NotImplementedError


class AlwaysTrigger(PreFlightTrigger):
    def should_run(self, diff_stats: object, pr: object) -> bool:
        return True


@dataclass(frozen=True)
class SurfaceAdvisorConfig:
    surface: str
    pre_flight_enabled: bool
    pre_flight_trigger: PreFlightTrigger | None
    mid_flight_enabled: bool
    post_verify_enabled: bool
    post_verify_authority: Literal["advisory", "veto"]
    executor_model: str
    advisor_model: str
    max_veto_retries: int
