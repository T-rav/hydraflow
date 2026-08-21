"""Regression for #11512: a live ruleset carrying GitHub's newer
``require_extra_approval_for_unattributed_changes`` parameter must not read as
drift against the canonical rulesets.

GitHub started returning the field on every ``pull_request`` rule; the
canonical contract did not declare it, so ``BranchProtectionAuditorLoop`` filed
a standing drift issue although nothing an operator set had changed. The
contract now declares the field (default ``true``, GitHub's own default) and
the renderer emits it.
"""

from __future__ import annotations

import json
from pathlib import Path

from branch_protection_audit import diff_ruleset

_ROOT = Path(__file__).resolve().parents[2]
_CANON = _ROOT / "docs" / "standards" / "branch_protection"


def _live_shape(canonical: dict) -> dict:
    """What GitHub returns today: the canonical rules plus the new field set to true."""
    live = json.loads(json.dumps(canonical))
    for rule in live["rules"]:
        if rule["type"] == "pull_request":
            rule["parameters"]["require_extra_approval_for_unattributed_changes"] = True
    return live


def test_canonical_rulesets_declare_the_unattributed_changes_field() -> None:
    for name in ("main_ruleset.json", "staging_ruleset.json"):
        ruleset = json.loads((_CANON / name).read_text())
        pr_rule = next(r for r in ruleset["rules"] if r["type"] == "pull_request")
        assert (
            pr_rule["parameters"]["require_extra_approval_for_unattributed_changes"]
            is True
        )


def test_live_ruleset_with_the_field_is_not_drift() -> None:
    for name in ("main_ruleset.json", "staging_ruleset.json"):
        canonical = json.loads((_CANON / name).read_text())
        assert diff_ruleset(canonical, _live_shape(canonical)) == []
