"""Audit live GitHub branch protection against the canonical rulesets.

Runtime analog of ``scripts/setup_branch_protection.py --audit``, factored out
so both the apply-er CLI and ``BranchProtectionAuditorLoop`` (ADR-0082) share
one drift-detection implementation. The fetch of live rulesets is injectable so
the loop and its tests do not depend on the network.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_DEFAULTS_TO_STRIP: dict[str, Any] = {
    "required_reviewers": [],
    "strict_required_status_checks_policy": False,
    "required_review_thread_resolution": False,
    "dismiss_stale_reviews_on_push": False,
    "require_code_owner_review": False,
    "require_last_push_approval": False,
    "do_not_enforce_on_create": False,
}
_PICK = {"name", "target", "enforcement", "conditions", "rules"}


def _normalize(node: Any) -> Any:
    """Strip None/empty/defaulted fields so canonical and live render alike."""
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for k, v in sorted(node.items()):
            if v is None or v in ([], {}):
                continue
            if k in _DEFAULTS_TO_STRIP and v == _DEFAULTS_TO_STRIP[k]:
                continue
            out[k] = _normalize(v)
        return out
    if isinstance(node, list):
        items = [_normalize(item) for item in node]
        # Sort required-status-check context dicts so GitHub's ordering (web UI
        # edits, API order) does not read as drift against the canonical order.
        if items and all(isinstance(i, dict) and set(i) == {"context"} for i in items):
            return sorted(items, key=lambda i: i["context"])
        return items
    return node


def _sort_rules(node: dict[str, Any]) -> dict[str, Any]:
    if isinstance(node.get("rules"), list):
        node["rules"] = sorted(node["rules"], key=lambda r: r.get("type", ""))
    return node


def diff_ruleset(canonical: dict[str, Any], live: dict[str, Any]) -> list[str]:
    """Human-readable drift lines for one ruleset; empty list means clean."""
    canon = _sort_rules({k: _normalize(v) for k, v in canonical.items() if k in _PICK})
    live_norm = _sort_rules({k: _normalize(v) for k, v in live.items() if k in _PICK})
    if canon == live_norm:
        return []
    return [
        "DRIFT: canonical and live differ.",
        f"  canonical: {json.dumps(canon, indent=2)}",
        f"  live:      {json.dumps(live_norm, indent=2)}",
    ]


def load_canonical(canonical_dir: Path) -> dict[str, dict[str, Any]]:
    """The canonical rulesets keyed by ruleset name."""
    main_cfg = json.loads((canonical_dir / "main_ruleset.json").read_text())
    staging_cfg = json.loads((canonical_dir / "staging_ruleset.json").read_text())
    return {"main protect": main_cfg, "staging protect": staging_cfg}


@dataclass(frozen=True)
class AuditReport:
    repo: str
    drifts: list[str]

    @property
    def clean(self) -> bool:
        return not self.drifts


_RULESET_NAME_FOR_BRANCH = {"main": "main protect", "staging": "staging protect"}


def ruleset_required_contexts(ruleset: dict[str, Any] | None) -> set[str]:
    """Required-status-check context names declared in one ruleset payload.

    Works on both a canonical (gates.toml-generated) ruleset and a live
    GitHub ruleset — same ``rules`` shape either way.
    """
    if not ruleset:
        return set()
    contexts: set[str] = set()
    for rule in ruleset.get("rules") or []:
        if rule.get("type") != "required_status_checks":
            continue
        checks = (rule.get("parameters") or {}).get("required_status_checks") or []
        contexts.update(c["context"] for c in checks if c.get("context"))
    return contexts


def legacy_protection_required_contexts(protection: dict[str, Any] | None) -> set[str]:
    """Required-status-check contexts from the classic branch-protection API.

    GitHub's classic ``/repos/{repo}/branches/{branch}/protection`` endpoint
    returns both the deprecated ``contexts`` (plain strings) and the newer
    ``checks`` (``{"context": ..., "app_id": ...}`` objects) under
    ``required_status_checks``; union both so neither shape is silently
    missed. ``protection`` is ``None`` when the branch has no classic rule at
    all (GitHub 404s the endpoint in that case — a clean state, not drift).
    """
    if not protection:
        return set()
    rsc = protection.get("required_status_checks") or {}
    contexts = {c for c in (rsc.get("contexts") or []) if c}
    contexts.update(c["context"] for c in (rsc.get("checks") or []) if c.get("context"))
    return contexts


def undeclared_legacy_contexts(
    canonical_ruleset: dict[str, Any] | None,
    live_ruleset: dict[str, Any] | None,
    legacy_protection: dict[str, Any] | None,
) -> list[str]:
    """Live-required contexts not declared by the canonical (contract) ruleset.

    ``canonical_ruleset`` is the ``gates.toml``-generated ruleset for one
    branch — its required-status-check set IS
    ``scripts.gates.resolve.resolve_contexts(contract, branch)``, materialized
    to disk by ``scripts/gen_gates.py`` and kept in sync by
    ``make gen-gates-check``. The live-*effective* set is the live ruleset's
    required checks UNION'd with the classic branch-protection API's required
    checks: GitHub enforces both independently, so a legacy branch-protection
    rule can require a context the contract never declared for this branch
    without a single ruleset field ever drifting — the class of drift
    ``diff_ruleset`` cannot see because it only compares ruleset-to-ruleset.
    Returns the sorted list of such undeclared contexts (empty means clean).
    """
    declared = ruleset_required_contexts(canonical_ruleset)
    live = ruleset_required_contexts(
        live_ruleset
    ) | legacy_protection_required_contexts(legacy_protection)
    return sorted(live - declared)


def audit_repo(
    repo: str,
    canonical_dir: Path,
    *,
    fetch_rulesets: Callable[[str], dict[str, dict[str, Any]]],
    fetch_legacy_protection: Callable[[str, str], dict[str, Any] | None],
) -> AuditReport:
    """Compare live branch protection to the canonical contract; collect drift.

    Two independent drift classes:

    1. **Ruleset drift** — a live ruleset's fields (merge methods, review
       count, required checks, code-scanning, ...) diverge from the
       ``gates.toml``-generated canonical ruleset JSON.
    2. **Undeclared legacy-layer drift** — GitHub's classic
       ``branches/{branch}/protection`` API requires a status-check context
       the canonical ruleset never declared for that branch (an undeclared
       legacy branch-protection layer stacking extra required checks on top
       of the declarative contract). Ruleset drift (1) cannot see this: the
       ruleset itself may match canonical exactly while the *effective*
       enforced set is larger, because GitHub enforces rulesets and classic
       protection independently.

    The ``setup_branch_protection.py`` CLI's ``_audit`` additionally checks
    ``allow_auto_merge`` and the presence of the ``staging`` branch; those are
    setup concerns the CLI reconciles on ``--apply`` and are intentionally
    outside this audit.
    """
    canonical = load_canonical(canonical_dir)
    live = fetch_rulesets(repo)
    drifts: list[str] = []
    for name, cfg in canonical.items():
        if name not in live:
            drifts.append(f"ruleset {name!r} is missing on the live repo")
            continue
        drifts.extend(f"[{name}] {line}" for line in diff_ruleset(cfg, live[name]))

    for branch, ruleset_name in _RULESET_NAME_FOR_BRANCH.items():
        if ruleset_name not in canonical:
            continue
        undeclared = undeclared_legacy_contexts(
            canonical[ruleset_name],
            live.get(ruleset_name),
            fetch_legacy_protection(repo, branch),
        )
        if undeclared:
            ctxs = ", ".join(undeclared)
            drifts.append(
                f"[{branch}] undeclared legacy branch-protection context(s) "
                f"required live but not in the declarative contract: {ctxs}"
            )
    return AuditReport(repo=repo, drifts=drifts)


def _run_gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, check=True)
    return result.stdout


def gh_fetch_rulesets(
    repo: str, *, gh: Callable[..., str] = _run_gh
) -> dict[str, dict[str, Any]]:
    """Live rulesets for ``repo`` (owner/name), keyed by name, via the gh CLI."""
    listing = json.loads(gh("api", f"/repos/{repo}/rulesets"))
    out: dict[str, dict[str, Any]] = {}
    for entry in listing:
        full = json.loads(gh("api", f"/repos/{repo}/rulesets/{entry['id']}"))
        out[entry["name"]] = full
    return out


def gh_fetch_legacy_protection(
    repo: str, branch: str, *, gh: Callable[..., str] = _run_gh
) -> dict[str, Any] | None:
    """Live classic branch-protection config for one branch, or ``None``.

    GitHub 404s ``/repos/{repo}/branches/{branch}/protection`` when the
    branch has no classic rule at all (the common case on a rulesets-only
    repo) — that is a clean state, not an error, so it maps to ``None``
    rather than raising.
    """
    try:
        body = gh("api", f"/repos/{repo}/branches/{branch}/protection")
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or ""
        if "HTTP 404" in stderr or "Branch not protected" in stderr:
            return None
        raise
    return json.loads(body)
