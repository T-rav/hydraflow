# tests/test_loop_fitness_completeness.py
"""Ratchet: every BaseBackgroundLoop subclass declares its own loop_fitness.

Mirrors test_loop_kill_switch_completeness.py. A loop that does not override
loop_fitness inherits the HOUSEKEEPING default silently; for NEW loops that is
a procedural miss (the author skipped declaring a real objective). New loops
are therefore NOT grandfathered and must define loop_fitness. The
_GRANDFATHERED set holds pre-existing loops awaiting migration and should only
shrink. See docs/superpowers/specs/2026-06-30-loop-fitness-scorecard-design.md.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

_CLASS_RE = re.compile(r"class\s+(\w+)\s*\(.*BaseBackgroundLoop.*\)")

# Pre-existing loops awaiting real fitness. Populate from Step 3. SHRINKS only.
_GRANDFATHERED: frozenset[str] = frozenset(
    {
        "adr_reviewer_loop",
        "adr_touchpoint_auditor_loop",
        "auto_agent_preflight_loop",
        "branch_protection_auditor_loop",
        "ci_monitor_loop",
        "contract_refresh_loop",
        "corpus_learning_loop",
        "cost_budget_watcher_loop",
        "dependabot_merge_loop",
        "diagnostic_loop",
        "diagram_loop",
        "edge_proposer_loop",
        "entry_evidence_loop",
        "epic_monitor_loop",
        "epic_sweeper_loop",
        "fake_coverage_auditor_loop",
        "flake_tracker_loop",
        "gate_activator_loop",
        "github_cache_loop",
        "health_monitor_loop",
        "label_drift_watcher_loop",
        "live_corpus_replay_loop",
        "log_ingest_loop",
        "memory_backlog_loop",
        "merge_state_watcher_loop",
        "pr_unsticker_loop",
        "pricing_refresh_loop",
        "principles_audit_loop",
        "rc_budget_loop",
        "repo_wiki_loop",
        "report_issue_loop",
        "retrospective_loop",
        "runs_gc_loop",
        "sandbox_failure_fixer_loop",
        "security_patch_loop",
        "sentry_loop",
        "skill_prompt_eval_loop",
        "staging_bisect_loop",
        "staging_promotion_loop",
        "stale_issue_gc_loop",
        "stale_issue_loop",
        "term_proposer_loop",
        "term_pruner_loop",
        "triage_retry_loop",
        "trust_fleet_sanity_loop",
        "wiki_rot_detector_loop",
        "workspace_gc_loop",
    }
)


def _loops_missing_fitness() -> list[str]:
    missing: list[str] = []
    for path in sorted(SRC.glob("*_loop.py")):
        text = path.read_text()
        if not _CLASS_RE.search(text):
            continue
        tree = ast.parse(text)
        loop_classes = [
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and any(
                base_id == "BaseBackgroundLoop"
                for base_id in (
                    getattr(b, "id", None) or getattr(b, "attr", None)
                    for b in node.bases
                )
            )
        ]
        for cls in loop_classes:
            has_fitness = any(
                isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef)
                and n.name == "loop_fitness"
                for n in cls.body
            )
            if not has_fitness:
                missing.append(path.stem)
    return [m for m in missing if m not in _GRANDFATHERED]


def test_every_loop_declares_fitness() -> None:
    missing = _loops_missing_fitness()
    assert not missing, (
        "Loops missing an explicit loop_fitness override (they silently "
        f"inherit HOUSEKEEPING): {sorted(set(missing))}. Add a loop_fitness "
        "method (return SCORED via a helper, or HOUSEKEEPING explicitly). New "
        "loops must NOT be added to _GRANDFATHERED."
    )
