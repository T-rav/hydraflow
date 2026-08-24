"""HydraFlow configuration via Pydantic."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

import file_util
from package_resources import ResourceNotFoundError, checkout_path
from queue_strategy import BandWeights, QueueStrategy
from scheduling_model import (
    ExecutionRuntime,
    SchedulingModel,
    resolve_preset,
)

logger = logging.getLogger("hydraflow.config")

# Branch prefix minted for Auto-Agent (preflight) sessions — see
# ``HydraFlowConfig.auto_agent_branch_for_issue``. Public (no leading
# underscore) so every module that mints or parses this namespace
# (``auto_agent_preflight_loop``, ``dependabot_merge_loop``,
# ``workspace_gc_loop``) shares one definition instead of duplicating the
# literal (#11182).
AUTO_AGENT_BRANCH_PREFIX = "agent/auto-agent-"


class Credentials(BaseModel):
    """Infrastructure credentials — separated from domain config.

    Holds raw secrets and connection strings that should never appear in
    domain-model serialization.  Built from environment variables at startup
    via ``build_credentials()``.
    """

    model_config = ConfigDict(frozen=True)

    gh_token: str = Field(
        default="",
        description="GitHub token for gh CLI auth",
    )
    whatsapp_token: str = Field(
        default="",
        description="WhatsApp Business API access token",
    )
    whatsapp_phone_id: str = Field(
        default="",
        description="WhatsApp Business API phone number ID",
    )
    whatsapp_recipient: str = Field(
        default="",
        description="WhatsApp recipient phone number (with country code)",
    )
    whatsapp_verify_token: str = Field(
        default="",
        description="WhatsApp webhook verification token",
    )
    whatsapp_app_secret: str = Field(
        default="",
        description="WhatsApp app secret used to verify X-Hub-Signature-256 webhook signatures",
    )


class ManagedRepo(BaseModel):
    """A GitHub repo under HydraFlow factory management.

    Source of truth for which repos the orchestrator dispatches
    pipelines against and which repos ``PrinciplesAuditLoop`` audits
    for drift + onboarding. See spec §4.4.
    """

    model_config = ConfigDict(frozen=True)

    slug: str = Field(description="GitHub slug 'owner/repo'")
    staging_branch: str = "staging"
    main_branch: str = "main"
    labels_namespace: str = ""
    enabled: bool = Field(
        default=True,
        description="Operator kill-switch per repo; disabled repos are skipped",
    )

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, v: str) -> str:
        parts = v.split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError(f"invalid slug {v!r}; expected 'owner/repo'")
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", v):
            raise ValueError(f"invalid slug {v!r}; expected 'owner/repo'")
        return v

    @field_validator("staging_branch", "main_branch")
    @classmethod
    def _validate_branch(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("branch name must be non-empty")
        return v


# Data-driven env-var override tables.
# Each tuple: (field_name, env_var_key, default_value)
_ENV_INT_OVERRIDES: list[tuple[str, str, int]] = [
    ("dashboard_port", "HYDRAFLOW_DASHBOARD_PORT", 5555),
    ("min_plan_words", "HYDRAFLOW_MIN_PLAN_WORDS", 60),
    ("max_plan_chars", "HYDRAFLOW_MAX_PLAN_CHARS", 5000),
    (
        "plan_design_decision_hitl_threshold",
        "HYDRAFLOW_PLAN_DESIGN_DECISION_HITL_THRESHOLD",
        2,
    ),
    (
        "max_pre_quality_review_attempts",
        "HYDRAFLOW_MAX_PRE_QUALITY_REVIEW_ATTEMPTS",
        3,
    ),
    ("max_diff_sanity_attempts", "HYDRAFLOW_MAX_DIFF_SANITY_ATTEMPTS", 1),
    ("max_scope_check_attempts", "HYDRAFLOW_MAX_SCOPE_CHECK_ATTEMPTS", 1),
    ("max_test_adequacy_attempts", "HYDRAFLOW_MAX_TEST_ADEQUACY_ATTEMPTS", 1),
    ("test_adequacy_repair_passes", "HYDRAFLOW_TEST_ADEQUACY_REPAIR_PASSES", 1),
    (
        "test_adequacy_coverage_timeout_secs",
        "HYDRAFLOW_TEST_ADEQUACY_COVERAGE_TIMEOUT_SECS",
        300,
    ),
    ("max_plan_compliance_attempts", "HYDRAFLOW_MAX_PLAN_COMPLIANCE_ATTEMPTS", 1),
    ("max_discover_attempts", "HYDRAFLOW_MAX_DISCOVER_ATTEMPTS", 3),
    ("max_discover_expansions", "HYDRAFLOW_MAX_DISCOVER_EXPANSIONS", 1),
    ("max_shape_attempts", "HYDRAFLOW_MAX_SHAPE_ATTEMPTS", 3),
    ("max_review_fix_attempts", "HYDRAFLOW_MAX_REVIEW_FIX_ATTEMPTS", 3),
    ("min_review_findings", "HYDRAFLOW_MIN_REVIEW_FINDINGS", 3),
    ("max_issue_body_chars", "HYDRAFLOW_MAX_ISSUE_BODY_CHARS", 10_000),
    ("max_review_diff_chars", "HYDRAFLOW_MAX_REVIEW_DIFF_CHARS", 15_000),
    ("gh_max_retries", "HYDRAFLOW_GH_MAX_RETRIES", 3),
    ("gh_api_concurrency", "HYDRAFLOW_GH_API_CONCURRENCY", 5),
    (
        "gh_circuit_breaker_max_failures",
        "HYDRAFLOW_GH_CIRCUIT_BREAKER_MAX_FAILURES",
        10,
    ),
    ("max_issue_attempts", "HYDRAFLOW_MAX_ISSUE_ATTEMPTS", 3),
    (
        "implement_no_progress_abort_attempts",
        "HYDRAFLOW_IMPLEMENT_NO_PROGRESS_ABORT_ATTEMPTS",
        1,
    ),
    ("max_decomposition_depth", "HYDRAFLOW_MAX_DECOMPOSITION_DEPTH", 2),
    (
        "max_total_decomposition_children",
        "HYDRAFLOW_MAX_TOTAL_DECOMPOSITION_CHILDREN",
        8,
    ),
    ("memory_sync_interval", "HYDRAFLOW_MEMORY_SYNC_INTERVAL", 3600),
    ("max_merge_conflict_fix_attempts", "HYDRAFLOW_MAX_MERGE_CONFLICT_FIX_ATTEMPTS", 3),
    ("max_ci_timeout_fix_attempts", "HYDRAFLOW_MAX_CI_TIMEOUT_FIX_ATTEMPTS", 2),
    ("data_poll_interval", "HYDRAFLOW_DATA_POLL_INTERVAL", 300),
    ("loop_startup_stagger_s", "HYDRAFLOW_LOOP_STARTUP_STAGGER_S", 120),
    ("max_sessions_per_repo", "HYDRAFLOW_MAX_SESSIONS_PER_REPO", 10),
    ("max_transcript_summary_chars", "HYDRAFLOW_MAX_TRANSCRIPT_SUMMARY_CHARS", 50_000),
    ("pr_unstick_interval", "HYDRAFLOW_PR_UNSTICK_INTERVAL", 3600),
    ("dependabot_merge_interval", "HYDRAFLOW_DEPENDABOT_MERGE_INTERVAL", 3600),
    (
        "dependabot_arch_autoheal_max_attempts",
        "HYDRAFLOW_DEPENDABOT_ARCH_AUTOHEAL_MAX_ATTEMPTS",
        2,
    ),
    ("report_issue_interval", "HYDRAFLOW_REPORT_ISSUE_INTERVAL", 30),
    ("stale_report_threshold_hours", "HYDRAFLOW_STALE_REPORT_THRESHOLD_HOURS", 6),
    ("epic_monitor_interval", "HYDRAFLOW_EPIC_MONITOR_INTERVAL", 1800),
    ("epic_sweep_interval", "HYDRAFLOW_EPIC_SWEEP_INTERVAL", 3600),
    ("workspace_gc_interval", "HYDRAFLOW_WORKTREE_GC_INTERVAL", 1800),
    (
        "worktree_gc_min_age_seconds",
        "HYDRAFLOW_WORKTREE_GC_MIN_AGE_SECONDS",
        1800,
    ),
    ("stale_issue_gc_interval", "HYDRAFLOW_STALE_ISSUE_GC_INTERVAL", 3600),
    ("stale_issue_threshold_days", "HYDRAFLOW_STALE_ISSUE_THRESHOLD_DAYS", 14),
    ("ci_monitor_interval", "HYDRAFLOW_CI_MONITOR_INTERVAL", 300),
    (
        "branch_protection_auditor_interval",
        "HYDRAFLOW_BRANCH_PROTECTION_AUDITOR_INTERVAL",
        604800,
    ),
    ("gate_activator_interval", "HYDRAFLOW_GATE_ACTIVATOR_INTERVAL", 604800),
    ("goal_supervisor_interval", "HYDRAFLOW_GOAL_SUPERVISOR_INTERVAL", 600),
    (
        "rails_drift_caretaker_interval",
        "HYDRAFLOW_RAILS_DRIFT_CARETAKER_INTERVAL",
        86400,
    ),
    ("rc_cadence_hours", "HYDRAFLOW_RC_CADENCE_HOURS", 4),
    (
        "rc_consecutive_failure_escalation_threshold",
        "HYDRAFLOW_RC_CONSECUTIVE_FAILURE_ESCALATION_THRESHOLD",
        3,
    ),
    ("staging_promotion_interval", "HYDRAFLOW_STAGING_PROMOTION_INTERVAL", 300),
    ("staging_rc_retention_days", "HYDRAFLOW_STAGING_RC_RETENTION_DAYS", 7),
    ("staging_bisect_interval", "HYDRAFLOW_STAGING_BISECT_INTERVAL", 600),
    (
        "staging_bisect_runtime_cap_seconds",
        "HYDRAFLOW_STAGING_BISECT_RUNTIME_CAP_SECONDS",
        2700,
    ),
    (
        "staging_bisect_watchdog_rc_cycles",
        "HYDRAFLOW_STAGING_BISECT_WATCHDOG_RC_CYCLES",
        2,
    ),
    (
        "loop_watchdog_default_seconds",
        "HYDRAFLOW_LOOP_WATCHDOG_DEFAULT_SECONDS",
        7200,
    ),
    ("loop_watchdog_llm_seconds", "HYDRAFLOW_LOOP_WATCHDOG_LLM_SECONDS", 14400),
    (
        "worker_stall_tight_multiplier",
        "HYDRAFLOW_WORKER_STALL_TIGHT_MULTIPLIER",
        2,
    ),
    (
        "boot_gap_alert_threshold_seconds",
        "HYDRAFLOW_BOOT_GAP_ALERT_THRESHOLD_SECONDS",
        600,
    ),
    ("collaborator_cache_ttl", "HYDRAFLOW_COLLABORATOR_CACHE_TTL", 600),
    (
        "issue_cache_enrich_ttl_seconds",
        "HYDRAFLOW_ISSUE_CACHE_ENRICH_TTL_SECONDS",
        300,
    ),
    ("artifact_retention_days", "HYDRAFLOW_ARTIFACT_RETENTION_DAYS", 30),
    ("artifact_max_size_mb", "HYDRAFLOW_ARTIFACT_MAX_SIZE_MB", 500),
    ("runs_gc_interval", "HYDRAFLOW_RUNS_GC_INTERVAL", 3600),
    ("gate_health_interval", "HYDRAFLOW_GATE_HEALTH_INTERVAL", 604800),
    (
        "gate_health_max_issues_per_tick",
        "HYDRAFLOW_GATE_HEALTH_MAX_ISSUES_PER_TICK",
        5,
    ),
    ("gate_health_run_window", "HYDRAFLOW_GATE_HEALTH_RUN_WINDOW", 50),
    ("gate_health_min_attempts", "HYDRAFLOW_GATE_HEALTH_MIN_ATTEMPTS", 3),
    (
        "gate_health_hang_tolerance_seconds",
        "HYDRAFLOW_GATE_HEALTH_HANG_TOLERANCE_SECONDS",
        90,
    ),
    ("pr_red_repair_interval", "HYDRAFLOW_PR_RED_REPAIR_INTERVAL", 300),
    ("pr_red_rerun_max_attempts", "HYDRAFLOW_PR_RED_RERUN_MAX_ATTEMPTS", 2),
    (
        "pr_red_repair_dispatch_max_attempts",
        "HYDRAFLOW_PR_RED_REPAIR_DISPATCH_MAX_ATTEMPTS",
        2,
    ),
    ("erosion_metrics_interval", "HYDRAFLOW_EROSION_METRICS_INTERVAL", 86400),
    (
        "erosion_metrics_max_issues_per_tick",
        "HYDRAFLOW_EROSION_METRICS_MAX_ISSUES_PER_TICK",
        3,
    ),
    ("fail_open_monitor_interval", "HYDRAFLOW_FAIL_OPEN_MONITOR_INTERVAL", 14400),
    (
        "fail_open_monitor_max_issues_per_tick",
        "HYDRAFLOW_FAIL_OPEN_MONITOR_MAX_ISSUES_PER_TICK",
        2,
    ),
    ("escape_ledger_interval", "HYDRAFLOW_ESCAPE_LEDGER_INTERVAL", 14400),
    (
        "escape_ledger_max_issues_per_tick",
        "HYDRAFLOW_ESCAPE_LEDGER_MAX_ISSUES_PER_TICK",
        3,
    ),
    (
        "escape_ledger_encoding_age_days",
        "HYDRAFLOW_ESCAPE_LEDGER_ENCODING_AGE_DAYS",
        14,
    ),
    (
        "escape_ledger_max_diagnoses_per_tick",
        "HYDRAFLOW_ESCAPE_LEDGER_MAX_DIAGNOSES_PER_TICK",
        25,
    ),
    ("intervention_tally_interval", "HYDRAFLOW_INTERVENTION_TALLY_INTERVAL", 86400),
    (
        "intervention_tally_max_classify_per_tick",
        "HYDRAFLOW_INTERVENTION_TALLY_MAX_CLASSIFY_PER_TICK",
        5,
    ),
    ("sampled_audit_interval", "HYDRAFLOW_SAMPLED_AUDIT_INTERVAL", 14400),
    (
        "sampled_audit_max_issues_per_tick",
        "HYDRAFLOW_SAMPLED_AUDIT_MAX_ISSUES_PER_TICK",
        3,
    ),
    (
        "sampled_audit_token_budget_per_tick",
        "HYDRAFLOW_SAMPLED_AUDIT_TOKEN_BUDGET_PER_TICK",
        40000,
    ),
    (
        "second_order_vitals_interval",
        "HYDRAFLOW_SECOND_ORDER_VITALS_INTERVAL",
        86400,
    ),
    (
        "second_order_vitals_window_days",
        "HYDRAFLOW_SECOND_ORDER_VITALS_WINDOW_DAYS",
        7,
    ),
    (
        "second_order_vitals_min_baseline_windows",
        "HYDRAFLOW_SECOND_ORDER_VITALS_MIN_BASELINE_WINDOWS",
        8,
    ),
    (
        "second_order_vitals_sustained_windows",
        "HYDRAFLOW_SECOND_ORDER_VITALS_SUSTAINED_WINDOWS",
        2,
    ),
    (
        "second_order_vitals_watch_k",
        "HYDRAFLOW_SECOND_ORDER_VITALS_WATCH_K",
        2,
    ),
    (
        "second_order_vitals_diverging_k",
        "HYDRAFLOW_SECOND_ORDER_VITALS_DIVERGING_K",
        3,
    ),
    (
        "second_order_vitals_history_max",
        "HYDRAFLOW_SECOND_ORDER_VITALS_HISTORY_MAX",
        120,
    ),
    (
        "second_order_vitals_min_merge_throughput",
        "HYDRAFLOW_SECOND_ORDER_VITALS_MIN_MERGE_THROUGHPUT",
        1,
    ),
    ("adr_review_interval", "HYDRAFLOW_ADR_REVIEW_INTERVAL", 86400),
    ("adr_review_approval_threshold", "HYDRAFLOW_ADR_REVIEW_APPROVAL_THRESHOLD", 2),
    ("adr_review_max_rounds", "HYDRAFLOW_ADR_REVIEW_MAX_ROUNDS", 3),
    ("pr_unstick_batch_size", "HYDRAFLOW_PR_UNSTICK_BATCH_SIZE", 10),
    ("harness_insight_window", "HYDRAFLOW_HARNESS_INSIGHT_WINDOW", 20),
    ("harness_pattern_threshold", "HYDRAFLOW_HARNESS_PATTERN_THRESHOLD", 3),
    ("max_runtime_log_chars", "HYDRAFLOW_MAX_RUNTIME_LOG_CHARS", 8_000),
    ("max_ci_log_chars", "HYDRAFLOW_MAX_CI_LOG_CHARS", 12_000),
    ("max_code_scanning_chars", "HYDRAFLOW_MAX_CODE_SCANNING_CHARS", 6_000),
    ("visual_max_retries", "HYDRAFLOW_VISUAL_MAX_RETRIES", 2),
    ("agent_timeout", "HYDRAFLOW_AGENT_TIMEOUT", 3600),
    ("transcript_summary_timeout", "HYDRAFLOW_TRANSCRIPT_SUMMARY_TIMEOUT", 120),
    ("quality_timeout", "HYDRAFLOW_QUALITY_TIMEOUT", 3600),
    ("git_command_timeout", "HYDRAFLOW_GIT_COMMAND_TIMEOUT", 30),
    ("salvage_commit_timeout", "HYDRAFLOW_SALVAGE_COMMIT_TIMEOUT", 1800),
    ("summarizer_timeout", "HYDRAFLOW_SUMMARIZER_TIMEOUT", 120),
    ("wiki_compilation_timeout", "HYDRAFLOW_WIKI_COMPILATION_TIMEOUT", 300),
    ("error_output_max_chars", "HYDRAFLOW_ERROR_OUTPUT_MAX_CHARS", 3000),
    (
        "max_troubleshooting_prompt_chars",
        "HYDRAFLOW_MAX_TROUBLESHOOTING_PROMPT_CHARS",
        3000,
    ),
    # Prompt budget configuration
    ("max_discussion_comment_chars", "HYDRAFLOW_MAX_DISCUSSION_COMMENT_CHARS", 500),
    ("max_common_feedback_chars", "HYDRAFLOW_MAX_COMMON_FEEDBACK_CHARS", 2_000),
    ("max_impl_plan_chars", "HYDRAFLOW_MAX_IMPL_PLAN_CHARS", 6_000),
    ("max_review_feedback_chars", "HYDRAFLOW_MAX_REVIEW_FEEDBACK_CHARS", 2_000),
    ("max_planner_comment_chars", "HYDRAFLOW_MAX_PLANNER_COMMENT_CHARS", 1_000),
    ("max_planner_line_chars", "HYDRAFLOW_MAX_PLANNER_LINE_CHARS", 500),
    ("max_planner_failed_plan_chars", "HYDRAFLOW_MAX_PLANNER_FAILED_PLAN_CHARS", 4_000),
    ("max_hitl_correction_chars", "HYDRAFLOW_MAX_HITL_CORRECTION_CHARS", 4_000),
    ("max_hitl_cause_chars", "HYDRAFLOW_MAX_HITL_CAUSE_CHARS", 2_000),
    ("max_ci_log_prompt_chars", "HYDRAFLOW_MAX_CI_LOG_PROMPT_CHARS", 6_000),
    ("max_unsticker_cause_chars", "HYDRAFLOW_MAX_UNSTICKER_CAUSE_CHARS", 3_000),
    (
        "max_verification_instructions_chars",
        "HYDRAFLOW_MAX_VERIFICATION_INSTRUCTIONS_CHARS",
        50_000,
    ),
    ("health_monitor_interval", "HYDRAFLOW_HEALTH_MONITOR_INTERVAL", 7200),
    ("wiki_freshness_stale_days", "HYDRAFLOW_WIKI_FRESHNESS_STALE_DAYS", 7),
    ("stale_code_alert_threshold", "HYDRAFLOW_STALE_CODE_ALERT_THRESHOLD", 10),
    ("stale_issue_interval", "HYDRAFLOW_STALE_ISSUE_INTERVAL", 86400),
    (
        "stale_issue_regression_rot_stale_days",
        "HYDRAFLOW_STALE_ISSUE_REGRESSION_ROT_STALE_DAYS",
        14,
    ),
    ("branch_gc_stale_days", "HYDRAFLOW_BRANCH_GC_STALE_DAYS", 3),
    (
        "branch_gc_min_delete_age_days",
        "HYDRAFLOW_BRANCH_GC_MIN_DELETE_AGE_DAYS",
        14,
    ),
    ("auditor_finding_max_age_days", "HYDRAFLOW_AUDITOR_FINDING_MAX_AGE_DAYS", 14),
    ("triage_max_turns", "HYDRAFLOW_TRIAGE_MAX_TURNS", 12),
    ("triage_retry_interval", "HYDRAFLOW_TRIAGE_RETRY_INTERVAL", 86400),
    (
        "triage_retry_max_issues_per_tick",
        "HYDRAFLOW_TRIAGE_RETRY_MAX_ISSUES_PER_TICK",
        5,
    ),
    ("triage_retry_max_attempts", "HYDRAFLOW_TRIAGE_RETRY_MAX_ATTEMPTS", 3),
    ("triage_infra_retry_interval", "HYDRAFLOW_TRIAGE_INFRA_RETRY_INTERVAL", 900),
    ("log_ingest_interval", "LOG_INGEST_INTERVAL", 14400),
    ("log_ingest_warning_min_count", "LOG_INGEST_WARNING_MIN_COUNT", 50),
    ("log_ingest_max_issues_per_run", "LOG_INGEST_MAX_ISSUES_PER_RUN", 3),
    ("security_patch_interval", "HYDRAFLOW_SECURITY_PATCH_INTERVAL", 3600),
    ("repo_wiki_interval", "HYDRAFLOW_REPO_WIKI_INTERVAL", 3600),
    (
        "dependabot_update_branch_max_attempts",
        "HYDRAFLOW_DEPENDABOT_UPDATE_BRANCH_MAX_ATTEMPTS",
        1,
    ),
    ("review_orphan_strike_threshold", "HYDRAFLOW_REVIEW_ORPHAN_STRIKE_THRESHOLD", 3),
    ("review_orphan_max_requeues", "HYDRAFLOW_REVIEW_ORPHAN_MAX_REQUEUES", 3),
    (
        "credit_fp_suppress_cooldown_seconds",
        "HYDRAFLOW_CREDIT_FP_SUPPRESS_COOLDOWN_SECONDS",
        300,
    ),
    ("repo_wiki_min_batch_files", "HYDRAFLOW_REPO_WIKI_MIN_BATCH_FILES", 8),
    ("repo_wiki_max_batch_age_hours", "HYDRAFLOW_REPO_WIKI_MAX_BATCH_AGE_HOURS", 24),
    ("max_repo_wiki_chars", "HYDRAFLOW_MAX_REPO_WIKI_CHARS", 15_000),
    ("diagnostic_interval", "HYDRAFLOW_DIAGNOSTIC_INTERVAL", 30),
    ("retrospective_interval", "HYDRAFLOW_RETROSPECTIVE_INTERVAL", 86400),
    ("principles_audit_interval", "HYDRAFLOW_PRINCIPLES_AUDIT_INTERVAL", 604800),
    (
        "principles_audit_max_issues_per_tick",
        "HYDRAFLOW_PRINCIPLES_AUDIT_MAX_ISSUES_PER_TICK",
        5,
    ),
    ("principles_audit_timeout_seconds", "HYDRAFLOW_PRINCIPLES_AUDIT_TIMEOUT", 1800),
    (
        "sandbox_failure_fixer_interval",
        "HYDRAFLOW_SANDBOX_FAILURE_FIXER_INTERVAL",
        3600,
    ),
    ("detector_calibration_interval", "HYDRAFLOW_DETECTOR_CALIBRATION_INTERVAL", 86400),
    (
        "detector_calibration_max_issues_per_tick",
        "HYDRAFLOW_DETECTOR_CALIBRATION_MAX_ISSUES_PER_TICK",
        3,
    ),
    (
        "detector_calibration_spray_min_entities",
        "HYDRAFLOW_DETECTOR_CALIBRATION_SPRAY_MIN_ENTITIES",
        5,
    ),
    ("gateway_coverage_interval", "HYDRAFLOW_GATEWAY_COVERAGE_INTERVAL", 3600),
    ("gateway_key_ttl_seconds", "HYDRAFLOW_GATEWAY_KEY_TTL_SECONDS", 3660),
    ("auto_agent_preflight_interval", "HYDRAFLOW_AUTO_AGENT_PREFLIGHT_INTERVAL", 120),
    ("auto_agent_max_attempts", "HYDRAFLOW_AUTO_AGENT_MAX_ATTEMPTS", 3),
    (
        "auto_agent_redrive_max_attempts",
        "HYDRAFLOW_AUTO_AGENT_REDRIVE_MAX_ATTEMPTS",
        1,
    ),
    ("auto_agent_redrive_ttl_days", "HYDRAFLOW_AUTO_AGENT_REDRIVE_TTL_DAYS", 5),
    (
        "auto_agent_redrive_human_quiet_days",
        "HYDRAFLOW_AUTO_AGENT_REDRIVE_HUMAN_QUIET_DAYS",
        2,
    ),
    (
        "auto_pr_preflight_stage_timeout_s",
        "HYDRAFLOW_AUTO_PR_PREFLIGHT_STAGE_TIMEOUT_S",
        600,
    ),
    ("pr_base_max_age_days", "HYDRAFLOW_PR_BASE_MAX_AGE_DAYS", 3),
    ("flake_tracker_interval", "HYDRAFLOW_FLAKE_TRACKER_INTERVAL", 14400),
    ("flake_threshold", "HYDRAFLOW_FLAKE_THRESHOLD", 3),
    ("xdist_quarantine_threshold", "HYDRAFLOW_XDIST_QUARANTINE_THRESHOLD", 2),
    ("skill_prompt_eval_interval", "HYDRAFLOW_SKILL_PROMPT_EVAL_INTERVAL", 604800),
    (
        "skill_prompt_eval_adversarial_timeout_seconds",
        "HYDRAFLOW_SKILL_PROMPT_EVAL_TIMEOUT",
        3600,
    ),
    (
        "skill_prompt_refine_max_weekly",
        "HYDRAFLOW_SKILL_PROMPT_REFINE_MAX_WEEKLY",
        2,
    ),
    (
        "fake_coverage_auditor_interval",
        "HYDRAFLOW_FAKE_COVERAGE_AUDITOR_INTERVAL",
        604800,
    ),
    (
        "memory_backlog_interval_seconds",
        "HYDRAFLOW_MEMORY_BACKLOG_INTERVAL",
        86_400,
    ),
    (
        "memory_backlog_max_issues_per_tick",
        "HYDRAFLOW_MEMORY_BACKLOG_MAX_ISSUES_PER_TICK",
        5,
    ),
    ("rc_budget_interval", "HYDRAFLOW_RC_BUDGET_INTERVAL", 14400),
    ("wiki_rot_detector_interval", "HYDRAFLOW_WIKI_ROT_DETECTOR_INTERVAL", 604800),
    (
        "wiki_rot_detector_max_issues_per_tick",
        "HYDRAFLOW_WIKI_ROT_DETECTOR_MAX_ISSUES_PER_TICK",
        10,
    ),
    (
        "adr_conformance_interval",
        "HYDRAFLOW_ADR_CONFORMANCE_INTERVAL",
        86400,
    ),
    ("term_proposer_interval", "HYDRAFLOW_TERM_PROPOSER_INTERVAL", 14400),
    ("term_proposer_max_per_tick", "HYDRAFLOW_TERM_PROPOSER_MAX_PER_TICK", 10),
    ("term_proposer_timeout", "HYDRAFLOW_TERM_PROPOSER_TIMEOUT", 180),
    (
        "term_proposer_cooldown_seconds",
        "HYDRAFLOW_TERM_PROPOSER_COOLDOWN_SECONDS",
        86400,
    ),
    ("term_pruner_interval", "HYDRAFLOW_TERM_PRUNER_INTERVAL", 86400),
    ("edge_proposer_interval", "HYDRAFLOW_EDGE_PROPOSER_INTERVAL", 86400),
    ("entry_evidence_interval", "HYDRAFLOW_ENTRY_EVIDENCE_INTERVAL", 86400),
    (
        "entry_evidence_max_entries_per_tick",
        "HYDRAFLOW_ENTRY_EVIDENCE_MAX_ENTRIES_PER_TICK",
        20,
    ),
    ("trust_fleet_sanity_interval", "HYDRAFLOW_TRUST_FLEET_SANITY_INTERVAL", 600),
    ("label_drift_watcher_interval", "HYDRAFLOW_LABEL_DRIFT_WATCHER_INTERVAL", 600),
    ("loop_anomaly_issues_per_hour", "HYDRAFLOW_LOOP_ANOMALY_ISSUES_PER_HOUR", 10),
    (
        "loop_anomaly_repair_min_sample",
        "HYDRAFLOW_LOOP_ANOMALY_REPAIR_MIN_SAMPLE",
        3,
    ),
    (
        "loop_anomaly_tick_error_min_sample",
        "HYDRAFLOW_LOOP_ANOMALY_TICK_ERROR_MIN_SAMPLE",
        3,
    ),
    (
        "loop_anomaly_hitl_low_severity_count",
        "HYDRAFLOW_LOOP_ANOMALY_HITL_LOW_SEVERITY_COUNT",
        3,
    ),
    ("corpus_learning_interval", "HYDRAFLOW_CORPUS_LEARNING_INTERVAL", 3600),
    ("contract_refresh_interval", "HYDRAFLOW_CONTRACT_REFRESH_INTERVAL", 604800),
    ("max_fake_repair_attempts", "HYDRAFLOW_MAX_FAKE_REPAIR_ATTEMPTS", 3),
    ("max_convergence_laps", "HYDRAFLOW_MAX_CONVERGENCE_LAPS", 3),
    (
        "convergence_oscillation_interval",
        "HYDRAFLOW_CONVERGENCE_OSCILLATION_INTERVAL",
        3600,
    ),
    (
        "convergence_oscillation_max_issues_per_tick",
        "HYDRAFLOW_CONVERGENCE_OSCILLATION_MAX_ISSUES_PER_TICK",
        3,
    ),
    (
        "convergence_oscillation_window",
        "HYDRAFLOW_CONVERGENCE_OSCILLATION_WINDOW",
        2,
    ),
    (
        "convergence_oscillation_min_loopback_stages",
        "HYDRAFLOW_CONVERGENCE_OSCILLATION_MIN_LOOPBACK_STAGES",
        2,
    ),
    ("fitness_scorecard_interval", "HYDRAFLOW_FITNESS_SCORECARD_INTERVAL", 86400),
    ("fitness_window_days", "HYDRAFLOW_FITNESS_WINDOW_DAYS", 30),
    ("fitness_min_samples", "HYDRAFLOW_FITNESS_MIN_SAMPLES", 5),
    ("auto_tighten_stability_ticks", "HYDRAFLOW_AUTO_TIGHTEN_STABILITY_TICKS", 3),
    ("auto_tighten_interval", "HYDRAFLOW_AUTO_TIGHTEN_INTERVAL", 86400),
    ("issue_refinement_interval", "HYDRAFLOW_ISSUE_REFINEMENT_INTERVAL", 86400),
    (
        "issue_refinement_full_sweep_interval",
        "HYDRAFLOW_ISSUE_REFINEMENT_FULL_SWEEP_INTERVAL",
        604800,
    ),
    ("issue_refinement_pair_budget", "HYDRAFLOW_ISSUE_REFINEMENT_PAIR_BUDGET", 24),
    (
        "issue_refinement_priority_budget",
        "HYDRAFLOW_ISSUE_REFINEMENT_PRIORITY_BUDGET",
        50,
    ),
    # Work-queue band-draw weights (#10037); see queue_strategy.BandWeights.
    ("queue_weight_p1", "HYDRAFLOW_QUEUE_WEIGHT_P1", 3),
    ("queue_weight_p2", "HYDRAFLOW_QUEUE_WEIGHT_P2", 2),
    ("queue_weight_unprioritised", "HYDRAFLOW_QUEUE_WEIGHT_UNPRIORITISED", 1),
]

_ENV_STR_OVERRIDES: list[tuple[str, str, str]] = [
    ("gateway_base_url", "HYDRAFLOW_GATEWAY_BASE_URL", "http://127.0.0.1:8080"),
    ("gateway_ledger_path", "HYDRAFLOW_GATEWAY_LEDGER_PATH", ""),
    ("gateway_repo_class", "HYDRAFLOW_GATEWAY_REPO_CLASS", "personal"),
    ("judge_independent_model", "HYDRAFLOW_JUDGE_INDEPENDENT_MODEL", ""),
    (
        "security_patch_severity_threshold",
        "HYDRAFLOW_SECURITY_PATCH_SEVERITY_THRESHOLD",
        "medium",
    ),
    ("sampled_audit_model", "HYDRAFLOW_SAMPLED_AUDIT_MODEL", ""),
    ("dashboard_host", "HYDRAFLOW_DASHBOARD_HOST", "127.0.0.1"),
    ("test_command", "HYDRAFLOW_TEST_COMMAND", "make test"),
    ("docker_image", "HYDRAFLOW_DOCKER_IMAGE", "ghcr.io/t-rav/hydraflow-agent:latest"),
    ("docker_network", "HYDRAFLOW_DOCKER_NETWORK", ""),
    ("changelog_file", "HYDRAFLOW_CHANGELOG_FILE", ""),
    ("release_tag_prefix", "HYDRAFLOW_RELEASE_TAG_PREFIX", "v"),
    ("main_branch", "HYDRAFLOW_MAIN_BRANCH", "main"),
    ("staging_branch", "HYDRAFLOW_STAGING_BRANCH", "staging"),
    ("rc_branch_prefix", "HYDRAFLOW_RC_BRANCH_PREFIX", "rc/"),
    ("repos_workspace_dir", "HYDRAFLOW_REPOS_WORKSPACE_DIR", "~/.hydra/repos"),
    ("log_ingest_label", "HYDRAFLOW_LOG_INGEST_LABEL", "hydraflow-log-ingest"),
    (
        "log_ingest_benign_patterns",
        "HYDRAFLOW_LOG_INGEST_BENIGN_PATTERNS",
        (
            "adapter pending,auth failed,authentication failed,"
            "repository not found,credit,creditexhausted,hydraflow.log_ingest"
        ),
    ),
    ("log_ingest_log_files", "HYDRAFLOW_LOG_INGEST_LOG_FILES", "logs/hydraflow.log"),
    ("repo_data_class", "HYDRAFLOW_REPO_DATA_CLASS", "internal"),
    ("regulated_labels", "HYDRAFLOW_REGULATED_LABELS", ""),
    ("dashboard_url", "HYDRAFLOW_DASHBOARD_URL", "http://localhost:5555"),
    ("issue_refinement_model", "HYDRAFLOW_ISSUE_REFINEMENT_MODEL", ""),
    ("skill_prompt_refine_model", "HYDRAFLOW_SKILL_PROMPT_REFINE_MODEL", ""),
    ("intervention_tally_model", "HYDRAFLOW_INTERVENTION_TALLY_MODEL", ""),
]

_ENV_FLOAT_OVERRIDES: list[tuple[str, str, float]] = [
    (
        "second_order_vitals_min_ci_pass_rate",
        "HYDRAFLOW_SECOND_ORDER_VITALS_MIN_CI_PASS_RATE",
        0.5,
    ),
    ("docker_cpu_limit", "HYDRAFLOW_DOCKER_CPU_LIMIT", 2.0),
    ("docker_spawn_delay", "HYDRAFLOW_DOCKER_SPAWN_DELAY", 2.0),
    ("visual_retry_delay", "HYDRAFLOW_VISUAL_RETRY_DELAY", 2.0),
    ("rc_budget_threshold_ratio", "HYDRAFLOW_RC_BUDGET_THRESHOLD_RATIO", 1.5),
    ("rc_budget_spike_ratio", "HYDRAFLOW_RC_BUDGET_SPIKE_RATIO", 2.0),
    ("loop_anomaly_repair_ratio", "HYDRAFLOW_LOOP_ANOMALY_REPAIR_RATIO", 2.0),
    (
        "loop_anomaly_staleness_multiplier",
        "HYDRAFLOW_LOOP_ANOMALY_STALENESS_MULTIPLIER",
        2.0,
    ),
    ("loop_anomaly_cost_spike_ratio", "HYDRAFLOW_LOOP_ANOMALY_COST_SPIKE_RATIO", 5.0),
    (
        "cost_plausibility_max_rate_multiple",
        "HYDRAFLOW_COST_PLAUSIBILITY_MAX_RATE_MULTIPLE",
        3.0,
    ),
    (
        "gh_circuit_breaker_reset_timeout_s",
        "HYDRAFLOW_GH_CIRCUIT_BREAKER_RESET_TIMEOUT_S",
        60.0,
    ),
    (
        "github_cache_issue_list_ttl_s",
        "HYDRAFLOW_GITHUB_CACHE_ISSUE_LIST_TTL_S",
        900.0,
    ),
    ("auto_tighten_coverage_margin", "HYDRAFLOW_AUTO_TIGHTEN_COVERAGE_MARGIN", 1.0),
    (
        "auto_agent_redrive_backoff_multiplier",
        "HYDRAFLOW_AUTO_AGENT_REDRIVE_BACKOFF_MULTIPLIER",
        3.0,
    ),
    # Work-queue starvation valve (#10037): hours before weighted_mix promotes.
    (
        "queue_starvation_threshold_hours",
        "HYDRAFLOW_QUEUE_STARVATION_THRESHOLD_HOURS",
        168.0,
    ),
]

# Optional floats — `None` when env var is missing/empty/invalid.
# Handled separately from the strictly-typed float table because pydantic's
# `float | None` fields don't participate in the `default == current` check.
_ENV_OPT_FLOAT_OVERRIDES: list[tuple[str, str, float | None]] = [
    ("auto_agent_cost_cap_usd", "HYDRAFLOW_AUTO_AGENT_COST_CAP_USD", None),
    ("auto_agent_daily_budget_usd", "HYDRAFLOW_AUTO_AGENT_DAILY_BUDGET_USD", None),
    ("daily_cost_budget_usd", "HYDRAFLOW_DAILY_COST_BUDGET_USD", None),
    ("issue_cost_alert_usd", "HYDRAFLOW_ISSUE_COST_ALERT_USD", None),
]

# Optional ints — `None` when env var is missing/empty/invalid. Mirrors
# _ENV_OPT_FLOAT_OVERRIDES; ge=1 is enforced by the pydantic constraint on
# the field, with out-of-range env values rejected here (warn + default).
_ENV_OPT_INT_OVERRIDES: list[tuple[str, str, int | None]] = [
    (
        "audit_retention_days_preflight",
        "HYDRAFLOW_AUDIT_RETENTION_DAYS_PREFLIGHT",
        None,
    ),
    (
        "audit_retention_days_health_decisions",
        "HYDRAFLOW_AUDIT_RETENTION_DAYS_HEALTH_DECISIONS",
        None,
    ),
    (
        "audit_retention_days_inference_telemetry",
        "HYDRAFLOW_AUDIT_RETENTION_DAYS_INFERENCE_TELEMETRY",
        None,
    ),
    (
        "audit_retention_days_approval_records",
        "HYDRAFLOW_AUDIT_RETENTION_DAYS_APPROVAL_RECORDS",
        None,
    ),
    (
        "audit_retention_days_evidence_packs",
        "HYDRAFLOW_AUDIT_RETENTION_DAYS_EVIDENCE_PACKS",
        None,
    ),
]

# Float overrides with tight [0, 1] bounds — handled separately from the
# parametrized table because the generic test adds ``default + 1.0`` which
# exceeds their upper bound.
_ENV_FLOAT_RATIO_OVERRIDES: list[tuple[str, str, float]] = [
    ("visual_warn_threshold", "HYDRAFLOW_VISUAL_WARN_THRESHOLD", 0.05),
    ("visual_fail_threshold", "HYDRAFLOW_VISUAL_FAIL_THRESHOLD", 0.15),
    ("loop_anomaly_tick_error_ratio", "HYDRAFLOW_LOOP_ANOMALY_TICK_ERROR_RATIO", 0.2),
    ("cost_throttle_ratio", "HYDRAFLOW_COST_THROTTLE_RATIO", 0.8),
]

# Formal give-up window thresholds (#10735) — one N-in-T pair per child-class.
_ENV_INT_OVERRIDES += [
    ("giveup_build_max_restarts", "HYDRAFLOW_GIVEUP_BUILD_MAX_RESTARTS", 3),
    ("giveup_build_window_secs", "HYDRAFLOW_GIVEUP_BUILD_WINDOW_SECS", 3600),
    ("giveup_review_max_restarts", "HYDRAFLOW_GIVEUP_REVIEW_MAX_RESTARTS", 3),
    ("giveup_review_window_secs", "HYDRAFLOW_GIVEUP_REVIEW_WINDOW_SECS", 3600),
    ("giveup_loop_max_restarts", "HYDRAFLOW_GIVEUP_LOOP_MAX_RESTARTS", 5),
    ("giveup_loop_window_secs", "HYDRAFLOW_GIVEUP_LOOP_WINDOW_SECS", 3600),
    ("giveup_plan_retry_max_restarts", "HYDRAFLOW_GIVEUP_PLAN_RETRY_MAX_RESTARTS", 2),
    ("giveup_plan_retry_window_secs", "HYDRAFLOW_GIVEUP_PLAN_RETRY_WINDOW_SECS", 3600),
]

_ENV_BOOL_OVERRIDES: list[tuple[str, str, bool]] = [
    ("dry_run", "HYDRAFLOW_DRY_RUN", False),
    ("factory_autostart", "HYDRAFLOW_FACTORY_AUTOSTART", True),
    (
        "test_adequacy_verifier_enabled",
        "HYDRAFLOW_TEST_ADEQUACY_VERIFIER_ENABLED",
        True,
    ),
    (
        "test_adequacy_verifier_fail_closed",
        "HYDRAFLOW_TEST_ADEQUACY_VERIFIER_FAIL_CLOSED",
        True,
    ),
    ("test_adequacy_pin_demand", "HYDRAFLOW_TEST_ADEQUACY_PIN_DEMAND", True),
    ("triage_blocker_gate_enabled", "HYDRAFLOW_TRIAGE_BLOCKER_GATE_ENABLED", True),
    ("triage_honeypot_enabled", "HYDRAFLOW_TRIAGE_HONEYPOT_ENABLED", True),
    ("triage_honeypot_enforce", "HYDRAFLOW_TRIAGE_HONEYPOT_ENFORCE", False),
    ("approval_records_enabled", "HYDRAFLOW_APPROVAL_RECORDS_ENABLED", True),
    ("evidence_pack_enabled", "HYDRAFLOW_EVIDENCE_PACK_ENABLED", True),
    ("merge_policy_enabled", "HYDRAFLOW_MERGE_POLICY_ENABLED", True),
    (
        "close_verification_enabled",
        "HYDRAFLOW_CLOSE_VERIFICATION_ENABLED",
        True,
    ),
    ("sensor_enrichment_enabled", "HYDRAFLOW_SENSOR_ENRICHMENT_ENABLED", True),
    ("gh_circuit_breaker_enabled", "HYDRAFLOW_GH_CIRCUIT_BREAKER_ENABLED", True),
    ("issue_cache_enabled", "HYDRAFLOW_ISSUE_CACHE_ENABLED", True),
    (
        "caching_issue_store_enabled",
        "HYDRAFLOW_CACHING_ISSUE_STORE_ENABLED",
        False,
    ),
    (
        "precondition_gate_enabled",
        "HYDRAFLOW_PRECONDITION_GATE_ENABLED",
        False,
    ),
    (
        "giveup_window_enabled",
        "HYDRAFLOW_GIVEUP_WINDOW_ENABLED",
        True,
    ),
    (
        "credit_failover_enabled",
        "HYDRAFLOW_CREDIT_FAILOVER_ENABLED",
        True,
    ),
    ("docker_read_only_root", "HYDRAFLOW_DOCKER_READ_ONLY_ROOT", True),
    ("docker_no_new_privileges", "HYDRAFLOW_DOCKER_NO_NEW_PRIVILEGES", True),
    (
        "transcript_summarization_enabled",
        "HYDRAFLOW_TRANSCRIPT_SUMMARIZATION_ENABLED",
        True,
    ),
    ("unstick_auto_merge", "HYDRAFLOW_UNSTICK_AUTO_MERGE", True),
    ("unstick_all_causes", "HYDRAFLOW_UNSTICK_ALL_CAUSES", True),
    (
        "enable_fresh_branch_rebuild",
        "HYDRAFLOW_ENABLE_FRESH_BRANCH_REBUILD",
        True,
    ),
    (
        "branch_gc_delete_enabled",
        "HYDRAFLOW_BRANCH_GC_DELETE_ENABLED",
        True,
    ),
    ("collaborator_check_enabled", "HYDRAFLOW_COLLABORATOR_CHECK_ENABLED", True),
    ("prompt_observatory_enabled", "HYDRAFLOW_PROMPT_OBSERVATORY_ENABLED", True),
    ("visual_gate_enabled", "HYDRAFLOW_VISUAL_GATE_ENABLED", False),
    ("visual_gate_bypass", "HYDRAFLOW_VISUAL_GATE_BYPASS", False),
    ("visual_validation_enabled", "HYDRAFLOW_VISUAL_VALIDATION_ENABLED", True),
    (
        "screenshot_redaction_enabled",
        "HYDRAFLOW_SCREENSHOT_REDACTION_ENABLED",
        True,
    ),
    ("screenshot_gist_public", "HYDRAFLOW_SCREENSHOT_GIST_PUBLIC", False),
    ("skip_preflight", "HYDRAFLOW_SKIP_PREFLIGHT", False),
    ("whatsapp_enabled", "HYDRAFLOW_WHATSAPP_ENABLED", False),
    (
        "sandbox_failure_fixer_enabled",
        "HYDRAFLOW_SANDBOX_FAILURE_FIXER_ENABLED",
        True,
    ),
    ("detector_calibration_enabled", "HYDRAFLOW_DETECTOR_CALIBRATION_ENABLED", True),
    ("gateway_coverage_enabled", "HYDRAFLOW_GATEWAY_COVERAGE_ENABLED", True),
    ("gateway_capture_bodies", "HYDRAFLOW_GATEWAY_CAPTURE_BODIES", False),
    (
        "gateway_fleet_ratchet_enabled",
        "HYDRAFLOW_GATEWAY_FLEET_RATCHET_ENABLED",
        False,
    ),
    (
        "gateway_route_shadow_enabled",
        "HYDRAFLOW_GATEWAY_ROUTE_SHADOW_ENABLED",
        True,
    ),
    (
        "gateway_policy_workspace_enabled",
        "HYDRAFLOW_GATEWAY_POLICY_WORKSPACE_ENABLED",
        True,
    ),
    ("auto_agent_preflight_enabled", "HYDRAFLOW_AUTO_AGENT_PREFLIGHT_ENABLED", True),
    ("auto_agent_redrive_enabled", "HYDRAFLOW_AUTO_AGENT_REDRIVE_ENABLED", True),
    (
        "auto_agent_hitl_intake_enabled",
        "HYDRAFLOW_AUTO_AGENT_HITL_INTAKE_ENABLED",
        True,
    ),
    (
        "auto_agent_light_intake_enabled",
        "HYDRAFLOW_AUTO_AGENT_LIGHT_INTAKE_ENABLED",
        True,
    ),
    (
        "auto_pr_preflight_gate_enabled",
        "HYDRAFLOW_AUTO_PR_PREFLIGHT_GATE_ENABLED",
        True,
    ),
    (
        "auto_pr_auto_merge_enabled",
        "HYDRAFLOW_AUTO_PR_AUTO_MERGE_ENABLED",
        True,
    ),
    (
        "pr_base_freshness_guard_enabled",
        "HYDRAFLOW_PR_BASE_FRESHNESS_GUARD_ENABLED",
        True,
    ),
    (
        "implement_two_stage_review_enabled",
        "HYDRAFLOW_IMPLEMENT_TWO_STAGE_REVIEW_ENABLED",
        True,
    ),
    ("staging_enabled", "HYDRAFLOW_STAGING_ENABLED", True),
    ("rc_auto_recut_enabled", "HYDRAFLOW_RC_AUTO_RECUT_ENABLED", False),
    (
        "rc_observed_advance_close_enabled",
        "HYDRAFLOW_RC_OBSERVED_ADVANCE_CLOSE_ENABLED",
        True,
    ),
    (
        "rc_promotion_health_enabled",
        "HYDRAFLOW_RC_PROMOTION_HEALTH_ENABLED",
        True,
    ),
    (
        "shadow_corpus_coverage_pruning_enabled",
        "HYDRAFLOW_SHADOW_CORPUS_COVERAGE_PRUNING_ENABLED",
        True,
    ),
    ("term_proposer_enabled", "HYDRAFLOW_TERM_PROPOSER_ENABLED", True),
    ("term_pruner_enabled", "HYDRAFLOW_TERM_PRUNER_ENABLED", True),
    ("edge_proposer_enabled", "HYDRAFLOW_EDGE_PROPOSER_ENABLED", True),
    (
        "use_quality_gate_in_review",
        "HYDRAFLOW_REVIEW_USE_QUALITY_GATE",
        True,
    ),
    (
        "implement_full_quality_gate",
        "HYDRAFLOW_IMPLEMENT_FULL_QUALITY_GATE",
        False,
    ),
    (
        "human_steering_enabled",
        "HYDRAFLOW_HUMAN_STEERING_ENABLED",
        True,
    ),
    # Static config gates — 34 loops (dark-factory §2.1 #3 defense-in-depth)
    ("adr_reviewer_loop_enabled", "HYDRAFLOW_ADR_REVIEWER_LOOP_ENABLED", True),
    (
        "adr_conformance_loop_enabled",
        "HYDRAFLOW_ADR_CONFORMANCE_LOOP_ENABLED",
        True,
    ),
    ("ci_monitor_loop_enabled", "HYDRAFLOW_CI_MONITOR_LOOP_ENABLED", True),
    (
        "branch_protection_auditor_loop_enabled",
        "HYDRAFLOW_BRANCH_PROTECTION_AUDITOR_LOOP_ENABLED",
        True,
    ),
    ("gate_activator_loop_enabled", "HYDRAFLOW_GATE_ACTIVATOR_LOOP_ENABLED", True),
    (
        "goal_supervisor_loop_enabled",
        "HYDRAFLOW_GOAL_SUPERVISOR_LOOP_ENABLED",
        False,  # ADR-0124: Tier-2 goal supervisor ships default OFF.
    ),
    (
        "rails_drift_caretaker_loop_enabled",
        "HYDRAFLOW_RAILS_DRIFT_CARETAKER_LOOP_ENABLED",
        False,
    ),
    ("contract_refresh_loop_enabled", "HYDRAFLOW_CONTRACT_REFRESH_LOOP_ENABLED", True),
    ("corpus_learning_loop_enabled", "HYDRAFLOW_CORPUS_LEARNING_LOOP_ENABLED", True),
    (
        "cost_budget_watcher_loop_enabled",
        "HYDRAFLOW_COST_BUDGET_WATCHER_LOOP_ENABLED",
        True,
    ),
    ("dependabot_merge_loop_enabled", "HYDRAFLOW_DEPENDABOT_MERGE_LOOP_ENABLED", True),
    ("diagnostic_loop_enabled", "HYDRAFLOW_DIAGNOSTIC_LOOP_ENABLED", True),
    (
        "diagnostic_exhausted_routes_autofix",
        "HYDRAFLOW_DIAGNOSTIC_EXHAUSTED_ROUTES_AUTOFIX",
        True,
    ),
    ("diagram_loop_enabled", "HYDRAFLOW_DIAGRAM_LOOP_ENABLED", True),
    ("entry_evidence_enabled", "HYDRAFLOW_ENTRY_EVIDENCE_ENABLED", True),
    ("epic_monitor_loop_enabled", "HYDRAFLOW_EPIC_MONITOR_LOOP_ENABLED", True),
    ("epic_sweeper_loop_enabled", "HYDRAFLOW_EPIC_SWEEPER_LOOP_ENABLED", True),
    (
        "fake_coverage_auditor_loop_enabled",
        "HYDRAFLOW_FAKE_COVERAGE_AUDITOR_LOOP_ENABLED",
        True,
    ),
    ("flake_tracker_loop_enabled", "HYDRAFLOW_FLAKE_TRACKER_LOOP_ENABLED", True),
    ("xdist_quarantine_enabled", "HYDRAFLOW_XDIST_QUARANTINE_ENABLED", True),
    ("github_cache_loop_enabled", "HYDRAFLOW_GITHUB_CACHE_LOOP_ENABLED", True),
    ("health_monitor_loop_enabled", "HYDRAFLOW_HEALTH_MONITOR_LOOP_ENABLED", True),
    (
        "self_repair_actuator_enabled",
        "HYDRAFLOW_SELF_REPAIR_ACTUATOR_ENABLED",
        True,
    ),
    (
        "label_drift_watcher_loop_enabled",
        "HYDRAFLOW_LABEL_DRIFT_WATCHER_LOOP_ENABLED",
        True,
    ),
    ("memory_backlog_loop_enabled", "HYDRAFLOW_MEMORY_BACKLOG_LOOP_ENABLED", True),
    (
        "merge_state_watcher_loop_enabled",
        "HYDRAFLOW_MERGE_STATE_WATCHER_LOOP_ENABLED",
        True,
    ),
    # #11595: auto-rebase actuator for the factory's own dirty PRs. Default
    # OFF — a branch-rewriting actuator is armed by the operator, not shipped
    # hot.
    ("pr_autorebase_enabled", "HYDRAFLOW_PR_AUTOREBASE_ENABLED", False),
    ("pr_unsticker_loop_enabled", "HYDRAFLOW_PR_UNSTICKER_LOOP_ENABLED", True),
    ("pricing_refresh_loop_enabled", "HYDRAFLOW_PRICING_REFRESH_LOOP_ENABLED", True),
    ("rc_budget_loop_enabled", "HYDRAFLOW_RC_BUDGET_LOOP_ENABLED", True),
    ("repo_wiki_loop_enabled", "HYDRAFLOW_REPO_WIKI_LOOP_ENABLED", True),
    ("report_issue_loop_enabled", "HYDRAFLOW_REPORT_ISSUE_LOOP_ENABLED", True),
    ("retrospective_loop_enabled", "HYDRAFLOW_RETROSPECTIVE_LOOP_ENABLED", True),
    ("runs_gc_loop_enabled", "HYDRAFLOW_RUNS_GC_LOOP_ENABLED", True),
    (
        "event_log_periodic_rotate_enabled",
        "HYDRAFLOW_EVENT_LOG_PERIODIC_ROTATE_ENABLED",
        True,
    ),
    ("state_prune_enabled", "HYDRAFLOW_STATE_PRUNE_ENABLED", True),
    ("security_patch_loop_enabled", "HYDRAFLOW_SECURITY_PATCH_LOOP_ENABLED", True),
    ("log_ingest_loop_enabled", "HYDRAFLOW_LOG_INGEST_LOOP_ENABLED", True),
    (
        "skill_prompt_eval_loop_enabled",
        "HYDRAFLOW_SKILL_PROMPT_EVAL_LOOP_ENABLED",
        True,
    ),
    (
        "skill_prompt_refine_enabled",
        "HYDRAFLOW_SKILL_PROMPT_REFINE_ENABLED",
        True,
    ),
    ("stale_issue_gc_loop_enabled", "HYDRAFLOW_STALE_ISSUE_GC_LOOP_ENABLED", True),
    ("gate_health_loop_enabled", "HYDRAFLOW_GATE_HEALTH_LOOP_ENABLED", True),
    ("pr_red_repair_loop_enabled", "HYDRAFLOW_PR_RED_REPAIR_LOOP_ENABLED", True),
    (
        "pr_red_repair_dispatch_enabled",
        "HYDRAFLOW_PR_RED_REPAIR_DISPATCH_ENABLED",
        True,
    ),
    (
        "fail_open_monitor_loop_enabled",
        "HYDRAFLOW_FAIL_OPEN_MONITOR_LOOP_ENABLED",
        True,
    ),
    (
        "judge_independence_enabled",
        "HYDRAFLOW_JUDGE_INDEPENDENCE_ENABLED",
        True,
    ),
    (
        "judge_self_mod_fail_closed_enabled",
        "HYDRAFLOW_JUDGE_SELF_MOD_FAIL_CLOSED",
        True,
    ),
    ("review_ultra_enabled", "HYDRAFLOW_REVIEW_ULTRA_ENABLED", False),
    (
        "review_ultra_auto_high_blast",
        "HYDRAFLOW_REVIEW_ULTRA_AUTO_HIGH_BLAST",
        False,
    ),
    (
        "erosion_metrics_loop_enabled",
        "HYDRAFLOW_EROSION_METRICS_LOOP_ENABLED",
        True,
    ),
    (
        "escape_ledger_loop_enabled",
        "HYDRAFLOW_ESCAPE_LEDGER_LOOP_ENABLED",
        True,
    ),
    (
        "intervention_tally_loop_enabled",
        "HYDRAFLOW_INTERVENTION_TALLY_LOOP_ENABLED",
        True,
    ),
    (
        "intervention_tally_classify_enabled",
        "HYDRAFLOW_INTERVENTION_TALLY_CLASSIFY_ENABLED",
        True,
    ),
    (
        "sampled_audit_loop_enabled",
        "HYDRAFLOW_SAMPLED_AUDIT_LOOP_ENABLED",
        True,
    ),
    (
        "sampled_audit_reaudit_enabled",
        "HYDRAFLOW_SAMPLED_AUDIT_REAUDIT_ENABLED",
        True,
    ),
    (
        "sampled_audit_auto_adjudicate_enabled",
        "HYDRAFLOW_SAMPLED_AUDIT_AUTO_ADJUDICATE_ENABLED",
        True,
    ),
    (
        "escape_ledger_auto_diagnose_enabled",
        "HYDRAFLOW_ESCAPE_LEDGER_AUTO_DIAGNOSE_ENABLED",
        True,
    ),
    (
        "second_order_vitals_loop_enabled",
        "HYDRAFLOW_SECOND_ORDER_VITALS_LOOP_ENABLED",
        True,
    ),
    (
        "human_branch_shepherd_enabled",
        "HYDRAFLOW_HUMAN_BRANCH_SHEPHERD_ENABLED",
        True,
    ),
    (
        "dependabot_conflict_heal_enabled",
        "HYDRAFLOW_DEPENDABOT_CONFLICT_HEAL_ENABLED",
        True,
    ),
    ("stale_issue_loop_enabled", "HYDRAFLOW_STALE_ISSUE_LOOP_ENABLED", True),
    ("triage_retry_loop_enabled", "HYDRAFLOW_TRIAGE_RETRY_LOOP_ENABLED", True),
    (
        "convergence_oscillation_loop_enabled",
        "HYDRAFLOW_CONVERGENCE_OSCILLATION_LOOP_ENABLED",
        True,
    ),
    (
        "trust_fleet_sanity_loop_enabled",
        "HYDRAFLOW_TRUST_FLEET_SANITY_LOOP_ENABLED",
        True,
    ),
    (
        "wiki_rot_detector_loop_enabled",
        "HYDRAFLOW_WIKI_ROT_DETECTOR_LOOP_ENABLED",
        True,
    ),
    ("workspace_gc_loop_enabled", "HYDRAFLOW_WORKSPACE_GC_LOOP_ENABLED", True),
    (
        "worktree_gc_all_roots_enabled",
        "HYDRAFLOW_WORKTREE_GC_ALL_ROOTS_ENABLED",
        True,
    ),
    ("auto_tighten_loop_enabled", "HYDRAFLOW_AUTO_TIGHTEN_LOOP_ENABLED", True),
    ("issue_refinement_enabled", "HYDRAFLOW_ISSUE_REFINEMENT_ENABLED", True),
]

# Literal-typed env-var overrides.
# Each tuple: (field_name, env_var_key)
# The default and allowed values are read dynamically from model_fields.
_ENV_LITERAL_OVERRIDES: list[tuple[str, str]] = [
    ("execution_mode", "HYDRAFLOW_EXECUTION_MODE"),
    ("docker_network_mode", "HYDRAFLOW_DOCKER_NETWORK_MODE"),
    ("epic_merge_strategy", "HYDRAFLOW_EPIC_MERGE_STRATEGY"),
    ("release_version_source", "HYDRAFLOW_RELEASE_VERSION_SOURCE"),
    ("implementation_provider", "HYDRAFLOW_IMPLEMENTATION_PROVIDER"),
    ("review_provider", "HYDRAFLOW_REVIEW_PROVIDER"),
    ("planner_provider", "HYDRAFLOW_PLANNER_PROVIDER"),
    ("triage_provider", "HYDRAFLOW_TRIAGE_PROVIDER"),
    ("ac_provider", "HYDRAFLOW_AC_PROVIDER"),
    ("repo_provider", "HYDRAFLOW_REPO_PROVIDER"),
    ("wiki_compilation_provider", "HYDRAFLOW_WIKI_COMPILATION_PROVIDER"),
    ("adr_review_provider", "HYDRAFLOW_ADR_REVIEW_PROVIDER"),
    ("transcript_summary_provider", "HYDRAFLOW_TRANSCRIPT_SUMMARY_PROVIDER"),
    ("triage_honeypot_provider", "HYDRAFLOW_TRIAGE_HONEYPOT_PROVIDER"),
    ("pr_unstick_provider", "HYDRAFLOW_PR_UNSTICK_PROVIDER"),
    ("term_proposer_provider", "HYDRAFLOW_TERM_PROPOSER_PROVIDER"),
    ("maintenance_provider", "HYDRAFLOW_MAINTENANCE_PROVIDER"),
]

# StrEnum-typed fields, kept separate from _ENV_LITERAL_OVERRIDES because
# get_args() is empty for an Enum subclass — the choices are the enum members.
_ENV_ENUM_OVERRIDES: list[tuple[str, str, type[StrEnum]]] = [
    ("queue_strategy", "HYDRAFLOW_QUEUE_STRATEGY", QueueStrategy),
    ("scheduling_model", "HYDRAFLOW_SCHEDULING_MODEL", SchedulingModel),
    ("execution_runtime", "HYDRAFLOW_EXECUTION_RUNTIME", ExecutionRuntime),
]

# Deprecated env var aliases (HYDRA_ → HYDRAFLOW_).
# During the deprecation period, old names are promoted to canonical names
# with a warning at startup.
_DEPRECATED_ENV_ALIASES: dict[str, str] = {
    "HYDRA_DOCKER_IMAGE": "HYDRAFLOW_DOCKER_IMAGE",
    "HYDRA_DOCKER_NETWORK": "HYDRAFLOW_DOCKER_NETWORK",
    "HYDRA_DOCKER_SPAWN_DELAY": "HYDRAFLOW_DOCKER_SPAWN_DELAY",
}
# Reverse lookup: canonical key → deprecated key (built once at import time).
_DEPRECATED_ENV_REVERSE: dict[str, str] = {
    v: k for k, v in _DEPRECATED_ENV_ALIASES.items()
}

_ALLOWED_TOOLS_COMBO: set[str] = {"claude", "codex"}


def _parse_combo(env_key: str, value: str) -> tuple[str, str]:
    """Parse a ``tool:model`` combo env var.

    Accepts the sentinel ``"inherit"`` for the SYSTEM / BACKGROUND variables,
    returning ``("inherit", "")``.  Any other value must contain exactly one
    colon: the left side a known tool, the right side a non-empty model
    string.

    Raises :class:`ValueError` with a clear message on malformed input.
    """
    stripped = value.strip()
    if stripped == "inherit":
        return "inherit", ""
    if ":" not in stripped:
        msg = (
            f"{env_key}={value!r} must be 'tool:model' "
            f"(e.g. claude:opus, gemini:gemini-3.1-pro-preview) or 'inherit'"
        )
        raise ValueError(msg)
    tool, _, model = stripped.partition(":")
    tool = tool.strip()
    model = model.strip()
    if tool not in _ALLOWED_TOOLS_COMBO:
        msg = (
            f"{env_key}={value!r} unknown tool {tool!r}; "
            f"allowed: {sorted(_ALLOWED_TOOLS_COMBO)}"
        )
        raise ValueError(msg)
    if not model:
        msg = f"{env_key}={value!r} model part is empty"
        raise ValueError(msg)
    return tool, model


# Each tuple: (env_key, tool_field, model_field)
# "inherit" is accepted for fields whose tool type includes it
# (system, background); otherwise it's rejected by Pydantic's Literal.
_ENV_COMBO_OVERRIDES: list[tuple[str, str, str]] = [
    ("HYDRAFLOW_SYSTEM", "system_tool", "system_model"),
    ("HYDRAFLOW_BACKGROUND", "background_tool", "background_model"),
    ("HYDRAFLOW_IMPLEMENT", "implementation_tool", "model"),
    ("HYDRAFLOW_REVIEW", "review_tool", "review_model"),
    (
        "HYDRAFLOW_TEST_ADEQUACY_VERIFIER",
        "test_adequacy_verifier_tool",
        "test_adequacy_verifier_model",
    ),
    ("HYDRAFLOW_PLANNER", "planner_tool", "planner_model"),
    ("HYDRAFLOW_TRIAGE", "triage_tool", "triage_model"),
    ("HYDRAFLOW_AC", "ac_tool", "ac_model"),
    (
        "HYDRAFLOW_TRANSCRIPT_SUMMARY",
        "transcript_summary_tool",
        "transcript_summary_model",
    ),
    ("HYDRAFLOW_WIKI_COMPILATION", "wiki_compilation_tool", "wiki_compilation_model"),
    ("HYDRAFLOW_ADR_REVIEW", "adr_review_tool", "adr_review_model"),
    ("HYDRAFLOW_REPORT_ISSUE", "report_issue_tool", "report_issue_model"),
    ("HYDRAFLOW_TERM_PROPOSER", "term_proposer_tool", "term_proposer_model"),
]


class HydraFlowConfig(BaseModel):
    """Configuration for the HydraFlow orchestrator."""

    # Issue selection
    ready_label: list[str] = Field(
        default=["hydraflow-ready"],
        description="GitHub issue labels to filter by (OR logic)",
    )
    batch_size: int = Field(default=15, ge=1, le=50, description="Issues per batch")
    repo: str = Field(
        default="",
        description="GitHub repo (owner/name); auto-detected from git remote if empty",
    )

    # Worker configuration — managed via config JSON file and dashboard UI,
    # not environment variables. All defaults are 1.
    max_workers: int = Field(default=1, ge=1, le=10, description="Concurrent agents")
    max_planners: int = Field(
        default=1, ge=1, le=10, description="Concurrent planning agents"
    )
    max_reviewers: int = Field(
        default=1, ge=1, le=10, description="Concurrent review agents"
    )
    max_triagers: int = Field(
        default=1, ge=1, le=10, description="Concurrent triage agents"
    )
    max_hitl_workers: int = Field(
        default=1, ge=1, le=5, description="Concurrent HITL correction agents"
    )

    # Dispatch-overlap guard (#10778) — pre-flight admission check that holds a
    # ready issue from concurrent dispatch when its predicted scope (a shared
    # referenced issue number, or an identical concrete file path) overlaps an
    # already-dispatched in-flight unit, serializing the two instead of building
    # them at once (the #10754 double-resolution class). Live: ImplementPhase
    # re-reads this off its shared config on every dispatch, so a toggle applies
    # to the next slot fill. Kill-switch: when off, every ready issue dispatches
    # as before with no overlap check.
    dispatch_overlap_guard_enabled: bool = Field(
        default=True,
        description=(
            "Hold a ready issue from concurrent dispatch when its predicted "
            "scope overlaps an in-flight build (shared issue reference or file), "
            "serializing rather than building both at once (#10778)."
        ),
    )

    # Work-queue discipline (#10037) — how IssueStore orders each stage queue.
    # ``IssueRefinementLoop`` (#9957) produces the P0/P1/P2 labels these read.
    # Default is 'weighted_mix': priority-driven selection is the intended
    # out-of-the-box behaviour, so a fresh instance picks by priority rather
    # than oldest-first. #10045 shipped 'fifo' to make the merge behaviour-
    # neutral; this makes the deliberate cutover. 'fifo' remains the escape
    # hatch — a live System-tab dial away, no restart (issue_store re-reads it
    # on every dequeue) — restoring the pre-#10037 ordering without a deploy.
    queue_strategy: QueueStrategy = Field(
        default=QueueStrategy.WEIGHTED_MIX,
        description=(
            "Stage-queue ordering: 'weighted_mix' (default — P0 preempts, then "
            "a weighted ratio draw with an age-based starvation guard), "
            "'priority' (strict P0>P1>P2, starves lower bands), or 'fifo' "
            "(oldest first, the pre-#10037 behaviour and escape hatch)"
        ),
    )
    # Weights are the relative share each band draws under 'weighted_mix'.
    # The floor of 1 is deliberate: it makes "a band cannot starve" an
    # unconditional guarantee rather than a property of the default values.
    queue_weight_p1: int = Field(
        default=3, ge=1, le=10, description="P1 draw share under weighted_mix"
    )
    queue_weight_p2: int = Field(
        default=2, ge=1, le=10, description="P2 draw share under weighted_mix"
    )
    queue_weight_unprioritised: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Unlabelled draw share under weighted_mix",
    )
    # Age at which a lower-band item is promoted ahead of the weighted draw so
    # it cannot languish forever (weighted_mix only). Generous by default: the
    # ratio draw is the normal path and this is the rarely-hit safety valve.
    queue_starvation_threshold_hours: float = Field(
        default=168.0,
        ge=1.0,
        le=8760.0,
        description="Hours before a lower-band item is force-promoted (weighted_mix)",
    )

    def band_weights(self) -> BandWeights:
        """Weighted-mix draw ratio in the form the ordering engine expects."""
        return BandWeights(
            p1=self.queue_weight_p1,
            p2=self.queue_weight_p2,
            unprioritised=self.queue_weight_unprioritised,
        )

    # --- Scheduling model (#11535) ---------------------------------------
    # Two orthogonal dials, deliberately separate: scheduling decides HOW a
    # picked issue is driven across phases, execution runtime decides WHO
    # decides inside a phase. The UI presents them as one preset; the backend
    # keeps them apart so #11537 can change one without touching the other
    # (docs/proposals/fable-subagent-scheduling.md, "Separate scheduling from
    # execution"). Both are restart-required: the orchestrator chooses which
    # pipeline loops to start once, at boot.
    #
    # Default is Classic (phase_requeue + stage_subprocess) — today's exact
    # behaviour, zero change on merge. Flipping it is a separate, factory-wide
    # decision gated on the ADR-0137 B5 evidence bar, and the ADR forbids that
    # flip landing on the same day as this build regardless of the numbers.
    scheduling_model: SchedulingModel = Field(
        default=SchedulingModel.PHASE_REQUEUE,
        description=(
            "How a picked issue is executed: 'phase_requeue' (Classic default "
            "- each phase re-acquires the issue from its own queue) or "
            "'issue_controller' (one fenced IssueDriver owns the issue across "
            "phases, ADR-0137). Restart required."
        ),
    )
    execution_runtime: ExecutionRuntime = Field(
        default=ExecutionRuntime.STAGE_SUBPROCESS,
        description=(
            "Who decides inside a phase: 'stage_subprocess' (the deterministic "
            "stage runners) or 'fable_director' (a Fable director dispatching "
            "brokered workers - not armed until #11537). Restart required."
        ),
    )
    # ADR-0137 C4: the controller's global WIP cap, on top of - never instead
    # of - the existing per-stage max_planners / max_workers / max_reviewers
    # caps, which the allocator respects. Inert under Classic, which has no
    # global cap at all (concurrency there is workers-per-phase).
    driver_max_in_flight: int = Field(
        default=4,
        ge=1,
        le=40,
        description=(
            "Maximum issues held by a live IssueDriver at once under "
            "scheduling_model='issue_controller'. Parked and HITL-waiting "
            "drivers release their slot (ADR-0137 C6). Raised to the sum of "
            "the per-stage caps if set below it — see "
            "effective_driver_max_in_flight. Ignored under Classic."
        ),
    )

    # --- Fable director, shadow mode (#11537) -----------------------------
    # Only read under execution_runtime='fable_director'. Under Classic and
    # under the deterministic controller nothing constructs a director, so
    # these are inert rather than merely defaulted.
    director_turn_timeout_seconds: int = Field(
        default=180,
        ge=30,
        le=1800,
        description=(
            "Wall-clock budget for one shadow Fable director turn. A turn that "
            "exceeds it is killed with its whole process group (ADR-0137 S6) "
            "and recorded as a failed turn, never retried in place. Ignored "
            "unless execution_runtime='fable_director'."
        ),
    )
    director_shadow_enabled: bool = Field(
        default=True,
        description=(
            "Kill switch for the shadow Fable director. Live: an operator can "
            "stop every director turn without restarting the factory, which "
            "matters because a director turn costs money and the dials that "
            "select it are restart-required. Off, the deterministic controller "
            "is entirely unaffected. Ignored unless "
            "execution_runtime='fable_director'."
        ),
    )
    director_shadow_usd_ceiling: float = Field(
        default=25.0,
        ge=0.0,
        le=10000.0,
        description=(
            "Total USD the shadow director may spend on turns in one run, "
            "across all issues. Once reached no further turn is started and "
            "the boundary is recorded as spend-ceiling. This is the AGGREGATE "
            "bound; director_shadow_usd_budget is the per-boundary figure the "
            "capsule advertises and bounds only what a director may request. "
            "Ignored unless execution_runtime='fable_director'."
        ),
    )
    director_shadow_usd_budget: float = Field(
        default=1.0,
        ge=0.0,
        le=100.0,
        description=(
            "USD budget a shadow director capsule advertises per boundary. At "
            "0.0 every dispatch the director requests is refused with "
            "BUDGET_EXHAUSTED - which is a legitimate way to observe a "
            "director's intent while admitting nothing at all. Ignored unless "
            "execution_runtime='fable_director'."
        ),
    )

    # --- Fable Plan canary (#11541, ADR-0137 P3) --------------------------
    # The dial on which a Fable director stops being an observer. It names one
    # canonical `owner/repo`, and only that repository's PLAN boundaries may
    # dispatch a brokered worker. Empty is off everywhere, which is both the
    # default and the rollback: clearing it disarms on the next boundary, with
    # no restart and no other edit. It arms nothing on its own — the director
    # must also be selected — and it never widens past PLAN.
    fable_plan_canary_repo: str = Field(
        default="",
        max_length=512,
        description=(
            "Canonical 'owner/repo' whose PLAN boundaries may dispatch real "
            "brokered Sonnet/Opus workers under execution_runtime="
            "'fable_director'. Empty (the default) dispatches nothing "
            "anywhere; clearing it is the one-action rollback. Anything that "
            "is not exactly owner/repo arms nothing. Deliberately NOT an env "
            "override: an env var that re-applies whenever the field is at its "
            "default would mean clearing the field did not disarm, and a "
            "rollback with two places to look is not one action (ADR-0141 D5)."
        ),
    )
    fable_plan_worker_timeout_seconds: int = Field(
        default=240,
        ge=30,
        le=900,
        description=(
            "Wall-clock budget for one brokered Plan BATCH, shared by its "
            "children. Each child is given whatever the batch has left, and a "
            "child that exceeds it is killed with its process group and its "
            "receipt is EXPIRED. It bounds the BATCH rather than each child, "
            "and its ceiling is deliberately low, because the dispatch is "
            "awaited inside the allocator tick: this figure is exactly how "
            "long one armed PLAN boundary can delay every other driver, and a "
            "per-child budget would multiply it by MAX_DISPATCH_BATCH. The "
            "default is of the same order as director_turn_timeout_seconds, "
            "which the shadow director already spends on that tick, and the "
            "ceiling sits well below CANARY_SLOT_TTL_SECONDS so the latch's "
            "backstop cannot reclaim a slot from a batch still running. "
            "Ignored unless fable_plan_canary_repo names this repository."
        ),
    )

    # --- Fable Implement canary (#11542, ADR-0137 P4) ---------------------
    # A SECOND dial, deliberately not a widening of the first. "Widen one role
    # boundary at a time" is the epic's own rollout rule, and one dial covering
    # both phases would mean an operator running the Plan canary today woke up
    # dispatching writers tomorrow. Two dials keep the two decisions separate
    # and keep #11541's bound literally true while this one is empty.
    fable_implement_canary_repo: str = Field(
        default="",
        max_length=512,
        description=(
            "Canonical 'owner/repo' whose IMPLEMENT boundaries may dispatch "
            "real brokered Sonnet implementer and Opus/Sonnet debugger workers "
            "under execution_runtime='fable_director'. Empty (the default) "
            "dispatches nothing anywhere; clearing it is the one-action "
            "rollback. Independent of fable_plan_canary_repo: arming one arms "
            "nothing about the other. Deliberately NOT an env override, for "
            "ADR-0141 D5's reason — an env var that re-applies whenever the "
            "field is at its default would mean clearing the field did not "
            "disarm."
        ),
    )
    fable_implement_worker_timeout_seconds: int = Field(
        default=240,
        ge=30,
        le=900,
        description=(
            "Wall-clock budget for one brokered IMPLEMENT BATCH, shared by its "
            "children. A child that exceeds what the batch has left is killed "
            "with its process group and its receipt is EXPIRED. Deliberately "
            "the SAME default and ceiling as the Plan batch, not larger: this "
            "dispatch is also awaited inside the allocator tick, so the figure "
            "is exactly how long one armed IMPLEMENT boundary can delay every "
            "other driver in the fleet. An earlier draft set 900s/3600s on the "
            "reasoning that a correction worker reads a diff rather than a "
            "goal — true, and not a licence to spend it on that tick. ADR-0137 "
            "makes moving dispatch off the tick the precondition for the batch "
            "growing, and this phase did not build it. Ignored unless "
            "fable_implement_canary_repo names this repository."
        ),
    )

    # --- Fable Review canary (#11543, ADR-0137 P5) -----------------------
    # A THIRD dial, deliberately not a widening of the first two. "Widen one
    # role boundary at a time" is the epic's own rollout rule; one dial covering
    # plan, implement and review would mean an operator running the Plan canary
    # today woke up dispatching REVIEWERS tomorrow. Review is also the boundary
    # where independence binds, so arming it must be its own decision.
    fable_review_canary_repo: str = Field(
        default="",
        max_length=512,
        description=(
            "Canonical 'owner/repo' whose REVIEW boundaries may dispatch a real "
            "brokered Opus reviewer under execution_runtime='fable_director'. "
            "Empty (the default) dispatches nothing anywhere; clearing it is the "
            "one-action rollback. Independent of fable_plan_canary_repo and "
            "fable_implement_canary_repo: arming one arms nothing about the "
            "others. Deliberately NOT an env override, for ADR-0141 D5's reason."
        ),
    )

    def fable_review_canary_armed(self) -> bool:
        """True when this process may dispatch a real brokered reviewer (#11543).

        The same two-decision shape as its siblings, over a third dial:
        selecting the director is restart-required, naming the review canary
        repository is live, and neither implies the other — nor does arming
        the plan or implement canary imply this one.
        """
        from hydraflow_gateway.routing_policy import canonicalize_repo

        if not self.uses_fable_director():
            return False
        armed = canonicalize_repo(str(self.fable_review_canary_repo or ""))
        return armed is not None and armed == canonicalize_repo(str(self.repo or ""))

    def fable_implement_canary_armed(self) -> bool:
        """True when this process may dispatch a real brokered writer (#11542).

        The same two-decision shape as :meth:`fable_plan_canary_armed`, over a
        different dial: selecting the director is restart-required, naming the
        implement canary repository is live, and neither implies the other.
        """
        from hydraflow_gateway.routing_policy import canonicalize_repo

        if not self.uses_fable_director():
            return False
        armed = canonicalize_repo(str(self.fable_implement_canary_repo or ""))
        return armed is not None and armed == canonicalize_repo(str(self.repo or ""))

    def fable_plan_canary_armed(self) -> bool:
        """True when this process may dispatch a real brokered Plan worker.

        Both halves are required and they are two different operator decisions:
        selecting the director (restart-required) and naming the canary
        repository (live). Collapsing them into one dial is how "we turned on
        the observer" becomes "we turned on the actuator" — the distinction
        #11537 built ``SchedulingPreset.director_dispatch_armed`` to preserve.

        The arming lives here rather than on the preset because a preset is
        fleet-wide and a canary must be bounded to one repository; a preset
        that armed dispatch would arm it for every repository the factory
        touches, which is the opposite of a bounded slice.
        """
        from hydraflow_gateway.routing_policy import canonicalize_repo

        if not self.uses_fable_director():
            return False
        armed = canonicalize_repo(str(self.fable_plan_canary_repo or ""))
        return armed is not None and armed == canonicalize_repo(str(self.repo or ""))

    def uses_fable_director(self) -> bool:
        """True when a shadow Fable director is attached to the driver.

        The counterpart of :meth:`uses_issue_driver`, and the single predicate
        every #11537 default-off guard reads. It is deliberately *not* the same
        question: ``issue_controller + stage_subprocess`` runs drivers with no
        director at all.
        """
        return self.execution_runtime is ExecutionRuntime.FABLE_DIRECTOR

    def director_probe_evidence_path(self) -> Path:
        """Where the committed probe evidence S4 asserts against lives.

        A checkout artifact, not a setting and not package data: it is
        *committed evidence* about a specific CLI build, produced by
        ``scripts/director_capability_probe.py`` (also checkout-only). A
        configurable path would let a stale or hand-edited file satisfy the one
        gate ADR-0137's conditional go depends on.

        Resolved through :func:`package_resources.checkout_path`, which raises
        rather than returning a path that does not exist — so an installed
        wheel with no checkout cannot arm S4, and the director refuses to run
        instead of asserting against nothing (#11589).
        """
        from package_resources import checkout_path

        return checkout_path(
            "tests",
            "fixtures",
            "director",
            "director_capability_probe_evidence.json",
        )

    def driver_stage_cap_total(self) -> int:
        """Total concurrent work today's per-stage caps allow a driver to occupy.

        Plan + implement + review + HITL. Triage stays Classic under
        ``issue_controller``, so its cap is not part of the driver's budget.
        """
        return (
            self.max_planners
            + self.max_workers
            + self.max_reviewers
            + self.max_hitl_workers
        )

    def effective_driver_max_in_flight(self) -> int:
        """The global WIP cap actually used, never below the stage-cap total.

        ADR-0137's narrowing of ADR-0094 rests on the driver being a *WIP
        limit* rather than a serialization, and that only holds if total
        concurrent work is no lower than today's per-stage caps already allow.
        The ADR makes it a binding constraint on this phase rather than an
        assumption, so a configured value below the floor is raised to it —
        the alternative is a throughput regression wearing a WIP limit's
        clothes, which is exactly what the constraint exists to prevent.
        """
        floor = self.driver_stage_cap_total()
        if self.driver_max_in_flight < floor:
            logger.warning(
                "driver_max_in_flight=%d is below the per-stage cap total (%d); "
                "raising it to the floor — a lower value would be a throughput "
                "regression, not a WIP limit (ADR-0137, ADR-0094 narrowing (i))",
                self.driver_max_in_flight,
                floor,
            )
            return floor
        return self.driver_max_in_flight

    @model_validator(mode="after")
    def _scheduling_combination_is_supported(self) -> HydraFlowConfig:
        """Reject an invalid or unarmed scheduling pair at load, loudly.

        ``queue_strategy`` shipped without this guard and needed a follow-up
        (#10053) to stop an unrecognised member silently dispatching as the
        default. A scheduler that quietly picks a discipline the operator did
        not choose is the dangerous shape, so the check is a load-time
        validator: a bad combination is a startup error, never a running
        factory that believes it is doing something else.
        """
        resolve_preset(self.scheduling_model, self.execution_runtime)
        return self

    def uses_issue_driver(self) -> bool:
        """True when this config runs per-issue drivers rather than Classic requeue.

        The single predicate every default-off guard reads, so "is the driver
        armed?" has exactly one answer across the orchestrator, the service
        registry and the ownership registry.
        """
        return resolve_preset(
            self.scheduling_model, self.execution_runtime
        ).uses_issue_driver

    # Plugin skill registry — see docs/superpowers/specs/2026-04-18-dynamic-plugin-skill-registry-design.md
    required_plugins: list[str] = Field(
        default_factory=lambda: [
            "superpowers",
            "code-review",
            "code-simplifier",
            "frontend-design",
            "playwright",
        ],
        description="Plugins that must be installed under ~/.claude/plugins/cache/ at startup",
    )
    language_plugins: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "python": ["pyright-lsp"],
            "typescript": ["typescript-lsp"],
            "csharp": ["csharp-lsp"],
            "go": ["gopls"],
            "rust": ["rust-analyzer"],
        },
        description="Language-conditional plugins loaded only when the language is detected in a target repo",
    )
    auto_install_plugins: bool = Field(
        default=True,
        description=(
            "When True, preflight attempts `claude plugin install name@marketplace --scope user` "
            "for missing Tier-1/Tier-2 plugins before failing."
        ),
    )
    # Per-phase whitelist. See ADR-0043 for rationale behind which skills are
    # included/excluded per phase (e.g., dialog-only and human-author skills
    # are excluded from every subagent phase).
    phase_skills: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "triage": ["superpowers:systematic-debugging"],
            "discover": ["superpowers:systematic-debugging"],
            "shape": ["superpowers:writing-plans"],
            "planner": [
                "superpowers:writing-plans",
                "superpowers:systematic-debugging",
            ],
            "agent": [
                "superpowers:test-driven-development",
                "superpowers:systematic-debugging",
                "superpowers:verification-before-completion",
                "code-simplifier:simplify",
                "frontend-design:frontend-design",
            ],
            "reviewer": [
                "code-review:code-review",
                "superpowers:systematic-debugging",
            ],
        },
        description=(
            "Per-phase whitelist of qualified skill names (`plugin:skill`) "
            "rendered into each runner's prompt."
        ),
    )

    @field_validator("phase_skills")
    @classmethod
    def _validate_phase_names(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        from plugin_skill_registry import PHASE_NAMES  # noqa: PLC0415

        unknown = set(v) - PHASE_NAMES
        if unknown:
            raise ValueError(
                f"unknown phase name(s) in phase_skills: {sorted(unknown)}; "
                f"expected subset of {sorted(PHASE_NAMES)}"
            )
        return v

    system_tool: Literal["inherit", "claude", "codex"] = Field(
        default="inherit",
        description="Optional global default tool for system agents; 'inherit' keeps per-agent defaults",
    )
    system_model: str = Field(
        default="",
        description="Optional global default model for system agents; empty keeps per-agent defaults",
    )
    background_tool: Literal["inherit", "claude", "codex"] = Field(
        default="inherit",
        description="Optional global default tool for background workers; 'inherit' keeps per-worker defaults",
    )
    background_model: str = Field(
        default="",
        description="Optional global default model for background workers; empty keeps per-worker defaults",
    )
    implementation_tool: Literal["claude", "codex"] = Field(
        default="claude",
        description="CLI backend for implementation agents",
    )
    model: str = Field(default="opus", description="Model for implementation agents")
    agent_unrestricted_tools: bool = Field(
        default=False,
        description=(
            "Escape hatch (ADR-0092): when True, issue-derived implementer/auto-agent "
            "spawns use the legacy bypassPermissions/danger-full-access mode instead of "
            "the hardened acceptEdits + tool-allowlist + WebFetch/WebSearch-disallow "
            "mode. Leave False unless the restricted allowlist breaks a backend."
        ),
    )

    # Review configuration
    review_tool: Literal["claude", "codex"] = Field(
        default="claude",
        description="CLI backend for review agents",
    )
    review_model: str = Field(default="sonnet", description="Model for review agents")

    # Independent test-adequacy verifier (#9546): a second-opinion pass with a
    # model that MUST stay independent of review_model — a shared model would
    # defeat the second opinion (the finder grading its own homework).
    test_adequacy_verifier_tool: Literal["claude", "codex"] = Field(
        default="claude",
        description="CLI backend for the independent test-adequacy verifier pass",
    )
    test_adequacy_verifier_model: str = Field(
        default="opus",
        description=(
            "Model for the independent test-adequacy verifier. Keep distinct "
            "from review_model — a shared model defeats the second opinion"
        ),
    )
    test_adequacy_verifier_enabled: bool = Field(
        default=True,
        description=(
            "Run the independent verifier pass when the test-adequacy finder "
            "emits an explicit OK (kill-switch; no-marker default-passes never "
            "trigger the verifier)"
        ),
    )
    test_adequacy_verifier_fail_closed: bool = Field(
        default=True,
        description=(
            "Treat a degraded verifier run (empty transcript / infra failure) "
            "as an OVERRIDE instead of keeping the finder's OK. Default ON "
            "(fail-closed); disable via the System tab to restore fail-soft."
        ),
    )

    # Judge-independence budget + fail-visible dispatch (#10371). The ledger
    # and dashboard alarm are always live; these dials gate the merge-outcome-
    # changing behaviours (opt-in until validated) and configure the second
    # model family that satisfies the independence budget.
    judge_independence_enabled: bool = Field(
        default=True,
        description=(
            "Route classed (structural/security/migration/self-mod) changes' "
            "post-verify verdict to an independent model family (#10371). "
            "Merge-outcome-changing; default ON (disable via the System tab); "
            "the fail-open ledger + alarm stay live regardless of this flag."
        ),
    )
    judge_self_mod_fail_closed_enabled: bool = Field(
        default=True,
        description=(
            "Fail-CLOSED for the self-modification class (#10371): a fail-open "
            "or a missing independent verdict on the factory's own instruments "
            "(gauntlet/gates/detectors/merge policy/this policy) STOPs the "
            "merge and escalates to HITL instead of passing. Default ON "
            "(disable via the System tab)."
        ),
    )
    judge_independent_model: str = Field(
        default="",
        description=(
            "Model from a family OUTSIDE the implementing roster that satisfies "
            "the judge-independence budget (#10371). Empty = no second family "
            "configured → degraded mode (same-family verdict, ledgered). A model "
            "whose family is inside the roster does not count as independent."
        ),
    )

    # Opt-in "ultra" deep-review tier (#10555). Runs the locally-installed
    # ``code-review`` plugin command headlessly as an extra adversarial pass;
    # high-confidence findings fold into the verdict. Default OFF: the fan-out
    # is expensive, so the tier only fires when this dial is on AND the issue
    # carries the ``review:ultra`` label OR (with the auto-high-blast dial on)
    # the diff's blast radius is "high". See ADR-0109.
    review_ultra_enabled: bool = Field(
        default=False,
        description=(
            "Enable the opt-in ultra deep-review tier (#10555). Default OFF — "
            "with defaults a review pass issues zero ultra spawns. Even when "
            "on, the tier only fires for a ``review:ultra``-labelled issue or a "
            "high-blast-radius diff (auto-high-blast dial), never on every PR."
        ),
    )
    review_ultra_auto_high_blast: bool = Field(
        default=False,
        description=(
            "When the ultra tier is enabled, also fire it automatically on any "
            "high-blast-radius diff (critical paths / large src change) even "
            "without the ``review:ultra`` label. Default OFF — label-only "
            "triggering until validated (#10555)."
        ),
    )
    review_ultra_model: str = Field(
        default="sonnet",
        description="Model for the ultra deep-review tier spawn (#10555).",
    )

    # CI check configuration
    ci_check_timeout: int = Field(
        default=600, ge=30, le=3600, description="Seconds to wait for CI checks"
    )
    ci_poll_interval: int = Field(
        default=30, ge=5, le=120, description="Seconds between CI status polls"
    )
    max_ci_fix_attempts: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Max CI fix-and-retry cycles (0 = skip CI wait)",
    )
    max_quality_fix_attempts: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Max quality fix-and-retry cycles before marking agent as failed",
    )
    max_pre_quality_review_attempts: int = Field(
        default=3,
        ge=0,
        le=5,
        description="Max pre-quality review/correction passes before quality verification",
    )
    max_diff_sanity_attempts: int = Field(
        default=1,
        ge=0,
        le=3,
        description="Max diff sanity check passes (0 = disabled)",
    )
    max_scope_check_attempts: int = Field(
        default=1,
        ge=0,
        le=3,
        description="Max scope check passes (0 = disabled)",
    )
    max_test_adequacy_attempts: int = Field(
        default=1,
        ge=0,
        le=3,
        description="Max test adequacy check passes (0 = disabled)",
    )
    test_adequacy_repair_passes: int = Field(
        default=1,
        ge=0,
        le=3,
        description=(
            "Bounded in-run repair passes when the test-adequacy gate fails "
            "(#11593): the concrete findings (finder/verifier gaps + "
            "coverage-delta uncovered lines) go back to the same implementer "
            "worktree with a focused write-the-missing-tests prompt, then the "
            "full check (coverage delta + independent verifier) re-runs. "
            "Default 1: 61 of 105 failed August runs died at this gate and a "
            "rejected run costs a median 29 min plus a whole restarted "
            "attempt, so one bounded rescue pass is cheaper than rejection. "
            "0 = today's straight-to-rejection behavior. "
            "max_test_adequacy_attempts=0 still disables the whole gate, "
            "repair included."
        ),
    )
    test_adequacy_pin_demand: bool = Field(
        default=True,
        description=(
            "Judge a test-adequacy retry against the demand the PREVIOUS "
            "attempt actually stated (#11644). #11643's calibration measured "
            "9 of 15 consecutive re-rejections demanding something entirely "
            "new (mean substantive overlap 0.04), so an implementer could "
            "satisfy every stated finding and still be rejected on a fresh "
            "set. With the pin in force a retry is rejected by a finding that "
            "restates the pinned demand, by a genuinely NEW finding that names "
            "a locatable referent, or by a deterministic coverage gap — but "
            "not by a new finding that names nothing locatable, which is "
            "recorded as advisory instead. Strictness is otherwise unchanged: "
            "a first attempt still blocks on every finding, and the "
            "coverage-delta source never routes through the contract at all. "
            "False = pre-#11644 behavior."
        ),
    )
    test_adequacy_coverage_timeout_secs: int = Field(
        default=300,
        ge=60,
        le=1800,
        description="Timeout in seconds for the coverage-delta make coverage run",
    )
    max_plan_compliance_attempts: int = Field(
        default=1,
        ge=0,
        le=3,
        description="Max plan compliance check passes (0 = disabled)",
    )
    max_discover_attempts: int = Field(
        default=3,
        ge=0,
        le=5,
        description="Max Discover-brief evaluator retries before HITL escalation (0 = disabled)",
    )
    max_discover_expansions: int = Field(
        default=1,
        ge=0,
        le=3,
        description=(
            "Max discover-expander subagent dispatches per issue before "
            "falling through to HITL escalation (ADR-0063 W3a; 0 = disabled)"
        ),
    )
    max_shape_attempts: int = Field(
        default=3,
        ge=0,
        le=5,
        description="Max Shape-proposal evaluator retries before HITL escalation (0 = disabled)",
    )
    max_review_fix_attempts: int = Field(
        default=3,
        ge=0,
        le=5,
        description=(
            "Max review fix-and-retry cycles before HITL escalation. 3 (was 2, "
            "#10922): a healthy convergence commonly needs a third round after "
            "two that each fixed real findings, and escalating those to a human "
            "wastes the self-solve the gate exists to allow."
        ),
    )
    min_review_findings: int = Field(
        default=3,
        ge=0,
        le=20,
        description="Minimum review findings threshold for adversarial review",
    )
    use_quality_gate_in_review: bool = Field(
        default=True,
        description=(
            "When ci_enabled=False, use `make quality` (full suite) in review fix "
            "prompts instead of `make lint && {test_cmd}`. Set False for repos "
            "without a wired Makefile quality target."
        ),
    )
    implement_full_quality_gate: bool = Field(
        default=False,
        description=(
            "Implementer post-build gate (#11568). Off (default): after each "
            "build and each quality-fix round the implementer runs "
            "`make quality-lite` (lint + typecheck + security) then "
            "`make test-impacted IMPACTED_ARGS=--bounded` (the tests its diff "
            "touches, never the whole suite; repos without that target run "
            "test_command) — both host-lock-free — and CI is the one "
            "full-suite gate per PR. On: restore the pre-#11568 full "
            "`make quality`, which queues every implementer on the host-wide "
            "quality lock (#11400) so max_workers no longer reflects real "
            "parallelism. HITL and diagnostic runners always run the full gate."
        ),
    )
    max_merge_conflict_fix_attempts: int = Field(
        default=3,
        ge=0,
        le=5,
        description="Max merge conflict resolution retry cycles",
    )
    max_ci_timeout_fix_attempts: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Max fix attempts for CI timeout (hanging test) failures",
    )
    max_issue_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Max total implementation attempts per issue before HITL escalation",
    )
    implement_no_progress_abort_attempts: int = Field(
        default=1,
        ge=0,
        le=10,
        description=(
            "Zero-commit abort threshold for ImplementPhase's flow "
            "(#10659/#10616, P2 of #10682; tightened by #11568): the attempt "
            "number at/after which a zero-commit (no output) attempt stops "
            "the retry loop and routes the issue to diagnose with the "
            "transcript tail. Default 1: the FIRST zero-commit result routes "
            "to diagnose (post-build ``zero-commit-abort`` node) instead of "
            "burning attempts 2 and 3 on the same shape — measured 2026-08-21 "
            "as the doubling of attempts per merged issue (1.2 → 2.2). The "
            "pre-build ``no-progress-abort`` node applies the same threshold "
            "to the immediately prior attempt of the current cycle (a "
            "backstop for state written before #11568). Raise to 2–3 to "
            "restore the ADR-0063 W5 corrective retry after a zero-commit "
            "attempt; set 0 to disable both aborts (retry to the "
            "``max_issue_attempts`` cap)."
        ),
    )
    max_decomposition_depth: int = Field(
        default=2,
        ge=0,
        le=5,
        description=(
            "Max recursive decomposition depth for decompose-to-converge (0 = "
            "disabled). Default 2: a parent decomposes into children, and a "
            "stalled child may re-decompose once more. Nested convergence is "
            "correct because EpicState carries parent_epic/superseded_issue "
            "lineage — the sweeper gate + EpicManager propagation ensure a root "
            "epic only closes after all transitive grandchild work finishes "
            "(#9757). le=5 bounds the chain; max_total_decomposition_children "
            "bounds fan-out."
        ),
    )
    max_total_decomposition_children: int = Field(
        default=8,
        ge=1,
        le=50,
        description="Max total child issues fanned out across a decomposition tree",
    )
    gh_max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Max retry attempts for gh CLI calls",
    )
    gh_api_concurrency: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Max concurrent gh/git subprocess calls (prevents API rate limiting)",
    )
    gh_circuit_breaker_enabled: bool = Field(
        default=True,
        description=(
            "Enable the gh/git circuit breaker (fails fast when GitHub is down). "
            "Runtime-tunable via PATCH /api/config — the live kill-switch."
        ),
    )
    gh_circuit_breaker_max_failures: int = Field(
        default=10,
        ge=1,
        le=1000,
        description=(
            "Consecutive gh/git failures before the circuit breaker OPENs "
            "(conservative — only trips on a sustained outage)"
        ),
    )
    gh_circuit_breaker_reset_timeout_s: float = Field(
        default=60.0,
        ge=1.0,
        le=3600.0,
        description=(
            "Seconds the gh/git circuit breaker stays OPEN before probing "
            "(HALF_OPEN); it auto-recovers so it can't halt the factory forever"
        ),
    )
    github_cache_issue_list_ttl_s: float = Field(
        default=900.0,
        ge=0.0,
        le=86400.0,
        description=(
            "Freshness bound (seconds) for the shared issue-list-by-label "
            "snapshots in GitHubDataCache (#9814). A read younger than this "
            "is served with no gh call; 0 disables caching (every read "
            "refreshes, still coalesced + degrade-safe). On refresh failure "
            "a stale snapshot is served while younger than 3x this bound."
        ),
    )
    loop_startup_stagger_s: int = Field(
        default=120,
        ge=0,
        le=3600,
        description=(
            "Spread window (seconds) for deterministic background-loop "
            "first-tick staggering (#9814). Each loop delays its first cycle "
            "by hash(worker_name) % this value so a restart doesn't fire "
            "every loop's GitHub reads at once. 0 disables. Loops with "
            "run_on_startup=True (e.g. github_cache) are exempt so the "
            "shared cache still populates immediately at boot."
        ),
    )

    # Task source
    task_source_type: Literal["github"] = Field(
        default="github",
        description="Task source backend. Only 'github' supported today.",
    )

    # Label lifecycle
    review_label: list[str] = Field(
        default=["hydraflow-review"],
        description="Labels for issues/PRs under review (OR logic)",
    )
    in_progress_label: list[str] = Field(
        default=["hydraflow-in-progress"],
        description=(
            "Durable cross-actor build-claim marker (#10168). Added to a "
            "``hydraflow-ready`` issue the moment a build STARTS on it and "
            "cleared when the PR opens (``ready → review`` swap removes it, "
            "since it is in ``all_pipeline_labels``) or on abandon/failure. "
            "Unlike ``review_label`` it is NOT a pipeline stage — it is an "
            "orthogonal claim marker that coexists with ``hydraflow-ready`` "
            "during the build so a second factory instance / parallel "
            "operator session / out-of-band Agent dispatch reading GitHub "
            "labels can see the issue is already being built and skip it. "
            "The in-process ``IssueStore._eagerly_transitioned`` fast-path "
            "stays; this is the durable belt-and-suspenders (ADR-0002)."
        ),
    )
    hitl_label: list[str] = Field(
        default=["hydraflow-hitl"],
        description="Labels for issues escalated to human-in-the-loop (OR logic)",
    )
    hitl_active_label: list[str] = Field(
        default=["hydraflow-hitl-active"],
        description="Labels for HITL items being actively processed (OR logic)",
    )
    hitl_autofix_label: list[str] = Field(
        default=["hydraflow-hitl-autofix"],
        description="Labels for HITL items undergoing automatic fix attempt (OR logic)",
    )
    light_autofix_label: list[str] = Field(
        default=["hydraflow-auto-light"],
        description=(
            "Claim label for #11298 light-lane issues being built by the "
            "single-session auto-agent (OR logic). Swapped on by PlanPhase "
            "at routing time; polled by AutoAgentPreflightLoop for intake "
            "and crash recovery."
        ),
    )
    fixed_label: list[str] = Field(
        default=["hydraflow-fixed"],
        description="Labels applied after PR is merged (OR logic)",
    )
    verify_label: list[str] = Field(
        default=["hydraflow-verify"],
        description="Labels for post-merge verification issues (OR logic)",
    )
    dup_label: list[str] = Field(
        default=["hydraflow-dup"],
        description="Labels applied when issue is already satisfied (no changes needed)",
    )
    parked_label: list[str] = Field(
        default=["hydraflow-parked"],
        description="Labels for issues parked awaiting author clarification (OR logic)",
    )
    triage_retry_exhausted_label: list[str] = Field(
        default=["triage-retry-exhausted"],
        description=(
            "Sub-label applied alongside hitl-escalation when TriageRetryLoop "
            "exhausts its retry budget on a parked issue (ADR-0063 W2)."
        ),
    )
    diagnose_label: list[str] = Field(
        default=["hydraflow-diagnose"],
        description="Labels for issues in diagnostic analysis (OR logic)",
    )
    # #11145 queue-merge ruling (2026-08-14): the bare literal is the
    # de-facto HITL-escalation queue — most caretaker writers and BOTH
    # pollers (auto_agent_preflight, detector_calibration) use it, and every
    # live escalation issue carries it. The prefixed default created a
    # second, unrouted queue; the default now matches reality so
    # config-sourced writers land on the queue the readers actually poll.
    hitl_escalation_label: list[str] = Field(
        default=["hitl-escalation"],
        description="Labels for stuck-loop HITL escalations (e.g. fake-coverage-auditor)",
    )
    fake_coverage_gap_label: list[str] = Field(
        default=["hydraflow-fake-coverage-gap"],
        description="Labels for fake-coverage-auditor gap issues (adapter or helper)",
    )
    adapter_surface_label: list[str] = Field(
        default=["hydraflow-adapter-surface"],
        description="Labels for un-cassetted public adapter methods on Fakes",
    )
    test_helper_label: list[str] = Field(
        default=["hydraflow-test-helper"],
        description="Labels for un-exercised Fake test helpers (script_*, fail_service, ...)",
    )
    fake_coverage_stuck_label: list[str] = Field(
        default=["hydraflow-fake-coverage-stuck"],
        description="Labels for stuck fake-coverage gaps (paired with hitl_escalation_label)",
    )
    rc_promotion_stuck_label: list[str] = Field(
        default=["rc-promotion-stuck"],
        description="Label for repeated staging→main promotion failures (paired with hitl_escalation_label)",
    )
    max_diagnosticians: int = Field(
        default=1,
        description="Max concurrent diagnostic workers",
    )
    diagnostic_interval: int = Field(
        default=30,
        description="Poll interval in seconds for diagnostic loop",
    )
    max_diagnostic_attempts: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Fix attempts before escalating to HITL",
    )
    epic_label: list[str] = Field(
        default=["hydraflow-epic"],
        description="Labels for epic tracking issues with linked sub-issues (OR logic)",
    )
    epic_child_label: list[str] = Field(
        default=["hydraflow-epic-child"],
        description="Labels for child issues linked to epics (OR logic)",
    )
    auto_decomposed_child_label: list[str] = Field(
        default=["auto-decomposed-child"],
        description=(
            "Label stamped on every child issue created by decompose-to-converge "
            "(ADR-0105), on top of epic_child_label/find_label. Further splits "
            "of a stamped child only happen through the stall-path call to "
            "IssueDecomposer.create_epic_from_result(depth=...), which the "
            "depth cap bounds (the #11298 intake auto-decomposition vector "
            "was removed)."
        ),
    )
    epic_group_planning: bool = Field(
        default=True,
        description="Group epic children for cohort planning with gap review",
    )
    epic_gap_review_max_iterations: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Max gap review + re-plan iterations (0 disables gap review)",
    )
    epic_decompose_complexity_threshold: int = Field(
        default=8,
        ge=1,
        le=10,
        description=(
            "Complexity score at which the triage cache ranks an issue "
            "'high' (TriagePhase._complexity_rank). No longer gates any "
            "decomposition action — the #11298 intake auto-decomposition "
            "path was removed; splits happen only via the ADR-0105 "
            "stall-path terminal."
        ),
    )
    backlog_budget: int = Field(
        default=25,
        ge=0,
        description=(
            "#11298 retirement valve: cap on open advisory factory-generated "
            "issues (find/plan/diagnose/parked labels, minus protected "
            "classes). Beyond the budget, StaleIssueLoop retires the oldest "
            "with a class-key comment — recurrence refiles via cross-tick "
            "folding (#11341), so retirement is cheap and reversible. "
            "0 disables the valve."
        ),
    )
    backlog_budget_min_age_days: int = Field(
        default=2,
        ge=0,
        description=(
            "Grace period before an advisory issue is retirement-eligible "
            "under backlog_budget — fresh filings get a chance to be worked."
        ),
    )
    epic_monitor_interval: int = Field(
        default=1800,
        description="Epic monitor loop interval in seconds (default 30 min)",
    )
    epic_sweep_interval: int = Field(
        default=3600,
        ge=600,
        le=86400,
        description="Epic sweeper loop interval in seconds (default 1 hour)",
    )
    workspace_gc_interval: int = Field(
        default=1800,
        ge=300,
        le=86400,
        description="Workspace GC loop interval in seconds (default 30 min)",
        validation_alias=AliasChoices("workspace_gc_interval", "worktree_gc_interval"),
    )
    worktree_gc_roots: list[str] = Field(
        default_factory=list,
        description=(
            "Allow-list of filesystem roots the WorkspaceGCLoop may sweep for "
            "orphan worktrees (#10698). Empty = use the known factory roots "
            "resolved by worktree_gc_root_paths(). A worktree whose path is not "
            "under one of these roots is never reaped (blast-radius gate)."
        ),
    )
    worktree_gc_min_age_seconds: int = Field(
        default=1800,
        ge=0,
        le=86400,
        description=(
            "Minimum age (seconds) a worktree must reach before the "
            "WorkspaceGCLoop enumerate phase will reap it (#10698). Guards "
            "against reaping a worktree created mid-run. 0 disables the guard."
        ),
    )
    stale_issue_gc_interval: int = Field(
        default=3600,
        ge=300,
        le=86400,
        description="Stale issue GC loop interval in seconds (default 1 hour)",
    )
    label_drift_watcher_interval: int = Field(
        default=600,
        ge=120,
        le=86400,
        description="LabelDriftWatcherLoop scan interval in seconds (120-86400).",
    )
    stale_issue_interval: int = Field(
        default=86400,
        ge=60,
        le=604800,
        description="Stale issue check interval (seconds)",
    )
    stale_issue_regression_rot_stale_days: int = Field(
        default=14,
        ge=1,
        le=365,
        description=(
            "Regression-rot threshold (days, #9597). StaleIssueLoop's "
            "regression-rot check flags a still-OPEN issue whose "
            "`tests/regressions/` pin has been `xfail` RED for longer than "
            "this many days as 'orphaned-RED' (a written-but-unimplemented "
            "contract). A closed issue with a still-RED pin ('false-close "
            "rot') is always flagged regardless of age. "
            "Env: HYDRAFLOW_STALE_ISSUE_REGRESSION_ROT_STALE_DAYS."
        ),
    )
    branch_gc_stale_days: int = Field(
        default=3,
        ge=1,
        le=90,
        description=(
            "Stale agent-branch GC threshold (days, #10011). StaleIssueLoop's "
            "branch-GC reconciler flags an `agent/issue-*` or `fix/*` remote "
            "branch carrying a `Fixes #N`-style commit as needing a truth "
            "comment once it has sat unmerged (no open PR, referenced issue "
            "still OPEN) for this many days. Posting the comment is deduped "
            "per branch regardless of this threshold. "
            "Env: HYDRAFLOW_BRANCH_GC_STALE_DAYS."
        ),
    )
    branch_gc_min_delete_age_days: int = Field(
        default=14,
        ge=1,
        le=365,
        description=(
            "Never delete a stale agent/fix branch younger than this many "
            "days (#10011), even when `branch_gc_delete_enabled=True` — a "
            "generous floor independent of `branch_gc_stale_days` since "
            "branch deletion is destructive. "
            "Env: HYDRAFLOW_BRANCH_GC_MIN_DELETE_AGE_DAYS."
        ),
    )
    branch_gc_delete_enabled: bool = Field(
        default=True,
        description=(
            "Allow StaleIssueLoop's branch-GC reconciler to actually delete "
            "stale unmerged `agent/issue-*` / `fix/*` branches past "
            "`branch_gc_min_delete_age_days` (#10011). Default ON (self-repair "
            "on by default): deletion is bounded by the generous "
            "`branch_gc_min_delete_age_days` floor. Disable via the System tab "
            "for report/comment-only, since branch deletion is destructive. "
            "Env: HYDRAFLOW_BRANCH_GC_DELETE_ENABLED."
        ),
    )
    triage_retry_interval: int = Field(
        default=86400,
        ge=3600,
        le=604800,
        description=(
            "TriageRetryLoop tick interval in seconds (default 24h, ADR-0063 W2). "
            "Re-runs parked-issue triage with the original parking reason as context."
        ),
    )
    triage_retry_max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description=(
            "Maximum number of autonomous retries before TriageRetryLoop escalates "
            "the parked issue to HITL via the triage_retry_exhausted_label "
            "sub-label (ADR-0063 W2)."
        ),
    )
    triage_retry_max_issues_per_tick: int = Field(
        default=5,
        ge=1,
        le=20,
        description=(
            "Max hitl-escalation issues TriageRetryLoop files in one tick "
            "(#10777). A mass re-park (e.g. an infra outage that parked the "
            "whole board) would otherwise file one HITL issue per exhausted "
            "parked issue in a single tick. Over-cap issues are deferred and "
            "retried next tick — a rate limit on filing volume, not a drop."
        ),
    )
    triage_infra_retry_interval: int = Field(
        default=900,
        ge=60,
        le=86400,
        description=(
            "Short re-flow floor (seconds, default 15m) for issues parked by a "
            "TRANSIENT INFRA failure (rate-limit truncation, subprocess exit 1, "
            "unparseable verdict) rather than a 'needs author clarification' "
            "verdict (#10290). Infra-parks are the infra's fault, not the "
            "issue's — they must re-flow as soon as infra recovers, not sit under "
            "the 24h clarification backoff (triage_retry_interval). TriageRetryLoop "
            "ticks at this cadence and applies this floor only to infra-parked "
            "issues; clarification-parks keep the 24h floor."
        ),
    )
    stale_issue_threshold_days: int = Field(
        default=14,
        ge=1,
        le=365,
        description="Days of inactivity before auto-closing an issue (default 14)",
    )
    ci_monitor_interval: int = Field(
        default=300,
        ge=60,
        le=86400,
        description="CI health monitor loop interval in seconds (default 5 min)",
    )
    branch_protection_auditor_interval: int = Field(
        default=604800,
        ge=3600,
        le=2592000,
        description=(
            "BranchProtectionAuditorLoop interval in seconds (default 7 days); "
            "audits live branch protection against the canonical rulesets (ADR-0082)"
        ),
    )
    goal_supervisor_interval: int = Field(
        default=600,
        ge=60,
        le=86400,
        description=(
            "GoalSupervisorLoop cadence in seconds (default 10m); the Tier-2 "
            "liveness supervisor that hands the read-only factory health "
            "snapshot to a Fable agent (ADR-0124)."
        ),
    )
    goal_supervisor_model: str = Field(
        default="claude-fable-5",
        description=(
            "Model for the GoalSupervisorLoop's Fable agent (ADR-0124). A "
            "claude-* model, spawned with tool=claude."
        ),
    )
    gate_activator_interval: int = Field(
        default=604800,
        ge=3600,
        le=2592000,
        description=(
            "GateActivatorLoop interval in seconds (default 7 days); proposes "
            "activating planned gates whose protected surface now exists (ADR-0082)"
        ),
    )
    rails_drift_caretaker_interval: int = Field(
        default=86400,
        ge=3600,
        le=2592000,
        description=(
            "RailsDriftCaretakerLoop interval in seconds (default 1 day); audits "
            "each managed repo's live state against its rails.yaml manifest (ADR-0121)"
        ),
    )
    collaborator_check_enabled: bool = Field(
        default=True,
        description="When True, skip issues from non-collaborators at fetch time",
    )
    collaborator_cache_ttl: int = Field(
        default=600,
        ge=60,
        le=7200,
        description="Collaborator list cache TTL in seconds (default 10 min)",
    )

    # Artifact retention
    artifact_retention_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="Days to retain run artifacts before cleanup (default 30)",
    )
    artifact_max_size_mb: int = Field(
        default=500,
        ge=10,
        le=10_000,
        description="Max total artifact storage in MB before oldest runs are pruned (default 500)",
    )
    runs_gc_interval: int = Field(
        default=3600,
        ge=300,
        le=86400,
        description="Runs GC loop interval in seconds (default 1 hour)",
    )
    gate_health_interval: int = Field(
        default=604800,
        ge=3600,
        le=2592000,
        description="GateHealthLoop cycle interval in seconds (default weekly)",
    )
    gate_health_run_window: int = Field(
        default=50,
        ge=10,
        le=200,
        description="Workflow runs analyzed per GateHealthLoop cycle",
    )
    gate_health_min_attempts: int = Field(
        default=3,
        ge=2,
        le=50,
        description=(
            "Minimum failures before GateHealthLoop flags a check: "
            "born-broken needs N, blame-correlation N-1"
        ),
    )
    gate_health_hang_tolerance_seconds: int = Field(
        default=90,
        ge=10,
        le=600,
        description=(
            "GateHealthLoop suspected-hang classifier (#10010): a CANCELLED "
            "job whose duration lands within this many seconds of its "
            "workflow's configured timeout-minutes is a candidate hang, "
            "not a generic cancellation"
        ),
    )
    gate_health_max_issues_per_tick: int = Field(
        default=5,
        ge=1,
        le=20,
        description=(
            "Max hydraflow-find issues GateHealthLoop files in one tick "
            "(#10777). Findings scale with distinct CI checks and analyzed "
            "runs; over-cap findings are folded into a single summary issue "
            "instead of one issue each — a rate limit on filing volume."
        ),
    )
    pr_red_repair_interval: int = Field(
        default=300,
        ge=60,
        le=86400,
        description=(
            "PrRedRepairLoop cycle interval in seconds (#10027 Phase 1: "
            "infra-flake retrier; default 5 minutes)"
        ),
    )
    pr_red_rerun_max_attempts: int = Field(
        default=2,
        ge=1,
        le=10,
        description=(
            "Max bounded `gh run rerun --failed` attempts per PR before "
            "PrRedRepairLoop escalates via a rollup issue (#10027)"
        ),
    )
    pr_red_repair_dispatch_max_attempts: int = Field(
        default=2,
        ge=1,
        le=10,
        description=(
            "Max bounded auto-agent dispatch attempts per PR before "
            "PrRedRepairLoop gives up on a real (non-infra-flake) settled "
            "red and labels the PR `hydraflow-hitl` for a human (#10027 "
            "Phase 2). Tracked separately from `pr_red_rerun_max_attempts` "
            "— a rerun is a cheap gh API call, a dispatch is a full "
            "auto-agent worktree attempt."
        ),
    )
    erosion_metrics_interval: int = Field(
        default=86400,
        ge=900,
        le=604800,
        description=(
            "ErosionMetricsLoop cycle interval in seconds (#10107, epic "
            "#10104: change-spread/concept-scatter drift → triage; v1 "
            "provisional cadence, default 4h)"
        ),
    )
    erosion_metrics_max_issues_per_tick: int = Field(
        default=3,
        ge=1,
        le=20,
        description=(
            "Max hydraflow-find issues ErosionMetricsLoop files in one tick "
            "(#10107). Overflow candidates beyond the cap for that tick's "
            "commit range are not carried over — a rate limit on filing "
            "volume, not a durable backlog."
        ),
    )
    fail_open_monitor_interval: int = Field(
        default=14400,
        ge=900,
        le=604800,
        description=(
            "FailOpenMonitorLoop cycle interval in seconds (#10371: watches the "
            "fail-open ledger's rate against a Shewhart control limit and files "
            "a hydraflow-find above-limit; default 4h)."
        ),
    )
    fail_open_monitor_max_issues_per_tick: int = Field(
        default=2,
        ge=1,
        le=20,
        description=(
            "Max hydraflow-find issues FailOpenMonitorLoop files in one tick "
            "(#10371). A rate limit on filing volume, not a durable backlog."
        ),
    )
    escape_ledger_interval: int = Field(
        default=14400,
        ge=900,
        le=604800,
        description=(
            "EscapeLedgerLoop cycle interval in seconds (#10367: post-merge "
            "escape detection + erosion trend surfaces; v1 provisional "
            "cadence, default 4h)"
        ),
    )
    escape_ledger_max_issues_per_tick: int = Field(
        default=3,
        ge=1,
        le=20,
        description=(
            "Finding-rate budget: max HITL/hydraflow-find issues "
            "EscapeLedgerLoop files in one tick for low-confidence or "
            "aging-unencoded escapes (#10367). Ledger RECORDING is never "
            "capped — only issue filing, so the instrument does not over-file."
        ),
    )
    escape_ledger_encoding_age_days: int = Field(
        default=14,
        ge=1,
        le=90,
        description=(
            "How long an escape may stay `encoded_as: none-yet` before "
            "EscapeLedgerLoop surfaces it for human triage (#10367). Every "
            "escape should terminate in an encoding (test/lesson/detector/ADR)."
        ),
    )
    escape_ledger_max_diagnoses_per_tick: int = Field(
        default=25,
        ge=1,
        le=500,
        description=(
            "Cap on how many eligible (low-confidence or aging-unencoded) "
            "escapes EscapeLedgerLoop runs the auto-diagnose pass (ADR-0115) "
            "over in one tick (#11176). Diagnosis runs over the FULL eligible "
            "set BEFORE the ask-budget cap (`escape_ledger_max_issues_per_tick`) "
            "is applied, so a machine-resolvable finding self-answers "
            "regardless of how many other findings are competing for that "
            "tick's ask budget; this separate, wider cap bounds the git/PRPort "
            "reads a synthetic flood of eligible findings could otherwise drive "
            "in one tick. Eligible findings beyond this cap fall through to the "
            "ask budget undiagnosed (fail-safe: they may still reach a human)."
        ),
    )
    escape_ledger_auto_diagnose_enabled: bool = Field(
        default=True,
        description=(
            "Before EscapeLedgerLoop files a LOW-CONFIDENCE or AGING escape for a "
            "human (SURFACE_REASON_LOW_CONFIDENCE / SURFACE_REASON_AGING), run a "
            "machine auto-diagnose pass (ADR-0115): trace the detecting commit, "
            "check whether the bug is already regression-encoded, and — if "
            "real+encoded — auto-record the resolution at high confidence "
            "(encoded-as regression-test) so the surface self-answers; "
            "auto-dismiss a clear false positive with a recorded reason. Only an "
            "INCONCLUSIVE diagnosis falls through to the human surface. Default "
            "ON (self-repair on by default; disable via the System tab); the "
            "pass is purely mechanical (git + issue-label reads, no LLM spawn), "
            "so it is air-gap-safe."
        ),
    )
    intervention_tally_interval: int = Field(
        default=86400,
        ge=900,
        le=604800,
        description=(
            "InterventionTallyLoop cycle interval in seconds (#10369: "
            "attention-side telemetry — human touches per 100 merges + "
            "loops-per-governor; v1 provisional cadence, default 4h)"
        ),
    )
    intervention_tally_max_classify_per_tick: int = Field(
        default=5,
        ge=1,
        le=50,
        description=(
            "Budget: max free-text steering directives InterventionTallyLoop "
            "sends to the cheap LLM in one tick (#10369). Bounds classification "
            "spend under a synthetic flood; over budget, rows keep their raw "
            "text at low confidence for later re-label. Recording is never "
            "capped — only LLM classification."
        ),
    )
    sampled_audit_interval: int = Field(
        default=14400,
        ge=900,
        le=604800,
        description=(
            "SampledAuditLoop cycle interval in seconds (#10370: sampled "
            "adversarial re-audit — the silent-escape estimator; v1 provisional "
            "cadence, default 4h)."
        ),
    )
    sampled_audit_max_issues_per_tick: int = Field(
        default=3,
        ge=1,
        le=20,
        description=(
            "Finding-rate budget: max hydraflow-find issues SampledAuditLoop "
            "files in one tick for re-audit disagreements (#10370). Sample "
            "RECORDING is never capped — only issue filing, so the instrument "
            "does not over-file."
        ),
    )
    sampled_audit_token_budget_per_tick: int = Field(
        default=40000,
        ge=0,
        le=5_000_000,
        description=(
            "Per-tick token budget cap on adversarial re-audit spend (#10370). "
            "Sampling is the point; exhaustive re-review is an explicit "
            "non-goal, so the selected sample is trimmed to what this budget "
            "covers. 0 audits nothing (sampling still records governance)."
        ),
    )
    sampled_audit_model: str = Field(
        default="",
        description=(
            "Model the SampledAuditLoop adversarial re-auditor runs on "
            "(#10370/#10371 independence policy). Point it at a DIFFERENT family "
            "from the implementing agent when the roster allows; empty falls "
            "back to the maintenance model, then the background model (a fresh "
            "same-family context)."
        ),
    )
    second_order_vitals_interval: int = Field(
        default=86400,
        ge=900,
        le=604800,
        description=(
            "SecondOrderVitalsLoop cycle interval in seconds (#10373: the "
            "capstone residual monitor over the instrument set — green-while-"
            "dying detection; v1 provisional cadence, default 4h). Decoupled from "
            "the evaluation window: the loop ticks at this cadence for report "
            "freshness and the diverging-edge alarm, but records a NEW per-window "
            "observation only once `second_order_vitals_window_days` has elapsed, "
            "so successive observations cover disjoint (non-overlapping) windows."
        ),
    )
    second_order_vitals_window_days: int = Field(
        default=7,
        ge=1,
        le=90,
        description=(
            "Trailing window (days) the SecondOrderVitalsLoop reads each "
            "instrument's series over for one per-window observation (#10373). "
            "Escapes/interventions/audit/independence are windowed by their own "
            "timestamps; erosion is taken from its latest monthly trend row. This "
            "is ALSO the observation cadence: a new observation is appended only "
            "once this many days have elapsed since the last, so consecutive "
            "observations are independent, non-overlapping windows — which is what "
            "makes `sustained_windows` count genuinely distinct windows rather "
            "than the same lingering event re-read across overlapping ticks."
        ),
    )
    second_order_vitals_min_baseline_windows: int = Field(
        default=8,
        ge=2,
        le=1000,
        description=(
            "How many observations a series must accumulate before it carries a "
            "Shewhart control limit and its family counts as *reporting* "
            "(#10373). A limit from one or two points is noise; below this the "
            "family degrades honestly to `n-of-5 reporting`, never a false green."
        ),
    )
    second_order_vitals_sustained_windows: int = Field(
        default=2,
        ge=1,
        le=100,
        description=(
            "How many CONSECUTIVE windows a family must stay above its control "
            "limit before it counts toward the k-of-5 divergence tally (#10373). "
            "The anti-flap half of the design — single-window blips never fire. "
            "Windows here are the independent, non-overlapping observation windows "
            "(see `second_order_vitals_window_days`), so this is roughly "
            "`sustained_windows * window_days` of real elapsed persistence, not N "
            "adjacent ticks."
        ),
    )
    second_order_vitals_watch_k: int = Field(
        default=2,
        ge=1,
        le=5,
        description=(
            "k-of-5: number of instrument families sustained above their control "
            "limits (with primary health green) for the `watch` verdict (#10373). "
            "`watch` is a dashboard state change only — no issue is filed."
        ),
    )
    second_order_vitals_diverging_k: int = Field(
        default=3,
        ge=1,
        le=5,
        description=(
            "k-of-5: number of instrument families sustained above their control "
            "limits (with primary health green) for the `diverging` verdict — the "
            "green-while-dying alarm (#10373). Files ONE find + HITL per episode."
        ),
    )
    second_order_vitals_history_max: int = Field(
        default=120,
        ge=8,
        le=100000,
        description=(
            "Max per-series observations SecondOrderVitalsLoop retains (#10373). "
            "Bounds the persisted baseline so the state file cannot grow without "
            "limit; the oldest windows fall off the front."
        ),
    )
    second_order_vitals_min_merge_throughput: int = Field(
        default=1,
        ge=0,
        le=100000,
        description=(
            "Merge-throughput floor (merges in the window) for primary health to "
            "count as green (#10373). An idle factory is not green-while-dying; "
            "below this the monitor stays silent."
        ),
    )
    second_order_vitals_min_ci_pass_rate: float = Field(
        default=0.5,
        ge=0.0,
        description=(
            "CI first-pass-rate floor for primary health to count as green "
            "(#10373). Read from the existing factory-health signal (never a "
            "re-derivation); below this the primary gates are not themselves "
            "green and the divergence monitor stays silent. Normally in [0,1]; "
            "a floor above 1.0 simply holds the monitor silent on the CI axis."
        ),
    )
    second_order_vitals_loop_enabled: bool = Field(
        default=True,
        description=(
            "Deploy-time kill-switch for SecondOrderVitalsLoop (#10373: the "
            "capstone residual monitor, read-only ADR-0029 Pattern B). Computes "
            "the green-while-dying verdict and reports it; never remediates, "
            "gates ordinary merges, or files fix PRs."
        ),
    )

    # Hash-chained audit stream retention (CH-1, #9729). None = keep forever.
    # A set value is a retention FLOOR: RunsGCLoop may prune records strictly
    # older than the floor and can never delete inside it. Regulated
    # deployments should set explicit values (e.g. 2555 days ~ 7y for
    # change-control evidence).
    audit_retention_days_preflight: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Days to retain preflight audit records (auto_agent/audit.jsonl). "
            "None = keep forever."
        ),
    )
    audit_retention_days_health_decisions: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Days to retain health-monitor decision records "
            "(memory/decisions.jsonl). None = keep forever."
        ),
    )
    audit_retention_days_inference_telemetry: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Days to retain inference telemetry records "
            "(metrics/prompt/inferences.jsonl). None = keep forever."
        ),
    )
    audit_retention_days_approval_records: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Days to retain merge approval records (CH-2, #9730; "
            "audit/approval_records.jsonl). None = keep forever — the "
            "recommended setting for change-control evidence."
        ),
    )
    audit_retention_days_evidence_packs: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Days to retain evidence-pack summary records (CH-4, #9732; "
            "audit/evidence_packs.jsonl). None = keep forever — the "
            "recommended setting for release evidence."
        ),
    )

    # CH-2 (#9730): kill-switch for the approval-record reconciler capability
    # hosted by MergeStateWatcherLoop. Not a loop gate — the loop keeps
    # unsticking conflicts when this is off; only evidence capture stops.
    approval_records_enabled: bool = Field(
        default=True,
        description=(
            "Capture structured merge-approval records (CH-2) on the "
            "MergeStateWatcherLoop tick."
        ),
    )

    # CH-4 (#9732): kill-switch for the release evidence-pack compiler
    # invoked by StagingPromotionLoop after a successful RC promotion.
    # Compile-only, report-only — never gates the promotion itself.
    evidence_pack_enabled: bool = Field(
        default=True,
        description=(
            "Compile a release evidence pack (CH-4) after each successful RC promotion."
        ),
    )

    # CH-3 (#9731): kill-switch for the policy-as-code merge gate consulted
    # at the factory's own autonomous merge seams (merge_policy.py). When on,
    # a missing/unparseable policy.yaml fails CLOSED (merges deny+escalate);
    # this switch and the policy-override:<reason-slug> break-glass label
    # are the escape hatches.
    merge_policy_enabled: bool = Field(
        default=True,
        description=(
            "Enforce docs/standards/factory_autonomy/policy.yaml before "
            "autonomous merges (CH-3)."
        ),
    )

    # G3 close-verification controller (#10358): the actuator half of the
    # close-verification loop. P10.7 (#10356) DETECTS a false auto-close (an
    # issue closed by a PR carrying neither a non-test source change nor a
    # tests/regressions/ delta — the #10223 signature, with the same
    # Skip-Regression: opt-out). When ON, a post-merge observer REOPENS the
    # closed issue and re-triages it (re-applies find_label) so a delta-less
    # "done" is actually driven to a fix. Default-OFF and fully inert until
    # enabled — same rollout discipline as the G1 auto-recut actuator.
    close_verification_enabled: bool = Field(
        default=True,
        description=(
            "Reopen + re-triage an issue a merged PR closed without a fix "
            "delta (the #10223 false-close signature). Default-on actuator "
            "for the P10.7 detector (#10358); disable via the System tab."
        ),
    )

    epic_stale_days: int = Field(
        default=7,
        ge=1,
        description="Days without activity before an epic is flagged as stale",
    )
    epic_merge_strategy: Literal[
        "independent", "bundled", "bundled_hitl", "ordered"
    ] = Field(
        default="independent",
        description="How to coordinate merging of epic sub-issue PRs",
    )
    # Release configuration
    release_version_source: Literal["epic_title", "milestone", "manual"] = Field(
        default="epic_title",
        description="How to determine the release version string",
    )
    release_tag_prefix: str = Field(
        default="v",
        description="Prefix for git tags (e.g. 'v' produces 'v1.2.0')",
    )

    # Discovery / planner configuration
    find_label: list[str] = Field(
        default=["hydraflow-find"],
        description="Labels for new issues to discover and triage into planning (OR logic)",
    )
    regulated_labels: str = Field(
        default="",
        description=(
            "Comma-separated label names forming the regulated change class "
            "(CH-5 traceability). Issues carrying any of these labels must "
            "declare a requirement ID (`req:<id>` label or `Req-ID:` body "
            "line). Empty (the default) means no change class is regulated."
        ),
    )
    clarity_threshold: int = Field(
        default=7,
        ge=1,
        le=10,
        description=(
            "Clarity score threshold (ADR-0107). Issues scoring below this are "
            "flagged to the planner's on-demand discover/shape decision gate "
            "(plan_phase_prepass.py:_should_discover_helper) as a discovery hint, "
            "rather than routed to a standalone Discover phase at triage time."
        ),
    )
    plan_review_min_complexity: int = Field(
        default=5,
        ge=0,
        le=10,
        description=(
            "Skip the adversarial plan review for issues triaged at or below "
            "this complexity (#11298 size tiering: the token report measured "
            "plan_reviewer at 42% of all factory tokens, and a one-file fix "
            "does not need a full agentic repo exploration of its plan — the "
            "implement-side skill gauntlet still guards the code). Cycled, "
            "escalated, or unclassified issues are ALWAYS reviewed. 0 "
            "disables tiering (every plan reviewed, pre-#11298 behavior)."
        ),
    )
    planner_lite_min_complexity: int = Field(
        default=5,
        ge=0,
        le=10,
        description=(
            "Force the lite plan scale for issues triaged at or below this "
            "complexity (#11298 size tiering, planner side: the token report "
            "measured the planner at 44% of all factory tokens; a simple "
            "issue gets the existing lite-plan prompt instead of the full "
            "exploration treatment). Cycled, escalated, or unclassified "
            "issues always fall back to heuristic scale detection, and a "
            "routed-back issue replans at full scale. 0 disables forcing."
        ),
    )
    max_shape_turns: int = Field(
        default=10,
        ge=2,
        le=20,
        description="Maximum conversation turns in a shape session",
    )
    shape_timeout_minutes: int = Field(
        default=60,
        ge=5,
        le=1440,
        description="Minutes to wait for human response before timing out shape conversation",
    )
    whatsapp_enabled: bool = Field(
        default=False,
        description="Enable WhatsApp notifications for shape conversations",
    )
    dashboard_url: str = Field(
        default="http://localhost:5555",
        description="Public URL of the dashboard for artifact links",
    )
    planner_label: list[str] = Field(
        default=["hydraflow-plan"],
        description="Labels for issues needing plans (OR logic)",
    )
    planner_tool: Literal["claude", "codex"] = Field(
        default="claude",
        description="CLI backend for planning agents",
    )
    planner_model: str = Field(default="opus", description="Model for planning agents")
    tdd_max_remediation_loops: int = Field(
        default=4,
        ge=0,
        description="Max fix attempts per TDD REFACTOR sub-agent before reporting failure",
    )
    triage_tool: Literal["claude", "codex"] = Field(
        default="claude",
        description="CLI backend for triage agents",
    )
    triage_model: str = Field(
        default="sonnet",
        description="Model for triage evaluation (fast/cheap)",
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        description=(
            "OpenAI-compatible base URL for the 'openrouter' one-shot LLM "
            "provider. The API key is read from the OPENROUTER_API_KEY env var "
            "(a secret — never stored on config or shown in the UI)."
        ),
    )
    zai_base_url: str = Field(
        default="https://api.z.ai/api/paas/v4",
        description=(
            "OpenAI-compatible base URL for the 'zai' one-shot LLM provider "
            "(z.ai / GLM). The API key is read from the ZAI_API_KEY env var "
            "(a secret — never stored on config or shown in the UI)."
        ),
    )
    zai_harness_base_url: str = Field(
        default="https://api.z.ai/api/anthropic",
        description=(
            "Anthropic-compatible base URL for the 'zai' *harness* backend — the "
            "endpoint the Claude CLI is pointed at (via ANTHROPIC_BASE_URL) when "
            "an agentic role sets provider='zai', so a tool-using maintenance loop "
            "runs on GLM. Distinct from zai_base_url (the one-shot /paas/v4 face). "
            "Auth prefers ZAI_CODING_PLAN_KEY (flat-rate GLM Coding Plan) and "
            "falls back to ZAI_API_KEY, so agentic spawns ride the plan while "
            "one-shot background traffic stays on API credits (secrets — env-only)."
        ),
    )
    gateway_base_url: str = Field(
        default="http://127.0.0.1:8080",
        min_length=1,
        description=(
            "Anthropic-compatible data-plane URL and control-plane origin for "
            "the session-tap gateway. HydraFlow mints at /control/v1/keys; the "
            "env-only HYDRAFLOW_GATEWAY_CONTROL_TOKEN authenticates that call."
        ),
    )
    gateway_ledger_path: str = Field(
        default="",
        description=(
            "Optional read-only path to the gateway metadata ledger. Empty "
            "uses <data_root>/gateway/requests.jsonl."
        ),
    )
    gateway_repo_class: Literal["hydraflow", "client", "personal"] = Field(
        default="personal",
        description=(
            "Governance class stamped onto gateway virtual keys. Defaults to "
            "personal (the privacy-safe no-body-capture class)."
        ),
    )
    gateway_capture_bodies: bool = Field(
        default=False,
        description=(
            "Request full prompt/response capture for gateway-routed spawns. "
            "Allowed only for gateway_repo_class='hydraflow'."
        ),
    )
    gateway_key_ttl_seconds: int = Field(
        default=3660,
        ge=60,
        le=86_400,
        description=(
            "Minimum lifetime requested for each per-spawn gateway virtual key. "
            "The runner raises the effective TTL when needed to cover the full "
            "subprocess timeout plus a cleanup grace period."
        ),
    )
    # Routing-policy shadow (#11536, ADR-0139). Observation only: the resolver
    # computes and records the route it *would* choose beside the route legacy
    # routing actually took, and changes neither. Nothing here enforces a
    # policy — enforcement is a later, separately gated phase.
    gateway_route_shadow_enabled: bool = Field(
        default=True,
        description=(
            "Record a shadow routing decision beside every spawn: what the "
            "policy resolver would have chosen versus what legacy routing did. "
            "Observation only — it never changes a provider, model, or command. "
            "Set false to stop writing the per-repo shadow decision chain."
        ),
    )
    gateway_policy_workspace_enabled: bool = Field(
        default=True,
        description=(
            "Serve the operator Routing policy workspace: read the per-repo "
            "policy snapshot, effective-route matrix, and mutation audit, and "
            "expose the revision-safe write plane. Routing behaviour is "
            "unaffected either way — enforcement is a later phase. Writes need "
            "an authenticated operator identity (env-only "
            "HYDRAFLOW_OPERATOR_TOKEN) AND a loopback dashboard bind, so this "
            "dial off is the third, blunt way to close them (ADR-0140)."
        ),
    )
    # Enforcement canary (#11539, ADR-0141). The FIRST dial on which a routing
    # decision changes what gets spawned — and deliberately the smallest one
    # that can: it names exactly one canonical `owner/repo`, and only that
    # repository's gateway-transported spawns are bound by policy. Empty is off
    # for every repository, which is both the default and the rollback: clearing
    # it disarms enforcement on the next spawn, with no restart and no policy
    # edit. It never promotes a spawn onto the gateway; it only binds traffic
    # already there.
    gateway_enforcement_canary_repo: str = Field(
        default="",
        max_length=512,
        description=(
            "Canonical 'owner/repo' whose gateway-routed spawns are bound by "
            "the routing policy resolver instead of by legacy dials. Empty "
            "(the default) enforces nothing anywhere; clearing it is the "
            "one-action rollback. Anything that is not exactly owner/repo — a "
            "runtime slug included — arms nothing. Deliberately NOT an env "
            "override: an env var that re-applies whenever the field is at its "
            "default would mean clearing the field did not disarm, and a "
            "rollback with two places to look is not one action (ADR-0141 D5)."
        ),
    )
    gateway_fleet_ratchet_enabled: bool = Field(
        default=False,
        description=(
            "Terminal gateway profile: promote untouched gateway-capable role "
            "dials to the gateway and fail config load for any explicitly "
            "configured direct harness role. Opt in only after deploy."
        ),
    )
    kimi_base_url: str = Field(
        default="https://api.moonshot.ai/v1",
        description=(
            "OpenAI-compatible base URL for the 'kimi' one-shot LLM provider "
            "(Moonshot / Kimi). The API key is read from the MOONSHOT_API_KEY "
            "env var (a secret — never stored on config or shown in the UI)."
        ),
    )
    # Per-role backend dials for the one-shot (no-tools) loops. "claude" keeps
    # the direct CLI harness, "gateway" sends that same harness through the tap,
    # and "openrouter", "zai", and "kimi" call a cheap direct model over an
    # OpenAI-compatible endpoint. Pair each with the role's *_model (e.g.
    # a DeepSeek id for openrouter, "glm-5.2" for zai, "kimi-k3" for kimi).
    wiki_compilation_provider: Literal[
        "claude", "gateway", "openrouter", "zai", "kimi"
    ] = Field(default="claude", description="Backend for wiki topic compilation.")
    adr_review_provider: Literal["claude", "gateway", "openrouter", "zai", "kimi"] = (
        Field(default="claude", description="Backend for the ADR reviewer.")
    )
    transcript_summary_provider: Literal[
        "claude", "gateway", "openrouter", "zai", "kimi"
    ] = Field(default="claude", description="Backend for transcript summarization.")
    triage_honeypot_provider: Literal[
        "claude", "gateway", "openrouter", "zai", "kimi"
    ] = Field(
        default="claude", description="Backend for the triage injection honeypot."
    )
    pr_unstick_provider: Literal["claude", "gateway", "openrouter", "zai", "kimi"] = (
        Field(
            default="claude", description="Backend for the PR-unsticker cause analysis."
        )
    )
    term_proposer_provider: Literal[
        "claude", "gateway", "openrouter", "zai", "kimi"
    ] = Field(
        default="claude",
        description="Backend for the term-proposer / entry-evidence drafters.",
    )
    # Per-role backend dials for the AGENTIC (tool-using) roles. Unlike the
    # one-shot dials above, these only offer harness transports: "claude" (the
    # native Anthropic endpoint), "zai" (the Claude CLI pointed at GLM's
    # /api/anthropic endpoint), or "gateway" (the per-spawn session tap). This
    # is what lets an operator route maintenance
    # loops to GLM while implement/review/plan/triage stay on Claude. Pair a
    # "zai" dial with a glm-* model (enforced by _harmonize_tool_model_defaults).
    #
    # ONLY roles with a dedicated, provider-honoring spawn get a dial. Sub-spawns
    # inherit their outer runner's provider (they share its harness), so they get
    # NO separate dial: the test-adequacy verifier and skill sub-spawns run on
    # implementation_provider; the AC precheck's subskill/debug closures run on
    # ac_provider; the verification judge shares review's tool+model so it runs
    # on review_provider. Adding a dead dial here would validate at config-load
    # yet never route at runtime — a footgun, so we don't.
    implementation_provider: Literal["claude", "gateway", "zai"] = Field(
        default="claude", description="Harness backend for implementation agents."
    )
    review_provider: Literal["claude", "gateway", "zai"] = Field(
        default="claude", description="Harness backend for review agents."
    )
    planner_provider: Literal["claude", "gateway", "zai"] = Field(
        default="claude", description="Harness backend for planning agents."
    )
    triage_provider: Literal["claude", "gateway", "zai"] = Field(
        default="claude", description="Harness backend for triage agents."
    )
    ac_provider: Literal["claude", "gateway", "zai"] = Field(
        default="claude", description="Harness backend for acceptance-criteria agents."
    )
    # One knob to route ALL maintenance loops to a backend, coherently. Unlike
    # the old background_model (which back-filled *_model only and could strand a
    # glm model on a claude-provider role), this sets provider AND model together
    # on the maintenance role-set. Dedicated dials cover wiki, ADR review,
    # transcript, drift resolver, term proposer, triage honeypot, and PR
    # unsticker; sampled audit, issue refinement, intervention tally, and skill
    # prompt refinement inherit these values at their lightweight seam. It NEVER
    # touches implement/review/plan/triage. Leave at claude/"" to configure
    # dedicated roles individually.
    maintenance_provider: Literal["claude", "gateway", "zai"] = Field(
        default="claude",
        description=(
            "Backend applied to every maintenance loop (not the work loops). "
            "Set to 'zai' to run all maintenance on GLM; pair with maintenance_model."
        ),
    )
    maintenance_model: str = Field(
        default="",
        description=(
            "Model applied to every maintenance loop when set (e.g. 'glm-5.2'). "
            "Empty keeps each maintenance role's own model. Only touches the "
            "maintenance role-set, never the work loops."
        ),
    )
    # Per-repo harness/backend override (#11211): lets an operator run this
    # repo's factory work on GLM while another repo (a different HydraFlowConfig
    # instance — one per registered repo, see repo_store.py) stays on Claude.
    # Applied at spawn time by repo_backend.apply_repo_provider, layered UNDER
    # any explicit per-role *_provider dial (which always wins when it has
    # already routed a role off "claude") and UNDER credit-failover (which only
    # further reroutes a spawn still resolving to "claude"). Resolution order:
    # role dial > repo_provider > credit-failover.
    repo_provider: Literal["claude", "gateway", "zai"] = Field(
        default="claude",
        description=(
            "Repo-wide harness backend override for this repo's work spawns. "
            "Set to 'zai' to run this repo on GLM; pair with repo_model. A "
            "role's own *_provider dial, when explicitly routed off claude, "
            "always wins over this. Falls back to claude (each role's own "
            "default) when unset."
        ),
    )
    repo_model: str = Field(
        default="",
        description=(
            "Model used when repo_provider reroutes a spawn to 'zai' (e.g. "
            "'glm-5.2'). Empty falls back to credit_failover_model."
        ),
    )
    # Credit failover (#10844): when a Claude *work* spawn hits an authoritative
    # Anthropic credit cap, reroute work spawns to the z.ai GLM backend and keep
    # going instead of pausing. Requires a zai key — ZAI_CODING_PLAN_KEY or
    # ZAI_API_KEY (no-op without one). Switch
    # back auto-probes Claude after cooldown / the error's reset time. Never
    # touches maintenance loops (they dial independently).
    credit_failover_enabled: bool = Field(
        default=True,
        description=(
            "Reroute work spawns to the GLM backend on an authoritative Claude "
            "credit cap instead of pausing (#10844). Requires ZAI_CODING_PLAN_KEY "
            "or ZAI_API_KEY."
        ),
    )
    credit_failover_model: str = Field(
        default="glm-5.2",
        description=(
            "Model for work spawns while credit-failover is active. Must be a "
            "glm-* model (the zai-backend requirement)."
        ),
    )
    credit_failover_cooldown_minutes: int = Field(
        default=15,
        ge=1,
        description=(
            "Minutes before probing Claude to switch back, used only when the "
            "credit error carries no explicit reset time (#10844)."
        ),
    )
    triage_max_turns: int = Field(
        default=12,
        ge=1,
        le=20,
        description=(
            "Max LLM turns for triage evaluation. Must cover #9127's "
            "verify-against-code exploration (Read/Grep to check currency and "
            "falsifiable claims) PLUS emitting the verdict. 3 was too low — the "
            "agent exhausted the budget mid-verification and terminated with "
            "error_max_turns (exit 1, no verdict), so every code-citing issue "
            "parked (#10291)."
        ),
    )
    triage_blocker_gate_enabled: bool = Field(
        default=True,
        description=(
            "Honour ``Blocked by: #N[, #M]`` lines in issue bodies during "
            "triage (#11614). A child whose declared prerequisite is still "
            "OPEN is held on its current pipeline label and re-evaluated on "
            "the next tick instead of being triaged into the plan queue, so "
            "phase-ordered epic children flow in declared order rather than "
            "all becoming eligible at once. Self-healing: no park, no extra "
            "label, no second actor. Every unreadable blocker fails OPEN. "
            "Kill switch for the gate; see src/blocker_gate.py."
        ),
    )
    triage_honeypot_enabled: bool = Field(
        default=True,
        description=(
            "Run the prompt-injection honeypot over each issue before the real "
            "triage agent handles it. A cheap agent is shown the untrusted body "
            "with a MOCK tool-belt (nothing executes); any mock-tool call means "
            "the body tried to hijack the agent — i.e. an injection attempt. "
            "See src/triage_honeypot.py."
        ),
    )
    triage_honeypot_enforce: bool = Field(
        default=False,
        description=(
            "When False (default), the honeypot runs in SHADOW mode: a trip "
            "emits a SYSTEM_ALERT + telemetry but the issue still proceeds to "
            "triage — so efficacy (false-positive vs catch rate) can be evaluated "
            "from telemetry before it gates real work. When True, a trip "
            "QUARANTINES the issue (ready=False) and the real triage agent is "
            "never handed the request. Flip to True once shadow telemetry looks "
            "good."
        ),
    )
    triage_honeypot_model: str = Field(
        default="haiku",
        description=(
            "Model for the triage injection honeypot. A cheap classifier — the "
            "signal is behavioural (did it call a mock tool), not deep reasoning."
        ),
    )
    triage_honeypot_timeout: float = Field(
        default=60.0,
        ge=5.0,
        le=600.0,
        description="Timeout (seconds) for the triage honeypot pre-check.",
    )
    auditor_finding_max_age_days: int = Field(
        default=14,
        ge=0,
        description=(
            "Auto-close auditor-filed findings older than this many days. "
            "0 = disabled. Auditor loops re-file findings on their next cycle."
        ),
    )
    min_plan_words: int = Field(
        default=60,
        ge=20,
        le=2000,
        description=(
            "Minimum word count for a valid plan — a floor that rejects only "
            "empty/skeletal plans; concise-but-complete briefs pass (#9955)"
        ),
    )
    max_plan_chars: int = Field(
        default=5000,
        ge=1000,
        le=45000,
        description=(
            "Hard character budget for a plan (#9955). Kept BELOW "
            "max_impl_plan_chars so the implement boundary never truncates — "
            "truncation is information loss the plan phase paid latency for."
        ),
    )
    plan_design_decision_hitl_threshold: int = Field(
        default=2,
        ge=1,
        le=50,
        description=(
            "Number of design-decision-class CRITICAL plan-review concerns "
            "(unresolved design decision / unvalidated core mechanism, e.g. from "
            "the Risk-Skeptic voter or AssumptionSurfacer) that routes an issue "
            "to `human-required` instead of swapping to `hydraflow-ready` at the "
            "plan->ready gate. Prevents the factory force-implementing "
            "design/research issues where the agent hangs to the timeout and "
            "retry-thrashes (issue #10659). Implementer-addressable concerns "
            "(buildability/coverage/AC) never count toward this threshold."
        ),
    )
    max_new_files_warning: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Warn if plan creates more than this many new files",
    )
    lite_plan_labels: list[str] = Field(
        default=["bug", "typo", "docs"],
        description="Issue labels that trigger a lite plan (fewer required sections)",
    )
    # Metric thresholds for improvement proposals
    quality_fix_rate_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Alert if quality fix rate exceeds this (0.0-1.0)",
    )
    approval_rate_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Alert if first-pass approval rate drops below this (0.0-1.0)",
    )
    hitl_rate_threshold: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Alert if HITL escalation rate exceeds this (0.0-1.0)",
    )

    # Cost budgets (spec §4.11 point 6). Both default to None = "disabled".
    daily_cost_budget_usd: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Soft daily cost budget (USD). When the last-24h machinery "
            "cost exceeds this, ReportIssueLoop files a hydraflow-find "
            "issue with label cost-budget-exceeded. None disables the check."
        ),
    )
    cost_throttle_ratio: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description=(
            "Fraction of daily_cost_budget_usd at which CostBudgetWatcherLoop "
            "starts soft-throttling caretaker loops (interval-stretch) before "
            "the hard-cap kill. 0 disables throttling; no effect when "
            "daily_cost_budget_usd is None. "
            "Env: HYDRAFLOW_COST_THROTTLE_RATIO."
        ),
    )
    issue_cost_alert_usd: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Per-issue cost alert (USD). When a merged issue's final cost "
            "exceeds this, PRManager.merge_pr files a hydraflow-find issue "
            "with label issue-cost-spike. None disables the check."
        ),
    )

    # Review insight aggregation
    review_insight_window: int = Field(
        default=10,
        ge=3,
        le=50,
        description="Number of recent reviews to analyze for patterns",
    )
    review_pattern_threshold: int = Field(
        default=3,
        ge=2,
        le=10,
        description="Minimum category frequency to trigger improvement proposal",
    )

    # Harness insight aggregation
    harness_insight_window: int = Field(
        default=20,
        ge=3,
        le=100,
        description="Number of recent failures to analyze for harness patterns",
    )
    harness_pattern_threshold: int = Field(
        default=3,
        ge=2,
        le=20,
        description="Minimum failure frequency to trigger harness improvement proposal",
    )

    # Agent prompt configuration
    subskill_tool: Literal["claude", "codex"] = Field(
        default="claude",
        description="CLI backend for low-tier subskill/tool-chain passes",
    )
    subskill_model: str = Field(
        default="haiku",
        description="Model used for low-tier subskill/tool-chain passes",
    )
    max_subskill_attempts: int = Field(
        default=0,
        ge=0,
        le=5,
        description="Max low-tier subskill precheck attempts per stage",
    )
    debug_escalation_enabled: bool = Field(
        default=True,
        description="Enable automatic escalation to debug model when low-tier prechecks signal risk/ambiguity",
    )
    debug_tool: Literal["claude", "codex"] = Field(
        default="claude",
        description="CLI backend for debug escalation passes",
    )
    debug_model: str = Field(
        default="opus",
        description="Model used for debug escalation passes",
    )
    max_debug_attempts: int = Field(
        default=1,
        ge=0,
        le=3,
        description="Max debug escalation attempts per stage",
    )
    subskill_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum low-tier confidence before skipping debug escalation",
    )
    # Timeouts
    quality_timeout: int = Field(
        default=3600,
        ge=60,
        le=7200,
        description=(
            "Timeout in seconds per post-build verification command: the full "
            "'make quality' (HITL / diagnostic runners) or each implement-path "
            "step — 'make quality-lite', then the impacted-test run (#11568)"
        ),
    )
    git_command_timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Timeout in seconds for simple git commands (rev-list, rev-parse, status)",
    )
    salvage_commit_timeout: int = Field(
        default=1800,
        ge=60,
        le=3600,
        description=(
            "Timeout in seconds for the salvage 'git commit' in "
            "AgentRunner._force_commit_uncommitted. This commit runs the repo's "
            "pre-commit hook (quality-lite / security / arch-check), so it needs a "
            "make-tier budget rather than the short git_command_timeout tier (#10598)."
        ),
    )
    summarizer_timeout: int = Field(
        default=120,
        ge=30,
        le=600,
        description="Timeout in seconds for transcript summarizer subprocess",
    )
    error_output_max_chars: int = Field(
        default=3000,
        ge=500,
        le=20_000,
        description="Max characters of error output to include in prompts and messages",
    )

    test_command: str = Field(
        default="make test",
        description="Quick test command for agent prompts",
    )
    max_issue_body_chars: int = Field(
        default=10_000,
        ge=1_000,
        le=100_000,
        description="Max characters for issue body in agent prompts before truncation",
    )
    max_review_diff_chars: int = Field(
        default=15_000,
        ge=1_000,
        le=200_000,
        description="Max characters for PR diff in reviewer prompts before truncation",
    )
    max_memory_chars: int = Field(
        default=4000,
        ge=500,
        le=50_000,
        description="Max characters for memory digest before compaction",
    )
    max_memory_prompt_chars: int = Field(
        default=4000,
        ge=500,
        le=50_000,
        description="Max characters for memory digest injected into agent prompts",
    )
    max_troubleshooting_prompt_chars: int = Field(
        default=3000,
        ge=500,
        le=10_000,
        description="Max characters for learned troubleshooting patterns in CI timeout prompts",
    )
    # LogIngestLoop — scans HydraFlow's own server log, clusters/dedups
    # ERROR + WARNING lines, and files GitHub issues into the pipeline.
    log_ingest_interval: int = Field(
        default=14400,
        ge=300,
        le=86400,
        description="Seconds between LogIngestLoop scans (default 4h).",
    )
    log_ingest_warning_min_count: int = Field(
        default=50,
        ge=1,
        le=100000,
        description=(
            "Minimum occurrence count for a WARNING cluster to become an "
            "issue candidate. ERROR clusters are always candidates."
        ),
    )
    log_ingest_max_issues_per_run: int = Field(
        default=3,
        ge=1,
        le=20,
        description=(
            "Hard cap on issues filed per LogIngestLoop cycle "
            "(ERROR-first, then count-descending)."
        ),
    )
    log_ingest_benign_patterns: str = Field(
        default=(
            "adapter pending,auth failed,authentication failed,"
            "repository not found,credit,creditexhausted,hydraflow.log_ingest"
        ),
        description=(
            "Comma-separated case-insensitive substrings; any cluster whose "
            "representative message or logger matches is dropped (known-benign "
            "allowlist). Avoids filing transient/expected noise."
        ),
    )
    log_ingest_label: str = Field(
        default="hydraflow-log-ingest",
        description="Label applied to issues filed by LogIngestLoop (alongside find_label).",
    )
    log_ingest_log_files: str = Field(
        default="logs/hydraflow.log",
        description=(
            "Comma-separated log file paths LogIngestLoop scans. Relative paths "
            "resolve against data_root; absolute paths are used as-is."
        ),
    )

    # Security patch monitoring
    security_patch_interval: int = Field(
        default=3600,
        ge=300,
        le=86400,
        description="Seconds between Dependabot alert polls",
    )
    security_patch_severity_threshold: Literal["critical", "high", "medium", "low"] = (
        Field(
            default="medium",
            description="Minimum severity to file issues for",
        )
    )
    # Sensor enrichment — positive prompt injection on captured tool output.
    # See src/sensor_enricher.py and docs/wiki/gotchas.md.
    sensor_enrichment_enabled: bool = Field(
        default=True,
        description=(
            "Append Agent Hints blocks to captured tool-failure output "
            "based on rules in sensor_rules.SEED_RULES."
        ),
    )

    # Local JSONL issue cache — append-only mirror of GitHub issue state.
    # See src/issue_cache.py and issue #6422.
    issue_cache_enabled: bool = Field(
        default=True,
        description=(
            "Write structured snapshots (classification, plans, reviews, "
            "reproductions, route-backs) to a local JSONL cache alongside "
            "GitHub. GitHub remains the primary source of truth."
        ),
    )

    # Read-through cache decorator (#6422). When enabled, IssueStore
    # is wrapped in CachingIssueStore which records every queue read
    # as a fetch snapshot and serves enrich_with_comments from the
    # cache when records are within the TTL window. Default ON
    # (self-repair on by default): read-through caching is active
    # whenever issue_cache_enabled is also on. Disable via the System
    # tab to fall back to the raw IssueStore.
    caching_issue_store_enabled: bool = Field(
        default=False,
        description=(
            "Wrap IssueStore in CachingIssueStore for read-through "
            "caching of fetches and enrich_with_comments. Requires "
            "issue_cache_enabled. Opt-in (default OFF): enable via the "
            "System tab after confirming cache coverage — it is the "
            "store that populates the review_stored records the "
            "precondition gate reads."
        ),
    )

    issue_cache_enrich_ttl_seconds: int = Field(
        default=300,
        ge=0,
        le=86400,
        description=(
            "TTL window for cached enrich_with_comments results. "
            "Records older than this are treated as stale and the "
            "decorator falls through to the inner store."
        ),
    )

    # Precondition gate enforcement (#6423). OPT-IN — default OFF. Enabling
    # it on a factory whose issue cache has no review_stored coverage yet
    # reroutes every READY issue back to `plan` forever: has_clean_review
    # can never be satisfied, so the full-machine pipeline advances nothing
    # (wedged RC promotion + post-merge smoke 2026-07-28 → #10846/#10845 when
    # #10791 flipped it on globally). giveup_window_enabled bounds the loop
    # but does not make the issue advance. Operators flip this ON via the
    # System tab AFTER confirming cache coverage (see service_registry).
    precondition_gate_enabled: bool = Field(
        default=False,
        description=(
            "Enforce stage preconditions on the implement and review "
            "phases. Requires issue_cache_enabled AND cache coverage of "
            "review_stored records. Opt-in (default OFF): enable via the "
            "System tab after confirming coverage, else READY issues route "
            "back to plan forever and the full-machine pipeline wedges."
        ),
    )
    # Formal give-up window (#10735, epic #10733 child 2) — OTP restart-
    # intensity per child-class. N abnormal exits/retries within T seconds
    # means the child is not converging under retry; the plan-retry route-back
    # then self-solves (ADR-0105 decompose / auto-agent diagnose) instead of
    # thrashing or dumping the issue on a human. resolve_window(config, cls) in
    # giveup_window.py is the single threshold source for all four classes.
    giveup_window_enabled: bool = Field(
        default=True,
        description=(
            "Wire the plan-retry route-back terminal to the formal give-up "
            "window: after giveup_plan_retry_max_restarts route-backs within "
            "giveup_plan_retry_window_secs, self-solve (decompose/diagnose) "
            "instead of routing back again. Default ON (self-repair on by "
            "default; disable via the System tab), and inert unless "
            "precondition_gate_enabled routes the plan-retry loop at all."
        ),
    )
    giveup_build_max_restarts: int = Field(
        default=3,
        ge=1,
        le=100,
        description="Give-up window N for the build child-class (abnormal exits in T).",
    )
    giveup_build_window_secs: int = Field(
        default=3600,
        ge=1,
        description="Give-up window T (seconds) for the build child-class.",
    )
    giveup_review_max_restarts: int = Field(
        default=3,
        ge=1,
        le=100,
        description="Give-up window N for the review child-class (abnormal exits in T).",
    )
    giveup_review_window_secs: int = Field(
        default=3600,
        ge=1,
        description="Give-up window T (seconds) for the review child-class.",
    )
    giveup_loop_max_restarts: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Give-up window N for the background-loop child-class.",
    )
    giveup_loop_window_secs: int = Field(
        default=3600,
        ge=1,
        description="Give-up window T (seconds) for the background-loop child-class.",
    )
    giveup_plan_retry_max_restarts: int = Field(
        default=2,
        ge=1,
        le=100,
        description=(
            "Give-up window N for the plan-retry child-class: plan->ready "
            "route-backs within giveup_plan_retry_window_secs before the "
            "issue self-solves. Defaults to 2 (the legacy hardcoded "
            "max_route_backs) so behaviour is unchanged when the window is on."
        ),
    )
    giveup_plan_retry_window_secs: int = Field(
        default=3600,
        ge=1,
        description="Give-up window T (seconds) for the plan-retry child-class.",
    )
    # Shadow corpus (#8786) — opt-in live sampling of production
    # subprocess calls. When enabled, every gh/git/docker/claude call
    # feeds a bounded, normalized, PII-scrubbed YAML corpus that
    # LiveCorpusReplayLoop will eventually diff against fake-adapter
    # outputs. Off by default until the v2 pattern is validated.
    shadow_corpus_max_per_adapter: int = Field(
        default=100,
        ge=10,
        le=10000,
        description=(
            "Per-adapter LRU cap on shadow corpus size. Most-recently-"
            "recorded call shapes survive eviction; older shapes are "
            "deleted from disk."
        ),
    )
    shadow_corpus_coverage_pruning_enabled: bool = Field(
        default=True,
        description=(
            "Drop shadow-corpus samples at record time when no registered "
            "dispatcher branch can form an opinion on them (#9633), so "
            "no-opinion VOLATILE calls never consume per-adapter LRU "
            "budget. Disable to record every adapter call."
        ),
    )
    live_corpus_replay_interval: int = Field(
        default=900,  # 15 min — drift surfaces within one fresh sample cycle
        ge=60,
        le=86400,
        description=(
            "Seconds between LiveCorpusReplayLoop ticks. Each tick diffs "
            "every fresh shadow-corpus sample against the matching fake-"
            "adapter output via registered dispatchers."
        ),
    )
    live_corpus_max_drift_attempts: int = Field(
        default=3,
        ge=1,
        le=20,
        description=(
            "Per-drift-signature attempt cap before LiveCorpusReplayLoop "
            "escalates to hitl-escalation (auto-agent preflight). Each "
            "tick that re-detects the same drift signature counts as "
            "one attempt; a clean tick clears all counters."
        ),
    )

    # Repo wiki
    repo_wiki_interval: int = Field(
        default=3600,
        ge=300,
        le=604800,
        description="Seconds between repo wiki lint cycles",
    )
    dependabot_update_branch_max_attempts: int = Field(
        default=1,
        ge=0,
        le=5,
        description=(
            "Bounded update-branch heals per CI-failed bot PR (#9889): a "
            "behind-base PR gets a fresh merge ref + full CI re-run before "
            "the failure strategy applies. 0 disables."
        ),
    )
    human_branch_shepherd_enabled: bool = Field(
        default=True,
        description=(
            "Class 5 (#9889): DependabotMergeLoop shepherds human-prefix "
            "branches (fix/, feat/, docs/, test/, chore/, refactor/) to merge "
            "once CI is green — same path as factory branches. Per-PR opt-out: "
            "the no-auto-merge label."
        ),
    )
    dependabot_conflict_heal_enabled: bool = Field(
        default=True,
        description=(
            "Item 2 (#9889): DependabotMergeLoop heals CI-green PRs whose "
            "merge fails on a genuine content conflict (mergeable=False). "
            "Factory-maintenance PRs are closed-superseded (their loop "
            "regenerates a fresh one, single-flight #9939); other bot PRs get "
            "one bounded update-branch before the failure strategy; human "
            "shepherd-prefix PRs get one dedup-bounded conflict comment and "
            "are otherwise left to their author. False restores the legacy "
            "log-and-give-up path."
        ),
    )
    review_orphan_strike_threshold: int = Field(
        default=3,
        ge=1,
        le=20,
        description=(
            "Consecutive PR-less sightings of a review-labeled issue before "
            "it is treated as an orphan and requeued to ready (#9815). "
            "Below the threshold the review loop keeps waiting for PR "
            "propagation as before."
        ),
    )
    review_orphan_max_requeues: int = Field(
        default=3,
        ge=0,
        le=10,
        description=(
            "Bounded orphan requeues per issue before escalating to HITL "
            "instead (#9815). 0 disables orphan requeue entirely (legacy "
            "wait-forever behavior)."
        ),
    )
    repo_wiki_min_batch_files: int = Field(
        default=8,
        ge=1,
        le=100,
        description=(
            "Defer the wiki maintenance PR until at least this many files "
            "changed — batches the near-hourly single-entry PR treadmill "
            "(each merge re-stales sibling PRs via the arch cascade). "
            "1 restores open-on-any-change."
        ),
    )
    repo_wiki_max_batch_age_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        description=(
            "Force a wiki maintenance PR open regardless of batch size once "
            "the newest merged maintenance PR is older than this — small "
            "dribbles still land within a bounded window."
        ),
    )
    max_repo_wiki_chars: int = Field(
        default=15_000,
        ge=1_000,
        le=100_000,
        description="Max characters for repo wiki context injected into agent prompts",
    )
    wiki_compilation_model: str = Field(
        default="haiku",
        description="Model for wiki compilation and synthesis",
    )
    wiki_compilation_tool: Literal["claude", "codex"] = Field(
        default="claude",
        description="CLI backend for wiki compilation",
    )
    wiki_compilation_timeout: int = Field(
        default=300,
        ge=30,
        le=600,
        description="Timeout in seconds for wiki compilation LLM calls",
    )

    # Hindsight + memory_auto_approve knobs removed in Phase 3 cutover.

    # Observability context injection
    max_runtime_log_chars: int = Field(
        default=8_000,
        ge=1_000,
        le=100_000,
        description="Max characters for runtime log injection",
    )
    max_ci_log_chars: int = Field(
        default=12_000,
        ge=1_000,
        le=100_000,
        description="Max characters for CI failure log injection",
    )
    max_code_scanning_chars: int = Field(
        default=6_000,
        ge=1_000,
        le=100_000,
        description="Max characters for code scanning alert injection",
    )

    # Prompt budget configuration — truncation limits for prompt sections
    max_discussion_comment_chars: int = Field(
        default=500,
        ge=100,
        le=10_000,
        description="Max characters per discussion comment in implementation prompts",
    )
    max_common_feedback_chars: int = Field(
        default=2_000,
        ge=100,
        le=20_000,
        description="Max characters for common feedback section in implementation prompts",
    )
    max_impl_plan_chars: int = Field(
        default=6_000,
        ge=1_000,
        le=50_000,
        description="Max characters for implementation plan in agent prompts",
    )
    max_review_feedback_chars: int = Field(
        default=2_000,
        ge=100,
        le=20_000,
        description="Max characters for review feedback in implementation prompts",
    )
    max_planner_comment_chars: int = Field(
        default=1_000,
        ge=100,
        le=10_000,
        description="Max characters per comment in planner prompts",
    )
    max_planner_line_chars: int = Field(
        default=500,
        ge=100,
        le=5_000,
        description="Max characters per line in planner prompts (prevents unsplittable chunks)",
    )
    max_planner_failed_plan_chars: int = Field(
        default=4_000,
        ge=500,
        le=50_000,
        description="Max characters for failed plan text in planner retry prompts",
    )
    max_hitl_correction_chars: int = Field(
        default=4_000,
        ge=500,
        le=50_000,
        description="Max characters for HITL human correction text in prompts",
    )
    max_hitl_cause_chars: int = Field(
        default=2_000,
        ge=100,
        le=20_000,
        description="Max characters for HITL escalation cause in prompts",
    )
    max_ci_log_prompt_chars: int = Field(
        default=6_000,
        ge=1_000,
        le=50_000,
        description="Max characters for CI logs in reviewer fix prompts",
    )
    max_unsticker_cause_chars: int = Field(
        default=3_000,
        ge=100,
        le=20_000,
        description="Max characters for escalation cause in PR unsticker prompts",
    )
    max_verification_instructions_chars: int = Field(
        default=50_000,
        ge=1_000,
        le=65_000,
        description="Max characters for verification instructions in post-merge issues",
    )

    # Visual gate
    prompt_observatory_enabled: bool = Field(
        default=True,
        description=(
            "Record prompt SHAPES (structural hashes, never content) at the "
            "CH-6 gate, so prompt coverage has an observed denominator rather "
            "than one inferred from builder naming conventions (#10857)"
        ),
    )
    visual_gate_enabled: bool = Field(
        default=False,
        description="Require visual validation gate before merge finalization",
    )
    visual_gate_bypass: bool = Field(
        default=False,
        description="Emergency bypass for visual gate (audit-logged)",
    )

    # Visual validation scope and flake mitigation
    visual_validation_enabled: bool = Field(
        default=True,
        description="Enable visual validation scope checks and runtime validation during review",
    )
    visual_validation_trigger_patterns: list[str] = Field(
        default_factory=lambda: [
            "src/ui/**",
            "ui/**",
            "frontend/**",
            "web/**",
            "*.css",
            "*.scss",
            "*.tsx",
            "*.jsx",
            "*.html",
        ],
        description="Glob patterns for files that trigger visual validation requirement",
    )
    visual_required_label: str = Field(
        default="hydraflow-visual-required",
        description="Override label to force visual validation regardless of file paths",
    )
    visual_skip_label: str = Field(
        default="hydraflow-visual-skip",
        description="Override label to skip visual validation with an audit reason",
    )
    visual_max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Max retries for transient visual validation failures",
    )
    visual_retry_delay: float = Field(
        default=2.0,
        ge=0.0,
        le=30.0,
        description="Seconds to wait between visual validation retries",
    )
    visual_warn_threshold: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Diff ratio above which a screen gets a WARN verdict",
    )
    visual_fail_threshold: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="Diff ratio above which a screen gets a FAIL verdict",
    )

    # Screenshot security
    screenshot_redaction_enabled: bool = Field(
        default=True,
        description=(
            "Run backend secret-pattern scan before uploading dashboard screenshots. "
            "When True, payloads matching known secret patterns (GitHub tokens, AWS keys, "
            "etc.) are rejected and the screenshot is stripped from the report. "
            "Frontend DOM redaction of [data-sensitive] elements is always active "
            "and is unaffected by this setting."
        ),
    )
    screenshot_gist_public: bool = Field(
        default=False,
        description="Upload screenshot gists as public (True) or secret/unlisted (False)",
    )

    # Research before planning. ResearchRunner spawns a real ``claude``
    # subprocess; disabling lets the sandbox skip that subprocess in the
    # air-gapped container. Production defaults to True.
    research_enabled: bool = Field(
        default=True,
        description="Run ResearchRunner before PlanPhase to inject codebase context",
    )
    # The research pre-pass is a full extra codebase-exploration subprocess
    # on top of the planner's own exploration — so it is gated, not run for
    # every issue. With ``research_enabled`` on, research runs only for issues
    # that need the depth: those carrying one of these escalation labels, and
    # those that have cycled back to planning (route-back count > 0). The
    # common first-pass issue skips research and lets the planner explore once.
    research_escalation_labels: list[str] = Field(
        # #11145: follows the merged HITL-escalation queue root.
        default=["hitl-escalation"],
        description=(
            "Labels that force the research pre-pass before planning "
            "(escalated issues). Cycled issues (route-back count > 0) also "
            "trigger research regardless of label. OR logic."
        ),
    )

    # Transcript summarization
    transcript_summarization_enabled: bool = Field(
        default=True,
        description="Run automatic transcript summarization after each agent phase",
    )
    transcript_summary_model: str = Field(
        default="haiku",
        description="Cheap model for summarising agent transcripts into structured learnings",
    )
    transcript_summary_tool: Literal["claude", "codex"] = Field(
        default="claude",
        description="CLI backend for transcript summarization",
    )
    max_transcript_summary_chars: int = Field(
        default=50_000,
        ge=5_000,
        le=500_000,
        description="Max transcript characters to send for summarization (truncated from end)",
    )
    # Report issue worker
    report_issue_tool: Literal["claude", "codex"] = Field(
        default="claude",
        description="CLI backend for report-issue worker",
    )
    report_issue_model: str = Field(
        default="opus",
        description="Model for report-issue worker (codebase research + structured issue creation)",
    )
    report_issue_interval: int = Field(
        default=30,
        ge=10,
        le=3600,
        description="Seconds between report-issue worker polls",
    )
    stale_report_threshold_hours: int = Field(
        default=6,
        ge=1,
        le=168,
        description="Hours after which a queued report is considered stale and auto-closed",
    )

    # Git configuration
    main_branch: str = Field(default="main", description="Base branch name")

    # Staging + RC promotion
    staging_branch: str = Field(
        default="staging",
        description="Integration branch name for agent PRs (when staging_enabled)",
    )
    staging_enabled: bool = Field(
        default=True,
        description=(
            "Master switch (ADR-0042 two-tier release): when true, agent PRs "
            "target staging_branch and main advances only via auto-promoted RC "
            "PRs. Default ON; disable via the System tab for single-tier "
            "(agent PRs target main directly)."
        ),
    )
    rc_conflict_heal_enabled: bool = Field(
        default=True,
        description=(
            "#11216: self-heal a DIRTY rc/* promotion PR by merging its "
            "base branch in (the manual recipe a human ran 3x on "
            "2026-08-15/16) instead of leaving it for an operator. Merge, "
            "never rebase — rebasing diverges the RC (#11045)."
        ),
    )
    rc_conflict_heal_max_attempts: int = Field(
        default=2,
        ge=1,
        le=10,
        description=(
            "Per-RC-branch cap on #11216 self-heal attempts; beyond it the "
            "conflict is genuinely unresolvable and escalates to the human."
        ),
    )
    rc_cadence_hours: int = Field(
        default=4,
        ge=1,
        le=168,
        description="Hours between release-candidate cuts",
    )
    rc_consecutive_failure_escalation_threshold: int = Field(
        default=3,
        ge=1,
        le=50,
        description=(
            "Consecutive RC-promotion CI failures before StagingPromotionLoop "
            "files one hitl-escalation issue (so a multi-day stall is noticed)"
        ),
    )
    rc_branch_prefix: str = Field(
        default="rc/",
        description="Prefix for release-candidate branch names",
    )
    rc_auto_recut_enabled: bool = Field(
        default=False,
        description=(
            "G1 (#10353): when true, StagingPromotionLoop re-cuts a fresh RC "
            "ahead of the normal cadence once the rc-promotion-stuck escalation "
            "is open AND staging CI is green again (the blocking gate cleared). "
            "Default OFF — inert until explicitly enabled; the live blocker-clear "
            "signal needs validation against a real RC before opt-in."
        ),
    )
    rc_observed_advance_close_enabled: bool = Field(
        default=True,
        description=(
            "G1 (#10353): when true, StagingPromotionLoop closes the RC-stuck "
            "trackers whenever `main` is observed to advance via a merged rc/* "
            "promotion PR (a manual/operator merge included), not only on the "
            "loop's own merge. Default ON (live). Kill-switch: the sandbox turns "
            "it OFF because the observed-advance sweep reads merged PRs via a raw "
            "`gh pr list` that bypasses FakeGitHub and would hang the air-gapped "
            "network (same class as evidence_pack / approval_records)."
        ),
    )
    rc_promotion_health_enabled: bool = Field(
        default=True,
        description=(
            "G1 (#10353): when true, StagingPromotionLoop emits the promotion "
            "error-signal — the `main..staging` commit gap + "
            "days_since_last_successful_promotion + consecutive_rc_failures — in "
            "its BACKGROUND_WORKER_STATUS telemetry each tick, so promotion "
            "health is measurable, not implied. Default ON (read-only "
            "observability). Kill-switch: the sandbox turns it OFF because the "
            "gap read spawns a raw `gh api compare` that bypasses FakeGitHub and "
            "would hang the air-gapped network (same class as evidence_pack / "
            "rc_observed_advance_close). The two other signals are state-only and "
            "always surface."
        ),
    )
    staging_promotion_interval: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="Seconds between StagingPromotionLoop ticks",
    )
    staging_rc_retention_days: int = Field(
        default=7,
        ge=1,
        le=90,
        description="Days to retain failed RC branches before cleanup",
    )
    staging_bisect_interval: int = Field(
        default=600,
        ge=60,
        le=86400,
        description=(
            "Seconds between StagingBisectLoop ticks — a state-tracker "
            "watchdog poll for last_rc_red_sha changes. See ADR-0042 §4.3."
        ),
    )
    staging_bisect_runtime_cap_seconds: int = Field(
        default=2700,
        ge=300,
        le=14400,
        description=(
            "Hard wall-clock cap on a single bisect run (default 45 min). "
            "On timeout the loop files hitl-escalation bisect-harness-failure."
        ),
    )
    # -- per-loop work-cycle watchdog (#9455 / #9556) -------------------------
    # Bounds every BaseBackgroundLoop._do_work() cycle so a hung loop cannot
    # block indefinitely and silently freeze its heartbeat. Loops opt into the
    # longer LLM bound via the LONG_LLM_CYCLE ClassVar.
    #
    # v1 intent = catch *true hangs* (a cycle that never returns), NOT enforce a
    # tight per-loop SLA. Bounds are deliberately generous so no legitimate
    # cycle is false-killed: the heaviest real cycles are bisect (~45 min),
    # adversarial eval (~60 min) and `make audit` (~30 min), all well under the
    # 2 h default. Operators tighten per-loop later via timeout_cb / config once
    # real per-loop SLAs are established. A killed cycle is recoverable (lost
    # cycle, retries next tick) and surfaces as a distinct "watchdog timeout"
    # ERROR, so a too-tight bound is self-evident and reclassifiable.
    loop_watchdog_default_seconds: int = Field(
        default=7200,
        ge=60,
        le=21600,
        description=(
            "Per-cycle watchdog bound (seconds) for normal background loops "
            "(default 2 h — generous, sized to catch true hangs without "
            "false-killing the heaviest legit cycle). A cycle exceeding this is "
            "cancelled and raises LoopCycleTimeoutError, reported as a loop "
            "error; the loop retries next tick. "
            "Env: HYDRAFLOW_LOOP_WATCHDOG_DEFAULT_SECONDS."
        ),
    )
    loop_watchdog_llm_seconds: int = Field(
        default=14400,
        ge=300,
        le=43200,
        description=(
            "Per-cycle watchdog bound (seconds) for loops that call an LLM or "
            "run an exceptionally long subprocess (LONG_LLM_CYCLE = True; "
            "default 4 h). Such cycles legitimately run far longer than poll "
            "cycles, so they get a wider bound than loop_watchdog_default_seconds. "
            "Env: HYDRAFLOW_LOOP_WATCHDOG_LLM_SECONDS."
        ),
    )
    worker_stall_tight_loops: list[str] = Field(
        default_factory=lambda: [
            "staging_bisect",
            "flake_tracker",
            "skill_prompt_eval",
        ],
        description=(
            "HealthMonitorLoop generic stall sweep (#10241): loops that opt "
            "into worker_stall_tight_multiplier instead of the blanket "
            "3×interval+cycle_timeout remediation threshold. The gap isn't "
            "unique to short-poll/long-cycle loops like staging_bisect (600s "
            "poll, 7200s watchdog, blanket threshold 9000s vs a 7200s trust "
            "alert, #10234) — any trust-loop whose poll interval exceeds its "
            "cycle_timeout has the same shape, just wider: flake_tracker "
            "(14400s poll, 7200s watchdog) has a blanket threshold of 50400s "
            "vs a 28800s trust alert, a ~6h window with an open anomaly issue "
            "and no attempted remediation (#10795); skill_prompt_eval's "
            "weekly poll (604800s, 7200s watchdog) widens that to a full "
            "extra week — blanket threshold 1821600s vs a 1209600s trust "
            "alert (#11091). Names here fire the auto-restart closer to "
            "that alert window while keeping the no-false-restart floor "
            "(see worker_stall_tight_multiplier)."
        ),
    )
    worker_stall_tight_multiplier: int = Field(
        default=2,
        ge=1,
        le=100,
        description=(
            "HealthMonitorLoop stall sweep (#10241): interval multiplier for "
            "loops in worker_stall_tight_loops (default 2 vs the blanket 3). "
            "The sweep RESTARTS a loop, so its threshold "
            "(multiplier×interval + cycle_timeout) must stay strictly above "
            "the worst-case legitimate heartbeat age — one pre-cycle poll "
            "interval plus a full cycle_timeout (the watchdog bound a healthy "
            "cycle cannot exceed). ge=1 preserves that no-false-restart floor "
            "(multiplier×interval + cycle_timeout > interval + cycle_timeout) "
            "while firing remediation ~1 interval closer to the trust-fleet "
            "staleness alert. Env: HYDRAFLOW_WORKER_STALL_TIGHT_MULTIPLIER."
        ),
    )
    # -- thread-level event-loop freeze detector (#9552) ----------------------
    # The asyncio cycle watchdog above cannot see a SYNCHRONOUS block inside a
    # cycle (CPU spin, blocking file I/O, non-async subprocess.run): such a
    # block freezes the whole event loop, including every asyncio-scheduled
    # watcher. EventLoopWatchdog (src/event_loop_watchdog.py) is the
    # out-of-loop complement: a daemon thread wall-clocks a 1s asyncio beacon.
    # Knobs are System-tab editable via settings_registry — deliberately NOT
    # in the env-override tables (knobs→System; secrets stay .env).
    event_loop_watchdog_enabled: bool = Field(
        default=True,
        description=(
            "Enable the thread-level event-loop freeze detector (#9552). A "
            "daemon watchdog thread checks a 1s asyncio liveness beacon; when "
            "the beacon goes stale past event_loop_watchdog_stall_seconds it "
            "dumps all thread stacks (faulthandler — names the blocking call "
            "site) and leaves a stall marker the health monitor escalates as "
            "a hydraflow-find issue. Detection + dump + notify only; process "
            "restart is the separate opt-in hard-restart knob. Captured at "
            "orchestrator startup (restart to apply)."
        ),
    )
    event_loop_watchdog_stall_seconds: int = Field(
        default=120,
        ge=30,
        le=3600,
        description=(
            "Beacon staleness (seconds) before the event loop is declared "
            "frozen (default 120 ≈ 120 missed 1s beacons — generous, so a "
            "briefly-blocking legitimate call never trips it; a true "
            "synchronous wedge is multi-minute). Re-read by the watchdog "
            "thread on every poll, so changes apply live."
        ),
    )
    event_loop_watchdog_hard_restart: bool = Field(
        default=False,
        description=(
            "OPT-IN hard recovery for a frozen event loop: after the stack "
            "dump and stall marker, exit the process with code 75 "
            "(EX_TEMPFAIL) so systemd/docker/launchd restarts it. Default "
            "OFF — notify-default, restart-opt-in, mirroring branch-GC and "
            "the external liveness watchdog (#10009). Enable only where a "
            "supervisor with Restart=always is in place; without one this "
            "turns a frozen process into a dead one. Re-read at trip time."
        ),
    )
    event_loop_watchdog_restart_after_episodes: int = Field(
        default=2,
        ge=1,
        le=10,
        description=(
            "How many accumulated freeze episodes a hard restart requires "
            "(#11604). Default 2: the first episode notifies (stack dump, "
            "stall marker, loop-stalled issue) and only a REPEAT exits the "
            "process. The counter is the stall marker's episode_count, which "
            "resets when the health monitor gets a healthy cycle and consumes "
            "the marker — so 'recovered well enough to file the issue' resets "
            "it, while 'froze, recovered, froze again' climbs it. Set to 1 to "
            "restore restart-on-first-episode. Re-read at trip time."
        ),
    )
    event_loop_watchdog_starvation_service_ratio: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "Observer service ratio below which a freeze is blamed on HOST "
            "CPU starvation rather than a wedged loop, vetoing the hard "
            "restart (#11604). The ratio is the watchdog thread's own polls "
            "taken over the freeze window divided by the polls its cadence "
            "called for: a wedged event loop does not stop a separate OS "
            "thread waking on time (ratio ~1.0), but an oversubscribed host "
            "starves the observer too. Default 0.5 — the observer must have "
            "lost HALF its own schedule before a restart is vetoed. Set to "
            "0.0 to disable the veto. Never vetoes the notify path. Re-read "
            "at trip time."
        ),
    )
    staging_bisect_flake_reruns: int = Field(
        default=2,
        ge=1,
        le=5,
        description=(
            "Number of additional bisect-probe runs the flake filter "
            "executes before declaring an RC red confirmed (spec §4.3 "
            "line 614). Default 2 enables 2-of-3 logic: any retry passing "
            "dismisses as flake; both retries failing confirms the red. "
            "Single-retry filters miscall ~50% of flakes as real "
            "regressions; this is the minimum defensible bar."
        ),
    )
    max_retry_lineage_attempts: int = Field(
        default=2,
        ge=1,
        le=20,
        description=(
            "Per-lineage cap (spec §4.3 lines 645–659; default 2). The "
            "bisect loop tracks retry attempts per `lineage_id` (hash of "
            "culprit-PR title + impacted-test set). When the count exceeds "
            "this cap, the loop stops retrying that lineage and files a "
            "`retry-lineage-exhausted` escalation. The default bounds the "
            "spec's worst-case sequence: original → revert → retry → red "
            "→ human."
        ),
    )
    staging_bisect_watchdog_rc_cycles: int = Field(
        default=2,
        ge=1,
        le=10,
        description=(
            "Max RC cycles to wait for a green outcome after an auto-revert "
            "before filing hitl-escalation rc-red-verify-timeout."
        ),
    )

    git_user_name: str = Field(
        default="",
        description="Git user.name for worktree commits; falls back to global git config if empty",
    )
    git_user_email: str = Field(
        default="",
        description="Git user.email for worktree commits; falls back to global git config if empty",
    )

    # Git-backed repo wiki (see docs/git-backed-wiki-design.md)
    repo_wiki_git_backed: bool = Field(
        default=True,
        description=(
            "When True, RepoWikiStore writes per-entry markdown files with "
            "YAML frontmatter under the tracked `repo_wiki/` layout; ingest "
            "commits the new files inside the active worktree so wiki "
            "updates ride the issue's PR. Feature flag for Phase 3 rollout."
        ),
    )
    repo_wiki_path: str = Field(
        default="repo_wiki",
        description="Tracked root directory (relative to repo_root) for the per-entry wiki layout",
    )
    repo_wiki_maintenance_auto_merge: bool = Field(
        default=True,
        description=(
            "When True, RepoWikiLoop enables auto-merge on its maintenance "
            "PRs (chore(wiki): maintenance ...) so merges happen on green CI "
            "without human approval. Phase 4."
        ),
    )
    repo_wiki_maintenance_pr_coalesce: bool = Field(
        default=True,
        description=(
            "When True, subsequent maintenance ticks append commits to an "
            "already-open maintenance PR instead of opening a new one. "
            "Phase 4."
        ),
    )
    semantic_drift_enabled: bool = Field(
        default=False,
        description=(
            "When True, RepoWikiLoop runs an LLM-backed semantic-drift pass "
            "on wiki entries whose citations still exist on disk but whose "
            "CLAIMs may have rotted (renamed defaults, swapped models, "
            "changed control flow). Off by default until eval-tuned."
        ),
    )
    semantic_drift_min_age_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description=(
            "Minimum entry age before the semantic-drift pass reconsiders "
            "it. Freshly written entries are trusted; only older ones are "
            "re-judged against current source."
        ),
    )
    semantic_drift_max_entries_per_tick: int = Field(
        default=10,
        ge=1,
        le=200,
        description=(
            "Cost bound: cap how many semantic-drift LLM calls the wiki "
            "loop makes per tick. Older entries beyond this cap carry over "
            "to the next tick."
        ),
    )
    wiki_anchor_prune_enabled: bool = Field(
        default=True,
        description=(
            "When True (#9954), RepoWikiLoop runs a deterministic prune pass "
            "that marks active tracked wiki entries stale when they lack a "
            "repo-specific anchor (a src/*.py path, ADR number, loop/Port "
            "class name, or config field) — i.e. generic best-practice "
            "platitudes. Mark-only (never deletes); the flips ride the "
            "normal batched maintenance PR. Default ON (self-repair on by "
            "default; disable via the System tab): it runs the prune pass "
            "that marks anchor-less platitude entries stale. The "
            "synthesis-time gate that blocks NEW anchor-less entries is "
            "always on and independent of this flag."
        ),
    )

    # Paths (auto-detected)
    repo_root: Path = Field(default=Path("."), description="Repository root directory")
    workspace_base: Path = Field(
        default=Path("."),
        description="Base directory for workspaces",
        validation_alias=AliasChoices("workspace_base", "worktree_base"),
    )
    data_root: Path = Field(
        default=Path("."),
        description="Directory for persistent HydraFlow data (.hydraflow)",
    )
    repos_workspace_dir: Path = Field(
        default=Path("~/.hydra/repos"),
        description="Base directory for cloned GitHub repos (default ~/.hydra/repos)",
    )
    state_file: Path = Field(default=Path("."), description="Path to state JSON file")

    # Event persistence
    event_log_path: Path = Field(
        default=Path("."),
        description="Path to event log JSONL file",
    )
    event_log_max_size_mb: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Max event log file size in MB before rotation",
    )
    event_log_retention_days: int = Field(
        default=7,
        ge=1,
        le=90,
        description="Days of event history to retain during rotation",
    )
    event_log_periodic_rotate_enabled: bool = Field(
        default=True,
        description=(
            "Rotate events.jsonl every RunsGCLoop cycle, not just at boot "
            "(#9905). The size bound inside rotation guarantees the "
            "post-rotation file fits event_log_max_size_mb."
        ),
    )
    boot_gap_alert_threshold_seconds: int = Field(
        default=600,
        ge=60,
        le=86400,
        description=(
            "At boot, if the gap between the last persisted events.jsonl "
            "entry and process start exceeds this many seconds, publish one "
            "SYSTEM_ALERT ('factory was down ~Xh') so the dashboard shows the "
            "outage after the fact (#10009). Default 10 minutes — long enough "
            "to not fire on a normal quick restart/deploy."
        ),
    )
    state_prune_enabled: bool = Field(
        default=True,
        description=(
            "Prune per-issue state.json entries (adversarial states, "
            "convergence ledgers, attempt counters) for issues that are no "
            "longer open, during StaleIssueGCLoop cycles (#9905)."
        ),
    )

    # Health monitor
    health_monitor_interval: int = Field(
        default=7200,
        ge=60,
        le=86400,
        description="Health monitor cycle interval in seconds",
    )
    fleet_vitals_enabled: bool = Field(
        default=True,
        description=(
            "#11391 fleet-vitals shadow supervisor: bands over the health "
            "monitor's fleet metrics (hitl_rate, first_pass_rate) with "
            "hysteresis; on alarm, attaches a mechanical change-ledger "
            "diagnosis and a SHADOW intervention proposal (never actuates)."
        ),
    )
    fleet_hitl_rate_alarm: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "hitl_rate alarm threshold (#11391). Founding incident of "
            "record: 0.74 logged at INFO while the light-tier cascade ran."
        ),
    )
    fleet_hitl_rate_rearm: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="hitl_rate must settle below this to re-arm the alarm.",
    )
    fleet_first_pass_floor: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description=(
            "first_pass_rate at or below this floor breaches (#11391); "
            "clears above 2x the floor."
        ),
    )
    fleet_board_growth_alarm: int = Field(
        default=8,
        ge=1,
        description=(
            "Net open-issue growth per health-monitor cycle (~2h) that "
            "breaches the board_growth band (#11391) — the 88-issue churn "
            "class: the #11390 valve bounds the LEVEL, this band alarms on "
            "the RATE so a new generator is caught in hours."
        ),
    )
    fleet_alarm_confirm_windows: int = Field(
        default=2,
        ge=1,
        le=10,
        description=(
            "Consecutive breaching health-monitor cycles required before a "
            "fleet alarm fires (ISA-18.2 confirm discipline)."
        ),
    )
    wiki_freshness_stale_days: int = Field(
        default=7,
        ge=1,
        le=365,
        description=(
            "Wiki-freshness threshold (days). HealthMonitorLoop files a "
            "`wiki-stale` issue when docs/wiki/log.jsonl has not moved in "
            "this many days, surfacing silent RepoWikiLoop stalls."
        ),
    )
    stale_code_alert_threshold: int = Field(
        default=10,
        ge=1,
        le=1000,
        description=(
            "Commits-behind threshold (#9596). HealthMonitorLoop files a "
            "`factory-stale-code` issue when the running instance's boot "
            "SHA is at least this many commits behind origin/<base_branch> "
            "(git_revision.get_commits_behind, #9663), surfacing a process "
            "that is still running old bytecode after a `git pull` without "
            "a restart."
        ),
    )

    # Config file persistence
    config_file: Path | None = Field(
        default=None,
        description="Path to JSON config file for persisting runtime changes",
    )
    repo_config_file: Path | None = Field(
        default=None,
        description="Repo-scoped config file path (defaults to data_root/config.json)",
        exclude=True,
    )
    cli_explicit_fields: frozenset[str] = Field(
        default_factory=frozenset,
        description="Fields explicitly set via CLI args (internal use)",
        exclude=True,
    )

    # Changelog
    changelog_file: str = Field(
        default="",
        description="Path to CHANGELOG.md file for epic completion changelog generation; "
        "empty string disables file output",
    )

    # Dashboard
    dashboard_host: str = Field(
        default="127.0.0.1",
        min_length=1,
        description="Interface/IP to bind the dashboard web server to",
    )
    dashboard_port: int = Field(
        default=5555, ge=1024, le=65535, description="Dashboard web UI port"
    )
    dashboard_enabled: bool = Field(
        default=True, description="Enable the live web dashboard"
    )
    factory_autostart: bool = Field(
        default=True,
        description=(
            "Autostart the host orchestrator once the server is healthy at "
            "boot — the same path as POST /api/control/start (#11208). "
            "Suppressed by an active operator-stopped latch (see "
            "state.get_operator_stopped); production only, never reached by "
            "MockWorld or the sandbox docker entrypoint."
        ),
    )

    # Polling
    poll_interval: int = Field(
        default=30, ge=5, le=300, description="Seconds between work-queue polls"
    )
    memory_sync_interval: int = Field(
        default=3600,
        ge=10,
        le=14400,
        description="Seconds between memory sync polls (default: 1 hour)",
    )
    data_poll_interval: int = Field(
        default=300,
        ge=10,
        le=600,
        description="Seconds between centralized GitHub issue store polls",
    )
    pr_unstick_interval: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Seconds between PR unsticker polls",
    )
    dependabot_merge_interval: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Seconds between Dependabot merge auto-merge polls",
    )
    dependabot_arch_autoheal_max_attempts: int = Field(
        default=2,
        ge=0,
        le=10,
        description=(
            "Max times DependabotMergeLoop will self-heal a bot PR whose CI is "
            "red purely on stale docs/arch/generated/ artifacts (merge "
            "origin/<base>, run arch-regen, push). When another open bot PR "
            "advances <base>, every other open bot PR's committed generated "
            "artifacts go stale and arch-check fails even on files the PR never "
            "touched, leaving the PR stuck open forever (observed on "
            "#9422-#9428). The loop merges + regenerates instead of skipping; a "
            "bounded retry is the safety net for a real (non-arch) failure: when "
            "regen does not turn the PR green within this many attempts, the "
            "normal failure_strategy applies. Set to 0 to disable self-heal "
            "entirely (kill switch)."
        ),
    )
    pr_unstick_batch_size: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Max PRs to unstick per cycle (fetch limit and parallel workers)",
    )
    unstick_auto_merge: bool = Field(
        default=True,
        description="Auto-merge PRs after fixing and CI passes",
    )
    unstick_all_causes: bool = Field(
        default=True,
        description="Process all HITL causes (not just merge conflicts)",
    )
    enable_fresh_branch_rebuild: bool = Field(
        default=True,
        description="After merge conflict resolution exhausts all attempts, "
        "try rebuilding on a fresh branch from main before escalating to HITL",
    )

    # ADR Council Review
    adr_review_interval: int = Field(
        default=86400,
        ge=28800,
        le=432000,
        description="Seconds between ADR review cycles",
    )
    adr_review_approval_threshold: int = Field(
        default=2,
        ge=1,
        le=3,
        description="Number of APPROVE votes needed for acceptance",
    )
    adr_review_max_rounds: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Maximum deliberation rounds before forcing a decision",
    )
    adr_review_tool: Literal["claude", "codex"] = Field(
        default="claude",
        description="CLI backend for the ADR council review orchestrator",
    )
    adr_review_model: str = Field(
        default="sonnet",
        description="Model for the ADR council review orchestrator",
    )

    # Session retention
    max_sessions_per_repo: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Max session logs to retain per repo",
    )

    # Acceptance criteria generation
    ac_model: str = Field(
        default="sonnet",
        description="Model for acceptance criteria generation (post-merge)",
    )
    ac_tool: Literal["claude", "codex"] = Field(
        default="claude",
        description="CLI backend for acceptance criteria generation",
    )
    verification_judge_tool: Literal["claude", "codex"] = Field(
        default="claude",
        description="CLI backend for verification judge agents",
    )

    # UI directories (fallback for worktree node_modules symlinking)
    ui_dirs: list[str] = Field(
        default_factory=lambda: ["ui"],
        description="UI directories containing package.json; auto-detected at runtime if present",
    )

    # Retrospective
    retrospective_window: int = Field(
        default=10,
        ge=3,
        le=100,
        description="Number of recent retrospective entries to scan for patterns",
    )
    retrospective_interval: int = Field(
        default=86400,
        ge=60,
        le=604800,
        description="Poll interval in seconds for retrospective analysis loop",
    )

    # Trust fleet — LoopFitnessScorecard (spec §5)
    fitness_scorecard_interval: int = Field(
        default=86400,
        ge=3600,
        le=604800,
        description="Seconds between loop-fitness scorecard cycles",
    )
    fitness_window_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="Rolling window (days) over which loop fitness is computed",
    )
    fitness_min_samples: int = Field(
        default=5,
        ge=1,
        le=10000,
        description=(
            "Min samples before a SCORED loop reports OK confidence. "
            "Right-sized to observed proposer throughput (6-14 filed per "
            "30-day window; #9841 — the old default of 20 was unreachable "
            "and every scorecard row stayed insufficient_data forever). "
            "Loops additionally cap this at their cadence-achievable sample "
            "count via loop_fitness.cadence_min_samples."
        ),
    )

    # Trust fleet — FlakeTrackerLoop (spec §4.5)
    flake_tracker_interval: int = Field(
        default=14400,
        ge=3600,
        le=2_592_000,
        description="Seconds between FlakeTrackerLoop ticks (default 4h)",
    )
    flake_threshold: int = Field(
        default=3,
        ge=2,
        le=20,
        description="Flake count in last 20 runs that triggers an issue (>=)",
    )
    xdist_quarantine_threshold: int = Field(
        default=2,
        ge=1,
        le=20,
        description=(
            "xdist-audit runs a test must be flagged fail-parallel/pass-serial "
            "in before FlakeTrackerLoop files a quarantine issue (>=)"
        ),
    )

    # Trust fleet — SkillPromptEvalLoop (spec §4.6)
    skill_prompt_eval_interval: int = Field(
        default=604800,
        ge=86400,
        le=2_592_000,
        description="Seconds between SkillPromptEvalLoop ticks (default 7d)",
    )
    skill_prompt_eval_max_corpus_cases: int = Field(
        default=500,
        ge=10,
        le=10_000,
        description=(
            "Defense-in-depth cap on adversarial corpus cases per weekly "
            "tick. Forwarded to the harness via HYDRAFLOW_TRUST_ADVERSARIAL_"
            "MAX_CASES (pre-spend) and applied as a Python-side sample "
            "(post-output) to bound operator-visible escalation flooding "
            "if the harness misses the env var."
        ),
    )
    skill_prompt_eval_live_case_budget: int = Field(
        default=12,
        ge=0,
        le=500,
        description=(
            "Max catcher-skill corpus cases a LIVE weekly backstop run "
            "evaluates via the per-skill live path (each builds its own "
            "skill's prompt and makes one real agent-CLI call; round-robin "
            "across skills). Forwarded to the corpus runner via HYDRAFLOW_"
            "TRUST_ADVERSARIAL_LIVE_BUDGET; inert unless HYDRAFLOW_TRUST_"
            "ADVERSARIAL_LIVE=1. 0 disables the per-skill live path. Keep "
            "aligned with corpus_runner.DEFAULT_LIVE_BUDGET (#10014)."
        ),
    )
    skill_prompt_eval_adversarial_timeout_seconds: int = Field(
        default=3600,
        ge=60,
        le=21600,
        description=(
            "Hard cap (seconds) on the `make trust-adversarial` subprocess "
            "read in SkillPromptEvalLoop (default 1h; also bounds the "
            "per-skill live refine-validation runner). Healthy runtime "
            "scales with corpus/repo size, so this is an operator knob, not "
            "a constant (#9555): too low silently degrades the weekly "
            "backstop to a permanent no-op (false timeout every tick); too "
            "high weakens wedged-child protection."
        ),
    )

    # Trust fleet — prompt self-refinement (#9724)
    skill_prompt_refine_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for skill-prompt self-refinement proposals.",
    )
    skill_prompt_refine_max_weekly: int = Field(
        default=2,
        ge=0,
        le=50,
        description="Max refine proposals filed per rolling 7-day window.",
    )
    skill_prompt_refine_model: str = Field(
        default="",
        description=(
            "Model override for skill-prompt refinement generation. "
            "Empty falls back to the maintenance model, then the background "
            "model, then 'sonnet'."
        ),
    )
    skill_prompt_refine_live_validation_budget: int = Field(
        default=4,
        ge=0,
        le=50,
        description=(
            "Max cases (the regressed case + a sample of that skill's own "
            "held-out honeypots) a refine-candidate live re-validation run "
            "forces through the real agent CLI instead of the "
            "expected_transcript.txt fixture — proving the candidate patch "
            "actually changed prompt->transcript behavior for the better, "
            "not just against the OLD prompt's canned transcript. Forwarded "
            "to the corpus runner via the `--force-live-cases` CLI flag; "
            "inert unless the operator has also set HYDRAFLOW_TRUST_"
            "ADVERSARIAL_LIVE=1 on the loop's environment (the same "
            "operator opt-in the weekly live backstop uses). 0 disables the "
            "sample — every validation case replays its fixture, matching "
            "pre-#10063 behavior. Distinct from "
            "skill_prompt_eval_live_case_budget (the weekly full-corpus "
            "backstop's budget): refine validation runs once per candidate "
            "attempt over a handful of cases, not the whole corpus (#10063)."
        ),
    )

    # Trust fleet — FakeCoverageAuditorLoop (spec §4.7)
    fake_coverage_auditor_interval: int = Field(
        default=604800,
        ge=86400,
        le=2_592_000,
        description="Seconds between FakeCoverageAuditorLoop ticks (default 7d)",
    )

    # Trust fleet — AdrConformanceLoop (ADR-0100)
    adr_conformance_interval: int = Field(
        default=86400,
        ge=3600,
        le=604800,
        description="Seconds between AdrConformanceLoop ticks (default 24h)",
    )

    # Trust fleet — MemoryBacklogLoop (ADR-0089)
    memory_backlog_interval_seconds: int = Field(
        default=86_400,
        ge=3_600,
        le=604_800,
        description="Cadence for MemoryBacklogLoop (default 24h, range 1h–7d).",
    )
    memory_backlog_max_issues_per_tick: int = Field(
        default=5,
        ge=1,
        le=20,
        description=(
            "Max memory-backlog issues MemoryBacklogLoop files in one tick "
            "(#10777). A batch of newly-pending mirror entries would otherwise "
            "file one issue each; over-cap entries are folded into a single "
            "summary issue instead."
        ),
    )
    memory_backlog_label: list[str] = Field(
        default=["hydraflow-memory-backlog"],
        description=(
            "Label applied to issues filed by MemoryBacklogLoop (alongside find_label)."
        ),
    )
    memory_backlog_stuck_label: list[str] = Field(
        default=["hydraflow-memory-backlog-stuck"],
        description=(
            "Escalation label after 3 unresolved attempts on the same memory entry."
        ),
    )

    # Trust fleet — RCBudgetLoop (spec §4.8)
    rc_budget_interval: int = Field(
        default=14400,
        ge=3600,
        le=604800,
        description="Seconds between RCBudgetLoop ticks (default 4h)",
    )
    rc_budget_threshold_ratio: float = Field(
        default=1.5,
        ge=1.0,
        le=5.0,
        description=(
            "Multiplier vs. 30-day rolling median; current_s >= ratio * median_s fires."
        ),
    )
    rc_budget_spike_ratio: float = Field(
        default=2.0,
        ge=1.0,
        le=10.0,
        description=(
            "Multiplier vs. max(recent 5 excl. current); "
            "current_s >= ratio * recent_max fires."
        ),
    )

    # Trust fleet — WikiRotDetectorLoop (spec §4.9)
    wiki_rot_detector_interval: int = Field(
        default=604800,
        ge=86400,
        le=2_592_000,
        description="Seconds between WikiRotDetectorLoop ticks (default 7d)",
    )
    wiki_rot_detector_max_issues_per_tick: int = Field(
        default=10,
        ge=1,
        le=100,
        description=(
            "Finding-rate budget: max hydraflow-find issues WikiRotDetectorLoop "
            "files in one tick across all repos and cite styles (#10767). Cites "
            "over the cap are summarized into a SINGLE issue instead of one "
            "each. Gates FILING only — ``broken_subjects`` accumulation is never "
            "capped, so ``reconcile_open`` cannot wrongly auto-close a live "
            "escalation for a merely rate-limited cite (patterns/0576)."
        ),
    )

    # Caretaker — AutoTightenLoop (auto-tightening ratchet)
    auto_tighten_stability_ticks: int = Field(default=3, ge=1)
    auto_tighten_coverage_margin: float = Field(default=1.0, ge=0.0)
    auto_tighten_interval: int = Field(default=86400, ge=60)

    # Trust fleet — TermProposerLoop (ADR-0054)
    term_proposer_enabled: bool = Field(
        default=True,
        description="Kill-switch for TermProposerLoop (ADR-0054).",
    )
    term_proposer_interval: int = Field(
        default=14400,
        ge=3600,
        le=86400,
        description="Seconds between TermProposerLoop ticks.",
    )
    term_proposer_max_per_tick: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Max term drafts produced per tick.",
    )
    term_proposer_cooldown_seconds: int = Field(
        default=86400,
        ge=3600,
        le=604800,
        description="Cooldown before retrying a candidate that previously failed validation or LLM draft.",
    )
    term_proposer_model: str = Field(
        default="sonnet",
        description="Model for the term-proposer / entry-evidence drafters.",
    )
    term_proposer_tool: Literal["claude", "codex"] = Field(
        default="claude",
        description="CLI backend for the term-proposer drafters (claude path only).",
    )
    term_proposer_timeout: int = Field(
        default=180,
        ge=30,
        le=1800,
        description="Per-call timeout (seconds) for the term-proposer drafters.",
    )

    # Trust fleet — TermPrunerLoop (ADR-0057)
    term_pruner_enabled: bool = Field(
        default=True,
        description="Kill-switch for TermPrunerLoop (ADR-0057).",
    )
    term_pruner_interval: int = Field(
        default=86400,
        ge=3600,
        le=604800,
        description="Seconds between TermPrunerLoop ticks.",
    )

    # Trust fleet — EdgeProposerLoop (ADR-0058)
    edge_proposer_enabled: bool = Field(
        default=True,
        description="Kill-switch for EdgeProposerLoop (ADR-0058).",
    )
    edge_proposer_interval: int = Field(
        default=86400,
        ge=3600,
        le=604800,
        description="Seconds between EdgeProposerLoop ticks.",
    )

    # Trust fleet — EntryEvidenceLoop (ADR-0062)
    entry_evidence_enabled: bool = Field(
        default=True,
        description="Kill-switch for EntryEvidenceLoop (ADR-0062).",
    )
    entry_evidence_interval: int = Field(
        default=86400,
        ge=3600,
        le=604800,
        description="Seconds between EntryEvidenceLoop ticks.",
    )
    entry_evidence_max_entries_per_tick: int = Field(
        default=20,
        ge=1,
        le=200,
        description=(
            "Max wiki entries the loop sends to the LLM per tick — bounds "
            "credit cost. Untracked entries roll over to the next tick."
        ),
    )

    # Trust fleet — CorpusLearningLoop (spec §4.1 v2)
    corpus_learning_interval: int = Field(
        default=3600,
        ge=3600,
        le=2_592_000,
        description=(
            "Seconds between CorpusLearningLoop ticks (default 1h, "
            "spec §4.1: the loop is reactive on new escape issues, so "
            "frequent ticks pick them up quickly)"
        ),
    )
    corpus_learning_signal_labels: tuple[str, ...] = Field(
        default=("skill-escape", "discover-escape", "shape-escape"),
        description=(
            "Escape-signal labels CorpusLearningLoop reads. Spec §4.1: covers "
            "skill-escape (post-impl), discover-escape (Discover §4.10), and "
            "shape-escape (Shape §4.10). Override for a stripped-down deployment."
        ),
    )
    corpus_learning_max_prs_per_tick: int = Field(
        default=10,
        ge=1,
        le=100,
        description=(
            "Max PRs CorpusLearningLoop opens per tick. Bounds blast radius "
            "when escape-signal dedup misses (e.g. issue retitled mid-tick). "
            "Surplus validated cases defer to the next tick."
        ),
    )
    corpus_learning_synthesis_model: str = Field(
        default="opus",
        description=(
            "LLM model the CorpusLearningLoop uses to synthesize new "
            "adversarial cases (spec §4.1 v2). Must be distinct from "
            "the production post-impl skill model — synthesizing with "
            "the same model that the corpus is meant to test creates "
            "correlated failure (the synthesis model's blind spots "
            "won't surface in the corpus). Default `opus` against "
            "production `sonnet`."
        ),
    )
    disturbance_dampener_enabled: bool = Field(
        default=False,
        description="Enable the DisturbanceDampenerLoop burn-down loop (ADR-0095). Dark by default.",
    )
    disturbance_dampener_interval_seconds: int = Field(
        default=3600,
        description="DisturbanceDampenerLoop tick interval in seconds.",
    )
    disturbance_dampener_max_prs_per_tick: int = Field(
        default=1,
        description="Max burn-down PRs DisturbanceDampenerLoop opens per tick. Bounds blast radius.",
    )

    # Human-on-the-loop continuous steering (ADR-0099 surface #4)
    human_steering_enabled: bool = Field(
        default=True,
        description=(
            "Enable the HumanSteeringLoop sensor for continuous human-on-the-loop "
            "steering (ADR-0099 #4). Default-on: safe because an empty "
            "human_steering_authorized_users allowlist honors nobody, so the "
            "sensor is inert until an operator login is explicitly allow-listed. "
            "Set HYDRAFLOW_HUMAN_STEERING_ENABLED=false to disable at deploy time."
        ),
    )
    human_steering_interval_seconds: int = Field(
        default=60,
        description="HumanSteeringLoop tick interval in seconds.",
    )
    human_steering_max_redos: int = Field(
        default=3,
        description="Max redo directives HumanSteeringLoop honors per issue before capping to prevent infinite redo.",
    )
    human_steering_authorized_users: list[str] = Field(
        default_factory=list,
        description="GitHub logins authorized to issue human-steering directives. Empty list honors nobody (safe default-on).",
    )

    # Trust fleet — ContractRefreshLoop (spec §4.2)
    contract_refresh_interval: int = Field(
        default=604800,
        ge=86400,
        le=2_592_000,
        description="Seconds between ContractRefreshLoop cycles (default 7 days)",
    )
    max_fake_repair_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description=(
            "Max per-adapter consecutive drift ticks before ContractRefreshLoop "
            "escalates a fake-drift issue to hitl-escalation (spec §4.2 Task 18)."
        ),
    )
    max_convergence_laps: int = Field(
        default=3,
        ge=1,
        le=20,
        description=(
            "Maximum outer-convergence laps allowed before a ConvergenceLedger "
            "escalates an issue (ADR-0094)."
        ),
    )
    convergence_oscillation_interval: int = Field(
        default=3600,
        ge=300,
        le=86400,
        description=(
            "Seconds between ConvergenceOscillationLoop ticks (default 1h). "
            "Must be between 5 minutes and 24 hours."
        ),
    )
    convergence_oscillation_loop_enabled: bool = Field(
        default=True,
        description=(
            "Enable the ConvergenceOscillationLoop caretaker that scans "
            "ConvergenceLedgers for cross-boundary oscillation and escalates "
            "stuck issues to HITL."
        ),
    )
    convergence_oscillation_window: int = Field(
        default=2,
        ge=2,
        le=10,
        description=(
            "Number of recent lap signatures to compare when detecting temporal "
            "outer oscillation (detect_outer_oscillation window parameter)."
        ),
    )
    convergence_oscillation_min_loopback_stages: int = Field(
        default=2,
        ge=1,
        le=3,
        description=(
            "Minimum number of distinct boundary stages (triage/shape/plan) "
            "that must have last_verdict==LOOP_BACK to trigger snapshot "
            "oscillation escalation."
        ),
    )
    convergence_oscillation_max_issues_per_tick: int = Field(
        default=3,
        ge=1,
        le=20,
        description=(
            "Max HITL oscillation issues ConvergenceOscillationLoop files in "
            "one tick (#10777). Ledgers scale with in-flight issues; over-cap "
            "oscillating ledgers are deferred (NOT marked escalated) and "
            "retried next tick — a rate limit on filing volume, not a drop."
        ),
    )
    contracts_sandbox_repo: str = Field(
        default="T-rav-Hydra-Ops/hydraflow-contracts-sandbox",
        description=(
            "GitHub slug for the sandbox repo ContractRefreshLoop's "
            "FakeGitHub recorder hits when re-recording cassettes "
            "(spec §8). Override if the sandbox org is renamed."
        ),
    )
    contract_refresh_external_enabled: bool = Field(
        default=True,
        description=(
            "Run ContractRefreshLoop's external recorders (github → "
            "contracts-sandbox repo, claude → api.anthropic.com, docker → "
            "alpine image pull). Disabling skips them so the loop completes "
            "fast in the air-gapped sandbox (only the local git recorder "
            "runs); each external recorder otherwise blocks up to the 120s "
            "subprocess timeout. Production defaults to True."
        ),
    )

    # Trust fleet — TrustFleetSanityLoop (spec §12.1)
    trust_fleet_sanity_interval: int = Field(
        default=600,
        ge=60,
        le=3600,
        description="Seconds between TrustFleetSanityLoop ticks (default 10m)",
    )
    loop_anomaly_issues_per_hour: int = Field(
        default=10,
        ge=1,
        le=1000,
        description=(
            "TrustFleetSanityLoop: files an escalation when any watched loop "
            "exceeds this many issues/hour (spec §12.1)."
        ),
    )
    loop_anomaly_repair_ratio: float = Field(
        default=2.0,
        ge=0.1,
        le=100.0,
        description=(
            "TrustFleetSanityLoop: `repair_failures_total / repair_successes_total` "
            "over 24h breach threshold (spec §12.1)."
        ),
    )
    loop_anomaly_repair_min_sample: int = Field(
        default=3,
        ge=1,
        le=1000,
        description=(
            "TrustFleetSanityLoop: minimum 24h `failed` count before the "
            "repair_ratio detector escalates a zero-success (`no_successes`) "
            "loop. Below this floor the signal is too small to escalate and "
            "the detector returns `insufficient_data` (false-positive guard, "
            "issue #9458)."
        ),
    )
    loop_anomaly_tick_error_ratio: float = Field(
        default=0.2,
        ge=0.01,
        le=1.0,
        description=(
            "TrustFleetSanityLoop: `ticks_errored / ticks_total` over 24h "
            "breach threshold (spec §12.1)."
        ),
    )
    loop_anomaly_tick_error_min_sample: int = Field(
        default=3,
        ge=1,
        le=1000,
        description=(
            "TrustFleetSanityLoop: minimum 24h `ticks_total` count before the "
            "tick_error_ratio detector escalates. Below this floor the signal "
            "is too small to escalate and the detector returns "
            "`insufficient_data` (false-positive guard, issue #9811)."
        ),
    )
    loop_anomaly_staleness_multiplier: float = Field(
        default=2.0,
        ge=1.0,
        le=100.0,
        description=(
            "TrustFleetSanityLoop: staleness breach when an enabled loop has not "
            "ticked in > this × its interval (spec §12.1)."
        ),
    )
    loop_anomaly_cost_spike_ratio: float = Field(
        default=5.0,
        ge=1.0,
        le=100.0,
        description=(
            "TrustFleetSanityLoop: current-day cost breach when > this × "
            "30-day median (spec §12.1; reads §4.11 cost endpoint, tolerates absence)."
        ),
    )
    cost_plausibility_max_rate_multiple: float = Field(
        default=3.0,
        ge=1.0,
        le=100.0,
        description=(
            "Cost-plausibility guard K (#10775): build_cost_by_model flags a "
            "model whose effective $/token exceeds K x its peak table rate "
            "(the largest of input/output/cache-write/cache-read) as a likely "
            "per-backend usage-semantics mis-bill — the z.ai/GLM 6-8x class "
            "(#10761). A correctly billed record's effective rate is always "
            "<= peak, so any K >= 1.0 is false-positive-free on clean data; the "
            "3.0 default adds headroom for char-estimate-mixed buckets. SOFT: "
            "logs a WARNING and surfaces cost_plausibility on the row, never "
            "fails the build or alters cost."
        ),
    )
    loop_anomaly_hitl_low_severity_count: int = Field(
        default=3,
        ge=1,
        le=1000,
        description=(
            "TrustFleetSanityLoop: files ONE fleet alert when the open HITL "
            "queue holds at least this many low-severity items — issues whose "
            "diagnosed severity is P4/Housekeeping OR that carry a housekeeping "
            "label (e.g. hydraflow-memory-backlog). A backstop for the pipeline "
            "over-escalating auto-filed housekeeping into human-judgment forks "
            "(#10310). Conservatively defaulted to 3 so a single mis-scoped "
            "item never pages a human."
        ),
    )

    # Managed repos + principles audit (spec §4.4)
    managed_repos: list[ManagedRepo] = Field(
        default_factory=list,
        description="Repos under HydraFlow factory management (spec §4.4)",
    )
    principles_audit_interval: int = Field(
        default=604800,
        ge=60,
        description=(
            "Seconds between PrinciplesAuditLoop ticks. "
            "Default 604800 = 7 days (spec §4.4)."
        ),
    )
    principles_audit_timeout_seconds: int = Field(
        default=1800,
        ge=60,
        le=21600,
        description=(
            "Hard cap (seconds) on the `make audit-json` subprocess read in "
            "PrinciplesAuditLoop (default 30m). Healthy runtime scales with "
            "repo size, so this is an operator knob, not a constant (#9555): "
            "too low silently degrades the audit to a permanent no-op (false "
            "timeout every tick); too high weakens wedged-child protection."
        ),
    )
    principles_audit_max_issues_per_tick: int = Field(
        default=5,
        ge=1,
        le=20,
        description=(
            "Max principles-drift issues PrinciplesAuditLoop files in one tick "
            "(#10777). Filing scales as managed_repos x regressed checks; "
            "over-cap regressions are deferred and retried next tick — a rate "
            "limit on filing volume, not a durable backlog."
        ),
    )

    # Data-governance prompt gate (CH-6, issue #9734)
    repo_data_class: str = Field(
        default="internal",
        description=(
            "Data-governance class for THIS repo's content: 'public-code' | "
            "'internal' | 'regulated-<name>'. Regulated classes get prompt "
            "redaction + a backend allowlist at every LLM spawn seam "
            "(prompt_gate.gate_prompt); unknown values fail CLOSED. Populated "
            "from the runtime repo registry (repos.json) for registered repos."
        ),
    )
    data_class_allowed_backends: dict[str, list[str]] = Field(
        default_factory=dict,
        description=(
            "Per-data-class allowed LLM CLI backends, e.g. "
            "{'regulated-phi': ['claude']}. Consulted by prompt_gate for "
            "regulated classes only; a regulated class with no entry allows "
            "NOTHING (fail closed). Unregulated classes are never checked."
        ),
    )
    data_class_redaction_patterns: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Extra named regex redaction patterns merged over "
            "prompt_gate.BUILTIN_REDACTION_PATTERNS for regulated-class "
            "prompts. Names appear in gate audit records; content never does."
        ),
    )

    # Auto-agent pre-flight loop (ADR-0049, spec §5.1)
    sandbox_failure_fixer_enabled: bool = Field(
        default=True,
        description=(
            "Static-config kill-switch for SandboxFailureFixerLoop (ADR-0049). "
            "Default ON (self-repair on by default); disable via the System "
            "tab or HYDRAFLOW_SANDBOX_FAILURE_FIXER_ENABLED=false."
        ),
    )
    sandbox_failure_fixer_interval: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Seconds between SandboxFailureFixerLoop cycles (default 1h).",
    )
    detector_calibration_enabled: bool = Field(
        default=True,
        description="UI kill-switch for DetectorCalibrationLoop (ADR-0049).",
    )
    detector_calibration_interval: int = Field(
        default=86400,
        ge=60,
        le=604800,
        description="Seconds between DetectorCalibrationLoop cycles (default 24h).",
    )
    detector_calibration_max_issues_per_tick: int = Field(
        default=3,
        ge=1,
        le=20,
        description=(
            "Max detector-calibration issues DetectorCalibrationLoop files in "
            "one tick (#10777). Churning subjects are mined from up to 500 "
            "closed escalations; over-cap subjects are folded into a single "
            "summary issue instead of one issue each."
        ),
    )
    detector_calibration_spray_min_entities: int = Field(
        default=5,
        ge=3,
        le=100,
        description=(
            "Minimum distinct #N entities one escalation template must hit "
            "inside the window before DetectorCalibrationLoop files a spray "
            "finding (#11427) — the compensating breadth signal for "
            "identity-preserving normalize (#11405). Floor of 3 stays above "
            "the 3-PR shape that produced #11405's fabricated churn."
        ),
    )
    gateway_coverage_enabled: bool = Field(
        default=True,
        description="UI kill-switch for GatewayCoverageLoop (ADR-0049).",
    )
    gateway_coverage_interval: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Seconds between GatewayCoverageLoop cycles (default 1h).",
    )
    auto_agent_preflight_enabled: bool = Field(
        default=True,
        description="UI kill-switch for AutoAgentPreflightLoop (ADR-0049).",
    )
    auto_agent_hitl_intake_enabled: bool = Field(
        default=True,
        description=(
            "Kill-switch for the #9721 widened intake: AutoAgentPreflightLoop "
            "also intercepts idle pipeline-origin hydraflow-hitl issues "
            "(attempt-cap exhaustion, quality-gate/zero-diff bails) in "
            "addition to hitl-escalation. Distinct from "
            "auto_agent_preflight_enabled, which gates the whole loop."
        ),
    )
    auto_agent_light_intake_enabled: bool = Field(
        default=True,
        description=(
            "#11298 light lane: PlanPhase routes issues triaged at or below "
            "auto_agent_light_max_complexity to the single-session auto-agent "
            "(one spawn: read issue -> implement -> test -> PR) instead of the "
            "staged plan/review pipeline. Exhaustion falls back to the staged "
            "pipeline, never to a human. Default ON since 2026-08-21 (operator "
            "ruling after the throughput analysis: attempts per merged issue "
            "had doubled on the staged path, #11568); set False to route every "
            "issue through the staged pipeline."
        ),
    )
    auto_agent_light_max_complexity: int = Field(
        default=3,
        ge=0,
        le=10,
        description=(
            "Complexity ceiling for the #11298 light lane - a conservative "
            "subset of the plan-tier band. Cycled, escalated, or unscored "
            "issues never route here (shared _tier_eligible guard)."
        ),
    )
    auto_pr_preflight_gate_enabled: bool = Field(
        default=True,
        description=(
            "Kill-switch for the auto-PR pre-flight quality-lite gate "
            "(#10013): ratchet+regressions pytest, arch --check, and ruff on "
            "staged files run inside the bot-PR worktree before gh pr create; "
            "a red stage blocks the PR instead of burning a CI cycle."
        ),
    )
    auto_pr_preflight_stage_timeout_s: int = Field(
        default=600,
        ge=30,
        le=3600,
        description=(
            "Per-stage timeout in seconds for the auto-PR pre-flight gate "
            "(#10013). A stage that exceeds it counts as red."
        ),
    )
    auto_pr_auto_merge_enabled: bool = Field(
        default=True,
        description=(
            "Kill-switch for arming auto-merge on bot PRs (#10672, Fix 2). "
            "When True (default, preserving behavior), the auto-PR merge path "
            "may run ``gh pr merge --auto --squash`` — but only after a "
            "fail-closed green-gate confirms the PR's statusCheckRollup is "
            "fully green (no failing or still-pending check). When False, "
            "auto-merge is never armed and PRs wait for a human/shepherd merge, "
            "without a code change."
        ),
    )
    pr_base_freshness_guard_enabled: bool = Field(
        default=True,
        description=(
            "Kill-switch for the implementer/pr_manager base-freshness guard "
            "(#10101, the #9964 class): before ``gh pr create`` on a "
            "long-lived implementer worktree, refuses (or auto "
            "fetch+merges) a branch whose merge-base with the base branch "
            "is older than ``pr_base_max_age_days``. Distinct from the "
            "auto_pr pre-flight gate (#10013), which covers the "
            "short-lived bot-PR worktree seam and always forks fresh."
        ),
    )
    pr_base_max_age_days: int = Field(
        default=3,
        ge=1,
        le=90,
        description=(
            "Max age in days of an implementer branch's merge-base with the "
            "base branch before the base-freshness guard (#10101) treats it "
            "as stale. Older than this triggers an in-worktree "
            "fetch+merge-update attempt before falling back to refusing the "
            "PR open."
        ),
    )
    implement_two_stage_review_enabled: bool = Field(
        default=True,
        description=(
            "Kill-switch for the ImplementPhase two-stage spec-compliance "
            "review (ADR-0063 W5). When enabled, a spec-compliance reviewer "
            "subagent runs after each failed implementation attempt and the "
            "gaps it surfaces are fed into the next attempt's prior_failure "
            "context. Disable to revert to the pre-W5 retry-with-error-only "
            "behavior."
        ),
    )
    auto_agent_preflight_interval: int = Field(
        default=120,
        ge=60,
        le=600,
        description="Seconds between AutoAgentPreflightLoop cycles (default 120).",
    )
    auto_agent_persona: str = Field(
        default=(
            "the lead engineer for this project — pragmatic, prefers small fixes, "
            "leaves regression tests, doesn't over-engineer. When in doubt about "
            "scope, do less."
        ),
        description="Persona substituted into the auto-agent shared prompt envelope.",
    )
    auto_agent_max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Per-issue attempt cap before auto-agent-exhausted (default 3).",
    )
    auto_agent_skip_sublabels: list[str] = Field(
        default_factory=lambda: ["principles-stuck", "cultural-check"],
        description=(
            "Sub-labels that bypass auto-agent pre-flight entirely. Default = the "
            "principles-audit recursion guard."
        ),
    )
    auto_agent_cost_cap_usd: float | None = Field(
        default=None,
        description=(
            "Per-attempt cost cap in USD. None = unlimited (observability-first; "
            "operator can set when needed)."
        ),
    )
    auto_agent_wall_clock_cap_s: int | None = Field(
        default=None,
        description="Per-attempt wall-clock cap in seconds. None = unlimited.",
    )
    auto_agent_daily_budget_usd: float | None = Field(
        default=None,
        description="Per-day total spend budget in USD. None = unlimited.",
    )
    auto_agent_redrive_enabled: bool = Field(
        default=True,
        description=(
            "Escalation TTL re-drive (#9719): re-feed auto-agent-exhausted "
            "escalations that carried human-required past the TTL back to "
            "preflight (labels removed, attempt counter cleared; the durable "
            "audit log — the diverse-retry source — is never cleared)."
        ),
    )
    auto_agent_redrive_max_attempts: int = Field(
        default=1,
        ge=0,
        le=5,
        description=(
            "Max re-drives per issue before it stays human-required "
            "permanently (0 disables re-drive behaviorally)."
        ),
    )
    auto_agent_redrive_ttl_days: int = Field(
        default=5,
        ge=1,
        le=90,
        description=(
            "Days an exhausted escalation carries human-required before its "
            "first re-drive."
        ),
    )
    auto_agent_redrive_backoff_multiplier: float = Field(
        default=3.0,
        ge=1.0,
        le=10.0,
        description=(
            "TTL multiplier per re-drive: the TTL for re-drive k is "
            "ttl_days * multiplier**k (default schedule 5d → 15d → stop at "
            "the max-attempts cap)."
        ),
    )
    auto_agent_redrive_human_quiet_days: int = Field(
        default=2,
        ge=0,
        le=90,
        description=(
            "Min days without a comment from an authorized human "
            "(human_steering_authorized_users) before an escalation may be "
            "re-driven. Empty allowlist → label-only claim detection."
        ),
    )

    # Credit pause
    credit_pause_buffer_minutes: int = Field(
        default=1,
        ge=0,
        le=30,
        description="Extra minutes to wait after reported credit reset time",
    )
    credit_fp_suppress_cooldown_seconds: int = Field(
        default=300,
        ge=10,
        le=3600,
        description=(
            "Cooldown after suppressing a false-positive credit signal from a "
            "source: within it, repeat signals from that source are log-only "
            "(no probe, no banner) and the raising loop restarts with a delay "
            "instead of a tight spin (#9888)."
        ),
    )
    credit_pause_require_probe: bool = Field(
        default=True,
        description=(
            "Before committing a GLOBAL credit pause, corroborate the "
            "text-detected credit signal with a live Anthropic API probe. "
            "is_credit_exhaustion matches credit-error PROSE, so a "
            "diagnostic/reviewer run quoting a prior cap in its analysis would "
            "otherwise trigger a multi-hour false global pause (#9807). The "
            "probe is ground truth (False only when the API itself confirms "
            "exhaustion). Kill-switch: set False to revert to pause-on-text."
        ),
    )
    auth_failure_require_probe: bool = Field(
        default=True,
        description=(
            "Before halting ALL loops on a GitHub AuthenticationError, "
            "corroborate the signal with a live `gh auth status` probe. A "
            "single gh call's stderr can match an auth pattern during a "
            "transient network/API blip, which used to stop the whole factory "
            "for hours (#9621). The probe is ground truth (False only when gh "
            "confirms the credentials are rejected); on a probe-refuted "
            "(transient) signal the crashed loop is restarted instead of "
            "stopping the factory. Kill-switch: set False to revert to "
            "halt-on-signal."
        ),
    )

    # Process timeouts
    agent_timeout: int = Field(
        default=3600,
        ge=60,
        le=14400,
        description="Default timeout in seconds for agent process runs",
    )
    transcript_summary_timeout: int = Field(
        default=120,
        ge=30,
        le=600,
        description="Timeout in seconds for transcript summarization model calls",
    )
    # Execution mode
    dry_run: bool = Field(
        default=False, description="Log actions without executing them"
    )
    skip_preflight: bool = Field(
        default=False, description="Skip startup preflight dependency checks"
    )
    execution_mode: Literal["host", "docker"] = Field(
        default="host",
        description="Run agents on host or in Docker containers",
    )

    # Docker isolation
    docker_image: str = Field(
        default="ghcr.io/t-rav/hydraflow-agent:latest",
        description="Docker image for agent containers",
    )
    docker_cpu_limit: float = Field(
        default=2.0,
        ge=0.5,
        le=16.0,
        description="CPU cores per container",
    )
    docker_memory_limit: str = Field(
        default="4g",
        description="Memory limit per container",
    )
    docker_network_mode: Literal["bridge", "none", "host"] = Field(
        default="bridge",
        description="Docker network mode",
    )
    docker_spawn_delay: float = Field(
        default=2.0,
        ge=0.0,
        le=30.0,
        description="Seconds between concurrent container starts",
    )
    docker_read_only_root: bool = Field(
        default=True,
        description="Read-only root filesystem in containers",
    )
    docker_no_new_privileges: bool = Field(
        default=True,
        description="Prevent privilege escalation in containers",
    )
    docker_pids_limit: int = Field(
        default=256,
        ge=16,
        le=4096,
        description="Max PIDs per container (prevents fork bombs)",
    )
    docker_tmp_size: str = Field(
        default="1g",
        description="Tmpfs size for /tmp in containers",
    )

    docker_network: str = Field(
        default="",
        description="Docker network name (empty = default bridge)",
    )
    docker_extra_mounts: list[str] = Field(
        default=[],
        description="Additional volume mounts as host:container:mode strings",
    )

    # Baseline policy
    baseline_snapshot_patterns: list[str] = Field(
        default=["**/__snapshots__/**", "**/*.snap.png", "**/*.baseline.png"],
        description="Glob patterns matching visual baseline files in the repo",
    )
    baseline_approval_required: bool = Field(
        default=True,
        description="Whether baseline updates require explicit approval",
    )
    baseline_approvers: list[str] = Field(
        default=[],
        description="GitHub usernames allowed to approve baseline updates (empty = repo collaborators)",
    )
    baseline_max_audit_records: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Maximum baseline audit records to retain per issue",
    )

    # -------------------------------------------------------------------------
    # Static config gates — 34 loops (dark-factory §2.1 #3 defense-in-depth)
    # Each field maps to a HYDRAFLOW_<UPPER_SNAKE>_ENABLED env var (see
    # _ENV_BOOL_OVERRIDES above). Setting any of these to False disables the
    # corresponding loop at deploy time without a code change.
    # -------------------------------------------------------------------------
    adr_reviewer_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for ADRReviewerLoop.",
    )
    adr_conformance_loop_enabled: bool = Field(
        default=True,
        description=(
            "Deploy-time kill-switch for AdrConformanceLoop (ADR-0100). "
            "Enabled by default (like sibling caretaker loops) after a dry-run "
            "against the full ADR corpus confirmed zero false-positive issue "
            "filing; set False to disable."
        ),
    )
    auto_tighten_loop_enabled: bool = Field(
        default=True,
        description=(
            "Kill-switch for AutoTightenLoop (auto-tightening ratchet). Enabled by "
            "default (ADR-0104) once actuation was e2e-verified; set the env var to "
            "false to disable."
        ),
    )
    ci_monitor_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for CIMonitorLoop.",
    )
    branch_protection_auditor_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for BranchProtectionAuditorLoop.",
    )
    goal_supervisor_loop_enabled: bool = Field(
        default=False,
        description=(
            "Deploy-time kill-switch for GoalSupervisorLoop (Tier-2 goal "
            "supervisor, ADR-0124). Ships default OFF."
        ),
    )
    gate_activator_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for GateActivatorLoop.",
    )
    rails_drift_caretaker_loop_enabled: bool = Field(
        default=False,
        description=(
            "Deploy-time kill-switch for RailsDriftCaretakerLoop (ADR-0121). "
            "Defaults OFF: the loop's live-observation layer (rails.yaml manifest "
            "vs marker-based layer detection) is v1 and the manifest-writer "
            "retrofit is still rolling out across managed repos; set "
            "HYDRAFLOW_RAILS_DRIFT_CARETAKER_LOOP_ENABLED=true to enable once "
            "every managed repo carries a manifest."
        ),
    )
    contract_refresh_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for ContractRefreshLoop.",
    )
    corpus_learning_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for CorpusLearningLoop.",
    )
    cost_budget_watcher_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for CostBudgetWatcherLoop.",
    )
    dependabot_merge_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for DependabotMergeLoop.",
    )
    diagnostic_loop_enabled: bool = Field(
        default=True,
        description=(
            "Deploy-time kill-switch for DiagnosticLoop. Was defaulted OFF "
            "(#9895) during the credit-flood incident; re-enabled after ALL "
            "three named blockers landed: #9888 (false-positive cooldown), "
            "#10001 (CREDIT_PROSE_SCAN opt-out + HITL comment dedup), and "
            "#9879/#10018 (gate off-thread + bounded diagnosis prompt)."
        ),
    )
    diagnostic_exhausted_routes_autofix: bool = Field(
        default=True,
        description=(
            "When the DiagnosticLoop's attempt budget is exhausted, route the "
            "issue straight to the Auto-Agent autofix stage (hydraflow-hitl-"
            "autofix) instead of the human-visible hydraflow-hitl queue "
            "(#10411/#10403): attempts-exhausted is an auto-resolvable too-big/"
            "wrong-strategy signal, not a human-judgment need. The Auto-Agent "
            "decomposes/retries and pages a human (human-required) only if it "
            "too exhausts. Set False to restore the pre-#10411 human-visible "
            "escalation."
        ),
    )
    diagram_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for DiagramLoop.",
    )
    epic_monitor_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for EpicMonitorLoop.",
    )
    epic_sweeper_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for EpicSweeperLoop.",
    )
    fake_coverage_auditor_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for FakeCoverageAuditorLoop.",
    )
    flake_tracker_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for FlakeTrackerLoop.",
    )
    xdist_quarantine_enabled: bool = Field(
        default=True,
        description=(
            "Kill-switch for FlakeTrackerLoop's xdist-quarantine detection "
            "(reads the xdist-audit report; independent of flake tracking)."
        ),
    )
    github_cache_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for GitHubCacheLoop.",
    )
    health_monitor_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for HealthMonitorLoop.",
    )
    self_repair_actuator_enabled: bool = Field(
        default=True,
        description=(
            "Deploy-time kill-switch for HealthMonitorLoop's persistent-error "
            "self-repair actuator (#10140): when a registry loop reports an "
            "`error` heartbeat for N consecutive cycles, auto-repair a known "
            "pattern (e.g. PrinciplesAuditLoop's managed_repos 404-repo prune) "
            "or file one deduped hydraflow-find issue naming the loop. "
            "Independent of `health_monitor_loop_enabled` so operators can "
            "disable auto-repair/auto-file without disabling the whole loop."
        ),
    )
    label_drift_watcher_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for LabelDriftWatcherLoop.",
    )
    memory_backlog_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for MemoryBacklogLoop.",
    )
    merge_state_watcher_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for MergeStateWatcherLoop.",
    )
    pr_autorebase_enabled: bool = Field(
        default=False,
        description=(
            "Arm the MergeStateWatcher auto-rebase actuator (#11595): when a "
            "factory-owned (agent/*) PR goes CONFLICTING because the base "
            "branch advanced, merge the base + regenerate docs/arch/generated "
            "in an ephemeral worktree and push, so CI re-dispatches without "
            "an operator. One attempt per PR per base head; source-file "
            "conflicts abort untouched and escalate to HITL. Default OFF — "
            "the operator arms a branch-rewriting actuator deliberately."
        ),
    )
    pr_unsticker_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for PRUnstickerLoop.",
    )
    pricing_refresh_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for PricingRefreshLoop.",
    )
    rc_budget_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for RCBudgetLoop.",
    )
    repo_wiki_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for RepoWikiLoop.",
    )
    report_issue_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for ReportIssueLoop.",
    )
    retrospective_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for RetrospectiveLoop.",
    )
    runs_gc_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for RunsGCLoop.",
    )
    security_patch_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for SecurityPatchLoop.",
    )
    log_ingest_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for LogIngestLoop.",
    )
    skill_prompt_eval_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for SkillPromptEvalLoop.",
    )
    stale_issue_gc_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for StaleIssueGCLoop.",
    )
    gate_health_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for GateHealthLoop (#9974).",
    )
    pr_red_repair_loop_enabled: bool = Field(
        default=True,
        description=(
            "Deploy-time kill-switch for PrRedRepairLoop (#10027 Phase 1: "
            "infra-flake retrier)."
        ),
    )
    pr_red_repair_dispatch_enabled: bool = Field(
        default=True,
        description=(
            "Dark-launch gate for PrRedRepairLoop's Phase 2 real-red "
            "auto-agent dispatch (#10027), ANDed with "
            "`pr_red_repair_loop_enabled` and the live `enabled_cb` "
            "kill-switch per ADR-0049 — not a replacement for either. "
            "When False, a real (non-infra-flake) settled red is left "
            "untouched (Phase 1 behavior only); the infra-flake rerun path "
            "is unaffected."
        ),
    )
    erosion_metrics_loop_enabled: bool = Field(
        default=True,
        description=(
            "Deploy-time kill-switch for ErosionMetricsLoop (#10107, epic "
            "#10104: v1 change-spread/concept-scatter drift caretaker). "
            "Defaults ON but conservative — the sensors' own baseline/"
            "threshold defaults keep it quiet until an operator snapshots "
            "a real repo-specific baseline."
        ),
    )
    fail_open_monitor_loop_enabled: bool = Field(
        default=True,
        description=(
            "Deploy-time kill-switch for FailOpenMonitorLoop (#10371: fail-open "
            "ledger rate → Shewhart control limit → hydraflow-find). Defaults "
            "ON but conservative — a control limit needs several days of ledger "
            "history before it can fire, so the loop is quiet until then."
        ),
    )
    escape_ledger_loop_enabled: bool = Field(
        default=True,
        description=(
            "Deploy-time kill-switch for EscapeLedgerLoop (#10367: post-merge "
            "escape ledger + erosion trend surfaces, read-only ADR-0029 "
            "Pattern B). Records escapes and renders trend reports; the "
            "finding-rate budget bounds any issue filing."
        ),
    )
    intervention_tally_loop_enabled: bool = Field(
        default=True,
        description=(
            "Deploy-time kill-switch for InterventionTallyLoop (#10369: "
            "attention-side telemetry, read-only ADR-0029 Pattern B). Senses "
            "+ records human touches (steering/HITL/control-route/CLI) and "
            "renders the rate report; never gates, blocks, or fixes."
        ),
    )
    intervention_tally_classify_enabled: bool = Field(
        default=True,
        description=(
            "Whether InterventionTallyLoop may send free-text steering "
            "directives to the cheap LLM for classification (#10369). OFF "
            "keeps free-text rows at low confidence with raw text preserved; "
            "the air-gapped sandbox pins this OFF (config_disable seam) so no "
            "classification spawn is reachable there."
        ),
    )
    intervention_tally_model: str = Field(
        default="",
        description=(
            "Model for InterventionTallyLoop's free-text steering "
            "classification (#10369); empty falls back to the maintenance "
            "model, then the background model, then 'sonnet'. Also stamped "
            "as each row's model_version_context."
        ),
    )
    sampled_audit_loop_enabled: bool = Field(
        default=True,
        description=(
            "Deploy-time kill-switch for SampledAuditLoop (#10370: sampled "
            "adversarial re-audit — the silent-escape estimator, read-only "
            "ADR-0029 Pattern B). Samples merged PRs, re-audits, records, and "
            "files disagreements; never gates, reverts, or opens fix PRs."
        ),
    )
    sampled_audit_reaudit_enabled: bool = Field(
        default=True,
        description=(
            "Gates the SampledAuditLoop adversarial re-audit LLM spawn (#10370). "
            "Default ON; the air-gapped sandbox pins it OFF "
            "(mockworld.sandbox_main._apply_sandbox_config_overrides) so the "
            "config_disable seam is TRUE — no real `claude` is reachable on the "
            "sandbox network. The loop still samples-and-ticks + governs."
        ),
    )
    sampled_audit_auto_adjudicate_enabled: bool = Field(
        default=True,
        description=(
            "Before SampledAuditLoop leaves a re-audit disagreement for a human "
            "adjudicator, run a machine auto-adjudicate pass (ADR-0115): a fresh "
            "adversarial LLM re-reads the merged diff + the auditor's finding and "
            "self-applies the disposition — `audit-upheld` (a real silent escape "
            "→ crosses into the escape ledger) or `audit-refuted` (auditor false "
            "alarm → closed with evidence). Only an INCONCLUSIVE adjudication is "
            "left unlabelled for a human. Default ON (self-repair on by "
            "default; disable via the System tab). Also gated by "
            "sampled_audit_reaudit_enabled, so the air-gapped sandbox "
            "(which pins re-audit OFF) reaches no adjudicator spawn either."
        ),
    )
    stale_issue_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for StaleIssueLoop.",
    )
    triage_retry_loop_enabled: bool = Field(
        default=True,
        description=(
            "Deploy-time kill-switch for TriageRetryLoop "
            "(ADR-0063 W2 — autonomous re-triage of parked issues)."
        ),
    )
    trust_fleet_sanity_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for TrustFleetSanityLoop.",
    )
    wiki_rot_detector_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for WikiRotDetectorLoop.",
    )
    workspace_gc_loop_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for WorkspaceGCLoop.",
    )
    worktree_gc_all_roots_enabled: bool = Field(
        default=True,
        description=(
            "Deploy-time kill-switch for the WorkspaceGCLoop all-root "
            "enumerate-and-reap phase (#10698). When False the loop keeps its "
            "legacy state/orphan-dir/branch phases but does NOT enumerate "
            "worktrees across every root."
        ),
    )

    # IssueRefinementLoop (spec #9957) — backlog-wide dedup, priority scoring,
    # operator digest.
    issue_refinement_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for IssueRefinementLoop (ADR-0049).",
    )
    issue_refinement_interval: int = Field(
        default=86400,
        ge=3600,
        le=604800,
        description="Seconds between IssueRefinementLoop incremental ticks (default 24h).",
    )
    issue_refinement_full_sweep_interval: int = Field(
        default=604800,
        ge=86400,
        le=2_592_000,
        description=(
            "Seconds between IssueRefinementLoop full-sweep ticks, where every "
            "open issue is treated as changed rather than just the "
            "incremental diff since the persisted index (default 7d)."
        ),
    )
    issue_refinement_pair_budget: int = Field(
        default=24,
        ge=0,
        le=200,
        description=(
            "Max duplicate-candidate pairs judged by an LLM call per "
            "IssueRefinementLoop tick."
        ),
    )
    issue_refinement_priority_budget: int = Field(
        default=50,
        ge=0,
        le=500,
        description=(
            "Max issues priority-scored by an LLM call per "
            "IssueRefinementLoop tick — bounds full-sweep spend, where every "
            "unguarded open issue is otherwise a scoring target (#10025)."
        ),
    )
    issue_refinement_model: str = Field(
        default="",
        description=(
            "Model override for IssueRefinementLoop judgment calls. Empty "
            "falls back to the maintenance model, then the background model, "
            "then 'sonnet'."
        ),
    )

    @field_validator(
        "ready_label",
        "review_label",
        "in_progress_label",
        "hitl_label",
        "hitl_active_label",
        "hitl_autofix_label",
        "fixed_label",
        "dup_label",
        "epic_label",
        "epic_child_label",
        "auto_decomposed_child_label",
        "find_label",
        "planner_label",
        "verify_label",
        "parked_label",
        "diagnose_label",
        "memory_backlog_label",
        "memory_backlog_stuck_label",
        "triage_retry_exhausted_label",
    )
    @classmethod
    def labels_must_not_be_empty(cls, v: list[str]) -> list[str]:
        """Reject empty label lists — downstream code indexes with [0]."""
        if not v:
            raise ValueError("Label list must contain at least one label")
        return v

    @field_validator("docker_memory_limit", "docker_tmp_size")
    @classmethod
    def validate_docker_size_notation(cls, v: str) -> str:
        """Validate Docker size notation (digits followed by b/k/m/g)."""
        if not re.fullmatch(r"\d+[bkmg]", v, re.IGNORECASE):
            msg = f"Invalid Docker size notation '{v}'; expected digits followed by b/k/m/g (e.g., '4g', '512m')"
            raise ValueError(msg)
        return v

    @field_validator("credit_failover_model")
    @classmethod
    def credit_failover_model_must_be_glm(cls, v: str) -> str:
        """The failover model runs on the zai backend, which requires glm-* (#10844)."""
        if not v.startswith("glm"):
            msg = (
                f"credit_failover_model must be a glm-* model (got '{v}') — the "
                "zai harness backend only accepts glm-* models."
            )
            raise ValueError(msg)
        return v

    @field_validator("repo_model")
    @classmethod
    def repo_model_must_be_glm_when_set(cls, v: str) -> str:
        """A non-empty repo_model runs on the zai backend, which requires glm-* (#11211).

        Empty is the "unset — fall back to credit_failover_model" sentinel and
        is always valid.
        """
        if v and not v.startswith("glm"):
            msg = (
                f"repo_model must be a glm-* model (got '{v}') — the zai "
                "harness backend only accepts glm-* models."
            )
            raise ValueError(msg)
        return v

    @field_validator("visual_fail_threshold")
    @classmethod
    def visual_fail_above_warn(cls, v: float, info: Any) -> float:
        """Ensure visual_fail_threshold > visual_warn_threshold."""
        warn = info.data.get("visual_warn_threshold", 0.05)
        if v <= warn:
            msg = (
                f"visual_fail_threshold ({v}) must be greater than "
                f"visual_warn_threshold ({warn})"
            )
            raise ValueError(msg)
        return v

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def all_pipeline_labels(self) -> list[str]:
        """Return a flat list of every pipeline-stage label (for cleanup)."""
        result: list[str] = []
        for labels in (
            self.find_label,
            self.planner_label,
            self.ready_label,
            self.review_label,
            self.hitl_label,
            self.hitl_active_label,
            self.hitl_autofix_label,
            # #11298 light-lane claim label — omitted here it would never be
            # cleared by swap_pipeline_labels (the #10785 stuck-stage-label
            # class): the exhaustion fallback's swap to planner_label would
            # leave the claim on forever, re-polled every tick while the plan
            # queue races the same issue.
            self.light_autofix_label,
            # ``diagnose`` and ``parked`` are route-back STAGES (the docstring
            # for ``in_progress_label`` below enumerates "hitl/diagnose/parked/
            # ready" as the swap targets) — but were omitted here, so
            # ``swap_pipeline_labels`` never cleared ``hydraflow-diagnose`` /
            # ``hydraflow-parked`` on transition. A diagnosed issue then
            # accumulated stale stage labels and jammed the pipeline (self-
            # diagnosed on #10785: diagnose label survived the ready swap).
            self.diagnose_label,
            self.parked_label,
            self.fixed_label,
            self.verify_label,
        ):
            result.extend(labels)
        # ``human-required`` is orthogonal to the stage machine, but listing it
        # here ensures ``swap_pipeline_labels`` clears it on a successful HITL
        # correction — so a corrected issue re-enters the pipeline clean instead
        # of carrying a stale blocker forever (ADR-0084, pillar C / anti-cycle).
        result.append("human-required")
        # ``in_progress_label`` is likewise orthogonal — a build-claim marker
        # (#10168) that coexists with ``hydraflow-ready`` during a build, not a
        # stage. Listing it here makes every ``swap_pipeline_labels`` call clear
        # it: the ``ready → review`` swap at PR-open drops the claim, and any
        # escalation/route-back swap (hitl/diagnose/parked/ready) clears it too,
        # so an issue can never get stuck claimed (ADR-0002).
        result.extend(self.in_progress_label)
        return result

    @property
    def dispatchable_stage_labels(self) -> list[str]:
        """Active pipeline-stage labels whose presence makes an issue a
        dispatch candidate — ``all_pipeline_labels`` minus the terminal
        markers (``fixed`` / ``verify``).

        A CLOSED issue must never keep one of these: a label-scan
        dispatcher (ready/plan/review/hitl work-picker) queues by label
        presence, so a stale active stage label left on a closed issue
        causes duplicate re-dispatch of already-shipped work (#10394).
        Terminal labels are preserved — they record shipped/verified
        state and no loop dispatches on them. Derived from the single
        ``all_pipeline_labels`` source, never a parallel hardcoded list.
        """
        terminal = {*self.fixed_label, *self.verify_label}
        return [lbl for lbl in self.all_pipeline_labels if lbl not in terminal]

    @property
    def log_dir(self) -> Path:
        """Return the directory for transcript / log files."""
        return self.data_root / "logs"

    @property
    def plans_dir(self) -> Path:
        """Return the directory for saved plan files."""
        return self.data_root / "plans"

    @property
    def memory_dir(self) -> Path:
        """Return the directory for memory / review-insight files."""
        return self.data_root / "memory"

    @property
    def visual_reports_dir(self) -> Path:
        """Return the directory for visual validation reports."""
        return self.data_root / "visual-reports"

    @property
    def diagnostics_dir(self) -> Path:
        """Directory for factory diagnostics data."""
        return self.data_root / "diagnostics"

    @property
    def factory_metrics_path(self) -> Path:
        """Path to the repo-scoped factory metrics JSONL store (ADR-0021 D2).

        Served by ``/api/diagnostics/*``. Lives under
        ``data_root/<repo_slug>/diagnostics`` so per-repo telemetry does not
        collide under a shared ``data_root`` (e.g. ``HYDRAFLOW_HOME``).
        """
        return self.repo_data_root / "diagnostics" / "factory_metrics.jsonl"

    def data_path(self, *parts: str | os.PathLike[str]) -> Path:
        """Return an absolute path inside the HydraFlow data_root."""
        return self.data_root.joinpath(*parts)

    def repo_data_path(self, *parts: str | os.PathLike[str]) -> Path:
        """Return an absolute path inside the repo-scoped data dir.

        Mirror of :meth:`data_path` but rooted at ``repo_data_root``
        (``data_root/<repo_slug>``). Use for per-repo operational stores that
        must not collide across repos sharing a ``data_root`` (ADR-0021 D2).
        """
        return self.repo_data_root.joinpath(*parts)

    def format_path_for_display(self, path: Path) -> str:
        """Return a human-friendly path relative to repo or data root when possible."""
        for base in (self.repo_root, self.data_root):
            with contextlib.suppress(ValueError):
                return str(path.relative_to(base))
        return str(path)

    @property
    def repo_slug(self) -> str:
        """Normalized repo identifier for path namespacing (e.g. ``org-repo``)."""
        return self.repo.replace("/", "-") if self.repo else self.repo_root.name

    @property
    def repo_data_root(self) -> Path:
        """Return the repo-scoped data directory (``data_root / repo_slug``)."""
        return self.data_root / self.repo_slug

    @property
    def repo_memory_dir(self) -> Path:
        """Repo-scoped memory dir for per-repo insight stores (ADR-0021 D2).

        Holds the retrospective/harness/review insight files. Distinct from
        :attr:`memory_dir` (flat ``data_root/memory``), which still hosts
        cross-repo knowledge (e.g. ``adr_decisions.jsonl``,
        ``hitl_recommendations.jsonl``).
        """
        return self.repo_data_root / "memory"

    @property
    def retrospectives_path(self) -> Path:
        """Repo-scoped retrospective records store (``repo_memory_dir``)."""
        return self.repo_memory_dir / "retrospectives.jsonl"

    @property
    def cost_inferences_path(self) -> Path:
        """Repo-scoped LLM inference cost-telemetry store (ADR-0021 D2)."""
        return self.repo_data_root / "metrics" / "prompt" / "inferences.jsonl"

    @property
    def pr_stats_path(self) -> Path:
        """Repo-scoped per-PR telemetry aggregates (ADR-0021 D2)."""
        return self.repo_data_root / "metrics" / "prompt" / "pr_stats.json"

    @property
    def prompt_efficiency_history_path(self) -> Path:
        """Repo-scoped baseline-history ledger for the efficiency sensor (#11116).

        One JSONL row per SkillPromptEvalLoop telemetry tick: the cumulative
        `get_source_totals()` snapshot that became the new baseline. The live
        baseline in state is overwritten every tick; this ledger is what lets
        a filed `prompt-inefficiency` claim be re-derived — or refuted —
        after the fact.
        """
        return self.repo_data_root / "metrics" / "prompt" / "efficiency_baselines.jsonl"

    @property
    def prompt_gate_audit_path(self) -> Path:
        """Repo-scoped data-governance gate audit trail (CH-6, issue #9734).

        JSONL records of gate decisions for regulated data classes: class,
        action, pattern-hit NAMES and counts — never prompt content.
        """
        return self.repo_data_root / "metrics" / "prompt_gate" / "gate_audit.jsonl"

    @property
    def prompt_observatory_path(self) -> Path:
        """Repo-scoped observed-prompt-shape ledger (#10857, #10858).

        JSONL records of prompt SHAPES seen at the CH-6 gate: a structural
        hash, the source, the tool, and anchor digests — never prompt content,
        the same discipline as ``prompt_gate_audit_path``. Feeds the observed
        side of prompt coverage, where the denominator is what the factory
        actually sent rather than what a naming convention could find.
        """
        return self.repo_data_root / "metrics" / "prompt_gate" / "observed_shapes.jsonl"

    @property
    def approval_records_path(self) -> Path:
        """Repo-scoped hash-chained merge-approval evidence stream (CH-2, #9730).

        PR numbers are repo-scoped, so the stream lives under
        ``repo_data_root`` — one chain per managed repo.
        """
        return self.repo_data_root / "audit" / "approval_records.jsonl"

    @property
    def evidence_packs_path(self) -> Path:
        """Repo-scoped hash-chained evidence-pack summary stream (CH-4, #9732).

        One ``record_type="evidence_pack"`` record per compiled RC pack;
        the pack directories themselves live under :attr:`evidence_dir`.
        """
        return self.repo_data_root / "audit" / "evidence_packs.jsonl"

    @property
    def evidence_dir(self) -> Path:
        """Root of the per-RC release evidence packs (CH-4, #9732)."""
        return self.repo_data_root / "evidence"

    @property
    def merge_policy_path(self) -> Path:
        """Resolve the factory-autonomy merge policy file (CH-3, #9731).

        A managed repo's own ``docs/standards/factory_autonomy/policy.yaml``
        when present; otherwise the copy in the HydraFlow *checkout* (the
        standard applies to every HydraFlow-format project). ``docs/`` is
        documentation, not package data, so a wheel install has no second
        copy — the property then names the managed repo's own expected
        location, which is the one path an operator can act on.
        ``merge_policy.enforce_merge_policy`` fails CLOSED on a missing or
        invalid file either way (#11589).
        """
        repo_local = (
            self.repo_root / "docs" / "standards" / "factory_autonomy" / "policy.yaml"
        )
        if repo_local.exists():
            return repo_local
        try:
            return checkout_path("docs", "standards", "factory_autonomy", "policy.yaml")
        except ResourceNotFoundError:
            return repo_local

    def base_branch(self) -> str:
        """Return the branch agent PRs should target.

        Returns ``staging_branch`` when ``staging_enabled`` is true, otherwise
        ``main_branch``. Use this everywhere the intent is "the branch we
        build off of". Use ``main_branch`` directly only where the intent is
        "the released/known-good branch" (e.g., RC promotion compare).
        """
        return self.staging_branch if self.staging_enabled else self.main_branch

    def branch_for_issue(self, issue_number: int) -> str:
        """Return the canonical branch name for a given issue number."""
        return f"agent/issue-{issue_number}"

    def auto_agent_branch_for_issue(self, issue_number: int) -> str:
        """Return the Auto-Agent (preflight) session branch name for an issue."""
        return f"{AUTO_AGENT_BRANCH_PREFIX}{issue_number}"

    def agent_branches_for_issue(self, issue_number: int) -> tuple[str, str]:
        """Both branch names an issue's work can live on (#11281).

        Manual dispatch mints ``agent/issue-{N}``; Auto-Agent preflight
        mints ``agent/auto-agent-{N}``. Consumers that resolve "the branch
        for this issue" must consider BOTH — knowing only the first is the
        defect class behind #11282 (review loop blind to auto-agent PRs)
        and #11281 (branch GC deleting live auto-agent work). Manual-first
        ordering matches the resolution precedence those consumers use.
        """
        return (
            self.branch_for_issue(issue_number),
            self.auto_agent_branch_for_issue(issue_number),
        )

    def regulated_label_set(self) -> frozenset[str]:
        """Parse ``regulated_labels`` CSV into a label set (CH-5).

        Blank entries are dropped; an empty result means no change class
        is regulated, so requirement IDs stay optional everywhere.
        """
        return frozenset(
            label.strip() for label in self.regulated_labels.split(",") if label.strip()
        )

    def workspace_path_for_issue(self, issue_number: int) -> Path:
        """Return the repo-scoped workspace directory path for a given issue number."""
        return self.workspace_base / self.repo_slug / f"issue-{issue_number}"

    def worktree_gc_root_paths(self) -> list[Path]:
        """Return the allow-list of roots the WorkspaceGCLoop may sweep (#10698).

        When ``worktree_gc_roots`` is configured it wins verbatim. Otherwise
        this returns the known factory worktree roots — where sub-agent,
        manual/dev, genpr, and factory-operational worktrees are created —
        so the enumerate-and-reap phase covers every leaking root, not just
        ``workspace_base/repo_slug/issue-<N>``. A worktree whose path is not
        under one of these roots is never reaped (fail-closed blast-radius
        gate); operators widen coverage via ``HYDRAFLOW_WORKTREE_GC_ROOTS``.
        """
        if self.worktree_gc_roots:
            return [Path(r).expanduser() for r in self.worktree_gc_roots]
        home = Path.home()
        candidates = [
            self.workspace_base,
            home / ".hydraflow" / "worktrees",
            home / ".hydraflow" / "dev",
            self.repo_root / ".claude" / "worktrees",
        ]
        seen: set[Path] = set()
        roots: list[Path] = []
        for root in candidates:
            if root not in seen:
                seen.add(root)
                roots.append(root)
        return roots

    @model_validator(mode="after")
    def resolve_defaults(self) -> HydraFlowConfig:
        """Resolve paths, repo slug, and apply env var overrides.

        Resolution order (seven steps):
          1. ``_resolve_base_paths`` — repo_root, workspace_base, data_root
          2. ``_resolve_repo_and_identity`` — repo slug, git identity
          3. ``_resolve_repo_scoped_paths`` — state_file, event_log_path, config_file
          4. ``_apply_env_overrides`` — env-var overrides for labels, tokens, etc.
          5. ``_apply_profile_overrides`` — grouped tool/model defaults for profiles
          6. ``_harmonize_tool_model_defaults`` — tool and model consistency
          7. ``_validate_docker`` — Docker configuration validation

        Base paths are resolved first because repo detection depends on repo_root,
        and repo-scoped paths depend on both data_root and the repo slug.

        Environment variables (checked when no explicit CLI value is given):
            HYDRAFLOW_GITHUB_REPO       → repo
            HYDRAFLOW_GITHUB_ASSIGNEE   → (used by slash commands only)
            HYDRAFLOW_GIT_USER_NAME     → git_user_name
            HYDRAFLOW_GIT_USER_EMAIL    → git_user_email
            HYDRAFLOW_MIN_PLAN_WORDS    → min_plan_words

        Tool/model overrides use the combo syntax (BREAKING: legacy *_TOOL/*_MODEL
        single-field env vars are no longer supported):
            HYDRAFLOW_TRIAGE=tool:model, HYDRAFLOW_IMPLEMENT=tool:model, etc.

        Label fields (ready_label, find_label, etc.) are config-file-only;
        HYDRAFLOW_LABEL_* env vars were removed in the Task 7 breaking change.
        """
        _resolve_base_paths(self)
        _resolve_repo_and_identity(self)
        _resolve_repo_scoped_paths(self)
        _apply_env_overrides(self)
        _apply_profile_overrides(self)
        _harmonize_tool_model_defaults(self)
        _validate_docker(self)
        return self


# The gh_token priority chain, in order (highest priority first). Also the keys
# _dotenv_lookup falls back on.
_GH_TOKEN_ENV_KEYS: tuple[str, ...] = ("HYDRAFLOW_GH_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")
# 1:1 credential-field → env-key. Read with empty-string defaults.
_WHATSAPP_ENV_KEYS: dict[str, str] = {
    "whatsapp_token": "HYDRAFLOW_WHATSAPP_TOKEN",
    "whatsapp_phone_id": "HYDRAFLOW_WHATSAPP_PHONE_ID",
    "whatsapp_recipient": "HYDRAFLOW_WHATSAPP_RECIPIENT",
    "whatsapp_verify_token": "HYDRAFLOW_WHATSAPP_VERIFY_TOKEN",
    "whatsapp_app_secret": "HYDRAFLOW_WHATSAPP_APP_SECRET",
}
#: Every env var :func:`build_credentials` reads, as one enumerable surface so
#: test isolation and .env/documentation generators don't hand-list the
#: credential keys (#10885). Folded into :func:`declared_env_keys`.
CREDENTIAL_ENV_KEYS: frozenset[str] = frozenset(_GH_TOKEN_ENV_KEYS) | frozenset(
    _WHATSAPP_ENV_KEYS.values()
)


def build_credentials(config: HydraFlowConfig) -> Credentials:
    """Build a ``Credentials`` instance from environment variables and .env files.

    Resolution priority for ``gh_token``: each key in :data:`_GH_TOKEN_ENV_KEYS`
    (``HYDRAFLOW_GH_TOKEN`` → ``GH_TOKEN`` → ``GITHUB_TOKEN``) in ``os.environ``,
    then the ``.env`` file in ``config.repo_root``. Other credential fields are
    read from :data:`_WHATSAPP_ENV_KEYS` with empty-string defaults. The full key
    surface is exported as :data:`CREDENTIAL_ENV_KEYS` (#10885).
    """
    gh_token = ""
    for key in _GH_TOKEN_ENV_KEYS:
        gh_token = os.environ.get(key, "")
        if gh_token:
            break
    if not gh_token:
        gh_token = _dotenv_lookup(config.repo_root, *_GH_TOKEN_ENV_KEYS)
    return Credentials(
        gh_token=gh_token,
        **{
            field: os.environ.get(env_key, "")
            for field, env_key in _WHATSAPP_ENV_KEYS.items()
        },
    )


def _apply_profile_overrides(config: HydraFlowConfig) -> None:
    """Apply grouped tool/model defaults for background and system workloads."""

    explicit_fields = set(config.__pydantic_fields_set__)

    def _apply_if_default(field: str, value: str) -> None:
        if field in explicit_fields:
            return
        if getattr(config, field) == HydraFlowConfig.model_fields[field].default:
            object.__setattr__(config, field, value)

    if config.system_tool != "inherit":
        for field in (
            "implementation_tool",
            "review_tool",
            "planner_tool",
            "ac_tool",
            "subskill_tool",
            "debug_tool",
        ):
            _apply_if_default(field, config.system_tool)
        # verification_judge_tool intentionally omitted — it is auto-synced
        # to review_tool inside _harmonize_tool_model_defaults.

    if config.system_model.strip():
        for field in (
            "model",
            "review_model",
            "planner_model",
            "ac_model",
            "subskill_model",
            "debug_model",
        ):
            _apply_if_default(field, config.system_model)

    if config.background_tool != "inherit":
        for field in (
            "triage_tool",
            "transcript_summary_tool",
            "report_issue_tool",
            "adr_review_tool",
        ):
            _apply_if_default(field, config.background_tool)

    if config.background_model.strip():
        for field in (
            "triage_model",
            "transcript_summary_model",
            "report_issue_model",
            "adr_review_model",
        ):
            _apply_if_default(field, config.background_model)

    # Maintenance knob: route the maintenance role-set to one backend coherently
    # (provider AND model together), never the work loops. A model is only
    # applied where the role actually has a *_model field (pr_unstick has none).
    if config.maintenance_provider != "claude" or config.maintenance_model.strip():
        for role in _MAINTENANCE_DIALED_ROLES:
            if config.maintenance_provider != "claude":
                _apply_if_default(f"{role}_provider", config.maintenance_provider)
            model_field = f"{role}_model"
            if (
                config.maintenance_model.strip()
                and model_field in HydraFlowConfig.model_fields
            ):
                _apply_if_default(model_field, config.maintenance_model)

    # Explicit terminal gateway profile. Safe defaults stay direct while the
    # ratchet is off; enabling it promotes every untouched gateway-capable dial
    # to the gateway. An operator-supplied direct value remains untouched here
    # so the validator can reject that attempted bypass below.
    if config.gateway_fleet_ratchet_enabled:
        for field in GATEWAY_CAPABLE_PROVIDER_FIELDS:
            _apply_if_default(field, "gateway")


# Maintenance roles with dedicated provider/model fields. Four additional
# caretaker roles inherit maintenance_* dynamically at their lightweight seam.
_MAINTENANCE_DIALED_ROLES: tuple[str, ...] = (
    "wiki_compilation",
    "adr_review",
    "transcript_summary",
    "term_proposer",
    "triage_honeypot",
    "pr_unstick",
)

# One registry for the provider dials whose Claude-CLI face can transit the
# gateway.  The first rollout canary is ``adr_review_provider``; defaults remain
# direct until an operator opts in.  The fleet ratchet, settings/schema tests,
# and model/provider validation all consume these tuples rather than growing
# independent role lists.
GATEWAY_CANARY_PROVIDER_FIELD = "adr_review_provider"
GATEWAY_AGENTIC_PROVIDER_FIELDS: tuple[str, ...] = (
    "implementation_provider",
    "review_provider",
    "planner_provider",
    "triage_provider",
    "ac_provider",
    "repo_provider",
)
GATEWAY_ONE_SHOT_PROVIDER_FIELDS: tuple[str, ...] = tuple(
    f"{role}_provider" for role in _MAINTENANCE_DIALED_ROLES
)
GATEWAY_CAPABLE_PROVIDER_FIELDS: tuple[str, ...] = (
    *GATEWAY_AGENTIC_PROVIDER_FIELDS,
    *GATEWAY_ONE_SHOT_PROVIDER_FIELDS,
)

# Model prefix → required tool. Any model starting with a listed prefix
# MUST pair with the given tool; any other pairing is rejected. glm-* rides the
# Claude CLI (pointed at z.ai's Anthropic-compatible endpoint), so it requires
# tool="claude".
_MODEL_TOOL_REQUIRED: list[tuple[str, str]] = [
    ("gpt-", "codex"),
    ("o1", "codex"),
    ("o3", "codex"),
    ("o4", "codex"),
    ("opus", "claude"),
    ("sonnet", "claude"),
    ("haiku", "claude"),
    ("claude-", "claude"),
    ("glm", "claude"),
]

# Model prefix → required provider (harness backend). A glm-* model only runs on
# the z.ai harness backend, so its role's *_provider MUST be "zai". Anything not
# listed is provider-agnostic on the tool axis but still subject to the inverse
# check (a "zai" provider requires a glm-* model).
_MODEL_PROVIDER_REQUIRED: list[tuple[str, str]] = [
    ("glm", "zai"),
]

# Stages without a dedicated *_provider dial inherit a provider from another
# config field. Map each to that source so its effective model is validated
# against EVERY backend it can actually run on. Subskill/debug are multi-caller:
# the AC precheck closures run them on ac_provider, while reviewer +
# verification-judge prechecks run them on review_provider. The one-shot
# caretaker roles inherit maintenance_provider at the central lightweight seam.
_STAGE_PROVIDER_SOURCE: dict[str, tuple[str, ...]] = {
    "test_adequacy_verifier": ("implementation_provider",),
    "subskill": ("ac_provider", "review_provider"),
    "debug": ("ac_provider", "review_provider"),
    # These one-shot caretaker roles share maintenance_provider rather than
    # exposing dead per-role dials. Their run_lightweight_agent calls omit the
    # provider deliberately so the central seam performs the same inheritance.
    "sampled_audit": ("maintenance_provider",),
    "issue_refinement": ("maintenance_provider",),
    "intervention_tally": ("maintenance_provider",),
    "skill_prompt_refine": ("maintenance_provider",),
}


def resolve_maintenance_model(
    *,
    role_model: str,
    maintenance_model: str,
    background_model: str,
) -> str:
    """Resolve a shared-provider caretaker's effective model."""
    return role_model or maintenance_model or background_model or "sonnet"


def resolve_maintenance_tool(
    config: HydraFlowConfig,
) -> Literal["claude", "codex"]:
    """Resolve the CLI tool shared-provider caretaker roles execute."""
    return "claude" if config.background_tool == "inherit" else config.background_tool


def _required_tool_for_model(model: str) -> str | None:
    m = model.lower()
    for prefix, tool in _MODEL_TOOL_REQUIRED:
        if m.startswith(prefix):
            return tool
    return None


def _required_provider_for_model(model: str) -> str | None:
    m = model.lower()
    for prefix, provider in _MODEL_PROVIDER_REQUIRED:
        if m.startswith(prefix):
            return provider
    return None


def _validate_gateway_enforcement_canary(config: HydraFlowConfig) -> None:
    """A canary dial that arms nothing must say so at load, not at the spawn.

    ADR-0141: only an exact canonical ``owner/repo`` arms the canary, and the
    runtime predicate fails closed on anything else. Failing closed is the right
    *behaviour* and the wrong *silence*: an operator who typed the path-safe
    runtime slug would believe a repository was governed while every spawn ran
    unenforced. The runtime check stays — this dial is live-editable, so a value
    can still arrive without passing through here — but a value written to the
    config file is refused where the mistake is still cheap.
    """
    from hydraflow_gateway.routing_policy import canonicalize_repo

    raw = str(config.gateway_enforcement_canary_repo or "").strip()
    if raw and canonicalize_repo(raw) is None:
        msg = (
            "gateway_enforcement_canary_repo must be an exact canonical "
            f"'owner/repo' (got {raw!r}); the path-safe runtime slug cannot "
            "identify a governed repository (ADR-0139 D2). Leave it empty to "
            "enforce nothing."
        )
        raise ValueError(msg)


#: Every Fable canary dial that names one repository. One tuple rather than one
#: validator per dial: #11542 added a second dial, and a copied validator is how
#: the two would eventually disagree about what "canonical" means.
_FABLE_CANARY_DIALS: tuple[str, ...] = (
    "fable_plan_canary_repo",
    "fable_implement_canary_repo",
    "fable_review_canary_repo",
)


def _validate_fable_plan_canary(config: HydraFlowConfig) -> None:
    """A Fable canary dial that arms nothing must say so at load (#11541/#11542).

    Same rule and the same reason as
    :func:`_validate_gateway_enforcement_canary`: only an exact canonical
    ``owner/repo`` arms the canary, the runtime predicate fails closed on
    anything else, and failing closed silently would leave an operator
    believing a repository was brokered while every boundary stayed shadow.
    The runtime check stays — these dials are live-editable — but a value
    written to the config file is refused where the mistake is still cheap.
    """
    from hydraflow_gateway.routing_policy import canonicalize_repo

    for dial in _FABLE_CANARY_DIALS:
        raw = str(getattr(config, dial, "") or "").strip()
        if raw and canonicalize_repo(raw) is None:
            msg = (
                f"{dial} must be an exact canonical 'owner/repo' "
                f"(got {raw!r}); the path-safe runtime slug cannot identify a "
                "canary repository. Leave it empty to dispatch nothing."
            )
            raise ValueError(msg)


def _validate_gateway_capture_policy(config: HydraFlowConfig) -> None:
    """Validate repo classification and the body-capture privacy boundary."""
    if config.gateway_repo_class not in {"hydraflow", "client", "personal"}:
        msg = "gateway_repo_class must be one of 'hydraflow', 'client', or 'personal'"
        raise ValueError(msg)
    if config.gateway_capture_bodies and config.gateway_repo_class != "hydraflow":
        msg = (
            "gateway_capture_bodies requires gateway_repo_class='hydraflow'; "
            "client and personal repo classes are metadata-only"
        )
        raise ValueError(msg)


def _gateway_direct_harness_roles(config: HydraFlowConfig) -> list[str]:
    """Return gateway-capable roles that still bypass the terminal profile."""
    direct = [
        f"{field}={provider!r}"
        for field in GATEWAY_AGENTIC_PROVIDER_FIELDS
        if (provider := getattr(config, field)) in {"claude", "zai"}
    ]
    # openrouter/zai/kimi are explicitly excluded one-shot HTTP faces. Only
    # their direct Claude-CLI option is a gateway bypass.
    direct.extend(
        f"{field}='claude'"
        for field in GATEWAY_ONE_SHOT_PROVIDER_FIELDS
        if getattr(config, field) == "claude"
    )
    return direct


def _validate_gateway_fleet_profile(config: HydraFlowConfig) -> None:
    """Enforce credential isolation and complete routing for the fleet ratchet."""
    if not config.gateway_fleet_ratchet_enabled:
        return
    if config.execution_mode != "docker":
        msg = (
            "gateway fleet ratchet requires execution_mode='docker'; "
            "host agent CLIs can read provider OAuth/keychain state even "
            "when their process environment is scrubbed"
        )
        raise ValueError(msg)
    if config.docker_extra_mounts:
        msg = (
            "gateway fleet ratchet forbids docker_extra_mounts; arbitrary "
            "host mounts can re-expose repository .env files or provider "
            "credential homes inside an otherwise isolated worker"
        )
        raise ValueError(msg)
    if resolve_maintenance_tool(config) != "claude":
        msg = (
            "gateway fleet ratchet requires background_tool='claude' or 'inherit'; "
            "shared caretaker Codex spawns cannot use the gateway's isolated "
            "Claude-harness runner"
        )
        raise ValueError(msg)
    if direct := _gateway_direct_harness_roles(config):
        msg = (
            "gateway fleet ratchet forbids direct Claude/z.ai harness "
            "providers; set gateway-capable roles to provider='gateway' "
            "(one-shot OpenAI-compatible providers remain allowed): "
            + ", ".join(direct)
        )
        raise ValueError(msg)


def _validate_gateway_pr_unstick_tool(config: HydraFlowConfig) -> None:
    """Validate PRUnsticker's implicit background-tool wiring."""
    # PRUnsticker's reflection call uses the shared background tool rather than
    # a dedicated ``pr_unstick_tool`` field. The gateway exposes an Anthropic
    # harness and therefore cannot execute a Codex background command.
    pr_unstick_tool = (
        "claude" if config.background_tool == "inherit" else config.background_tool
    )
    if config.pr_unstick_provider == "gateway" and pr_unstick_tool != "claude":
        msg = (
            "pr_unstick: provider 'gateway' requires background_tool='claude' "
            f"or 'inherit'; got {config.background_tool!r}"
        )
        raise ValueError(msg)


_StageToolModel = tuple[str, str, str]


def _tool_model_stage_pairs(config: HydraFlowConfig) -> tuple[_StageToolModel, ...]:
    """Return every independently configurable stage/tool/model triple."""
    return (
        ("implementation", config.implementation_tool, config.model),
        ("review", config.review_tool, config.review_model),
        (
            "test_adequacy_verifier",
            config.test_adequacy_verifier_tool,
            config.test_adequacy_verifier_model,
        ),
        ("planner", config.planner_tool, config.planner_model),
        ("triage", config.triage_tool, config.triage_model),
        ("ac", config.ac_tool, config.ac_model),
        ("subskill", config.subskill_tool, config.subskill_model),
        ("debug", config.debug_tool, config.debug_model),
        (
            "transcript_summary",
            config.transcript_summary_tool,
            config.transcript_summary_model,
        ),
        (
            "wiki_compilation",
            config.wiki_compilation_tool,
            config.wiki_compilation_model,
        ),
        ("report_issue", config.report_issue_tool, config.report_issue_model),
        ("adr_review", config.adr_review_tool, config.adr_review_model),
        ("term_proposer", config.term_proposer_tool, config.term_proposer_model),
        (
            "sampled_audit",
            resolve_maintenance_tool(config),
            resolve_maintenance_model(
                role_model=config.sampled_audit_model,
                maintenance_model=config.maintenance_model,
                background_model=config.background_model,
            ),
        ),
        (
            "issue_refinement",
            resolve_maintenance_tool(config),
            resolve_maintenance_model(
                role_model=config.issue_refinement_model,
                maintenance_model=config.maintenance_model,
                background_model=config.background_model,
            ),
        ),
        (
            "intervention_tally",
            resolve_maintenance_tool(config),
            resolve_maintenance_model(
                role_model=config.intervention_tally_model,
                maintenance_model=config.maintenance_model,
                background_model=config.background_model,
            ),
        ),
        (
            "skill_prompt_refine",
            resolve_maintenance_tool(config),
            resolve_maintenance_model(
                role_model=config.skill_prompt_refine_model,
                maintenance_model=config.maintenance_model,
                background_model=config.background_model,
            ),
        ),
    )


def _validate_stage_provider(
    *,
    stage: str,
    tool: str,
    model: str,
    provider: str,
    required_provider: str | None,
) -> None:
    """Validate one routing provider against a stage's tool and model."""
    if provider == "gateway" and tool != "claude":
        msg = f"{stage}: provider 'gateway' requires tool 'claude'; got tool {tool!r}"
        raise ValueError(msg)
    provider_matches = provider == required_provider or (
        provider == "gateway" and required_provider == "zai"
    )
    if required_provider is not None and not provider_matches:
        msg = (
            f"{stage}: model {model!r} requires provider "
            f"{required_provider!r} but a routing runner is on provider "
            f"{provider!r}"
        )
        raise ValueError(msg)
    if provider == "zai" and required_provider != "zai":
        msg = (
            f"{stage}: provider 'zai' (the GLM harness) requires a glm-* "
            f"model, got {model!r}"
        )
        raise ValueError(msg)


def _validate_stage_tool_model(
    config: HydraFlowConfig, stage: str, tool: str, model: str
) -> None:
    """Validate a stage's tool/model pair against every routing provider."""
    if not model:
        return  # empty — inherited/unset
    if "flash" in model.lower():
        msg = (
            f"{stage}: model {model!r} is a *flash* variant; "
            "flash models are rejected for the factory (insufficient "
            "reasoning quality). Use a pro-tier model instead."
        )
        raise ValueError(msg)
    required_tool = _required_tool_for_model(model)
    if required_tool is not None and required_tool != tool:
        msg = (
            f"{stage}: mismatched pair {tool!r}+{model!r}; "
            f"model {model!r} requires tool {required_tool!r}"
        )
        raise ValueError(msg)

    # Some stages inherit another role's provider rather than owning a dial, so
    # validate against every provider they can inherit. Roles without a mapping
    # or dedicated dial default to the Claude harness.
    provider_fields = _STAGE_PROVIDER_SOURCE.get(stage, (f"{stage}_provider",))
    providers = {getattr(config, field, "claude") for field in provider_fields}
    required_provider = _required_provider_for_model(model)
    for provider in providers:
        _validate_stage_provider(
            stage=stage,
            tool=tool,
            model=model,
            provider=provider,
            required_provider=required_provider,
        )


def _harmonize_tool_model_defaults(config: HydraFlowConfig) -> None:
    """Validate that every (tool, model) pair is internally consistent.

    Rejects:
      - Any ``*-flash*`` model in any role (quality guard for the factory).
      - Cross-provider mismatches (e.g. ``codex`` + ``opus``,
        ``gemini`` + ``gpt-5-codex``).

    Also auto-syncs ``verification_judge_tool`` to ``review_tool`` because
    the two share ``review_model`` — the tools MUST agree, so we pick the
    review side as the source of truth and let the ``review`` pair check
    catch the underlying model mismatch if one exists. Emits a warning
    when an explicit ``verification_judge_tool`` is being overridden so
    the user isn't surprised.
    """
    if config.verification_judge_tool != config.review_tool:
        logger.warning(
            "verification_judge_tool=%r does not match review_tool=%r; "
            "the two share review_model so they must agree. "
            "Overriding verification_judge_tool to %r.",
            config.verification_judge_tool,
            config.review_tool,
            config.review_tool,
        )
    object.__setattr__(config, "verification_judge_tool", config.review_tool)

    _validate_gateway_capture_policy(config)
    _validate_gateway_enforcement_canary(config)
    _validate_fable_plan_canary(config)
    _validate_gateway_fleet_profile(config)
    _validate_gateway_pr_unstick_tool(config)
    for stage, tool, model in _tool_model_stage_pairs(config):
        _validate_stage_tool_model(config, stage, tool, model)


def _resolve_base_paths(config: HydraFlowConfig) -> None:
    """Resolve repo_root, workspace_base, and data_root.

    These base paths have no dependency on the repo slug and must be resolved
    first so that ``_resolve_repo_and_identity`` can use ``repo_root`` for
    git-remote detection and ``_resolve_repo_scoped_paths`` can use ``data_root``.
    """
    if config.repo_root == Path("."):
        object.__setattr__(config, "repo_root", _find_repo_root())
    else:
        object.__setattr__(config, "repo_root", config.repo_root.expanduser().resolve())
    if config.workspace_base == Path("."):
        default_worktrees = Path("~/.hydraflow/worktrees").expanduser().resolve()
        object.__setattr__(config, "workspace_base", default_worktrees)
    else:
        object.__setattr__(
            config, "workspace_base", config.workspace_base.expanduser().resolve()
        )
    # HYDRAFLOW_DATA_ROOT is the canonical override; HYDRAFLOW_HOME is kept
    # as a legacy alias so existing deployments continue to work.
    env_data_root = (
        os.environ.get("HYDRAFLOW_DATA_ROOT", "").strip()
        or os.environ.get("HYDRAFLOW_HOME", "").strip()
    )
    if env_data_root:
        data_root = Path(env_data_root).expanduser().resolve()
    elif config.data_root == Path("."):
        data_root = (config.repo_root / ".hydraflow").resolve()
    else:
        data_root = config.data_root.expanduser().resolve()
    object.__setattr__(config, "data_root", data_root)


_REPO_SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


def _validate_repo_format(repo: str) -> None:
    """Raise ``ValueError`` if *repo* is not a valid ``owner/repo`` slug."""
    if not repo:
        return  # empty repo is handled elsewhere
    if ".." in repo:
        msg = f"Invalid repo format {repo!r} — path traversal not allowed"
        raise ValueError(msg)
    if not _REPO_SLUG_RE.fullmatch(repo):
        msg = f"Invalid repo format {repo!r} — expected 'owner/repo'"
        raise ValueError(msg)


def _resolve_repo_and_identity(config: HydraFlowConfig) -> None:
    """Resolve repo slug and git identity from env vars."""
    # Repo slug: env var → git remote → empty
    if not config.repo:
        config.repo = os.environ.get("HYDRAFLOW_GITHUB_REPO", "") or _detect_repo_slug(
            config.repo_root
        )

    if config.repo:
        _validate_repo_format(config.repo)

    # Git identity:
    # explicit value → HYDRAFLOW_GIT_USER_NAME/EMAIL env vars
    # → GIT_* author/committer env vars → .env fallback
    if not config.git_user_name:
        env_name = (
            os.environ.get("HYDRAFLOW_GIT_USER_NAME", "")
            or os.environ.get("GIT_AUTHOR_NAME", "")
            or os.environ.get("GIT_COMMITTER_NAME", "")
            or _dotenv_lookup(
                config.repo_root,
                "HYDRAFLOW_GIT_USER_NAME",
                "GIT_AUTHOR_NAME",
                "GIT_COMMITTER_NAME",
            )
        )
        if env_name:
            object.__setattr__(config, "git_user_name", env_name)
    if not config.git_user_email:
        env_email = (
            os.environ.get("HYDRAFLOW_GIT_USER_EMAIL", "")
            or os.environ.get("GIT_AUTHOR_EMAIL", "")
            or os.environ.get("GIT_COMMITTER_EMAIL", "")
            or _dotenv_lookup(
                config.repo_root,
                "HYDRAFLOW_GIT_USER_EMAIL",
                "GIT_AUTHOR_EMAIL",
                "GIT_COMMITTER_EMAIL",
            )
        )
        if env_email:
            object.__setattr__(config, "git_user_email", env_email)


def _resolve_repo_scoped_paths(config: HydraFlowConfig) -> None:
    """Resolve state_file, event_log_path, and config_file under repo-scoped dirs.

    Called after both ``_resolve_base_paths`` (which provides ``data_root``) and
    ``_resolve_repo_and_identity`` (which provides the repo slug).  Default paths
    are placed directly under ``data_root / <slug>`` — no intermediate flat
    defaults are created first.

    Explicitly-provided paths are left untouched (just expanded/resolved).

    Legacy flat files are migrated on first run: if the repo-scoped file does not
    exist but the legacy flat file does, a copy is made so no data is lost.
    """
    data_root = config.data_root
    slug = config.repo_slug
    explicit = config.__pydantic_fields_set__

    # Target directory: repo-scoped when a slug is available, flat otherwise.
    # NOTE: repo_slug never returns "" for a non-root repo_root, so the `else
    # data_root` branch below and the `if slug` migration guards are only
    # reached when repo_root is the filesystem root ("/").
    repo_dir = data_root / slug if slug else data_root

    # --- state_file ---
    if "state_file" not in explicit:
        target = repo_dir / "state.json"
        if slug:
            flat = data_root / "state.json"
            if not target.exists() and flat.exists():
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(flat, target)
                except OSError as exc:
                    logger.warning("Failed to migrate %s → %s: %s", flat, target, exc)
        object.__setattr__(config, "state_file", target)
    else:
        object.__setattr__(
            config, "state_file", config.state_file.expanduser().resolve()
        )

    # --- event_log_path ---
    if "event_log_path" not in explicit:
        target = repo_dir / "events.jsonl"
        if slug:
            flat = data_root / "events.jsonl"
            if not target.exists() and flat.exists():
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(flat, target)
                except OSError as exc:
                    logger.warning("Failed to migrate %s → %s: %s", flat, target, exc)
        object.__setattr__(config, "event_log_path", target)
    else:
        object.__setattr__(
            config, "event_log_path", config.event_log_path.expanduser().resolve()
        )

    # --- config_file ---
    # config_file defaults to None (persistence disabled); only resolve if explicit.
    if "config_file" in explicit and config.config_file is not None:
        object.__setattr__(
            config, "config_file", config.config_file.expanduser().resolve()
        )

    # --- sessions.jsonl (derived from state_file parent, migrate if needed) ---
    # Only migrate when state_file is at its default location; skip when the user
    # has pointed state_file at a custom path to avoid copying into arbitrary dirs.
    if "state_file" not in explicit:
        flat_sessions = data_root / "sessions.jsonl"
        scoped_sessions = config.state_file.parent / "sessions.jsonl"
        if (
            scoped_sessions != flat_sessions
            and not scoped_sessions.exists()
            and flat_sessions.exists()
        ):
            try:
                scoped_sessions.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(flat_sessions, scoped_sessions)
            except OSError as exc:
                logger.warning(
                    "Failed to migrate %s → %s: %s", flat_sessions, scoped_sessions, exc
                )


#: Test-isolation seam (#10902): repo roots whose ``.env`` :func:`_dotenv_lookup`
#: must treat as absent. Production leaves this empty. The pytest session fixture
#: registers the real checkout root (via :func:`mark_default_repo_dotenv_inert`)
#: so a default-constructed ``HydraFlowConfig()`` in a test cannot read the
#: operator's real ``.env`` (which carries a live ``HYDRAFLOW_GH_TOKEN``) even
#: after ``os.environ`` is scrubbed. An explicit ``repo_root=tmp_path`` — the
#: dotenv-fallback tests — is a different root and is unaffected.
_DOTENV_INERT_ROOTS: set[Path] = set()


def mark_default_repo_dotenv_inert() -> Path:
    """Make the default-resolved repo root's ``.env`` inert for _dotenv_lookup.

    Test-only seam (#10902); never called in production. Returns the marked root.
    Uses the same :func:`_find_repo_root` the default ``repo_root`` resolves
    through, so the registered path matches ``config.repo_root`` exactly.
    """
    root = _find_repo_root()
    _DOTENV_INERT_ROOTS.add(root)
    return root


def register_dotenv_inert_root(root: Path) -> None:
    """Mark an explicit ``root``'s ``.env`` inert for _dotenv_lookup (#10902)."""
    _DOTENV_INERT_ROOTS.add(root.expanduser().resolve())


def unregister_dotenv_inert_root(root: Path) -> None:
    """Undo :func:`register_dotenv_inert_root` for ``root`` (#10902).

    Discards only ``root`` — leaves any other registered roots (e.g. the session
    fixture's real-checkout registration) intact.
    """
    _DOTENV_INERT_ROOTS.discard(root.expanduser().resolve())


def clear_dotenv_inert_roots() -> None:
    """Reset the #10902 inert-root seam (test teardown)."""
    _DOTENV_INERT_ROOTS.clear()


def _dotenv_lookup(repo_root: Path, *keys: str) -> str:
    """Read first matching non-empty value from ``repo_root/.env``."""
    if _DOTENV_INERT_ROOTS and repo_root.expanduser().resolve() in _DOTENV_INERT_ROOTS:
        # Test-isolation seam (#10902): the real checkout .env is inert.
        return ""
    env_file = repo_root / ".env"
    if not env_file.exists():
        return ""
    try:
        text = env_file.read_text(encoding="utf-8")
    except OSError:
        return ""
    parsed = _parse_dotenv_text(text)
    for key in keys:
        val = parsed.get(key, "").strip()
        if val:
            return val
    return ""


def _parse_dotenv_text(text: str) -> dict[str, str]:
    """Parse minimal .env key/value content for local config fallbacks."""
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        else:
            # For unquoted values, treat inline " # comment" suffixes as comments.
            # Keep literal '#' when no whitespace precedes it.
            value = re.sub(r"\s+#.*$", "", value).rstrip()
        result[key] = value
    return result


def _get_env(key: str) -> str | None:
    """Return the env var value for *key*, falling back to any deprecated alias."""
    val = os.environ.get(key)
    if val is not None:
        return val
    old_key = _DEPRECATED_ENV_REVERSE.get(key)
    if old_key is not None:
        val = os.environ.get(old_key)
        if val is not None:
            logger.warning("Deprecated env var %s; use %s instead", old_key, key)
            return val
    return None


def declared_env_keys() -> frozenset[str]:
    """Every env var key any ``_ENV_*_OVERRIDES`` table (or deprecated alias)
    reads, regardless of prefix.

    Derived at runtime from the override tables themselves — never hand-list
    these keys elsewhere. Callers needing a hermetic environment (e.g. the
    test suite's session-scoped isolation fixture) should scrub this whole
    set rather than a ``HYDRAFLOW_``/``HYDRA_`` prefix rule alone, since
    several overrides (``OTEL_SERVICE_NAME``, ``HF_ENV``, ...) follow
    third-party naming conventions instead (#10876). Credential keys are
    *deliberately excluded* — they are read directly by
    :func:`build_credentials` (not a table) and are enumerated separately as
    :data:`CREDENTIAL_ENV_KEYS`, which the isolation fixture scrubs in addition
    to this set (#10885). Folding them in here would make the #10876 leak guard
    flag the deliberately-seeded ``GH_TOKEN=test-token``.
    """
    keys: set[str] = set()
    for table in (
        _ENV_INT_OVERRIDES,
        _ENV_STR_OVERRIDES,
        _ENV_FLOAT_OVERRIDES,
        _ENV_OPT_FLOAT_OVERRIDES,
        _ENV_OPT_INT_OVERRIDES,
        _ENV_FLOAT_RATIO_OVERRIDES,
        _ENV_BOOL_OVERRIDES,
    ):
        keys.update(env_key for _field, env_key, _default in table)
    keys.update(env_key for _field, env_key in _ENV_LITERAL_OVERRIDES)
    keys.update(env_key for _field, env_key, _enum_cls in _ENV_ENUM_OVERRIDES)
    keys.update(env_key for env_key, _tool_field, _model_field in _ENV_COMBO_OVERRIDES)
    keys.update(_DEPRECATED_ENV_ALIASES.keys())
    keys.update(_DEPRECATED_ENV_ALIASES.values())
    return frozenset(keys)


def env_override_keys() -> frozenset[str]:
    """Every env var key ``HydraFlowConfig``'s ``resolve_defaults()`` might
    read directly via ``os.environ`` — a superset of :func:`declared_env_keys`.

    ``declared_env_keys()`` only covers the data-driven ``_ENV_*_OVERRIDES``
    tables. Several steps in ``resolve_defaults`` — ``_resolve_base_paths``,
    ``_resolve_repo_and_identity``, and the special-case list/docker/JSON
    overrides at the end of ``_apply_env_overrides`` — read ``os.environ``
    directly for fields the tables don't model (list-typed fields, JSON-shaped
    overrides, values needing custom bounds validation). Those keys are
    hand-listed below; ``tests/architecture/test_config_env_key_coverage.py``
    BFS-walks the actual ``resolve_defaults`` call graph (not all of
    ``config.py`` — ``build_credentials()`` reads its own env vars but is
    never called from ``resolve_defaults``, so it's outside this graph by
    construction, not via an exemption list) and fails the build if a
    non-``HYDRAFLOW_``/``HYDRA_``/``GIT_``-prefixed literal is read anywhere
    in it without a matching entry here — so this list cannot silently drift
    out of sync (#10859).

    Callers building a hermetic ``HydraFlowConfig`` (:func:`declared_default_config`)
    should scrub this whole set — plus, belt-and-braces, any currently-set
    ``HYDRAFLOW_``/``HYDRA_``/``GIT_``-prefixed key, since a key can land in
    ``config.py`` and still be missed here on review.
    """
    return declared_env_keys() | {
        "HYDRAFLOW_DATA_ROOT",
        "HYDRAFLOW_HOME",
        "HYDRAFLOW_GITHUB_REPO",
        "HYDRAFLOW_GIT_USER_NAME",
        "HYDRAFLOW_GIT_USER_EMAIL",
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "HYDRAFLOW_DOCKER_ENABLED",
        "HYDRA_DOCKER_ENABLED",
        "HYDRAFLOW_LITE_PLAN_LABELS",
        "HYDRAFLOW_HUMAN_STEERING_AUTHORIZED_USERS",
        "HYDRAFLOW_WORKTREE_GC_ROOTS",
        "HYDRAFLOW_DOCKER_MEMORY_LIMIT",
        "HYDRAFLOW_DOCKER_TMP_SIZE",
        "HYDRAFLOW_DOCKER_PIDS_LIMIT",
        "HYDRAFLOW_MANAGED_REPOS",
    }


def declared_default_config(**overrides: Any) -> HydraFlowConfig:
    """Build a ``HydraFlowConfig`` reflecting only declared field defaults —
    no process environment, no ``.env`` file.

    ``HydraFlowConfig()``'s ``resolve_defaults`` validator (``mode="after"``)
    always runs; there is no constructor flag to skip it, so a bare
    ``HydraFlowConfig()`` is a function of whatever the host process's
    environment and ``repo_root/.env`` happen to contain. That breaks
    ADR-0087's "same input -> same score" for any caller that needs a
    machine-independent snapshot of the declared defaults — e.g. the prompt
    audit's rendered-corpus baseline (#10859).

    Two channels are neutralised for the duration of construction, both
    restored (even if construction raises):

    1. ``os.environ`` — every key in :func:`env_override_keys`, plus any
       currently-set ``HYDRAFLOW_``/``HYDRA_``/``GIT_``-prefixed key, is
       popped. The prefix set matches exactly what
       ``tests/architecture/test_config_env_key_coverage.py`` treats as
       "safe" without an explicit :func:`env_override_keys` entry — if the
       two ever drift apart, a new prefixed env read could pass that ratchet
       while still leaking through here.
    2. ``repo_root/.env`` — ``_dotenv_lookup`` (the git-identity fallback)
       reads this file directly, bypassing ``os.environ`` entirely, so
       scrubbing ``os.environ`` alone cannot suppress it. Unless the caller
       passes an explicit ``repo_root`` override, this defaults to a freshly
       created, empty temporary directory: no ``.env`` exists there and no
       git remote is configured, so ``_dotenv_lookup`` and the repo-slug
       git-remote detection both take their "nothing found" branch without
       any change to their own logic. An explicit ``repo_root`` override
       bypasses this, same precedence as every other field here.

    Harness/test-only — not for use on any hot or concurrent path.
    """
    scrub_keys = env_override_keys() | {
        key for key in os.environ if key.startswith(("HYDRAFLOW_", "HYDRA_", "GIT_"))
    }
    saved_env = {key: os.environ.pop(key) for key in scrub_keys if key in os.environ}
    try:
        with tempfile.TemporaryDirectory(
            prefix="hydraflow-declared-default-"
        ) as tmp_dir:
            fields: dict[str, Any] = {"repo_root": Path(tmp_dir)}
            fields.update(overrides)
            return HydraFlowConfig(**fields)
    finally:
        os.environ.update(saved_env)


def _apply_env_overrides(config: HydraFlowConfig) -> None:
    """Apply all data-driven and special-case env var overrides."""

    # Data-driven env var overrides (int fields)
    for field, env_key, default in _ENV_INT_OVERRIDES:
        if getattr(config, field) == default:
            env_val = _get_env(env_key)
            if env_val is not None:
                with contextlib.suppress(ValueError):
                    new_val = int(env_val)
                    for constraint in HydraFlowConfig.model_fields[field].metadata:
                        ge = getattr(constraint, "ge", None)
                        le = getattr(constraint, "le", None)
                        if ge is not None and new_val < ge:
                            raise ValueError(
                                f"{env_key}={new_val} is below minimum {ge}"
                            )
                        if le is not None and new_val > le:
                            raise ValueError(
                                f"{env_key}={new_val} is above maximum {le}"
                            )
                    object.__setattr__(config, field, new_val)

    # Data-driven env var overrides (str fields)
    for field, env_key, default in _ENV_STR_OVERRIDES:
        current = getattr(config, field)
        if str(current) == default:
            env_val = _get_env(env_key)
            if env_val is not None:
                # Preserve the field's type (e.g. Path vs str)
                field_type = type(current)
                new_val = field_type(env_val) if field_type is not str else env_val
                object.__setattr__(config, field, new_val)

    # Data-driven env var overrides (float fields)
    for field, env_key, default in _ENV_FLOAT_OVERRIDES:
        if getattr(config, field) == default:
            env_val = _get_env(env_key)
            if env_val is not None:
                with contextlib.suppress(ValueError):
                    new_val = float(env_val)
                    for constraint in HydraFlowConfig.model_fields[field].metadata:
                        ge = getattr(constraint, "ge", None)
                        le = getattr(constraint, "le", None)
                        if ge is not None and new_val < ge:
                            raise ValueError(
                                f"{env_key}={new_val} is below minimum {ge}"
                            )
                        if le is not None and new_val > le:
                            raise ValueError(
                                f"{env_key}={new_val} is above maximum {le}"
                            )
                    object.__setattr__(config, field, new_val)

    # Optional float overrides — empty string or unset → None, parse failures
    # log a warning and leave the value as the default. ge=0 enforced via
    # pydantic constraint on the field itself.
    for field, env_key, default in _ENV_OPT_FLOAT_OVERRIDES:
        env_val = _get_env(env_key)
        if env_val is None or env_val == "":
            object.__setattr__(config, field, default)
            continue
        try:
            parsed = float(env_val)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid %s=%r — treating as unset",
                env_key,
                env_val,
            )
            object.__setattr__(config, field, default)
            continue
        if parsed < 0:
            logger.warning(
                "%s=%s is below minimum 0; ignoring env override",
                env_key,
                parsed,
            )
            object.__setattr__(config, field, default)
            continue
        object.__setattr__(config, field, parsed)

    # Optional int overrides — applied only when the field is still at its
    # default (explicit constructor values win, matching the int/str tables).
    # Empty string or unset leaves the default; parse failures and values
    # below the ge=1 field constraint log a warning and are ignored.
    for field, env_key, default in _ENV_OPT_INT_OVERRIDES:
        if getattr(config, field) != default:
            continue
        env_val = _get_env(env_key)
        if env_val is None or env_val == "":
            continue
        try:
            parsed_int = int(env_val)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid %s=%r — treating as unset",
                env_key,
                env_val,
            )
            continue
        if parsed_int < 1:
            logger.warning(
                "%s=%s is below minimum 1; ignoring env override",
                env_key,
                parsed_int,
            )
            continue
        object.__setattr__(config, field, parsed_int)

    # Ratio float overrides ([0, 1] bounds) — parse failures are silently ignored
    # but out-of-bounds values emit a warning so operators know their config was rejected.
    for field, env_key, default in _ENV_FLOAT_RATIO_OVERRIDES:
        if getattr(config, field) == default:
            env_val = _get_env(env_key)
            if env_val is not None:
                try:
                    new_val = float(env_val)
                except ValueError:
                    continue
                in_bounds = True
                for constraint in HydraFlowConfig.model_fields[field].metadata:
                    ge = getattr(constraint, "ge", None)
                    le = getattr(constraint, "le", None)
                    if ge is not None and new_val < ge:
                        logger.warning(
                            "%s=%s is below minimum %s; ignoring env override",
                            env_key,
                            new_val,
                            ge,
                        )
                        in_bounds = False
                        break
                    if le is not None and new_val > le:
                        logger.warning(
                            "%s=%s is above maximum %s; ignoring env override",
                            env_key,
                            new_val,
                            le,
                        )
                        in_bounds = False
                        break
                if in_bounds:
                    object.__setattr__(config, field, new_val)

    # Cross-field validation: visual_fail_threshold must remain > visual_warn_threshold
    # after env overrides (the Pydantic field_validator only fires at model construction).
    # Strategy: revert only visual_fail_threshold first; if that still violates the
    # invariant (e.g. warn was also overridden to a value >= the fail default), revert
    # visual_warn_threshold too so we always land on a valid pair.
    if config.visual_fail_threshold <= config.visual_warn_threshold:
        _fail_default: float = HydraFlowConfig.model_fields[
            "visual_fail_threshold"
        ].default
        _warn_default: float = HydraFlowConfig.model_fields[
            "visual_warn_threshold"
        ].default
        logger.warning(
            "visual_fail_threshold (%.4f) is not greater than visual_warn_threshold (%.4f) "
            "after env overrides; reverting visual_fail_threshold to default (%.4f)",
            config.visual_fail_threshold,
            config.visual_warn_threshold,
            _fail_default,
        )
        object.__setattr__(config, "visual_fail_threshold", _fail_default)
        if config.visual_fail_threshold <= config.visual_warn_threshold:
            logger.warning(
                "visual_warn_threshold (%.4f) still >= fail default (%.4f); "
                "reverting visual_warn_threshold to default (%.4f) as well",
                config.visual_warn_threshold,
                _fail_default,
                _warn_default,
            )
            object.__setattr__(config, "visual_warn_threshold", _warn_default)

    # Data-driven env var overrides (bool fields)
    for field, env_key, default in _ENV_BOOL_OVERRIDES:
        if getattr(config, field) == default:
            env_val = _get_env(env_key)
            if env_val is not None:
                object.__setattr__(
                    config,
                    field,
                    env_val.lower() not in ("0", "false", "no"),
                )

    # Combo env vars: HYDRAFLOW_<STAGE>=tool:model
    #
    # Precedence (#10657): an explicitly supplied value — a constructor kwarg,
    # a config-file value, or a PATCH edit re-validated through
    # ``model_validate`` — beats the matching ``HYDRAFLOW_*`` env var, exactly
    # like every other ``_ENV_*_OVERRIDES`` table above. The combo loop was the
    # sole table that applied the env value unconditionally, so a PATCH edit to
    # a combo-covered model/tool field (``patch_config`` re-runs this loop) was
    # silently reverted to the env value. ``__pydantic_fields_set__`` is the
    # "was this explicitly supplied?" signal; it is snapshotted *before* the
    # loop so combo entries can't mask each other, and it stays authoritative
    # even though the loop adds to it as it applies env-only fields (#9717).
    explicit_before_combo = set(config.__pydantic_fields_set__)
    for env_key, tool_field, model_field in _ENV_COMBO_OVERRIDES:
        env_val = _get_env(env_key)
        if env_val is None:
            continue
        tool, model = _parse_combo(env_key, env_val)  # raises on malformed
        # "inherit" is only valid for fields whose Literal includes it;
        # Pydantic would reject otherwise — pre-empt with a clearer message.
        if tool == "inherit" and tool_field not in {"system_tool", "background_tool"}:
            msg = (
                f"{env_key}=inherit not allowed; {tool_field} requires an explicit tool"
            )
            raise ValueError(msg)
        if tool_field not in explicit_before_combo:
            object.__setattr__(config, tool_field, tool)
            # Register as explicitly-set: object.__setattr__ bypasses Pydantic's
            # fields-set tracking, so without this the group cascade in
            # _apply_profile_overrides treats the field as untouched and — when
            # the env value equals the field default — silently overwrites the
            # operator's per-role choice (#9717).
            config.__pydantic_fields_set__.add(tool_field)
        if (
            model and model_field not in explicit_before_combo
        ):  # empty only for "inherit"
            object.__setattr__(config, model_field, model)
            config.__pydantic_fields_set__.add(model_field)

    # Data-driven env var overrides (Literal-typed fields)
    for field, env_key in _ENV_LITERAL_OVERRIDES:
        field_info = HydraFlowConfig.model_fields[field]
        if getattr(config, field) == field_info.default:
            env_val = _get_env(env_key)
            if env_val is not None:
                allowed = get_args(field_info.annotation)
                if env_val in allowed:
                    object.__setattr__(config, field, env_val)
                    config.__pydantic_fields_set__.add(field)
                else:
                    logger.warning(
                        "Invalid %s=%r; expected one of %s",
                        env_key,
                        env_val,
                        allowed,
                    )

    # Data-driven env var overrides (StrEnum-typed fields)
    for field, env_key, enum_cls in _ENV_ENUM_OVERRIDES:
        field_info = HydraFlowConfig.model_fields[field]
        if getattr(config, field) == field_info.default:
            env_val = _get_env(env_key)
            if env_val is not None:
                try:
                    object.__setattr__(config, field, enum_cls(env_val))
                    config.__pydantic_fields_set__.add(field)
                except ValueError:
                    logger.warning(
                        "Invalid %s=%r; expected one of %s",
                        env_key,
                        env_val,
                        [member.value for member in enum_cls],
                    )

    # Backward-compat bridge: promote legacy HYDRAFLOW_DOCKER_ENABLED /
    # HYDRA_DOCKER_ENABLED to execution_mode="docker" when the canonical
    # HYDRAFLOW_EXECUTION_MODE env var was not explicitly set.
    if config.execution_mode == "host":
        _docker_enabled_raw = os.environ.get(
            "HYDRAFLOW_DOCKER_ENABLED"
        ) or os.environ.get("HYDRA_DOCKER_ENABLED")
        if _docker_enabled_raw is not None:
            _execution_mode_explicit = os.environ.get("HYDRAFLOW_EXECUTION_MODE")
            if _execution_mode_explicit is None and _docker_enabled_raw.lower() not in (
                "0",
                "false",
                "no",
            ):
                object.__setattr__(config, "execution_mode", "docker")
                logger.warning(
                    "HYDRAFLOW_DOCKER_ENABLED / HYDRA_DOCKER_ENABLED is deprecated; "
                    "use HYDRAFLOW_EXECUTION_MODE=docker instead."
                )

    # Lite plan labels (comma-separated list, special-case)
    env_lite_labels = os.environ.get("HYDRAFLOW_LITE_PLAN_LABELS")
    if env_lite_labels is not None and config.lite_plan_labels == [
        "bug",
        "typo",
        "docs",
    ]:
        parsed = [lbl.strip() for lbl in env_lite_labels.split(",") if lbl.strip()]
        if parsed:
            object.__setattr__(config, "lite_plan_labels", parsed)

    # Human-steering authorized users (comma-separated list, special-case)
    env_steering_users = os.environ.get("HYDRAFLOW_HUMAN_STEERING_AUTHORIZED_USERS")
    if env_steering_users is not None and config.human_steering_authorized_users == []:
        parsed = [u.strip() for u in env_steering_users.split(",") if u.strip()]
        if parsed:
            object.__setattr__(config, "human_steering_authorized_users", parsed)

    # Extra worktree-GC sweep roots (comma-separated list, special-case; #10698)
    env_gc_roots = os.environ.get("HYDRAFLOW_WORKTREE_GC_ROOTS")
    if env_gc_roots is not None and config.worktree_gc_roots == []:
        parsed = [r.strip() for r in env_gc_roots.split(",") if r.strip()]
        if parsed:
            object.__setattr__(config, "worktree_gc_roots", parsed)

    # Docker resource limit overrides (validated fields handled manually
    # because str/int overrides need format/bounds validation that
    # the data-driven tables don't provide)
    if config.docker_memory_limit == "4g":  # still at default
        env_mem = os.environ.get("HYDRAFLOW_DOCKER_MEMORY_LIMIT")
        if env_mem is not None:
            if not re.fullmatch(r"\d+[bkmg]", env_mem, re.IGNORECASE):
                msg = f"Invalid HYDRAFLOW_DOCKER_MEMORY_LIMIT '{env_mem}'; expected digits followed by b/k/m/g (e.g., '4g', '512m')"
                raise ValueError(msg)
            object.__setattr__(config, "docker_memory_limit", env_mem)

    if config.docker_tmp_size == "1g":  # still at default
        env_tmp = os.environ.get("HYDRAFLOW_DOCKER_TMP_SIZE")
        if env_tmp is not None:
            if not re.fullmatch(r"\d+[bkmg]", env_tmp, re.IGNORECASE):
                msg = f"Invalid HYDRAFLOW_DOCKER_TMP_SIZE '{env_tmp}'; expected digits followed by b/k/m/g (e.g., '1g', '512m')"
                raise ValueError(msg)
            object.__setattr__(config, "docker_tmp_size", env_tmp)

    if config.docker_pids_limit == 256:  # still at default
        env_pids = os.environ.get("HYDRAFLOW_DOCKER_PIDS_LIMIT")
        if env_pids is not None:
            try:
                pids_val = int(env_pids)
            except ValueError as exc:
                logger.warning(
                    "HYDRAFLOW_DOCKER_PIDS_LIMIT value '%s' is not an integer; keeping default %d (%s)",
                    env_pids,
                    config.docker_pids_limit,
                    exc,
                    exc_info=True,
                )
            else:
                if not (16 <= pids_val <= 4096):
                    msg = f"HYDRAFLOW_DOCKER_PIDS_LIMIT must be between 16 and 4096, got {pids_val}"
                    raise ValueError(msg)
                object.__setattr__(config, "docker_pids_limit", pids_val)

    # JSON-shaped overrides (spec §4.4 — managed repos)
    mr_raw = _get_env("HYDRAFLOW_MANAGED_REPOS")
    if mr_raw:
        try:
            decoded = json.loads(mr_raw)
            if isinstance(decoded, list):
                object.__setattr__(
                    config,
                    "managed_repos",
                    [ManagedRepo(**item) for item in decoded],
                )
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("Ignoring malformed HYDRAFLOW_MANAGED_REPOS: %s", exc)


def _validate_docker(config: HydraFlowConfig) -> None:
    """Validate Docker availability when execution_mode is 'docker'."""
    if config.execution_mode != "docker":
        return

    if not config.docker_image.strip():
        # No image configured → fall back to host execution; no Docker validation needed.
        return

    if shutil.which("docker") is None:
        msg = (
            "execution_mode is 'docker' but the 'docker' command was not found on PATH"
        )
        raise ValueError(msg)

    if bool(config.git_user_name) ^ bool(config.git_user_email):
        logger.warning(
            "Docker mode git identity is incomplete (name=%r email=%r); commits may fall back to host identity.",
            config.git_user_name,
            config.git_user_email,
        )
    elif not config.git_user_name and not config.git_user_email:
        logger.warning(
            "Docker mode git identity not configured; commits may use fallback host/global git identity "
            "(set HYDRAFLOW_GIT_USER_NAME and HYDRAFLOW_GIT_USER_EMAIL, e.g. in .env)."
        )


def _find_repo_root() -> Path:
    """Walk up from cwd and return the outermost git repo root.

    This intentionally favors the top-level repository when invoked from
    nested repos/worktrees under a parent repo.
    """
    current = Path.cwd().resolve()
    found: list[Path] = []
    while current != current.parent:
        if (current / ".git").exists():
            found.append(current)
        current = current.parent
    if found:
        return found[-1]
    return Path.cwd().resolve()


def _detect_repo_slug(repo_root: Path) -> str:
    """Extract ``owner/repo`` from the git remote origin URL.

    Falls back to an empty string if detection fails.
    """
    import subprocess  # noqa: PLC0415
    from urllib.parse import urlparse

    def _from_https(remote: str) -> str:
        parsed = urlparse(remote)
        host = (parsed.hostname or "").lower()
        if host != "github.com":
            return ""
        path = parsed.path.lstrip("/").removesuffix(".git")
        return path

    def _from_ssh(remote: str) -> str:
        # Example: git@github.com:owner/repo.git
        if "@" not in remote or ":" not in remote:
            return ""
        user_host, _, remainder = remote.partition(":")
        _, _, host = user_host.partition("@")
        if host.lower() != "github.com":
            return ""
        return remainder.lstrip("/").removesuffix(".git")

    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        url = result.stdout.strip()
        if not url:
            return ""
        if url.startswith("http://") or url.startswith("https://"):
            return _from_https(url)
        if url.startswith("git@"):
            return _from_ssh(url)
        return ""
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return ""


def load_config_file(path: Path | None) -> dict[str, Any]:
    """Load a JSON config file and return its contents as a dict.

    Returns an empty dict if the file is missing, unreadable, or invalid.
    """
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return {}
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_config_file(path: Path | None, values: dict[str, Any]) -> None:
    """Save config values to a JSON file, merging with existing contents.

    Uses atomic write (temp file + ``os.replace``) to prevent data loss from
    concurrent writes or crashes mid-write (TOCTOU race condition).
    """
    if path is None:
        return

    existing: dict[str, Any] = {}
    try:
        existing = json.loads(path.read_text())
        if not isinstance(existing, dict):
            logger.warning(
                "Config file %s contained non-dict JSON; starting fresh", path
            )
            existing = {}
    except FileNotFoundError:
        logger.debug("Config file %s not found; will create", path)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read config file %s: %s; starting fresh", path, exc)
    existing.update(values)
    try:
        file_util.atomic_write(path, json.dumps(existing, indent=2) + "\n")
    except OSError as exc:
        logger.warning("Failed to write config file %s: %s", path, exc)
