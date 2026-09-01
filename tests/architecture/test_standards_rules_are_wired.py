"""A standard's normative rules must name the check that catches a violation.

Every standard already declares `enforced_by`. That declaration says a file
exists; it does not say the file checks the RULE. Both of these declare
identically:

- ``testing``'s MockWorld ratchet asks the live tree "is every loop driven by a
  scenario?" and reddens when one is not;
- ``factory_operation``'s drift guard asks its own README "do these two tables
  partition the standards directory?" — a documentation-consistency check that
  would stay green while the factory violated every word of the prose.

Both kinds are worth having. Being unable to tell them apart is not. The
``ports-and-loops`` README states "Must satisfy the Protocol structurally" and
its enforcer checks that a registry TABLE lists the live ports — real, but
about listing. Nothing objected while ~60 tests hand-rolled a bare `MagicMock`
where a Port belonged, and adding one async method to a Protocol broke all of
them at once (#11908).

"Does enforcer X check rule Y" is not statically decidable, so this gate does
what `guard_enumeration_registry.detects_drop` and the producer-probe gate's
`UNPROBED_BASELINE` already do here: make the mapping DECLARED, verify the
declarations resolve, and ratchet the unmapped remainder shrink-only.

Schema, in `docs/standards/<id>/standard.yaml`::

    rules:
      - id: fake-satisfies-protocol
        claim: Every Port's Fake satisfies the Protocol structurally
        enforced_by: tests/test_mockworld_fakes_conformance.py::test_fake_signatures_match_port
    unenforced:
      - id: tests-use-the-fake-not-a-bare-mock
        claim: A test standing in for a Port uses its Fake, not a bare MagicMock
        why: No check exists yet; ~60 sites would need migrating first (#11908).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
STANDARDS = REPO_ROOT / "docs" / "standards"

#: Standards with no `rules:` block yet. SHRINK-ONLY — wire one and lower it.
#: Never raise it: a new standard ships its rules mapped, or it is not ready.
UNWIRED_STANDARDS_BASELINE = 0

#: Declared-but-unenforced rules across all standards. SHRINK-ONLY.
UNENFORCED_RULES_BASELINE = 3


def _standards() -> list[tuple[str, dict[str, Any]]]:
    out = []
    for path in sorted(STANDARDS.glob("*/standard.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        out.append((path.parent.name, data))
    return out


def _node_resolves(spec: str) -> bool:
    """Does ``path::node`` name a real test function or class in the tree?"""
    path_part, _, node = str(spec).partition("::")
    path = REPO_ROOT / path_part
    if not path.exists():
        return False
    if not node:
        return True
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return False
    names = {
        n.name
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    }
    return all(part in names for part in node.split("::"))


ALL = _standards()
WITH_RULES = [(n, d) for n, d in ALL if d.get("rules")]


class TestTheScanHasASubject:
    def test_standards_are_discovered(self):
        assert ALL, f"no standard.yaml found under {STANDARDS} — gate is vacuous"

    def test_at_least_one_standard_is_wired(self):
        """Otherwise every assertion below iterates an empty list and passes."""
        assert WITH_RULES, "no standard declares `rules:` — nothing is being checked"


class TestDeclaredRulesResolve:
    @pytest.mark.parametrize(
        ("name", "data"), WITH_RULES, ids=[n for n, _ in WITH_RULES]
    )
    def test_every_rule_names_a_check_that_exists(self, name: str, data: dict):
        broken = [
            f"{r.get('id')} -> {r.get('enforced_by')}"
            for r in data["rules"]
            if not _node_resolves(r.get("enforced_by", ""))
        ]

        assert not broken, f"{name}: rules cite checks that do not resolve: {broken}"

    @pytest.mark.parametrize(
        ("name", "data"), WITH_RULES, ids=[n for n, _ in WITH_RULES]
    )
    def test_every_rule_is_identified_and_claims_something(self, name: str, data: dict):
        thin = [
            r
            for r in data["rules"]
            if not str(r.get("id", "")).strip()
            or len(str(r.get("claim", "")).strip()) < 20
        ]

        assert not thin, f"{name}: rules without an id or a real claim: {thin}"

    @pytest.mark.parametrize(
        ("name", "data"), WITH_RULES, ids=[n for n, _ in WITH_RULES]
    )
    def test_rule_ids_are_unique_within_a_standard(self, name: str, data: dict):
        ids = [r.get("id") for r in data["rules"]]

        assert len(ids) == len(set(ids)), f"{name}: duplicate rule ids in {ids}"


class TestUnenforcedRulesCarryAReason:
    @pytest.mark.parametrize(("name", "data"), ALL, ids=[n for n, _ in ALL])
    def test_an_unenforced_rule_states_why(self, name: str, data: dict):
        blank = [
            r.get("id")
            for r in (data.get("unenforced") or [])
            if len(str(r.get("why", "")).strip()) < 20
        ]

        assert not blank, (
            f"{name}: unenforced rules with no reason: {blank}. An exemption "
            "without a stated reason pre-approves whatever lands next."
        )


class TestTheGapOnlyShrinks:
    def test_unwired_standards_never_grow(self):
        unwired = sorted(n for n, d in ALL if not d.get("rules"))

        assert len(unwired) <= UNWIRED_STANDARDS_BASELINE, (
            f"{len(unwired)} standards declare no `rules:` mapping, over a "
            f"baseline of {UNWIRED_STANDARDS_BASELINE}. Every one of them can "
            "state a rule in prose that nothing checks. Wire one — do not "
            f"raise the baseline.\n{unwired}"
        )

    def test_the_unwired_baseline_carries_no_slack(self):
        unwired = len([n for n, d in ALL if not d.get("rules")])

        assert unwired == UNWIRED_STANDARDS_BASELINE, (
            f"baseline {UNWIRED_STANDARDS_BASELINE} but {unwired} are unwired — "
            "tighten it so the next unwired standard reddens."
        )

    def test_unenforced_rules_never_grow(self):
        total = sum(len(d.get("unenforced") or []) for _n, d in ALL)

        assert total <= UNENFORCED_RULES_BASELINE, (
            f"{total} rules are declared unenforced, over a baseline of "
            f"{UNENFORCED_RULES_BASELINE}. Write the check instead."
        )

    def test_the_unenforced_baseline_carries_no_slack(self):
        total = sum(len(d.get("unenforced") or []) for _n, d in ALL)

        assert total == UNENFORCED_RULES_BASELINE, (
            f"baseline {UNENFORCED_RULES_BASELINE} but {total} are declared "
            "unenforced — tighten it."
        )
