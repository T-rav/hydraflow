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
        return [_normalize(item) for item in node]
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


def audit_repo(
    repo: str,
    canonical_dir: Path,
    *,
    fetch_rulesets: Callable[[str], dict[str, dict[str, Any]]],
) -> AuditReport:
    """Compare each canonical ruleset to live; collect human-readable drift."""
    canonical = load_canonical(canonical_dir)
    live = fetch_rulesets(repo)
    drifts: list[str] = []
    for name, cfg in canonical.items():
        if name not in live:
            drifts.append(f"ruleset {name!r} is missing on the live repo")
            continue
        drifts.extend(f"[{name}] {line}" for line in diff_ruleset(cfg, live[name]))
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
