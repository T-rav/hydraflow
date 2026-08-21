"""Regression #11512: [branch-protection] ruleset drift on T-rav/hydraflow.

Both live rulesets (``main protect`` and ``staging protect``) carry
``pull_request.parameters.require_extra_approval_for_unattributed_changes:
true`` (GitHub's additional-approval-for-unattributed-changes review
hardening), but the declarative contract cannot express it: ``BranchEnvelope``
(``scripts/gates/contract.py``) has no such field and ``render_ruleset``
(``scripts/gates/resolve.py``) hardcodes a parameter set that never emits it.
The generated canonical JSONs therefore lack the key while live reads ``true``,
so ``diff_ruleset`` (``src/branch_protection_audit.py``) fires DRIFT on both
rulesets and ``BranchProtectionAuditorLoop`` files #11512. The prescribed
remediation cannot converge: ``make gen-gates`` is a no-op while the contract
lacks the field (artifacts are CI-enforced in sync), and
``setup_branch_protection.py --apply`` PUTs the flag-less canonical — either
stripping the live hardening or leaving the drift standing.

This is the CI-Gate precedent (the ``ci-aggregate`` comment in gates.toml): a
live protection absent from the contract must be *declared* in it, not
stripped from live.

Pins (RED until the contract declares the flag and the artifacts are
regenerated):

* ``diff_ruleset`` between the shipped canonical and the exact live shape from
  the issue (canonical + GitHub's ``id`` + the flag) must be clean for both
  rulesets — the reported drift must not exist once the contract is the source
  of truth;
* ``audit_repo`` over that live snapshot must report clean — the end-to-end
  shape the caretaker loop audits;
* the committed canonical rulesets must declare
  ``require_extra_approval_for_unattributed_changes: true`` in the
  ``pull_request`` rule — guards against "fixing" the audit by stripping the
  live flag instead of declaring it (the regression class the CI-Gate
  comment warns about).

Counter-pins (green today and must stay green): the live fixture really
carries the flag, and ``diff_ruleset`` still fires on an unrelated genuine
drift, so the clean assertions above can never pass vacuously.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from branch_protection_audit import audit_repo, diff_ruleset, load_canonical

CANONICAL_DIR = Path("docs/standards/branch_protection")
_FLAG = "require_extra_approval_for_unattributed_changes"


def _live_from_issue(canonical_cfg: dict[str, Any]) -> dict[str, Any]:
    """The live ruleset shape #11512 reported: canonical + ``id`` + the flag.

    The issue's live dumps differ from canonical by exactly one field —
    ``pull_request.parameters.require_extra_approval_for_unattributed_changes``
    is ``true`` live and absent canonical — plus GitHub's ``id``. Deriving the
    fixture from the committed canonical (rather than transcribing the
    snapshot) keeps the pin pointed at that single delta as the canonical
    evolves.
    """
    live = json.loads(json.dumps(canonical_cfg))  # deep copy
    live["id"] = 8082
    pr = next(r for r in live["rules"] if r["type"] == "pull_request")
    pr["parameters"][_FLAG] = True
    return live


def test_diff_ruleset_clean_against_issue_live_snapshot() -> None:
    canonical = load_canonical(CANONICAL_DIR)
    for name, cfg in canonical.items():
        live = _live_from_issue(cfg)
        # Fixture liveness: the pin must be testing the flag, not a fixture
        # that lost it.
        pr = next(r for r in live["rules"] if r["type"] == "pull_request")
        assert pr["parameters"][_FLAG] is True
        diffs = diff_ruleset(cfg, live)
        assert diffs == [], f"[{name}] " + "\n".join(diffs)


def test_audit_repo_clean_against_issue_live_snapshot() -> None:
    canonical = load_canonical(CANONICAL_DIR)

    def fetch_rulesets(_repo: str) -> dict[str, Any]:
        return {name: _live_from_issue(cfg) for name, cfg in canonical.items()}

    report = audit_repo(
        "T-rav/hydraflow",
        CANONICAL_DIR,
        fetch_rulesets=fetch_rulesets,
        fetch_legacy_protection=lambda _repo, _branch: None,
    )
    assert report.clean, report.drifts


def test_canonical_rulesets_declare_unattributed_change_approval() -> None:
    canonical = load_canonical(CANONICAL_DIR)
    for name in ("main protect", "staging protect"):
        pr = next(r for r in canonical[name]["rules"] if r["type"] == "pull_request")
        assert pr["parameters"].get(_FLAG) is True, (
            f"{name}: canonical does not declare {_FLAG}, but the live ruleset "
            "carries true — the audit reports permanent drift (#11512)"
        )


def test_diff_ruleset_still_detects_other_genuine_drift() -> None:
    """Counter-pin: the clean assertions above must not pass vacuously."""
    cfg = json.loads((CANONICAL_DIR / "main_ruleset.json").read_text())
    live = _live_from_issue(cfg)
    pr = next(r for r in live["rules"] if r["type"] == "pull_request")
    pr["parameters"]["allowed_merge_methods"] = ["squash"]
    assert diff_ruleset(cfg, live) != []
