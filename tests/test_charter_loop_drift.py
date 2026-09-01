"""The observation layer for charter v2 loops (#11865, ADR-0145).

#11860 shipped the parse layer. This is what the caretaker DOES with a v2
charter: two drift classes, deliberately asymmetric in severity, and an
absent-vs-empty rule that decides whether the check runs at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from charter import ObservedRepo, compute_charter_drift
from charter_model import (
    FINDING_ACTOR_WITHOUT_LOOP,
    FINDING_LOOP_WITHOUT_ACTOR,
    NON_FATAL_FINDING_CLASSES,
    Charter,
)

_KNOWN = frozenset({"testing"})


def _drift(charter_data: dict, actor_files: tuple[str, ...] | None):
    charter = Charter.from_dict(charter_data)
    observed = ObservedRepo(known_standards=_KNOWN, actor_files=actor_files)
    report = compute_charter_drift(charter, observed, repo="owner/repo")
    return [f for f in report.findings if "loop" in f.finding_class]


class TestTheTwoSidesAreAsymmetric:
    """One-way binding is how `standard.yaml` and its README drifted (#11751).
    Making BOTH sides fatal would make migration impossible, which is how a
    guard gets deleted rather than met."""

    def test_a_loop_naming_a_missing_actor_is_fatal(self) -> None:
        findings = _drift({"loops": {"ghost": {"actor": "nobody"}}}, ("finance.md",))
        classes = {f.finding_class for f in findings}

        assert FINDING_LOOP_WITHOUT_ACTOR in classes
        assert FINDING_LOOP_WITHOUT_ACTOR not in NON_FATAL_FINDING_CLASSES, (
            "a loop that cannot run must be fatal — a kernel worker handed an "
            "unreadable actor refuses the run rather than falling back to a "
            "default prompt (ADR-0145 Ruling 2)"
        )

    def test_an_actor_no_loop_names_is_non_fatal(self) -> None:
        findings = _drift(
            {"loops": {"finance-close": {"actor": "finance"}}},
            ("finance.md", "records.md"),
        )
        actor_findings = [
            f for f in findings if f.finding_class == FINDING_ACTOR_WITHOUT_LOOP
        ]

        assert [f.check_id for f in actor_findings] == [
            f"{FINDING_ACTOR_WITHOUT_LOOP}:records"
        ]
        assert FINDING_ACTOR_WITHOUT_LOOP in NON_FATAL_FINDING_CLASSES, (
            "a repo mid-migration looks exactly like this; enlarging the "
            "mandate is a human's ENACT, not a caretaker's"
        )

    def test_a_fully_bound_charter_is_clean(self) -> None:
        """Anti-vacuity: the checks must be satisfiable, not merely present."""
        assert (
            _drift({"loops": {"finance": {"actor": "finance"}}}, ("finance.md",)) == []
        )


class TestAbsentVersusEmpty:
    """Guard 3 decides whether the binding check runs AT ALL."""

    def test_an_unmigrated_repo_is_not_checked(self) -> None:
        """Filing "no loop names this actor" against every actor in a v1 repo
        would bury the finding under noise on day one."""
        assert _drift({"schema_version": 1}, ("finance.md", "records.md")) == []

    def test_an_empty_block_IS_checked(self) -> None:
        """`loops: {}` is a CLAIM — that nothing runs — and a claim is worth
        testing against the actors that exist."""
        findings = _drift({"loops": {}}, ("finance.md",))
        assert [f.finding_class for f in findings] == [FINDING_ACTOR_WITHOUT_LOOP]


class TestAnUnreadableActorsDirectoryFilesNothing:
    """`None` is a fault, not an empty set."""

    def test_a_missing_listing_suppresses_both_sides(self) -> None:
        """With an empty listing every loop would look like it names a missing
        actor, and the check would file drift on a measurement nobody took —
        the same fail-loud reasoning `known_standards` already carries."""
        assert _drift({"loops": {"finance": {"actor": "finance"}}}, None) == []

    def test_an_empty_listing_is_not_the_same_as_a_missing_one(self) -> None:
        """An actors directory that exists and is empty is a real observation:
        a loop naming an actor there genuinely has no contract."""
        findings = _drift({"loops": {"finance": {"actor": "finance"}}}, ())
        assert [f.finding_class for f in findings] == [FINDING_LOOP_WITHOUT_ACTOR]


class TestAmbiguousActorsAreFatal:
    def test_both_layouts_for_one_actor_is_reported(self) -> None:
        """Two files for one key is the two-tables defect at file granularity."""
        findings = _drift({"loops": {"x": {"actor": "x"}}}, ("x.md", "x/README.md"))
        assert any("ambiguous" in f.check_id for f in findings)


class TestHydraflowsOwnCharter:
    """The repo dogfoods its own contract."""

    def test_it_is_v2_and_drift_clean(self) -> None:
        """A charter that files drift on its own repo the day it lands teaches
        everyone to ignore the caretaker."""
        from charter import load_charter
        from charter_drift_caretaker_loop import observe_repo

        root = Path(__file__).resolve().parents[1]
        charter = load_charter(root)

        assert charter is not None
        assert charter.schema_version == 2
        assert charter.loops.present is True

        report = compute_charter_drift(
            charter, observe_repo(root, charter), repo="T-rav/hydraflow"
        )
        assert report.findings == (), (
            f"HydraFlow's own charter is not drift-clean: "
            f"{[f.check_id for f in report.findings]}"
        )

    def test_every_declared_loop_is_dormant(self) -> None:
        """Enabling is an ENACT (ADR-0143 Ruling 6 guard 4). If a loop here
        ever ships enabled, it must be a human's commit — this catches the
        accident, not the decision."""
        from charter import load_charter

        charter = load_charter(Path(__file__).resolve().parents[1])
        assert charter is not None
        enabled = [loop.name for loop in charter.loops.loops if loop.enabled]
        assert enabled == [], f"loops enabled without an operator ENACT: {enabled}"


class TestTheScaffold:
    """`charter_init.py` writes silence rather than omitting it."""

    def test_it_scaffolds_one_dormant_loop_per_actor(self, tmp_path: Path) -> None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from charter_init import build_charter

        agents = tmp_path / "agents"
        agents.mkdir()
        (agents / "finance.md").write_text("contract")
        (agents / "records").mkdir()
        (agents / "records" / "README.md").write_text("contract")
        (agents / "README.md").write_text("not an actor")

        charter = build_charter(tmp_path)

        assert charter.schema_version == 2
        assert [loop.name for loop in charter.loops.loops] == ["finance", "records"]
        assert all(not loop.enabled for loop in charter.loops.loops), (
            "a scaffold that enabled loops would take the operator's ENACT by default"
        )

    def test_a_repo_with_no_actors_still_declares_the_block(
        self, tmp_path: Path
    ) -> None:
        """Present-and-empty, not absent: the scaffold has DECIDED, and the
        caretaker should check that decision rather than skip the repo."""
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from charter_init import build_charter

        (tmp_path / "agents").mkdir()
        charter = build_charter(tmp_path)

        assert charter.loops.present is True
        assert charter.loops.loops == ()


@pytest.mark.parametrize(
    ("cls", "fatal"),
    [(FINDING_LOOP_WITHOUT_ACTOR, True), (FINDING_ACTOR_WITHOUT_LOOP, False)],
    ids=["loop-without-actor", "actor-without-loop"],
)
def test_the_severity_split_is_declared_not_incidental(cls: str, fatal: bool) -> None:
    """Parametrised over both so neither can be reclassified alone.

    The asymmetry is the design decision in this change; a test naming one
    side would let the other drift into matching it.
    """
    assert (cls not in NON_FATAL_FINDING_CLASSES) is fatal
