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
    # --- Scheduling model (#11535) ---------------------------------------
    # Not live: the orchestrator decides which pipeline loops to start once, at
    # boot, so a change here is a restart-required edit. Marking it live would
    # show the operator a green "applied" badge over a factory still running
    # the old discipline — the exact dishonesty this registry's docstring
    # warns against.
    "scheduling_model": SettingSpec("Scheduling", live=False, order=20),
    "execution_runtime": SettingSpec("Scheduling", live=False, order=21),
    "driver_max_in_flight": SettingSpec("Scheduling", live=False, order=22),
    # --- Fable director, shadow mode (#11537) ----------------------------
    # Same group and the same live=False reason: the director is attached to
    # the allocator once, at boot, so a live badge would be a lie.
    "director_turn_timeout_seconds": SettingSpec("Scheduling", live=False, order=23),
    "director_shadow_usd_budget": SettingSpec("Scheduling", live=False, order=24),
    # live=True, unlike its neighbours: this one is a kill switch, and a kill
    # switch that needs a restart is not a kill switch (docs/wiki/patterns.md).
    "director_shadow_enabled": SettingSpec("Scheduling", live=True, order=25),
    "director_shadow_usd_ceiling": SettingSpec("Scheduling", live=True, order=26),
    # --- Fable Plan canary (#11541) --------------------------------------
    # Live for the same reason the enforcement canary's dial is (ADR-0141 D5):
    # ``plan_broker.canary_repo`` re-reads it at every boundary, so clearing it
    # stops the next dispatch without a restart. That liveness IS the rollback
    # — an actuator an operator has to restart the factory to disarm is not a
    # canary switch.
    "fable_plan_canary_repo": SettingSpec("Scheduling", live=True, order=27),
    "fable_plan_worker_timeout_seconds": SettingSpec("Scheduling", live=True, order=28),
    "fable_implement_canary_repo": SettingSpec("Scheduling", live=True, order=29),
    "fable_review_canary_repo": SettingSpec("Scheduling", live=True, order=30),
    "fable_review_worker_timeout_seconds": SettingSpec(
        "Scheduling", live=True, order=31
    ),
    "fable_implement_worker_timeout_seconds": SettingSpec(
        "Scheduling", live=True, order=30
    ),
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
    # Live: AgentRunner._verify_quality reads it on every post-build gate.
    "implement_full_quality_gate": SettingSpec("CI & Quality", live=True, order=12),
    # Independent test-adequacy verifier (#9546). Live: AgentRunner._run_skill
    # re-reads all three via getattr(config, ...) on every skill dispatch.
    "test_adequacy_verifier_enabled": SettingSpec("CI & Quality", live=True, order=20),
    "test_adequacy_verifier_fail_closed": SettingSpec(
        "CI & Quality", live=True, order=21
    ),
    # Repair-in-run (#11593). Live: AgentRunner._run_skill reads it via
    # getattr(config, skill.repair_config_key) on every gate evaluation.
    "test_adequacy_repair_passes": SettingSpec("CI & Quality", live=True, order=22),
    # Demand contract (#11644). Live: skill_gate reads it via
    # getattr(config, skill.pin_config_key) on every gate evaluation.
    "test_adequacy_pin_demand": SettingSpec("CI & Quality", live=True, order=23),
    "test_adequacy_verifier_model": SettingSpec("Models", live=True, order=4),
    # Live: auto_pr re-reads both via trace_collector.get_active_config()
    # on every gate run (#10013), so a toggle applies to the next bot PR.
    "auto_pr_preflight_gate_enabled": SettingSpec("CI & Quality", live=True, order=8),
    "auto_pr_preflight_stage_timeout_s": SettingSpec(
        "CI & Quality", live=True, order=9
    ),
    # Live: ImplementPhase reads both off its shared HydraFlowConfig
    # reference on every PR-open (#10101), so a toggle applies to the next
    # implementer PR without a restart.
    "pr_base_freshness_guard_enabled": SettingSpec("CI & Quality", live=True, order=10),
    "pr_base_max_age_days": SettingSpec("CI & Quality", live=True, order=11),
    # --- Scheduling ------------------------------------------------------
    "poll_interval": SettingSpec("Scheduling", live=True, order=0),
    "pr_unstick_interval": SettingSpec("Scheduling", live=True, order=1),
    "pr_unstick_batch_size": SettingSpec("Scheduling", live=True, order=2),
    # Restart-required: each loop reads the stagger window once, at the top
    # of its run() task (#9814).
    "loop_startup_stagger_s": SettingSpec("Scheduling", live=False, order=3),
    # --- PR Unsticker ----------------------------------------------------
    "unstick_auto_merge": SettingSpec("PR Unsticker", live=True, order=0),
    "unstick_all_causes": SettingSpec("PR Unsticker", live=True, order=1),
    # Live: PRAutoRebase reads config.pr_autorebase_enabled on every
    # MergeStateWatcher attempt, so flipping it applies on the next tick.
    "pr_autorebase_enabled": SettingSpec("PR Unsticker", live=True, order=2),
    # --- Branching & Release --------------------------------------------
    # Structural — captured into loop wiring at startup; change then restart.
    "staging_enabled": SettingSpec("Branching & Release", live=False, order=0),
    "staging_branch": SettingSpec("Branching & Release", live=False, order=1),
    "main_branch": SettingSpec("Branching & Release", live=False, order=2),
    "rc_cadence_hours": SettingSpec("Branching & Release", live=True, order=3),
    # Live: StagingBisectLoop reads the cap from config at the start of every
    # bisect run (#9580 — was PATCH-mutable-in-principle but operator-invisible).
    "staging_bisect_runtime_cap_seconds": SettingSpec(
        "Branching & Release", live=True, order=4
    ),
    # --- Reliability -----------------------------------------------------
    "gh_circuit_breaker_enabled": SettingSpec("Reliability", live=True, order=0),
    "merge_policy_enabled": SettingSpec("Reliability", live=True, order=1),
    "stale_code_alert_threshold": SettingSpec("Reliability", live=True, order=2),
    # Live: GitHubDataCache.get_issues_by_label re-reads the bound on every
    # call (#9814), so a change applies to the next cached read.
    "github_cache_issue_list_ttl_s": SettingSpec("Reliability", live=True, order=3),
    # Live: ImplementPhase re-reads this off its shared config on every dispatch
    # (#10778), so a toggle applies to the next slot fill.
    "dispatch_overlap_guard_enabled": SettingSpec("Reliability", live=True, order=4),
    # Self-repair defaults-on (feat/self-repair-on-by-default). These gate
    # issue-lifecycle reliability behaviours.
    # Restart-required: service_registry wires the PreconditionGate + the
    # CachingIssueStore wrapper at startup, so flipping these persists + needs a
    # restart to re-wire (honest "restart" badge).
    "precondition_gate_enabled": SettingSpec("Reliability", live=False, order=5),
    "caching_issue_store_enabled": SettingSpec("Reliability", live=False, order=6),
    # Live: PostMergeHandler re-reads close_verification off its shared config on
    # every merge event (reconcile_false_close(config=self._config, ...)).
    "close_verification_enabled": SettingSpec("Reliability", live=True, order=7),
    # --- Autonomy (self-repair / self-solve) -----------------------------
    # Restart-required: service_registry builds the give-up self-solver graph at
    # startup, so a toggle persists + needs a restart to re-wire.
    "giveup_window_enabled": SettingSpec("Autonomy", live=False, order=0),
    # Live: each loop re-reads the flag in its per-tick _do_work, so a toggle
    # applies on the next cycle without a restart.
    "sandbox_failure_fixer_enabled": SettingSpec("Autonomy", live=True, order=1),
    "escape_ledger_auto_diagnose_enabled": SettingSpec("Autonomy", live=True, order=2),
    # --- Governance (adjudication / independence / audit) ----------------
    # Live: ReviewPhase re-reads these off its shared config on every review
    # dispatch; the loops re-read their flags per tick.
    "judge_independence_enabled": SettingSpec("Governance", live=True, order=0),
    "judge_self_mod_fail_closed_enabled": SettingSpec("Governance", live=True, order=1),
    "sampled_audit_auto_adjudicate_enabled": SettingSpec(
        "Governance", live=True, order=2
    ),
    "wiki_anchor_prune_enabled": SettingSpec("Governance", live=True, order=3),
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
    # #11604 escalation gates on the DESTRUCTIVE path only — both re-read at
    # trip time, so tuning them never needs a restart.
    "event_loop_watchdog_restart_after_episodes": SettingSpec(
        "Event-Loop Watchdog", live=True, order=3
    ),
    "event_loop_watchdog_starvation_service_ratio": SettingSpec(
        "Event-Loop Watchdog", live=True, order=4
    ),
    # --- Goal Supervisor (Tier-2 liveness, ADR-0124) ----------------------
    # enabled: deploy-time kill-switch (captured at startup → restart badge).
    # interval: the cadence is re-read via interval_cb each cycle → live.
    "goal_supervisor_loop_enabled": SettingSpec("Goal Supervisor", live=False, order=0),
    "goal_supervisor_interval": SettingSpec("Goal Supervisor", live=True, order=1),
    # --- Branch GC (stale agent-branch reconciler, #10011) ----------------
    # Live: StaleIssueLoop re-reads these each tick, no restart needed.
    # delete_enabled defaults False (report/comment-only) since deletion is
    # destructive — this is the knob the operator flips to opt in.
    "branch_gc_stale_days": SettingSpec("Branch GC", live=True, order=0),
    "branch_gc_min_delete_age_days": SettingSpec("Branch GC", live=True, order=1),
    "branch_gc_delete_enabled": SettingSpec("Branch GC", live=True, order=2),
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
    # --- Repo Backend (per-repo model/harness override, #11211) -----------
    # Live: repo_backend.apply_repo_provider re-reads both at every spawn.
    "repo_provider": SettingSpec("Model Routing", live=True, order=70),
    "repo_model": SettingSpec("Model Routing", live=True, order=71),
    # --- Routing shadow (policy resolver observation, #11536 / ADR-0139) ---
    # Live: route_shadow re-reads the switch at every spawn seam, so turning it
    # off stops the next spawn's recording without a restart. Observation only —
    # it can never change which provider or model a spawn uses.
    "gateway_route_shadow_enabled": SettingSpec("Model Routing", live=True, order=80),
    # --- Routing policy workspace (#11538 / ADR-0140) ------------------------
    # Live: every policy route reads the dial per request, so closing it takes
    # effect on the next call without a restart. It gates the workspace only;
    # no routing decision reads it.
    "gateway_policy_workspace_enabled": SettingSpec(
        "Model Routing", live=True, order=81
    ),
    # --- Enforcement canary (#11539 / ADR-0141) -----------------------------
    # Live: route_enforcement re-reads it at every governed spawn seam, so
    # clearing it disarms enforcement on the NEXT spawn without a restart. That
    # liveness is the whole rollback story — an enforcement dial an operator has
    # to restart the factory to unset is not a canary switch.
    "gateway_enforcement_canary_repo": SettingSpec(
        "Model Routing", live=True, order=82
    ),
    # --- Issue Refinement (backlog dedup + priority scoring, #9957) ----------
    "issue_refinement_enabled": SettingSpec("Issue Refinement", live=True, order=0),
    "issue_refinement_pair_budget": SettingSpec("Issue Refinement", live=True, order=1),
    "issue_refinement_priority_budget": SettingSpec(
        "Issue Refinement", live=True, order=2
    ),
    "issue_refinement_model": SettingSpec("Issue Refinement", live=True, order=3),
    # --- Trust Fleet (heavy-make subprocess caps, #9555) ------------------
    # Live: each loop re-reads the cap from the live config at the start of
    # every heavy `make` invocation, and PATCH /api/control/config mutates
    # that same config instance in-place — an in-flight subprocess keeps its
    # original bound (correct semantics), the next one picks up the change.
    "skill_prompt_eval_adversarial_timeout_seconds": SettingSpec(
        "Trust Fleet", live=True, order=0
    ),
    "principles_audit_timeout_seconds": SettingSpec("Trust Fleet", live=True, order=1),
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


# --- Workflow sections (operator-legible grouping, #10786) ------------------
# The settings screen's fine-grained ``group`` is the source of truth for a
# field's home; the operator console's workflow-config panel wants a COARSER,
# stage/concern-oriented grouping on top of it. Rather than a UI-side allowlist
# (which would silently hide a newly registered field), the section is derived
# HERE from the group, so a new registry entry lands in a section automatically.
#
# ``build_settings_schema`` emits the derived section per row as an ADDITIVE
# ``section`` key; the existing ``group`` key is untouched, so the classic flat
# ``RuntimeSettingsPanel`` keeps working unchanged.
OTHER_SECTION = "Other"

GROUP_TO_SECTION: dict[str, str] = {
    "Work Queue": "Work Queue",
    "Concurrency": "Workers & Batch",
    "Scheduling": "Scheduling",
    "Models": "Model Routing",
    "Model Routing": "Model Routing",
    "CI & Quality": "CI & Quality",
    "Trust Fleet": "CI & Quality",
    "Prompt Refinement": "CI & Quality",
    "Issue Refinement": "CI & Quality",
    "PR Unsticker": "Merge & Release",
    "Branching & Release": "Merge & Release",
    "Reliability": "Safety & Reliability",
    "Autonomy": "Safety & Reliability",
    "Governance": "Safety & Reliability",
    "Event-Loop Watchdog": "Safety & Reliability",
    "Branch GC": "Safety & Reliability",
    "Paths": "Paths",
}


def section_for_group(group: str) -> str:
    """Map a settings ``group`` to its coarse workflow ``section``.

    Any group without an explicit mapping falls back to :data:`OTHER_SECTION`,
    so every registered field is guaranteed to land in some section — a field
    can never be silently dropped from the workflow-config panel.
    """
    return GROUP_TO_SECTION.get(group, OTHER_SECTION)


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
                "section": section_for_group(spec.group),
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
