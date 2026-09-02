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
UNENFORCED_RULES_BASELINE = 0


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


#: The "Properties:" line every standard.yaml carries names the registry that
#: validates the standards themselves. It is a property of the format, not an
#: enforcer of any one standard's rules.
_FORMAT_BOILERPLATE = frozenset({"tests/architecture/test_standards_registry.py"})

#: README-named test files not cited by any rule. SHRINK-ONLY.
UNCITED_README_ENFORCERS_BASELINE = 0


def _readme_named_tests(name: str) -> set[str]:
    """Test files a standard's README names, keeping only files that hold tests."""
    import re

    readme = STANDARDS / name / "README.md"
    if not readme.exists():
        return set()
    found: set[str] = set()
    for ref in set(re.findall(r"tests/[\w/]+\.py", readme.read_text(encoding="utf-8"))):
        path = REPO_ROOT / ref
        if not path.exists():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        if any(
            isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
            and n.name.startswith("test_")
            for n in ast.walk(tree)
        ):
            found.add(ref)
    return found


def _cited_files(data: dict[str, Any]) -> set[str]:
    cited = {
        str(r.get("enforced_by", "")).partition("::")[0]
        for r in (data.get("rules") or [])
    }
    enf = data.get("enforced_by") or []
    cited |= {
        str(e).partition("::")[0] for e in (enf if isinstance(enf, list) else [enf])
    }
    return cited


class TestReadmeCrossReferencesAreHonoured:
    """A README that names its own enforcer is ground truth for the citation.

    This is the check that would have caught the real mistake: a rule about
    FakeGitHub side effects in scenarios cited a Port-argument ratchet, while
    the README sentence stating that rule ended "…test_mockworld_scenario_fake
    _boundaries.py enforces this."

    A resolving-but-wrong citation is invisible to every other assertion here.
    Vocabulary overlap does not separate them — measured, the wrong citation
    scored 0.88 against the right one's 0.89 — but the document's own
    cross-reference does.
    """

    @pytest.mark.parametrize(("name", "data"), ALL, ids=[n for n, _ in ALL])
    def test_every_readme_named_enforcer_is_cited_or_excused(
        self, name: str, data: dict
    ):
        excused = {
            str(e.get("path"))
            for e in (data.get("readme_mentions_not_enforcers") or [])
        }
        uncited = (
            _readme_named_tests(name)
            - _cited_files(data)
            - excused
            - _FORMAT_BOILERPLATE
        )

        assert not uncited, (
            f"{name}: the README names {sorted(uncited)} but no rule cites them. "
            "Either they enforce a rule (cite them) or they are examples "
            "(list them under readme_mentions_not_enforcers with a reason)."
        )

    @pytest.mark.parametrize(("name", "data"), ALL, ids=[n for n, _ in ALL])
    def test_every_non_enforcer_states_why(self, name: str, data: dict):
        blank = [
            e.get("path")
            for e in (data.get("readme_mentions_not_enforcers") or [])
            if len(str(e.get("why", "")).strip()) < 20
        ]

        assert not blank, f"{name}: non-enforcers with no reason: {blank}"

    def test_the_scan_finds_readme_references_at_all(self):
        """Guard the guard: a regex that matches nothing passes vacuously."""
        total = sum(len(_readme_named_tests(n)) for n, _ in ALL)

        assert total >= 10, f"only {total} README-named test files found — scan broken"
