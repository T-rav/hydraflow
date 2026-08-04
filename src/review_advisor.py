"""Advisor-pattern self-repairing review.

Per docs/superpowers/specs/2026-05-08-advisor-pattern-self-repairing-review-design.md.
All model invocations go through Claude Code subagent dispatch — no direct
Anthropic SDK calls in this module.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, cast

from pydantic import BaseModel, Field

import judge_calibration as jc
import judge_independence as ji
from human_steering import fenced_steering_guidance

if TYPE_CHECKING:  # pragma: no cover - typing only
    from events import EventBus

logger = logging.getLogger(__name__)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_BLOCK_RE = re.compile(r"(\{.*\})", re.DOTALL)


def _extract_json_block(payload: str) -> str:
    """Extract the JSON object from an agent transcript.

    The Claude subagent's response can include prose, stream events, or
    fenced code blocks around the JSON we asked for. Production transcripts
    are not bare JSON — see src/spec_match.py for the same pattern.

    Order: fenced JSON > last/greediest ``{...}`` block > bare payload.
    """
    m = _JSON_FENCE_RE.search(payload)
    if m:
        return m.group(1)
    m = _JSON_BLOCK_RE.search(payload)
    if m:
        return m.group(1)
    return payload


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
    # Optional — threaded into the prompt so MockWorld runners can route
    # advisor calls back to FakeLLM.pop_advisor_result(issue_number, role).
    # Production callers can leave this unset; the field only changes prompt
    # text when populated.
    issue_number: int | None = None
    # Human-on-the-loop continuous steering (ADR-0099 #4): live operator
    # guidance for this issue, sourced by :class:`ReviewPhase` from
    # ``StateTracker.get_human_steering``. Folded into the prompt fenced
    # via :func:`fenced_steering_guidance`. Empty when the feature is off
    # or no guidance was posted — the fold is then a no-op.
    human_guidance: str = ""


class Disagreement(BaseModel):
    executor_claim: str
    advisor_assessment: str
    severity: Literal["blocking", "concern"]


class PostVerifyResult(BaseModel):
    verdict: Literal["APPROVE", "VETO"]
    reasoning: str
    disagreements: list[Disagreement] = Field(default_factory=list)
    suggested_fix_direction: str | None = None
    # #10836 judge calibration: the advisor's confidence (0.0-1.0) that its own
    # verdict is correct. Optional + defaulted so older/other payloads that omit
    # it still validate unchanged; when present it is the proper-scoring signal
    # the calibration ledger records against eventual outcomes.
    confidence: float | None = None


class PostVerifyInput(BaseModel):
    surface: str
    diff: str
    spec: str | None = None
    executor_verdict_summary: str
    executor_fix_diff: str | None = None
    pre_flight_plan: ReviewPlan | None = None
    attempt_number: int = 0
    # Optional — threaded into the prompt so MockWorld runners can route
    # advisor calls back to FakeLLM.pop_advisor_result(issue_number, role).
    # Production callers can leave this unset; the field only changes prompt
    # text when populated.
    issue_number: int | None = None
    lens: Literal["correctness", "security", "spec"] | None = None
    # Human-on-the-loop continuous steering (ADR-0099 #4): live operator
    # guidance for this issue, sourced by :class:`ReviewPhase` from
    # ``StateTracker.get_human_steering``. Folded into the prompt fenced
    # via :func:`fenced_steering_guidance`. Empty when the feature is off
    # or no guidance was posted — the fold is then a no-op.
    human_guidance: str = ""
    # #10371 blast-radius classification hint. Extra paths unioned with the
    # paths parsed from ``diff`` when classifying the change (judge-independence
    # budget). Load-bearing for surfaces whose "diff" is NOT a unified diff and
    # therefore carries no ``+++ b/`` / ``diff --git`` headers for
    # ``classify_diff`` to read — most importantly the ADR-review surface, where
    # the ADR draft lives in the issue body. Reviewing an ADR is the canonical
    # STRUCTURAL (ADR-touching) change per the #10371 spec, so the caller
    # declares the paths the review pertains to rather than letting a header-less
    # body silently classify as "unclassed" (which would deny it an independent
    # verdict). Empty (default) keeps the ordinary path byte-for-byte unchanged.
    classification_paths: list[str] = Field(default_factory=list)


# Per-lens focus preambles prepended to the PostVerifyAdvisor prompt when a
# lens is set. Promoted to module-level so tests can import the mapping and
# verify prompt content without instantiating the full advisor.
_POST_VERIFY_LENS_GUIDANCE: dict[str, str] = {
    "correctness": "Focus this review pass on CORRECTNESS: logic errors, broken edge cases, race conditions, wrong behavior.",
    "security": "Focus this review pass on SECURITY and RISK: injection, authz/authn, secrets, unsafe deserialization, blast radius.",
    "spec": "Focus this review pass on SPEC ADHERENCE: does the diff do what the issue/spec requires, nothing more, nothing less.",
}


def _env_truthy(value: str | None) -> bool | None:
    """Tri-state: True/False if value is set and parses; None if unset."""
    if value is None:
        return None
    return value.strip().lower() not in {"false", "0", "no", "off", ""}


def _role_env_segment(role: str) -> str:
    """Compact role name for env vars: pre_flight -> PREFLIGHT, midflight -> MIDFLIGHT."""
    return role.replace("_", "").upper()


def is_advisor_enabled(surface: str, role: str) -> bool:
    """AND across master, per-role, per-surface kill-switches.

    Defaults to True when env unset.
    """
    if _env_truthy(os.environ.get("HYDRAFLOW_REVIEW_ADVISOR_ENABLED")) is False:
        return False
    role_env = f"HYDRAFLOW_REVIEW_{_role_env_segment(role)}_ENABLED"
    if _env_truthy(os.environ.get(role_env)) is False:
        return False
    surface_env = f"HYDRAFLOW_{surface.upper()}_ADVISOR_ENABLED"
    return _env_truthy(os.environ.get(surface_env)) is not False


def resolve_model(surface: str, role: str, default: str) -> str:
    """Per-surface > global > default."""
    role_seg = _role_env_segment(role)
    per_surface = os.environ.get(f"HYDRAFLOW_{surface.upper()}_{role_seg}_MODEL")
    if per_surface:
        return per_surface
    global_val = os.environ.get(f"HYDRAFLOW_REVIEW_{role_seg}_MODEL")
    if global_val:
        return global_val
    return default


# Judge-independence budget + fail-visible dispatch (#10371). The LEDGER and
# dashboard ALARM are always live (a fail-open must never be silent). The two
# behaviours that change a MERGE OUTCOME are feature-flagged OFF by default so
# they are opt-in until validated: routing a classed change's verdict to an
# independent model family, and the self-modification fail-closed STOP / HITL
# escalation. The single source of truth for both flags is the config layer
# (``HydraFlowConfig.judge_independence_enabled`` /
# ``judge_self_mod_fail_closed_enabled``, env-mapped in ``config.py``); the
# resolved booleans are threaded into :class:`PostVerifyAdvisor` at construction
# by ``review_phase``. This module never reads the env vars directly.


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


@dataclass(frozen=True)
class DiffStats:
    changed_paths: list[str]
    lines_changed: int


@dataclass(frozen=True)
class PRContext:
    prior_fix_attempts: int = 0


CRITICAL_PATHS_EXACT: frozenset[str] = frozenset(
    {
        "src/orchestrator.py",
        "src/service_registry.py",
        "src/coordinator.py",
        "src/review_phase.py",
        "src/review_advisor.py",
    }
)

CRITICAL_PATH_GLOBS: tuple[str, ...] = (
    "src/persistence/*",
    "src/state/*",
    "src/*_loop.py",
)


def _matches_critical(path: str) -> bool:
    if path in CRITICAL_PATHS_EXACT:
        return True
    return any(fnmatch.fnmatch(path, glob) for glob in CRITICAL_PATH_GLOBS)


# Re-exported for tests / external membership checks.
CRITICAL_PATHS = CRITICAL_PATHS_EXACT


# T29 — self-modification guard (spec §5.8). The advisor must never approve
# changes to its own implementation silently. When a diff touches these paths,
# resolve_post_verify_authority forces "veto" regardless of the surface's
# configured authority — even on advisory surfaces (e.g., wiki_ingest).
#
# Public contract (T30.5 I3): the wiki ingest descriptor synthesizer in
# ``review_phase`` imports this set to keep a single source of truth for
# advisor's own implementation paths. Different matchers (unified-diff
# headers vs. content-substring) consume the same paths.
SELF_MODIFYING_PATHS: frozenset[str] = frozenset(
    {
        "src/review_advisor.py",
        "src/review_phase.py",
    }
)


def _diff_touches_self_modifying_paths(diff: str) -> bool:
    """Detect whether a diff modifies advisor's own implementation files."""
    for path in SELF_MODIFYING_PATHS:
        if (
            f"diff --git a/{path}" in diff
            or f"diff --git b/{path}" in diff
            or f"+++ b/{path}" in diff
            or f"--- a/{path}" in diff
        ):
            return True
    return False


def resolve_post_verify_authority(
    *,
    surface_config: SurfaceAdvisorConfig,
    diff: str,
) -> Literal["advisory", "veto"]:
    """Resolve post-verify authority, applying spec §5.8 self-modification guard.

    When the diff modifies advisor's own implementation files (review_advisor.py
    or review_phase.py), force veto authority — the advisor must not approve
    changes to itself with anything less than its strongest mode, even on
    surfaces (wiki_ingest) that default to advisory.
    """
    if _diff_touches_self_modifying_paths(diff):
        return "veto"
    return surface_config.post_verify_authority


def should_pre_flight(diff_stats: DiffStats, pr: PRContext) -> bool:
    """Composite predicate for whether to run pre-flight on a PR review."""
    if _env_truthy(os.environ.get("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON")):
        return True
    if pr.prior_fix_attempts >= 1:
        return True
    if any(_matches_critical(p) for p in diff_stats.changed_paths):
        return True
    nontrivial_src = [p for p in diff_stats.changed_paths if p.startswith("src/")]
    return bool(nontrivial_src and diff_stats.lines_changed > 20)


_BLAST_MEDIUM_LINES_THRESHOLD = 200


def compute_blast_radius(
    diff_stats: DiffStats,
) -> Literal["low", "medium", "high"]:
    """Classify a diff's blast radius for retry-budget and iteration-count decisions.

    Tiers:
    - 'high'  — any changed path matches CRITICAL_PATHS_EXACT or CRITICAL_PATH_GLOBS.
    - 'medium' — no critical paths, but > _BLAST_MEDIUM_LINES_THRESHOLD lines
                 changed in src/.
    - 'low'   — everything else (docs, config, small src changes).

    Reuses _matches_critical() so the classification stays in sync with
    pre-flight trigger logic. Callers (PostVerifyAdvisor retry budget,
    StateData persistence, ADR-0051 iteration planning) consume the tier
    as a Literal rather than computing it themselves.
    """
    if any(_matches_critical(p) for p in diff_stats.changed_paths):
        return "high"
    src_lines = (
        diff_stats.lines_changed
        if any(p.startswith("src/") for p in diff_stats.changed_paths)
        else 0
    )
    if src_lines > _BLAST_MEDIUM_LINES_THRESHOLD:
        return "medium"
    return "low"


BLAST_RADIUS_RETRIES: dict[str, int] = {"low": 1, "medium": 2, "high": 3}


def min_review_passes_for_blast_radius(
    blast_radius: Literal["low", "medium", "high"],
) -> int:
    """Return the minimum fresh-eyes review passes required for a given blast radius.

    Per ADR-0051 stratified table: low=1, medium=2, high=3. Exposed as a
    named function (rather than a dict lookup at call sites) so the dashboard
    endpoint and ReviewStateMixin can import a single source of truth.
    """
    return BLAST_RADIUS_RETRIES[blast_radius]


def diff_stats_from_text(diff: str) -> DiffStats:
    """Compute a coarse :class:`DiffStats` from a raw unified-diff string.

    Used by ``ReviewPhase`` to feed the composite ``should_pre_flight`` predicate
    when no structured stats source is available. Counts ``+``/``-`` body lines
    and extracts post-image paths from ``+++ b/...`` headers. Tolerant of empty
    or malformed input — returns an empty :class:`DiffStats` rather than
    raising.
    """
    paths: list[str] = []
    lines_changed = 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            paths.append(line[len("+++ b/") :].strip())
        elif (
            line.startswith("+")
            and not line.startswith("+++")
            or line.startswith("-")
            and not line.startswith("---")
        ):
            lines_changed += 1
    return DiffStats(changed_paths=paths, lines_changed=lines_changed)


def format_pre_flight_for_prompt(plan: ReviewPlan | None) -> str:
    """Render a :class:`ReviewPlan` as a markdown section for the executor prompt.

    Returns an empty string when ``plan`` is ``None`` so callers can append
    unconditionally without branching. Production callers wire this into the
    reviewer's prompt so the executor's review uses the advisor's rubric.
    """
    if plan is None:
        return ""
    return (
        "\n\n## Pre-flight review plan (from advisor)\n\n"
        f"{plan.model_dump_json(indent=2)}\n\n"
        "Use this as your review rubric — focus on the listed focus_areas and "
        "rubric items. If you observe any of the escalation_signals, treat "
        "them as blocking unless you can show with evidence that they don't "
        "apply."
    )


class CompositeTrigger(PreFlightTrigger):
    def should_run(self, diff_stats: DiffStats, pr: PRContext) -> bool:  # type: ignore[override]
        return should_pre_flight(diff_stats, pr)


_SURFACE_DEFAULTS: dict[str, dict[str, object]] = {
    "pr_review": {
        "pre_flight_enabled": True,
        "pre_flight_trigger": CompositeTrigger(),
        "mid_flight_enabled": True,
        "post_verify_enabled": True,
        "post_verify_authority": "veto",
    },
    "pre_merge_spec_check": {
        "pre_flight_enabled": False,
        "pre_flight_trigger": None,
        "mid_flight_enabled": True,
        "post_verify_enabled": True,
        "post_verify_authority": "veto",
    },
    "adr_review": {
        "pre_flight_enabled": True,
        "pre_flight_trigger": AlwaysTrigger(),
        "mid_flight_enabled": False,
        "post_verify_enabled": True,
        "post_verify_authority": "veto",
    },
    "visual_gate": {
        "pre_flight_enabled": False,
        "pre_flight_trigger": None,
        "mid_flight_enabled": False,
        "post_verify_enabled": True,
        "post_verify_authority": "veto",
    },
    "wiki_ingest": {
        "pre_flight_enabled": False,
        "pre_flight_trigger": None,
        "mid_flight_enabled": False,
        "post_verify_enabled": True,
        "post_verify_authority": "advisory",
    },
}


def build_surface_config(surface: str) -> SurfaceAdvisorConfig:
    """Build the config for a surface, resolving models against env each call.

    Called once per review to capture env state at start.
    """
    base = _SURFACE_DEFAULTS[surface]
    pre_flight_enabled = base["pre_flight_enabled"]
    pre_flight_trigger = base["pre_flight_trigger"]
    mid_flight_enabled = base["mid_flight_enabled"]
    post_verify_enabled = base["post_verify_enabled"]
    post_verify_authority = base["post_verify_authority"]
    assert isinstance(pre_flight_enabled, bool)
    assert pre_flight_trigger is None or isinstance(
        pre_flight_trigger, PreFlightTrigger
    )
    assert isinstance(mid_flight_enabled, bool)
    assert isinstance(post_verify_enabled, bool)
    assert post_verify_authority in ("advisory", "veto")
    return SurfaceAdvisorConfig(
        surface=surface,
        pre_flight_enabled=pre_flight_enabled,
        pre_flight_trigger=pre_flight_trigger,
        mid_flight_enabled=mid_flight_enabled,
        post_verify_enabled=post_verify_enabled,
        post_verify_authority=post_verify_authority,
        executor_model=resolve_model(surface, "executor", default="sonnet"),
        advisor_model=resolve_model(surface, "advisor", default="opus"),
    )


# Snapshot — production code paths should call build_surface_config(surface)
# so env overrides are picked up at runtime. Tests / static inspection use this.
SURFACE_ADVISOR_CONFIGS: dict[str, SurfaceAdvisorConfig] = {
    surface: build_surface_config(surface) for surface in _SURFACE_DEFAULTS
}


class _AdvisorSubagentRunner(Protocol):
    """Minimal protocol the runner adapter must satisfy.

    Production wiring is provided by ReviewPhase via agent_cli (T9).

    The ``role`` parameter is required so MockWorld can route advisor calls
    to the correct scripted queue. Substring-based role detection on the
    prompt is a footgun — PR bodies discussing the advisor pattern itself
    contain marker substrings (T24.5 closed I1+I2).
    """

    async def run(
        self,
        *,
        model: str,
        subagent_type: str,
        prompt: str,
        role: Literal[
            "pre_flight",
            "mid_flight",
            "post_verify",
            "post_verify:correctness",
            "post_verify:security",
            "post_verify:spec",
        ],
    ) -> str: ...  # pragma: no cover - protocol


class PostVerifyAdvisor:
    """Always-on second-opinion gate. Runs as a separate Claude Code subagent.

    Authority is determined by the SurfaceAdvisorConfig:
    - "veto" — verdict is final (caller honors APPROVE/VETO)
    - "advisory" — VETO is downgraded to APPROVE before return; reasoning
      and disagreements are preserved for telemetry / logging
    """

    def __init__(
        self,
        runner: _AdvisorSubagentRunner,
        surface_config: SurfaceAdvisorConfig,
        *,
        log_path: Path | None = None,
        pr_number: int | None = None,
        authority_override: Literal["advisory", "veto"] | None = None,
        ledger_path: Path | None = None,
        event_bus: EventBus | None = None,
        judge_independence_enabled: bool = False,
        self_mod_fail_closed_enabled: bool = False,
        independent_model: str = "",
        factory_bound_files: frozenset[str] = frozenset(),
        judge_verdict_ledger_path: Path | None = None,
    ) -> None:
        self._runner = runner
        self._cfg = surface_config
        self._log_path = log_path
        # Threaded through to the jsonl session log so each entry carries
        # the PR number per spec §"Logging". Production callers wire this
        # from review_phase.py; tests may leave it unset.
        self._pr_number = pr_number
        # T29 self-modification guard: when the caller has computed an
        # authority override (e.g. via resolve_post_verify_authority because
        # the diff touches advisor's own files), use that instead of the
        # surface config's configured authority. None means "fall through
        # to surface_config.post_verify_authority".
        self._authority_override = authority_override
        # #10371 judge-independence budget + fail-visible dispatch.
        # ``ledger_path`` (``<data_root>/diagnostics/fail_open_ledger.jsonl``)
        # enables the always-live fail-open / independence-unavailable ledger;
        # ``event_bus`` raises the dashboard alarm. The two flags gate the
        # merge-outcome-changing behaviours (independent routing / self-mod
        # STOP). ``independent_model`` is the resolved cross-family judge model
        # ("" when no second family is configured → degraded mode).
        self._ledger_path = ledger_path
        self._event_bus = event_bus
        self._judge_independence_enabled = judge_independence_enabled
        self._self_mod_fail_closed_enabled = self_mod_fail_closed_enabled
        self._independent_model = independent_model
        # ADR-0123 / #10851 mechanical backstop: source files an ADR governs with
        # `Binds: factory`/`both`. A change to one is self-modification by declared
        # direction, catching gate-enablement config the substring enumeration
        # under-includes. Computed once by the caller (which has the repo/ADR dir)
        # via judge_independence.factory_bound_source_files; empty => enumeration
        # only (backward-compatible).
        self._factory_bound_files = factory_bound_files
        # #10836 judge calibration: when set, each verdict (the judge's RAW call,
        # before any advisory downgrade) is best-effort appended to this ledger
        # for proper-scoring against eventual outcomes. None (tests / disabled) →
        # no recording. The append is fail-soft and can never affect the verdict.
        self._judge_verdict_ledger_path = judge_verdict_ledger_path

    async def run(self, inp: PostVerifyInput) -> PostVerifyResult:
        start = time.monotonic()
        # #10371: classify the diff's blast radius once. Unclassed changes take
        # exactly the pre-#10371 path (the spec's non-goal: the ordinary review
        # path is untouched). Classification is cheap and side-effect-free.
        # ``classification_paths`` (default empty) is unioned in for surfaces
        # whose "diff" is not a unified diff — e.g. the ADR-review surface, whose
        # header-less ADR body would otherwise classify as "unclassed" and be
        # denied the independent verdict it (as a structural/ADR-touching change)
        # requires.
        classes = ji.classify_diff(
            inp.diff, factory_bound_files=self._factory_bound_files
        )
        if inp.classification_paths:
            classes = classes | ji.classify_paths(
                inp.classification_paths,
                factory_bound_files=self._factory_bound_files,
            )
        # Independence routing (flagged). Resolves the model this pass dispatches
        # to (an independent family for classed changes when available) and may
        # short-circuit self-modification changes to a HITL escalation when no
        # independent family is configured and fail-closed is on.
        dispatch_model, independent, judge_family, hitl_result = (
            self._resolve_independence(inp, classes)
        )
        if hitl_result is not None:
            return hitl_result

        prompt = self._build_prompt(inp)
        _role = cast(
            Literal[
                "pre_flight",
                "mid_flight",
                "post_verify",
                "post_verify:correctness",
                "post_verify:security",
                "post_verify:spec",
            ],
            f"post_verify:{inp.lens}" if inp.lens else "post_verify",
        )
        try:
            payload = await self._runner.run(
                model=dispatch_model,
                subagent_type="hydraflow-review-advisor",
                prompt=prompt,
                role=_role,
            )
        except Exception as exc:
            # Authentication, credit, and likely-bug errors must propagate
            # per docs/wiki/dark-factory.md §2.2 — they signal infrastructure
            # state (or programming bugs) the orchestrator's higher layers
            # need to see, not transient advisor-runner failures.
            from exception_classify import (  # noqa: PLC0415
                reraise_on_credit_or_bug,
            )

            try:
                reraise_on_credit_or_bug(exc)
            except BaseException:
                self._emit_log(
                    prompt=prompt, payload=None, start=start, error="runner-error"
                )
                raise
            reason = f"runner-error: {exc!r}"
            result = self._handle_failure(reason=reason, inp=inp, classes=classes)
            await self._alarm_fail_open(inp, classes, reason=reason, result=result)
            self._emit_log(
                prompt=prompt, payload=None, start=start, error="runner-error"
            )
            return result

        try:
            data = json.loads(_extract_json_block(payload))
            result = PostVerifyResult.model_validate(data)
        except Exception as exc:
            reason = f"parse-error: {exc!r}"
            result = self._handle_failure(reason=reason, inp=inp, classes=classes)
            await self._alarm_fail_open(inp, classes, reason=reason, result=result)
            self._emit_log(
                prompt=prompt, payload=payload, start=start, error="parse-error"
            )
            return result

        # #10836: capture the judge's RAW verdict + confidence BEFORE any
        # advisory downgrade — calibration scores the judge's true call, not the
        # policy-adjusted one.
        raw_verdict = result.verdict
        raw_confidence = result.confidence

        # Advisory authority: downgrade VETO to APPROVE; preserve diagnostic info.
        # T29: an explicit authority_override (computed by callers when the
        # diff modifies advisor's own files) takes precedence over the
        # surface config's configured authority.
        authority = self._authority_override or self._cfg.post_verify_authority
        if authority == "advisory" and result.verdict == "VETO":
            result = PostVerifyResult(
                verdict="APPROVE",
                reasoning=result.reasoning,
                disagreements=result.disagreements,
                suggested_fix_direction=result.suggested_fix_direction,
                confidence=result.confidence,
            )
        self._emit_log(prompt=prompt, payload=payload, start=start, error=None)
        # #10371: record coverage for classed changes — whether this verdict
        # carried an independent family, and whether that judge dissented
        # (disagreement-by-family). Feeds the gauntlet-calibration report.
        self._record_classed_verdict(
            inp,
            classes,
            independent=independent,
            judge_family=judge_family,
            result=result,
        )
        # #10836: best-effort proper-scoring record of the raw verdict. Fail-soft
        # by construction — never affects the verdict returned above.
        self._record_calibration_verdict(inp, raw_verdict, raw_confidence)
        return result

    def _record_calibration_verdict(
        self,
        inp: PostVerifyInput,
        verdict: Literal["APPROVE", "VETO"],
        confidence: float | None,
    ) -> None:
        """Best-effort append of this verdict to the judge-calibration ledger.

        No-op unless a ledger path is wired AND the advisor emitted a numeric
        confidence (we never fabricate one — an absent confidence is honestly
        skipped). The subject is keyed by PR number so it joins the escape ledger
        (:func:`judge_calibration.subject_for_pr`), falling back to the issue when
        no PR is known. ``judge_id`` distinguishes the per-lens judges; the whole
        call is wrapped fail-soft so a recording error can never reach the review
        pipeline.
        """
        if self._judge_verdict_ledger_path is None or confidence is None:
            return
        if self._pr_number is not None:
            subject_id = jc.subject_for_pr(self._pr_number)
        elif inp.issue_number is not None:
            subject_id = jc.subject_for_issue(inp.issue_number)
        else:
            return
        judge_id = f"post_verify:{inp.lens}" if inp.lens else "post_verify"
        jc.record_verdict(
            self._judge_verdict_ledger_path,
            judge_id=judge_id,
            judge_family="review_advisor",
            subject_id=subject_id,
            verdict=jc.Verdict.PASS if verdict == "APPROVE" else jc.Verdict.FAIL,
            confidence=confidence,
            recorded_at=datetime.now(UTC),
        )

    def _resolve_independence(
        self,
        inp: PostVerifyInput,
        classes: frozenset[ji.BlastRadiusClass],
    ) -> tuple[str, bool, str, PostVerifyResult | None]:
        """Resolve the dispatch model + independence bookkeeping for this pass.

        Returns ``(dispatch_model, independent, judge_family, hitl_result)``.
        When ``hitl_result`` is non-None the caller must return it immediately
        (a self-modification change with no independent family and fail-closed
        on → HITL escalation, never a silent same-family pass).

        No-op for unclassed changes or when the independence feature flag is
        off: dispatch stays on the configured advisor model. Degraded paths
        (classed change, no independent family) write a ledgered
        ``independence-unavailable`` record so the degradation is never silent.
        """
        default_model = self._cfg.advisor_model
        default_family = ji.model_family(default_model)
        if not self._judge_independence_enabled or not ji.requires_independent_verdict(
            classes
        ):
            return (default_model, False, default_family, None)

        disp = ji.disposition_for_independence(
            classes, independent_available=bool(self._independent_model)
        )
        if disp == ji.IndependenceDisposition.INDEPENDENT_AVAILABLE:
            model = self._independent_model
            return (model, True, ji.model_family(model), None)

        # Degraded: no independent family configured/reachable. Ledger it.
        self._ledger_independence_unavailable(inp, classes, disp)
        if (
            disp == ji.IndependenceDisposition.DEGRADED_SELF_MOD_HITL
            and self._self_mod_fail_closed_enabled
        ):
            # A missing independent verdict on the verdict-machinery is a stop:
            # escalate to HITL instead of merging on a same-family verdict.
            hitl = PostVerifyResult(
                verdict="VETO",
                reasoning=(
                    "judge-independence: self-modification change requires an "
                    "independent verdict but no independent model family is "
                    "configured — escalating to HITL rather than passing on a "
                    "same-family verdict (fail-closed, #10371)."
                ),
                disagreements=[],
            )
            return (default_model, False, default_family, hitl)
        # Non-self-mod (or self-mod with fail-closed off): proceed same-family,
        # but the degradation is ledgered above (never silent).
        return (default_model, False, default_family, None)

    def _record_classed_verdict(
        self,
        inp: PostVerifyInput,
        classes: frozenset[ji.BlastRadiusClass],
        *,
        independent: bool,
        judge_family: str,
        result: PostVerifyResult,
    ) -> None:
        """Ledger a verdict on a classed change (coverage + disagreement-by-family)."""
        if self._ledger_path is None or not self._judge_independence_enabled:
            return
        if not ji.requires_independent_verdict(classes):
            return
        dissent = result.verdict == "VETO" or any(
            d.severity == "blocking" for d in result.disagreements
        )
        ji.record_classed_verdict(
            self._ledger_path,
            lens=inp.lens,
            pr=self._pr_number,
            surface=self._cfg.surface,
            classes=classes,
            independent=independent,
            judge_family=judge_family,
            verdict=result.verdict,
            dissent=dissent,
        )

    def _ledger_independence_unavailable(
        self,
        inp: PostVerifyInput,
        classes: frozenset[ji.BlastRadiusClass],
        disposition: ji.IndependenceDisposition,
    ) -> None:
        if self._ledger_path is None:
            return
        ji.record_independence_unavailable(
            self._ledger_path,
            lens=inp.lens,
            pr=self._pr_number,
            surface=self._cfg.surface,
            classes=classes,
            disposition=disposition,
        )

    async def _alarm_fail_open(
        self,
        inp: PostVerifyInput,
        classes: frozenset[ji.BlastRadiusClass],
        *,
        reason: str,
        result: PostVerifyResult,
    ) -> None:
        """Raise the dashboard alarm for a fail-open event. Never raises.

        The ledger row is written synchronously in ``_handle_failure``; this
        publishes the SYSTEM_ALERT so a fail-open is loud, not silent. Publish
        failures are swallowed — a broken alarm must not break the pipeline.
        """
        if self._event_bus is None:
            return
        try:
            from events import EventType, HydraFlowEvent

            await self._event_bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_ALERT,
                    data={
                        "kind": "judge_fail_open",
                        "surface": self._cfg.surface,
                        "pr": self._pr_number,
                        "lens": inp.lens,
                        "failure_class": ji.classes_label(classes),
                        "self_modification": ji.is_self_modification(classes),
                        "disposition": (
                            "fail_closed_stop"
                            if result.verdict == "VETO"
                            and ji.is_self_modification(classes)
                            and self._self_mod_fail_closed_enabled
                            else "fail_open_ledgered"
                        ),
                        "reason": reason,
                    },
                )
            )
        except Exception:
            logger.warning("judge_fail_open SYSTEM_ALERT publish failed", exc_info=True)

    def _emit_log(
        self,
        *,
        prompt: str,
        payload: str | None,
        start: float,
        error: str | None,
    ) -> None:
        """Best-effort per-PR jsonl session log. Never raises."""
        if self._log_path is None:
            return
        duration_ms = int((time.monotonic() - start) * 1000)
        # Token counts are placeholders: the runner adapter does not yet
        # surface them. Emitting `None` documents the field shape (per spec
        # §"Logging") so downstream consumers can light up token-aware
        # dashboards without a schema migration when the runner exposes
        # token usage.
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "pr_number": self._pr_number,
            "surface": self._cfg.surface,
            "role": "post_verify",
            "model": self._cfg.advisor_model,
            "duration_ms": duration_ms,
            "input_summary_chars": len(prompt),
            "output_summary_chars": len(payload or ""),
            "tokens_in": None,
            "tokens_out": None,
            "error": error,
        }
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception:
            # best-effort logging; never block the pipeline
            logger.debug("advisor session log write failed", exc_info=True)

    def _handle_failure(
        self,
        *,
        reason: str,
        inp: PostVerifyInput | None = None,
        classes: frozenset[ji.BlastRadiusClass] | None = None,
    ) -> PostVerifyResult:
        """Degraded-path verdict for a dispatch/parse failure (#10371).

        Ledgers the fail-open event (always live when ``ledger_path`` is set —
        a fail-open must never be silent) and resolves the verdict:

        - **Self-modification class + fail-closed flag on → VETO (STOP).** A
          missing verdict on the machinery that produces verdicts is a stop,
          not a degraded pass.
        - Otherwise the pre-#10371 behaviour: ``HYDRAFLOW_REVIEW_POSTVERIFY_
          FAIL_AS_VETO`` forces VETO, else fail-open (APPROVE).
        """
        classes = classes if classes is not None else frozenset()
        disposition = ji.disposition_for_fail_open(
            classes, self_mod_fail_closed_enabled=self._self_mod_fail_closed_enabled
        )
        # Fail-visible: append the ledger row for every fail-open event.
        if self._ledger_path is not None:
            ji.record_fail_open(
                self._ledger_path,
                lens=inp.lens if inp is not None else None,
                pr=self._pr_number,
                surface=self._cfg.surface,
                classes=classes,
                disposition=disposition,
                reason=reason,
            )

        fail_as_veto = _env_truthy(
            os.environ.get("HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO")
        )
        fail_closed = disposition == ji.FailOpenDisposition.FAIL_CLOSED_STOP
        verdict: Literal["APPROVE", "VETO"] = (
            "VETO" if (fail_closed or fail_as_veto) else "APPROVE"
        )
        reasoning = (
            f"judge-independence fail-closed (self-modification): {reason}"
            if fail_closed
            else f"advisor-degraded: {reason}"
        )
        logger.warning(
            "post_verify advisor degraded surface=%s classes=%s reason=%s -> %s",
            self._cfg.surface,
            ji.classes_label(classes),
            reason,
            verdict,
        )
        return PostVerifyResult(
            verdict=verdict,
            reasoning=reasoning,
            disagreements=[],
        )

    def _build_prompt(self, inp: PostVerifyInput) -> str:
        sections = [
            f"Surface: {inp.surface}",
            f"Attempt #: {inp.attempt_number}",
        ]
        if inp.issue_number is not None:
            # Emitted so MockWorld's runner can extract the issue number from
            # the prompt and look up the scripted advisor response. Production
            # callers may leave issue_number unset.
            sections.append(f"Issue: {inp.issue_number}")
        sections.extend(
            [
                "",
                "## Diff",
                inp.diff[:8000],
                "",
                f"## Executor verdict summary\n{inp.executor_verdict_summary}",
            ]
        )
        if inp.executor_fix_diff:
            sections.append(f"\n## Executor fix\n{inp.executor_fix_diff[:4000]}")
        if inp.pre_flight_plan is not None:
            sections.append(
                f"\n## Pre-flight plan\n{inp.pre_flight_plan.model_dump_json()}"
            )
        # Second-order failure check for critical-path diffs (refinement §R2)
        _critical_diff = any(
            _matches_critical(p) for p in diff_stats_from_text(inp.diff).changed_paths
        )
        if _critical_diff:
            sections.append(
                "\n## Second-order failure check (required for shared-infrastructure diffs)\n"
                "Answer explicitly before your verdict:\n"
                "1. What is the failure mode if THIS fix itself fails?\n"
                "2. Is that failure mode broader or more severe than the original bug?\n"
                "If yes to (2), record a disagreement with severity='blocking'."
            )
        sections.append(
            "\nRespond with JSON matching the PostVerifyResult schema:\n"
            '{"verdict":"APPROVE"|"VETO","reasoning":str,'
            '"disagreements":[{"executor_claim":str,"advisor_assessment":str,'
            '"severity":"blocking"|"concern"}],'
            '"suggested_fix_direction":str|null,'
            '"confidence":float}\n'
            "confidence is your probability (0.0-1.0) that THIS verdict is "
            "correct — a calibrated self-estimate, not a formality."
        )
        prompt = "\n".join(sections)
        if inp.lens:
            prompt = f"{_POST_VERIFY_LENS_GUIDANCE[inp.lens]}\n\n{prompt}"
        return prompt + fenced_steering_guidance(inp.human_guidance)


class PreFlightAdvisor:
    """Conditional pre-review planner. Produces a ReviewPlan to scope the
    executor's review or returns None on degraded paths.

    Unlike PostVerifyAdvisor, pre-flight is always advisory — degraded paths
    return None ("no plan available; executor proceeds without one") rather
    than synthesizing an APPROVE/VETO verdict. There is no FAIL_AS_VETO
    counterpart for pre-flight.
    """

    def __init__(
        self,
        runner: _AdvisorSubagentRunner,
        surface_config: SurfaceAdvisorConfig,
        *,
        log_path: Path | None = None,
        pr_number: int | None = None,
    ) -> None:
        self._runner = runner
        self._cfg = surface_config
        self._log_path = log_path
        self._pr_number = pr_number

    async def run(self, inp: PreFlightInput) -> ReviewPlan | None:
        prompt = self._build_prompt(inp)
        start = time.monotonic()
        payload: str | None = None
        try:
            payload = await self._runner.run(
                model=self._cfg.advisor_model,
                subagent_type="hydraflow-review-advisor",
                prompt=prompt,
                role="pre_flight",
            )
        except Exception as exc:
            from exception_classify import (  # noqa: PLC0415
                reraise_on_credit_or_bug,
            )

            reraise_on_credit_or_bug(exc)
            self._emit_log(
                prompt=prompt, payload=None, start=start, error="runner-error"
            )
            logger.warning(
                "pre_flight advisor degraded surface=%s reason=runner-error: %r",
                self._cfg.surface,
                exc,
            )
            return None

        try:
            data = json.loads(_extract_json_block(payload))
            plan = ReviewPlan.model_validate(data)
        except Exception as exc:
            self._emit_log(
                prompt=prompt, payload=payload, start=start, error="parse-error"
            )
            logger.warning(
                "pre_flight advisor degraded surface=%s reason=parse-error: %r",
                self._cfg.surface,
                exc,
            )
            return None

        self._emit_log(prompt=prompt, payload=payload, start=start, error=None)
        return plan

    def _emit_log(
        self,
        *,
        prompt: str,
        payload: str | None,
        start: float,
        error: str | None,
    ) -> None:
        if self._log_path is None:
            return
        duration_ms = int((time.monotonic() - start) * 1000)
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "pr_number": self._pr_number,
            "surface": self._cfg.surface,
            "role": "pre_flight",
            "model": self._cfg.advisor_model,
            "duration_ms": duration_ms,
            "input_summary_chars": len(prompt),
            "output_summary_chars": len(payload or ""),
            "tokens_in": None,
            "tokens_out": None,
            "error": error,
        }
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception:
            logger.debug("pre_flight advisor session log write failed", exc_info=True)

    def _build_prompt(self, inp: PreFlightInput) -> str:
        sections = [
            f"Surface: {inp.surface}",
            f"Prior fix attempts: {inp.prior_attempts}",
        ]
        if inp.issue_number is not None:
            # Emitted so MockWorld's runner can extract the issue number from
            # the prompt and look up the scripted advisor response. Production
            # callers may leave issue_number unset.
            sections.append(f"Issue: {inp.issue_number}")
        sections.extend(
            [
                "",
                "## Diff",
                inp.diff[:8000],
            ]
        )
        if inp.spec is not None:
            sections.append(f"\n## Spec / issue body\n{inp.spec[:4000]}")
        if inp.related_paths:
            sections.append(
                "\n## Related paths\n" + "\n".join(f"- {p}" for p in inp.related_paths)
            )
        sections.append(
            "\nProduce a ReviewPlan as JSON matching this schema:\n"
            '{"risk_summary":str,'
            '"focus_areas":[{"description":str,"files":[str],"rationale":str}],'
            '"rubric":[str],'
            '"escalation_signals":[str]}'
            "\nFocus on: what could go wrong with this diff, what the reviewer "
            "should look for, and any signals that suggest mid-flight consult."
        )
        prompt = "\n".join(sections)
        return prompt + fenced_steering_guidance(inp.human_guidance)


class MidFlightAdvisor:
    """Build the Task-tool invocation the executor uses to consult the advisor.

    This class is a descriptor + template builder — it does NOT invoke the
    Task tool. The executor session itself calls Task(**invocation) with the
    dict returned by build_task_invocation. This keeps the Task dispatch
    inside the executor's session boundary (which the advisor pattern
    requires for "shared context" — the advisor sees the executor's
    summary, not the literal conversation history).

    T21 wires the TOOL_DESCRIPTION into the executor's review prompt and
    instructs the executor to call Task(...) with the build_task_invocation
    output when it needs a judgment call.
    """

    TOOL_DESCRIPTION = (
        "Consult an Opus advisor when uncertain about a review decision, "
        "fix strategy, or whether an issue is real. The advisor is dispatched "
        "via the Task tool with subagent_type='hydraflow-review-advisor'. "
        "The advisor does NOT see your full conversation history — include "
        "enough context in your question. Do NOT use this tool for things "
        "you can verify yourself (running tests, reading files, grepping "
        "code) — only judgment calls where the right answer requires more "
        "than mechanical verification."
    )

    def __init__(self, surface_config: SurfaceAdvisorConfig) -> None:
        self._cfg = surface_config

    def build_task_invocation(
        self,
        *,
        question: str,
        context_summary: str,
        options: list[str] | None = None,
    ) -> dict[str, str] | None:
        """Build the Task-tool invocation dict, or None if mid-flight is disabled.

        Returns a dict with keys ``model``, ``subagent_type``, ``prompt``,
        suitable for ``Task(**invocation)``. Returns None if the surface's
        ``mid_flight_enabled`` flag is False or the kill-switch chain
        disables mid-flight on this surface.
        """
        if not self._cfg.mid_flight_enabled:
            return None
        if not is_advisor_enabled(self._cfg.surface, "midflight"):
            return None
        prompt = self._render_prompt(question, context_summary, options or [])
        return {
            "model": self._cfg.advisor_model,
            "subagent_type": "hydraflow-review-advisor",
            "prompt": prompt,
        }

    # Sentinel marker prepended to every mid-flight consult prompt.
    # Mid-flight calls are dispatched from inside the executor's session via
    # the Task tool, which does NOT thread through ``_AdvisorSubagentRunner``
    # and therefore cannot pass an explicit ``role=`` parameter. The runner
    # adapter (``_PostVerifyRunner.run`` in src/review_phase.py) detects
    # this sentinel as the only signal that a prompt is a mid-flight
    # consult. Format: HTML comment so it never renders in any markdown
    # view, versioned so future format changes can be detected, and
    # specific enough that PR bodies discussing the advisor pattern won't
    # naturally contain it (T24.5 closed I1+I2).
    SENTINEL = "<!-- HYDRAFLOW_MIDFLIGHT_CONSULT_PROMPT_v1 -->"

    @staticmethod
    def _render_prompt(question: str, context: str, options: list[str]) -> str:
        sections = [
            MidFlightAdvisor.SENTINEL,
            "## Mid-flight consult",
            f"### Question\n{question}",
            f"\n### Context (summary from executor)\n{context}",
        ]
        if options:
            sections.append(
                "\n### Options under consideration\n"
                + "\n".join(f"- {o}" for o in options)
            )
        sections.append(
            '\nRespond with JSON: {"reasoning":str,"recommendation":str,'
            '"confidence":float}'
        )
        return "\n".join(sections)


def _max_midflight_consults() -> int:
    """Per-review cap on consult_advisor invocations.

    Read at call time (not import time) so monkeypatch in tests works.
    Falls back to the default (5) on any parse failure.
    """
    raw = os.environ.get("HYDRAFLOW_REVIEW_MIDFLIGHT_MAX_CONSULTS", "5")
    try:
        return int(raw)
    except ValueError:
        return 5


def build_mid_flight_prompt(
    surface_config: SurfaceAdvisorConfig,
) -> str | None:
    """Build the executor-prompt section that documents the consult_advisor
    Task tool. Returns None when mid-flight is disabled for the surface.

    The executor uses this to know when and how to call the Task tool with
    ``subagent_type="hydraflow-review-advisor"`` mid-review. This is purely
    instruction text — the actual Task dispatch happens inside the executor's
    session. Returning None keeps callers' prompt-builder branch-free: they
    inject ``section or ""``.
    """
    advisor = MidFlightAdvisor(surface_config=surface_config)
    # Probe — pass placeholder args; we only care whether the gate is open.
    if advisor.build_task_invocation(question="probe", context_summary="probe") is None:
        return None
    cap = _max_midflight_consults()
    return (
        "\n## Mid-flight advisor (Opus consult tool)\n\n"
        f"{MidFlightAdvisor.TOOL_DESCRIPTION}\n\n"
        "Invoke via:\n"
        "  Task(\n"
        '    subagent_type="hydraflow-review-advisor",\n'
        '    model="opus",\n'
        "    prompt=<see template below>\n"
        "  )\n\n"
        "Prompt template (the FIRST line MUST be the sentinel exactly as shown\n"
        "— it is how the runner adapter detects this is a mid-flight consult\n"
        "and routes it to the correct advisor queue):\n"
        f"  {MidFlightAdvisor.SENTINEL}\n"
        "  ## Mid-flight consult\n"
        "  Issue: <number>          # required so MockWorld can route\n"
        "  ### Question\n"
        "  <your judgment question>\n"
        "  ### Context (summary from executor)\n"
        "  <what you've already established>\n"
        "  [### Options under consideration\n"
        "   - option A\n"
        "   - option B]                # optional\n\n"
        "  Respond with JSON: "
        '{"reasoning":str,"recommendation":str,"confidence":float}\n\n'
        f"Cap: at most {cap} consult calls per review. "
        "Past the cap, the tool will return advisor-unavailable; decide on your own."
    )
