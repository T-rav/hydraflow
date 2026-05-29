"""Resolve per-branch required contexts and render GitHub ruleset JSON."""

from __future__ import annotations

from typing import Any

from scripts.gates.contract import Contract

_REF = {"main": "~DEFAULT_BRANCH", "staging": "refs/heads/staging"}


def resolve_contexts(contract: Contract, branch: str) -> list[str]:
    """Active gate contexts required on ``branch``, in contract order."""
    return [
        g.name
        for g in contract.gates
        if g.status == "active" and branch in g.required_on
    ]


def render_ruleset(contract: Contract, branch: str) -> dict[str, Any]:
    """Render the full GitHub ruleset payload for ``branch`` from the contract."""
    env = contract.branches[branch]
    rules: list[dict[str, Any]] = [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {
            "type": "pull_request",
            "parameters": {
                "required_approving_review_count": env.required_approving_review_count,
                "dismiss_stale_reviews_on_push": False,
                "require_code_owner_review": False,
                "require_last_push_approval": False,
                "required_review_thread_resolution": False,
                "allowed_merge_methods": env.allowed_merge_methods,
            },
        },
        {
            "type": "required_status_checks",
            "parameters": {
                "do_not_enforce_on_create": False,
                "strict_required_status_checks_policy": False,
                "required_status_checks": [
                    {"context": c} for c in resolve_contexts(contract, branch)
                ],
            },
        },
    ]
    if env.code_quality_severity is not None:
        rules.append(
            {
                "type": "code_quality",
                "parameters": {"severity": env.code_quality_severity},
            }
        )
    if env.code_scanning:
        rules.append(
            {
                "type": "code_scanning",
                "parameters": {
                    "code_scanning_tools": [
                        {
                            "tool": t.tool,
                            "security_alerts_threshold": t.security_alerts_threshold,
                            "alerts_threshold": t.alerts_threshold,
                        }
                        for t in env.code_scanning
                    ]
                },
            }
        )
    name = "main protect" if branch == "main" else f"{branch} protect"
    return {
        "name": name,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"exclude": [], "include": [_REF[branch]]}},
        "rules": rules,
    }
