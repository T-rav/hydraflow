"""UL bot-PR single-flight guard (#9893/#9890).

The four UL generator loops (term_proposer / edge_proposer / entry_evidence /
term_pruner) all edit docs/wiki/terms, so two open UL PRs conflict with each
other — the 2026-07-18 pile was seven duplicate edge-proposer PRs going DIRTY
while the loop kept regenerating. The guard: before opening, each loop asks
its BotPRPort for ANY open PR carrying a UL family label and skips the tick
(``status == "skipped_open_pr"``) when one exists — at most one UL-graph PR
in flight across the whole family.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from edge_proposer_loop import EDGE_PROPOSER_PR_LABEL, EdgeProposerLoop
from entry_evidence_loop import ENTRY_EVIDENCE_PR_LABEL
from mockworld.fakes.fake_bot_pr import FakeBotPR
from term_proposer_loop import TERM_PROPOSER_PR_LABEL, UL_BOT_PR_LABELS
from term_pruner_loop import TERM_PRUNER_PR_LABEL, TermPrunerLoop
from ubiquitous_language import BoundedContext, Term, TermKind, TermStore


def test_family_constant_matches_every_loop_label() -> None:
    assert set(UL_BOT_PR_LABELS) == {
        TERM_PROPOSER_PR_LABEL,
        EDGE_PROPOSER_PR_LABEL,
        ENTRY_EVIDENCE_PR_LABEL,
        TERM_PRUNER_PR_LABEL,
    }


class TestFakeBotPRSingleFlight:
    @pytest.mark.asyncio
    async def test_open_pr_is_findable_by_any_family_label(self) -> None:
        fake = FakeBotPR()
        n = await fake.open_bot_pr(
            branch="ul-edges/abc",
            title="t",
            body="b",
            labels=[EDGE_PROPOSER_PR_LABEL],
            files={},
        )
        assert await fake.find_open_bot_pr(labels=list(UL_BOT_PR_LABELS)) == n
        assert await fake.find_open_bot_pr(labels=["unrelated-label"]) is None

    @pytest.mark.asyncio
    async def test_closed_pr_is_no_longer_found(self) -> None:
        fake = FakeBotPR()
        n = await fake.open_bot_pr(
            branch="ul-pruner/abc",
            title="t",
            body="b",
            labels=[TERM_PRUNER_PR_LABEL],
            files={},
        )
        fake.close_pr(n)
        assert await fake.find_open_bot_pr(labels=list(UL_BOT_PR_LABELS)) is None


def _seed_terms(repo: Path, *terms: Term) -> None:
    terms_dir = repo / "docs" / "wiki" / "terms"
    terms_dir.mkdir(parents=True, exist_ok=True)
    store = TermStore(terms_dir)
    for t in terms:
        store.write(t)


def _edge_fixture(repo: Path) -> tuple[EdgeProposerLoop, FakeBotPR]:
    src = repo / "src"
    src.mkdir(exist_ok=True)
    (src / "alpha.py").write_text("from bravo import Bravo\n\nclass Alpha:\n    pass\n")
    (src / "bravo.py").write_text("class Bravo:\n    pass\n")
    _seed_terms(
        repo,
        Term(
            id="01H_ALPHA",
            name="Alpha",
            kind=TermKind.SERVICE,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition="Alpha service that depends on Bravo.",
            code_anchor="src/alpha.py:Alpha",
            confidence="accepted",
        ),
        Term(
            id="01H_BRAVO",
            name="Bravo",
            kind=TermKind.SERVICE,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition="Bravo service used by Alpha.",
            code_anchor="src/bravo.py:Bravo",
            confidence="accepted",
        ),
    )
    port = FakeBotPR()
    config = MagicMock()
    config.edge_proposer_enabled = True
    config.edge_proposer_interval = 86400
    loop = EdgeProposerLoop(
        config=config, deps=MagicMock(), pr_port=port, repo_root=repo
    )
    return loop, port


class TestEdgeProposerSingleFlight:
    @pytest.mark.asyncio
    async def test_skips_when_sibling_family_pr_open(self, tmp_path: Path) -> None:
        loop, port = _edge_fixture(tmp_path)
        blocker = await port.open_bot_pr(
            branch="ul-evidence/zzz",
            title="sibling",
            body="",
            labels=[ENTRY_EVIDENCE_PR_LABEL],  # cross-loop: evidence blocks edges
            files={},
        )
        port.calls.clear()

        result = await loop._do_work()

        assert result["status"] == "skipped_open_pr"
        assert result["open_pr"] == blocker
        assert result["opened_pr"] is False
        assert port.calls == []

    @pytest.mark.asyncio
    async def test_opens_once_family_pr_closes(self, tmp_path: Path) -> None:
        loop, port = _edge_fixture(tmp_path)
        blocker = await port.open_bot_pr(
            branch="ul-edges/old",
            title="old",
            body="",
            labels=[EDGE_PROPOSER_PR_LABEL],
            files={},
        )
        port.calls.clear()
        assert (await loop._do_work())["status"] == "skipped_open_pr"
        port.close_pr(blocker)

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["opened_pr"] is True
        assert len(port.calls) == 1

    @pytest.mark.asyncio
    async def test_no_proposals_never_queries_the_port(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        port = FakeBotPR()
        config = MagicMock()
        config.edge_proposer_enabled = True
        config.edge_proposer_interval = 86400
        loop = EdgeProposerLoop(
            config=config, deps=MagicMock(), pr_port=port, repo_root=tmp_path
        )
        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["opened_pr"] is False
        assert port.find_queries == 0


class TestTermPrunerSingleFlight:
    @pytest.mark.asyncio
    async def test_skips_when_family_pr_open(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        _seed_terms(
            tmp_path,
            Term(
                id="01H_GONE",
                name="Gone",
                kind=TermKind.SERVICE,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="Anchor no longer resolves.",
                code_anchor="src/gone.py:Gone",
                confidence="accepted",
            ),
        )
        port = FakeBotPR()
        blocker = await port.open_bot_pr(
            branch="ul-proposed/zzz",
            title="sibling",
            body="",
            labels=[TERM_PROPOSER_PR_LABEL],
            files={},
        )
        port.calls.clear()
        config = MagicMock()
        config.term_pruner_enabled = True
        config.term_pruner_interval = 86400
        loop = TermPrunerLoop(
            config=config, deps=MagicMock(), pr_port=port, repo_root=tmp_path
        )

        result = await loop._do_work()

        assert result["status"] == "skipped_open_pr"
        assert result["open_pr"] == blocker
        assert port.calls == []
