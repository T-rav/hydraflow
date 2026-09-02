"""`purpose` — goal referential integrity through the seam (#11856).

The operator ruled on 2026-08-31 (ADR-0143 Amendment 2026-09-01): a declared
goal must be cited by some Article, so it cannot be pure decoration. Presence
and shape land in charter drift; this half is a `(standard, subject)` judgement
over facts gathered from several surfaces, which is what the seam is for.

Semantic conformance stays refused. Nothing here asks whether the work SERVES a
goal — only whether something claims to.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from charter import Articles, Charter, LocalArticle, Purpose, load_charter
from policy.facts import STANDARD_PURPOSE, collect_purpose_facts
from policy.models import DecisionStatus
from policy.python_engine import MissingFactError, PythonDecisionEngine

_NOW = datetime.now(UTC)


def _charter(*goals: str, local: tuple[LocalArticle, ...] = ()) -> Charter:
    return Charter(
        purpose=Purpose(product="a factory", goals=goals),
        articles=Articles(standards=(), assurance="internal", local=local),
    )


def _repo(tmp_path: Path, *, standards: str = "", adr: str = "") -> Path:
    (tmp_path / "docs" / "standards" / "s").mkdir(parents=True)
    (tmp_path / "docs" / "standards" / "s" / "README.md").write_text(
        standards, encoding="utf-8"
    )
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "docs" / "adr" / "0001-x.md").write_text(adr, encoding="utf-8")
    return tmp_path


def _decide(charter: Charter, repo_root: Path):
    facts = collect_purpose_facts(charter, repo_root=repo_root, observed_at=_NOW)
    return PythonDecisionEngine().decide(facts, charter=None)


class TestTheCollectorObservesWithoutJudging:
    def test_one_subject_per_goal(self, tmp_path: Path) -> None:
        facts = collect_purpose_facts(
            _charter("a_goal", "b_goal"), repo_root=_repo(tmp_path), observed_at=_NOW
        )

        assert {f.subject for f in facts} == {"a_goal", "b_goal"}

    def test_each_surface_is_its_own_fact(self, tmp_path: Path) -> None:
        # Never a single `anchored` boolean: the engine must re-derive the
        # disjunction, or a parity test against another engine reads the same
        # helper on both sides instead of reaching the same conclusion twice.
        facts = collect_purpose_facts(
            _charter("a_goal"), repo_root=_repo(tmp_path), observed_at=_NOW
        )

        assert {f.key for f in facts} == {
            "cited_in_standards",
            "cited_in_adrs",
            "cited_in_local_articles",
        }

    def test_no_fact_carries_a_verdict(self, tmp_path: Path) -> None:
        facts = collect_purpose_facts(
            _charter("a_goal"), repo_root=_repo(tmp_path), observed_at=_NOW
        )

        assert all(isinstance(f.value, bool) for f in facts)
        assert not any("anchor" in f.key or "compliant" in f.key for f in facts)


class TestWhereACitationCounts:
    @pytest.mark.parametrize(
        ("standards", "adr", "local", "surface"),
        [
            pytest.param(
                "serves a_goal here", "", (), "cited_in_standards", id="standard"
            ),
            pytest.param("", "ADR text naming a_goal", (), "cited_in_adrs", id="adr"),
            pytest.param(
                "",
                "",
                (LocalArticle(article_id="x", statement="we pursue a_goal"),),
                "cited_in_local_articles",
                id="local-article",
            ),
        ],
    )
    def test_a_citation_on_any_surface_anchors_the_goal(
        self,
        tmp_path: Path,
        standards: str,
        adr: str,
        local: tuple[LocalArticle, ...],
        surface: str,
    ) -> None:
        charter = _charter("a_goal", local=local)
        repo = _repo(tmp_path, standards=standards, adr=adr)

        (decision,) = _decide(charter, repo)

        assert decision.status is DecisionStatus.COMPLIANT
        assert surface in decision.reason

    def test_an_uncited_goal_is_decoration(self, tmp_path: Path) -> None:
        (decision,) = _decide(_charter("a_goal"), _repo(tmp_path))

        assert decision.status is DecisionStatus.VIOLATED
        assert "a_goal" in decision.reason


class TestTheDecoys:
    def test_the_charter_declaring_the_goal_does_not_anchor_it(
        self, tmp_path: Path
    ) -> None:
        """The declaration is what CREATES the obligation.

        Letting `charter.yaml` satisfy it would anchor every goal by
        construction and make the check vacuous — `uncheckable-charter` wearing
        a different hat. The charter is not among the citation surfaces, and
        this is the test that says so.
        """
        (decision,) = _decide(_charter("a_goal"), _repo(tmp_path))

        assert decision.status is DecisionStatus.VIOLATED

    def test_a_longer_sibling_does_not_anchor_a_shorter_goal(
        self, tmp_path: Path
    ) -> None:
        # Substring matching would let `lights_off` ride on
        # `lights_off_operation`, so every goal would be anchored by any
        # goal that happens to contain it.
        repo = _repo(tmp_path, standards="we serve a_goal_v2 only")

        (decision,) = _decide(_charter("a_goal"), repo)

        assert decision.status is DecisionStatus.VIOLATED

    def test_a_hyphenated_neighbour_is_not_a_citation(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, standards="see also pre-a_goal-suffix")

        (decision,) = _decide(_charter("a_goal"), repo)

        assert decision.status is DecisionStatus.VIOLATED


class TestTheMandateIsTheOperatorsAct:
    def test_a_charter_not_declaring_purpose_produces_no_decision(
        self, tmp_path: Path
    ) -> None:
        """`governs()` filters this standard like any other.

        ADR-0143's ENACT discipline: the mandate change is the operator's act,
        recorded, not implied by code. A repo becomes subject to `purpose` by
        declaring it, not by this module existing.
        """
        governed_elsewhere = Charter(
            purpose=Purpose(product="a factory", goals=("a_goal",)),
            articles=Articles(standards=("adr_enforcement",), assurance="internal"),
        )
        facts = collect_purpose_facts(
            governed_elsewhere, repo_root=_repo(tmp_path), observed_at=_NOW
        )

        assert PythonDecisionEngine().decide(facts, charter=governed_elsewhere) == []

    def test_a_charter_declaring_purpose_is_judged(self, tmp_path: Path) -> None:
        governed = Charter(
            purpose=Purpose(product="a factory", goals=("a_goal",)),
            articles=Articles(standards=(STANDARD_PURPOSE,), assurance="internal"),
        )
        facts = collect_purpose_facts(
            governed, repo_root=_repo(tmp_path), observed_at=_NOW
        )

        assert len(PythonDecisionEngine().decide(facts, charter=governed)) == 1


class TestThinEvidenceFailsClosed:
    def test_a_missing_citation_fact_raises_rather_than_defaulting(self) -> None:
        """A subject missing a fact its standard needs must not default.

        Defaulting the absent surface to False would report a goal as
        decoration on the strength of evidence nobody gathered.
        """
        facts = collect_purpose_facts(
            _charter("a_goal"), repo_root=Path("/nonexistent"), observed_at=_NOW
        )
        partial = [f for f in facts if f.key != "cited_in_adrs"]

        with pytest.raises(MissingFactError):
            PythonDecisionEngine().decide(partial, charter=None)


class TestThisRepoObeysItsOwnRule:
    def test_every_declared_goal_is_anchored(self) -> None:
        """The check would be theatre if the repo declaring it failed it.

        All three were unanchored when this landed — zero citations outside
        `charter.yaml` — which is the check doing its job, not a bug. They are
        cited now, from each standard's own opening claim.
        """
        repo_root = Path(__file__).resolve().parents[1]
        charter = load_charter(repo_root)
        assert charter is not None

        facts = collect_purpose_facts(charter, repo_root=repo_root, observed_at=_NOW)
        unanchored = [
            d.subject
            for d in PythonDecisionEngine().decide(facts, charter=None)
            if d.status is not DecisionStatus.COMPLIANT
        ]

        assert not unanchored, f"goals cited nowhere: {unanchored}"

    def test_the_repo_declares_goals_to_check(self) -> None:
        """Anti-vacuity: the test above is silent on a charter with no goals."""
        charter = load_charter(Path(__file__).resolve().parents[1])
        assert charter is not None

        assert len(charter.purpose.goals) >= 3


def test_an_unanchored_goal_never_blocks_a_merge() -> None:
    """Governance hygiene for a human, not a gate on the PR author.

    Blocking would make every PR answerable for the charter's editorial state,
    which is neither the author's business nor decidable at merge time.
    """
    facts = collect_purpose_facts(
        _charter("a_goal"), repo_root=Path("/nonexistent"), observed_at=_NOW
    )

    (decision,) = PythonDecisionEngine().decide(facts, charter=None)

    assert decision.status is DecisionStatus.VIOLATED
    assert decision.blocking is False
