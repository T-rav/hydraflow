"""Runtime-editable settings registry — the single opt-in list for the UI.

Adding a field here is the ONLY step to make it editable in the settings screen
(replacing the old four-point wiring: ``_MUTABLE_FIELDS`` + a per-field
``ControlStatusConfig`` DTO + env-override plumbing). Everything else — input
type, description, default, min/max, enum choices, current value — is derived
from the Pydantic ``Field`` automatically by :func:`build_settings_schema`.

Only two things can't be inferred from the type, so they live here:
- ``group``: which section of the screen the field appears under.
- ``live``: True when the running system re-reads the value each tick (safe to
  apply in-memory); False when it's captured at startup (persist + restart).

Honesty rule: mark ``live=True`` only when the value is verified to be re-read
at runtime. When unsure, use ``live=False`` — a truthful "restart" badge beats
a lying "live" one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, get_args, get_origin

import annotated_types as at

if TYPE_CHECKING:
    from config import HydraFlowConfig

SettingType = Literal["bool", "int", "float", "enum", "str"]


@dataclass(frozen=True)
class SettingSpec:
    """UI-only metadata for a runtime-editable config field."""

    group: str
    live: bool
    order: int = 0


# field_name -> SettingSpec. This IS the mutable-field allowlist; the control
# route derives its allowlist from ``set(SETTINGS)``.
SETTINGS: dict[str, SettingSpec] = {
    # --- Concurrency -----------------------------------------------------
    "max_triagers": SettingSpec("Concurrency", live=True, order=0),
    "max_workers": SettingSpec("Concurrency", live=True, order=1),
    "max_planners": SettingSpec("Concurrency", live=True, order=2),
    "max_reviewers": SettingSpec("Concurrency", live=True, order=3),
    "max_hitl_workers": SettingSpec("Concurrency", live=True, order=4),
    "batch_size": SettingSpec("Concurrency", live=True, order=5),
    # --- Work Queue (stage-queue ordering, #10037) -----------------------
    # Live: IssueStore re-reads these on every dequeue, so a change takes
    # effect on the next phase tick without a restart.
    "queue_strategy": SettingSpec("Work Queue", live=True, order=0),
    "queue_weight_p1": SettingSpec("Work Queue", live=True, order=1),
    "queue_weight_p2": SettingSpec("Work Queue", live=True, order=2),
    "queue_weight_unprioritised": SettingSpec("Work Queue", live=True, order=3),
    "queue_starvation_threshold_hours": SettingSpec("Work Queue", live=True, order=4),
    # --- Models ----------------------------------------------------------
    "model": SettingSpec("Models", live=True, order=0),
    "planner_model": SettingSpec("Models", live=True, order=1),
    "review_model": SettingSpec("Models", live=True, order=2),
    # --- CI & Quality ----------------------------------------------------
    "max_ci_fix_attempts": SettingSpec("CI & Quality", live=True, order=0),
    "max_quality_fix_attempts": SettingSpec("CI & Quality", live=True, order=1),
    "max_review_fix_attempts": SettingSpec("CI & Quality", live=True, order=2),
    "max_merge_conflict_fix_attempts": SettingSpec("CI & Quality", live=True, order=3),
    "min_review_findings": SettingSpec("CI & Quality", live=True, order=4),
    "ci_check_timeout": SettingSpec("CI & Quality", live=True, order=5),
    "ci_poll_interval": SettingSpec("CI & Quality", live=True, order=6),
    "test_adequacy_coverage_timeout_secs": SettingSpec(
        "CI & Quality", live=True, order=7
    ),
    # Independent test-adequacy verifier (#9546). Live: AgentRunner._run_skill
    # re-reads all three via getattr(config, ...) on every skill dispatch.
    "test_adequacy_verifier_enabled": SettingSpec("CI & Quality", live=True, order=20),
    "test_adequacy_verifier_fail_closed": SettingSpec(
        "CI & Quality", live=True, order=21
    ),
    "test_adequacy_verifier_model": SettingSpec("Models", live=True, order=4),
    # Live: auto_pr re-reads both via trace_collector.get_active_config()
    # on every gate run (#10013), so a toggle applies to the next bot PR.
    "auto_pr_preflight_gate_enabled": SettingSpec("CI & Quality", live=True, order=8),
    "auto_pr_preflight_stage_timeout_s": SettingSpec(
        "CI & Quality", live=True, order=9
    ),
    # --- Scheduling ------------------------------------------------------
    "poll_interval": SettingSpec("Scheduling", live=True, order=0),
    "pr_unstick_interval": SettingSpec("Scheduling", live=True, order=1),
    "pr_unstick_batch_size": SettingSpec("Scheduling", live=True, order=2),
    # --- PR Unsticker ----------------------------------------------------
    "unstick_auto_merge": SettingSpec("PR Unsticker", live=True, order=0),
    "unstick_all_causes": SettingSpec("PR Unsticker", live=True, order=1),
    # --- Branching & Release --------------------------------------------
    # Structural — captured into loop wiring at startup; change then restart.
    "staging_enabled": SettingSpec("Branching & Release", live=False, order=0),
    "staging_branch": SettingSpec("Branching & Release", live=False, order=1),
    "main_branch": SettingSpec("Branching & Release", live=False, order=2),
    "rc_cadence_hours": SettingSpec("Branching & Release", live=True, order=3),
    # --- Reliability -----------------------------------------------------
    "gh_circuit_breaker_enabled": SettingSpec("Reliability", live=True, order=0),
    "merge_policy_enabled": SettingSpec("Reliability", live=True, order=1),
    "stale_code_alert_threshold": SettingSpec("Reliability", live=True, order=2),
    # --- Event-Loop Watchdog (thread-level freeze detector, #9552) --------
    # enabled gates thread startup (captured at orchestrator start) → restart
    # badge; the other two are re-read by the watchdog thread on every poll /
    # at trip time (the builder threads them through as live callables).
    # hard_restart defaults False (notify-default, restart-opt-in) — flipping
    # it is the operator's explicit consent to supervisor-driven restarts.
    "event_loop_watchdog_enabled": SettingSpec(
        "Event-Loop Watchdog", live=False, order=0
    ),
    "event_loop_watchdog_stall_seconds": SettingSpec(
        "Event-Loop Watchdog", live=True, order=1
    ),
    "event_loop_watchdog_hard_restart": SettingSpec(
        "Event-Loop Watchdog", live=True, order=2
    ),
    # --- Branch GC (stale agent-branch reconciler, #10011) ----------------
    # Live: StaleIssueLoop re-reads these each tick, no restart needed.
    # delete_enabled defaults False (report/comment-only) since deletion is
    # destructive — this is the knob the operator flips to opt in.
    "branch_gc_stale_days": SettingSpec("Branch GC", live=True, order=0),
    "branch_gc_min_delete_age_days": SettingSpec("Branch GC", live=True, order=1),
    "branch_gc_delete_enabled": SettingSpec("Branch GC", live=True, order=2),
    # --- Memory ----------------------------------------------------------
    "memory_auto_approve": SettingSpec("Memory", live=True, order=0),
    # --- Paths -----------------------------------------------------------
    # A workspace path is read when workspaces are created at startup.
    "workspace_base": SettingSpec("Paths", live=False, order=0),
    # --- Model Routing (one-shot loop backends) --------------------------
    # Each one-shot loop gets a provider dial (claude harness vs an OpenAI-
    # compatible cheap direct model — openrouter or zai) paired with its model id
    # — both editable here, no config file. Live: the next spawn re-reads them.
    # The provider API keys are secrets and are intentionally NOT here — they
    # stay in .env (OPENROUTER_API_KEY / ZAI_API_KEY / MOONSHOT_API_KEY).
    "openrouter_base_url": SettingSpec("Model Routing", live=True, order=0),
    "zai_base_url": SettingSpec("Model Routing", live=True, order=1),
    "kimi_base_url": SettingSpec("Model Routing", live=True, order=2),
    "wiki_compilation_provider": SettingSpec("Model Routing", live=True, order=10),
    "wiki_compilation_model": SettingSpec("Model Routing", live=True, order=11),
    "adr_review_provider": SettingSpec("Model Routing", live=True, order=20),
    "adr_review_model": SettingSpec("Model Routing", live=True, order=21),
    "transcript_summary_provider": SettingSpec("Model Routing", live=True, order=30),
    "transcript_summary_model": SettingSpec("Model Routing", live=True, order=31),
    "triage_honeypot_provider": SettingSpec("Model Routing", live=True, order=40),
    "triage_honeypot_model": SettingSpec("Model Routing", live=True, order=41),
    # pr-unsticker shares the general background_model (below), so only its
    # provider dial lives here.
    "pr_unstick_provider": SettingSpec("Model Routing", live=True, order=50),
    "term_proposer_provider": SettingSpec("Model Routing", live=True, order=60),
    "term_proposer_model": SettingSpec("Model Routing", live=True, order=61),
    "background_model": SettingSpec("Models", live=True, order=3),
    # --- Issue Refinement (backlog dedup + priority scoring, #9957) ----------
    "issue_refinement_enabled": SettingSpec("Issue Refinement", live=True, order=0),
    "issue_refinement_pair_budget": SettingSpec("Issue Refinement", live=True, order=1),
    "issue_refinement_priority_budget": SettingSpec(
        "Issue Refinement", live=True, order=2
    ),
    "issue_refinement_model": SettingSpec("Issue Refinement", live=True, order=3),
    # --- Prompt Refinement (skill-prompt self-refinement, #9724) ----------
    "skill_prompt_refine_enabled": SettingSpec("Prompt Refinement", live=True, order=0),
    "skill_prompt_refine_max_weekly": SettingSpec(
        "Prompt Refinement", live=True, order=1
    ),
    "skill_prompt_refine_model": SettingSpec("Prompt Refinement", live=True, order=2),
}


def mutable_field_names() -> set[str]:
    """The set of config fields the control route may mutate."""
    return set(SETTINGS)


def _unwrap_optional(annotation: Any) -> Any:
    """``X | None`` / ``Optional[X]`` -> ``X`` (settings are never None-typed)."""
    args = get_args(annotation)
    if args:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return annotation


def _derive_type(annotation: Any) -> tuple[SettingType, list[Any] | None]:
    """Map a Python annotation to a UI input type + enum choices."""
    ann = _unwrap_optional(annotation)
    if get_origin(ann) is Literal:
        return "enum", list(get_args(ann))
    if isinstance(ann, type) and issubclass(ann, Enum):
        return "enum", [m.value for m in ann]
    if ann is bool:
        return "bool", None
    if ann is int:
        return "int", None
    if ann is float:
        return "float", None
    return "str", None


def _jsonable(value: Any) -> Any:
    """Coerce a config value to a JSON-friendly primitive for the UI."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return value


def build_settings_schema(config: HydraFlowConfig) -> list[dict[str, Any]]:
    """Derive the settings-screen schema from the registry + Pydantic model.

    One row per registry entry, sorted by (group, order, name). Unknown field
    names are skipped defensively (a guard test asserts the registry has none).
    """
    fields = type(config).model_fields
    rows: list[dict[str, Any]] = []
    for name, spec in SETTINGS.items():
        info = fields.get(name)
        if info is None:
            continue
        ui_type, choices = _derive_type(info.annotation)
        minimum: Any = None
        maximum: Any = None
        for meta in info.metadata:
            if isinstance(meta, at.Ge):
                minimum = meta.ge
            elif isinstance(meta, at.Gt):
                minimum = meta.gt
            elif isinstance(meta, at.Le):
                maximum = meta.le
            elif isinstance(meta, at.Lt):
                maximum = meta.lt
        rows.append(
            {
                "name": name,
                "group": spec.group,
                "live": spec.live,
                "type": ui_type,
                "description": info.description or "",
                "default": _jsonable(info.default),
                "value": _jsonable(getattr(config, name)),
                "min": minimum,
                "max": maximum,
                "choices": choices,
            }
        )
    rows.sort(key=lambda r: (r["group"], SETTINGS[r["name"]].order, r["name"]))
    return rows
