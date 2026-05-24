"""Canonical backend catalog for background worker display and intervals."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from config import HydraFlowConfig


class WorkerDisplayDef(NamedTuple):
    """Human-facing metadata for a worker row in the system UI."""

    name: str
    label: str
    description: str


WORKER_DISPLAY_DEFS: tuple[WorkerDisplayDef, ...] = (
    WorkerDisplayDef(
        "triage",
        "Triage",
        "Classifies freshly discovered issues and routes them into the pipeline.",
    ),
    WorkerDisplayDef(
        "plan",
        "Plan",
        "Builds implementation plans for triaged issues that are ready to execute.",
    ),
    WorkerDisplayDef(
        "implement",
        "Implement",
        "Runs coding agents to implement planned issues and open pull requests.",
    ),
    WorkerDisplayDef(
        "review",
        "Review",
        "Reviews PRs, applies fixes, and merges approved work when checks pass.",
    ),
    WorkerDisplayDef(
        "memory_sync",
        "Memory Manager",
        "Ingests memory and transcript issues into durable learnings and proposals.",
    ),
    WorkerDisplayDef(
        "retrospective",
        "Retrospective",
        "Captures post-merge outcomes and identifies recurring delivery patterns.",
    ),
    WorkerDisplayDef(
        "review_insights",
        "Review Insights",
        "Aggregates recurring review feedback into improvement opportunities.",
    ),
    WorkerDisplayDef(
        "pipeline_poller",
        "Pipeline Poller",
        "Refreshes live pipeline snapshots for dashboard queue/status rendering.",
    ),
    WorkerDisplayDef(
        "pr_unsticker",
        "PR Unsticker",
        "Requeues stalled HITL PRs by validating requirements and reopening flow.",
    ),
    WorkerDisplayDef(
        "report_issue",
        "Report Issue",
        "Processes queued bug reports into GitHub issues via the configured agent.",
    ),
    WorkerDisplayDef(
        "epic_monitor",
        "Epic Monitor",
        "Detects stale epics and refreshes dashboard progress rollups.",
    ),
    WorkerDisplayDef(
        "adr_reviewer",
        "ADR Reviewer",
        "Reviews proposed ADRs via a 3-judge council and routes to accept, reject, or escalate.",
    ),
    WorkerDisplayDef(
        "merge_state_watcher",
        "Merge State Watcher",
        "Auto-rebases or escalates PRs whose GitHub mergeability is conflicting.",
    ),
    WorkerDisplayDef(
        "workspace_gc",
        "Workspace GC",
        "Garbage-collects stale workspaces and orphaned branches.",
    ),
    WorkerDisplayDef(
        "runs_gc",
        "Runs GC",
        "Purges expired pipeline run artifacts and keeps the runs store bounded.",
    ),
    WorkerDisplayDef(
        "health_monitor",
        "Health Monitor",
        "Monitors pipeline health, auto-tuning signals, and recurring operational patterns.",
    ),
    WorkerDisplayDef(
        "dependabot_merge",
        "Dependabot Merge",
        "Auto-merges dependency update PRs from configured bots after CI passes.",
    ),
    WorkerDisplayDef(
        "staging_promotion",
        "Staging Promotion",
        "Cuts release-candidate snapshots from staging and promotes green candidates.",
    ),
    WorkerDisplayDef(
        "stale_issue",
        "Stale General Issue Cleanup",
        "Auto-closes stale general issues using configurable staleness rules.",
    ),
    WorkerDisplayDef(
        "github_cache",
        "GitHub Cache",
        "Single-poller cache for GitHub data shared by dashboard and worker consumers.",
    ),
    WorkerDisplayDef(
        "sentry_ingest",
        "Sentry Ingest",
        "Polls Sentry for unresolved errors and files pipeline issues.",
    ),
    WorkerDisplayDef(
        "stale_issue_gc",
        "Stale HITL Issue GC",
        "Auto-closes stale HITL escalation issues after the configured grace period.",
    ),
    WorkerDisplayDef(
        "ci_monitor",
        "CI Monitor",
        "Detects failing CI on main and files or auto-closes issues.",
    ),
    WorkerDisplayDef(
        "security_patch",
        "Security Patch",
        "Polls Dependabot alerts and files issues for fixable vulnerabilities.",
    ),
    WorkerDisplayDef(
        "code_grooming",
        "Code Grooming",
        "Runs periodic code-quality audits and files issues for important findings.",
    ),
    WorkerDisplayDef(
        "repo_wiki",
        "Repo Wiki",
        "Maintains per-repo knowledge wikis compiled from delivery cycles.",
    ),
    WorkerDisplayDef(
        "diagnostic",
        "Diagnostic Agent",
        "Analyzes escalated issues and attempts targeted fixes before HITL.",
    ),
    WorkerDisplayDef(
        "corpus_learning",
        "Corpus Learning",
        "Synthesizes adversarial cases from skill/discover/shape escape signals and opens corpus-update PRs.",
    ),
    WorkerDisplayDef(
        "contract_refresh",
        "Contract Refresh",
        "Re-records fake-adapter cassettes and opens refresh PRs when committed cassettes drift from live behavior.",
    ),
    WorkerDisplayDef(
        "staging_bisect",
        "Staging Bisect",
        "Bisects RC red between last-green and current-red, opens auto-revert PRs, and watches the next RC.",
    ),
    WorkerDisplayDef(
        "principles_audit",
        "Principles Audit",
        "Weekly ADR-0044 audit of HydraFlow-self plus managed repos; blocks onboarding on P1-P5 fails.",
    ),
    WorkerDisplayDef(
        "flake_tracker",
        "Flake Tracker",
        "Detects persistently flaky tests across recent RC runs and files flake-tracker issues.",
    ),
    WorkerDisplayDef(
        "skill_prompt_eval",
        "Skill Prompt Eval",
        "Weekly adversarial-corpus gate against built-in skills; flags PASS-to-FAIL regressions.",
    ),
    WorkerDisplayDef(
        "fake_coverage_auditor",
        "Fake Coverage Auditor",
        "Flags fake-adapter methods without cassettes and scenario helpers nobody calls.",
    ),
    WorkerDisplayDef(
        "adr_touchpoint_auditor",
        "ADR Touchpoint Auditor",
        "Scans merged PRs for code changes that drift from cited ADR touchpoints.",
    ),
    WorkerDisplayDef(
        "memory_backlog",
        "Memory Backlog",
        "Files hydraflow-find issues for pending memory feedback entries.",
    ),
    WorkerDisplayDef(
        "rc_budget",
        "RC Budget",
        "Detects RC wall-clock bloat via rolling-median and spike signals across recent runs.",
    ),
    WorkerDisplayDef(
        "wiki_rot_detector",
        "Wiki Rot Detector",
        "Scans per-repo wikis for citations whose source code has moved or vanished.",
    ),
    WorkerDisplayDef(
        "trust_fleet_sanity",
        "Trust Fleet Sanity",
        "Meta-observer watching trust loops for stalls, escalation spam, errors, and cost spikes.",
    ),
    WorkerDisplayDef(
        "label_drift_watcher",
        "Label Drift Watcher",
        "Reconciles issue and PR label drift across linked pipeline entities.",
    ),
    WorkerDisplayDef(
        "auto_agent_preflight",
        "Auto-Agent Pre-Flight",
        "Attempts autonomous resolution of HITL escalations before surfacing them to humans.",
    ),
    WorkerDisplayDef(
        "sandbox_failure_fixer",
        "Sandbox Failure Fixer",
        "Dispatches an auto-agent to repair sandbox promotion failures.",
    ),
    WorkerDisplayDef(
        "diagram_loop",
        "Diagram Loop",
        "Regenerates architecture diagrams and opens drift PRs when generated docs change.",
    ),
    WorkerDisplayDef(
        "pricing_refresh",
        "Pricing Refresh",
        "Daily upstream-pricing refresh caretaker; opens human-reviewed PRs on pricing drift.",
    ),
    WorkerDisplayDef(
        "cost_budget_watcher",
        "Cost Budget Watcher",
        "Polls rolling-24h LLM spend and disables caretaker loops when the daily cap is exceeded.",
    ),
    WorkerDisplayDef(
        "term_proposer",
        "Term Proposer",
        "Proposes missing ubiquitous-language terms from load-bearing code signals.",
    ),
    WorkerDisplayDef(
        "term_pruner",
        "Term Pruner",
        "Deprecates accepted ubiquitous-language terms whose code anchors no longer resolve.",
    ),
    WorkerDisplayDef(
        "edge_proposer",
        "Edge Proposer",
        "Proposes relationship edges between existing ubiquitous-language terms.",
    ),
    WorkerDisplayDef(
        "entry_evidence",
        "Entry Evidence",
        "Links wiki entries to ubiquitous-language terms so Atlas can render evidence leaves.",
    ),
    WorkerDisplayDef(
        "live_corpus_replay",
        "Live Corpus Replay",
        "Replays live corpus samples against fake-adapter shapes to catch drift.",
    ),
)

CONFIG_INTERVAL_ATTRS: dict[str, str] = {
    "memory_sync": "memory_sync_interval",
    "pr_unsticker": "pr_unstick_interval",
    "report_issue": "report_issue_interval",
    "epic_monitor": "epic_monitor_interval",
    "workspace_gc": "workspace_gc_interval",
    "runs_gc": "runs_gc_interval",
    "adr_reviewer": "adr_review_interval",
    "health_monitor": "health_monitor_interval",
    "dependabot_merge": "dependabot_merge_interval",
    "staging_promotion": "staging_promotion_interval",
    "staging_bisect": "staging_bisect_interval",
    "stale_issue": "stale_issue_interval",
    "github_cache": "data_poll_interval",
    "sentry_ingest": "sentry_poll_interval",
    "stale_issue_gc": "stale_issue_gc_interval",
    "ci_monitor": "ci_monitor_interval",
    "security_patch": "security_patch_interval",
    "code_grooming": "code_grooming_interval",
    "repo_wiki": "repo_wiki_interval",
    "diagnostic": "diagnostic_interval",
    "retrospective": "retrospective_interval",
    "principles_audit": "principles_audit_interval",
    "flake_tracker": "flake_tracker_interval",
    "skill_prompt_eval": "skill_prompt_eval_interval",
    "fake_coverage_auditor": "fake_coverage_auditor_interval",
    "adr_touchpoint_auditor": "adr_touchpoint_auditor_interval",
    "memory_backlog": "memory_backlog_interval_seconds",
    "rc_budget": "rc_budget_interval",
    "wiki_rot_detector": "wiki_rot_detector_interval",
    "trust_fleet_sanity": "trust_fleet_sanity_interval",
    "label_drift_watcher": "label_drift_watcher_interval",
    "contract_refresh": "contract_refresh_interval",
    "corpus_learning": "corpus_learning_interval",
    "auto_agent_preflight": "auto_agent_preflight_interval",
    "sandbox_failure_fixer": "sandbox_failure_fixer_interval",
    "term_proposer": "term_proposer_interval",
    "term_pruner": "term_pruner_interval",
    "edge_proposer": "edge_proposer_interval",
    "entry_evidence": "entry_evidence_interval",
    "live_corpus_replay": "live_corpus_replay_interval",
}

STATIC_INTERVAL_DEFAULTS: dict[str, int] = {
    "pipeline_poller": 5,
    "diagram_loop": 14_400,
    "pricing_refresh": 86_400,
    "cost_budget_watcher": 300,
}


def default_worker_interval(config: HydraFlowConfig, name: str) -> int | None:
    """Return the configured/default interval for a known worker."""
    if name in STATIC_INTERVAL_DEFAULTS:
        return STATIC_INTERVAL_DEFAULTS[name]
    attr = CONFIG_INTERVAL_ATTRS.get(name)
    if attr is None:
        return None
    value = getattr(config, attr, None)
    return int(value) if value is not None else None
