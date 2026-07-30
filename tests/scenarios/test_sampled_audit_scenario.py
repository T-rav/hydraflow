"""MockWorld scenario for SampledAuditLoop (#10370).

End-to-end over FakeGitHub + a real (tiny) git repo fixture on disk — the
sampler's git adapter (``merged_changes_for_range``) shells out to real git
against ``config.repo_root``, so this scenario builds an actual merged commit
rather than seeding FakeGitHub state (mirrors
``tests/scenarios/test_escape_ledger_scenario.py``). The adversarial re-audit is
an INJECTED fake so nothing shells out to a real ``claude``.

Proves the loop + FakeGitHub port integrate across the whole disposition path:
a seeded merged PR is sampled, re-audited (``disagree``), recorded to the
append-only ``audit_samples.jsonl``, and a ``hydraflow-find`` issue is filed IN
FakeGitHub; then closing that issue (upheld) reconciles on the next tick into a
``sampled-audit`` escape-ledger cross-link.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops

_DISAGREE = '{"verdict": "disagree", "findings": "unchecked index"}'


class _FakeAuditor:
    async def audit(self, *, prompt: str) -> str:
        _ = prompt
        return _DISAGREE


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "audit_repo"
    repo.mkdir()
    (repo / "src").mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@e.dev")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "-q", "-m", "init", "--allow-empty")
    return repo


def _head(repo: Path) -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _seed_merged_pr(repo: Path, pr: int = 55) -> tuple[str, str]:
    base = _head(repo)
    (repo / "src" / "mod.py").write_text("def f(i):\n    return [0][i]\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"feat: add lookup (#{pr})")
    return base, _head(repo)


def _make_state(initial_sha: str) -> Any:
    from unittest.mock import MagicMock

    state = MagicMock()
    store: dict[str, Any] = {"sha": initial_sha, "rate": 1.0, "history": []}
    state.get_sampled_audit_last_processed_sha.side_effect = lambda: store["sha"]
    state.set_sampled_audit_last_processed_sha.side_effect = lambda s: (
        store.__setitem__("sha", s)
    )
    state.get_sampled_audit_governed_rate.side_effect = lambda: store["rate"]
    state.set_sampled_audit_governed_rate.side_effect = lambda r: store.__setitem__(
        "rate", r
    )
    state.get_sampled_audit_disagreement_history.side_effect = lambda: list(
        store["history"]
    )
    state.set_sampled_audit_disagreement_history.side_effect = lambda h: (
        store.__setitem__("history", list(h))
    )
    state._store = store
    return state


def _make_dedup() -> Any:
    from unittest.mock import MagicMock

    dedup = MagicMock()
    store: set[str] = set()
    dedup.get.side_effect = lambda: set(store)
    dedup.set_all.side_effect = lambda v: (store.clear(), store.update(v))
    return dedup


def _build_loop(
    tmp_path: Path,
    repo: Path,
    github: Any,
    state: Any,
    *,
    auto_adjudicate: bool = False,
    adjudicator: Any = None,
) -> Any:
    from sampled_audit_loop import SampledAuditLoop
    from tests.helpers import make_bg_loop_deps

    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "repo_root", repo)
    object.__setattr__(bg.config, "data_root", tmp_path / "data")
    object.__setattr__(bg.config, "sampled_audit_loop_enabled", True)
    object.__setattr__(bg.config, "sampled_audit_reaudit_enabled", True)
    object.__setattr__(
        bg.config, "sampled_audit_auto_adjudicate_enabled", auto_adjudicate
    )
    return SampledAuditLoop(
        config=bg.config,
        pr_manager=github,
        state=state,
        dedup=_make_dedup(),
        deps=bg.loop_deps,
        auditor=_FakeAuditor(),
        adjudicator=adjudicator,
    )


class _FakeAdjudicator:
    def __init__(self, verdict: str) -> None:
        self._verdict = verdict

    async def adjudicate(self, *, prompt: str) -> str:
        _ = prompt
        return f'{{"verdict": "{self._verdict}", "rationale": "scenario"}}'


class TestSampledAuditScenario:
    async def test_seeded_merge_sampled_audited_and_find_filed(
        self, tmp_path: Path
    ) -> None:
        world = MockWorld(tmp_path)
        github = world.github
        repo = _init_repo(tmp_path)
        base, head = _seed_merged_pr(repo, pr=55)

        state = _make_state(base)
        loop = _build_loop(tmp_path, repo, github, state)

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["sampled"] == 1
        assert result["disagreements"] == 1
        assert result["filed"] == 1

        from audit.store import AuditSampleLedger

        samples = AuditSampleLedger(loop._samples_path).read_all()
        assert len(samples) == 1
        assert samples[0].verdict == "disagree"
        assert samples[0].pr_number == 55
        assert samples[0].no_verdict_contamination()
        assert state._store["sha"] == head

        # The find issue was filed IN FakeGitHub with the sampled-audit label.
        find_issue = samples[0].find_issue
        assert find_issue
        labels = await github.get_issue_labels(find_issue)
        assert "sampled-audit" in labels

    async def test_upheld_disagreement_crosslinks_into_escape_ledger(
        self, tmp_path: Path
    ) -> None:
        world = MockWorld(tmp_path)
        github = world.github
        repo = _init_repo(tmp_path)
        base, _head_sha = _seed_merged_pr(repo, pr=61)

        state = _make_state(base)
        loop = _build_loop(tmp_path, repo, github, state)

        # Tick 1: sample + audit + file the find issue (still open → pending).
        await loop._do_work()
        from audit.store import AuditSampleLedger
        from escape.ledger import EscapeLedger

        assert EscapeLedger(loop._escape_ledger_path).read_all() == []
        find_issue = AuditSampleLedger(loop._samples_path).read_all()[0].find_issue
        assert find_issue

        # Adjudication upholds it with the EXPLICIT audit-upheld label (a bare
        # close no longer infers upheld — that would let an incidental stale/dup
        # close fabricate an escape); tick 2 reconciles it into the escape ledger
        # as a sampled-audit detection.
        await github.add_labels(find_issue, ["audit-upheld"])
        await github.close_issue(find_issue)
        result2 = await loop._do_work()
        assert result2["status"] == "no_new_commits"

        escapes = EscapeLedger(loop._escape_ledger_path).read_all()
        assert len(escapes) == 1
        assert escapes[0].detection_source == "sampled-audit"
        assert escapes[0].originating_pr == 61


class TestSampledAuditAutoAdjudicateScenario:
    """ADR-0115: the machine adjudicator self-resolves a disagreement — no human."""

    async def test_upheld_auto_adjudication_crosslinks_without_a_human(
        self, tmp_path: Path
    ) -> None:
        # End-to-end: a sampled disagreement is filed, then the MACHINE
        # adjudicator upholds it (applies audit-upheld) and reconcile crosses it
        # into the escape ledger — no human ever touches the find issue.
        world = MockWorld(tmp_path)
        github = world.github
        repo = _init_repo(tmp_path)
        base, head = _seed_merged_pr(repo, pr=71)

        state = _make_state(base)
        loop = _build_loop(
            tmp_path,
            repo,
            github,
            state,
            auto_adjudicate=True,
            adjudicator=_FakeAdjudicator("upheld"),
        )

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["disagreements"] == 1
        assert result["filed"] == 1
        assert result["adjudicated"] == 1
        assert result["reconciled"] == 1
        assert state._store["sha"] == head

        from audit.store import AuditSampleLedger
        from escape.ledger import EscapeLedger

        sample = AuditSampleLedger(loop._samples_path).read_all()[0]
        # The machine self-applied audit-upheld — no human labelled it.
        labels = await github.get_issue_labels(sample.find_issue)
        assert "audit-upheld" in labels
        # And it crossed into the escape ledger, all in one tick.
        escapes = EscapeLedger(loop._escape_ledger_path).read_all()
        assert len(escapes) == 1
        assert escapes[0].detection_source == "sampled-audit"
        assert escapes[0].originating_pr == 71

    async def test_refuted_auto_adjudication_closes_without_a_human(
        self, tmp_path: Path
    ) -> None:
        world = MockWorld(tmp_path)
        github = world.github
        repo = _init_repo(tmp_path)
        base, _head = _seed_merged_pr(repo, pr=72)

        state = _make_state(base)
        loop = _build_loop(
            tmp_path,
            repo,
            github,
            state,
            auto_adjudicate=True,
            adjudicator=_FakeAdjudicator("refuted"),
        )

        result = await loop._do_work()

        assert result["adjudicated"] == 1

        from audit.store import AuditSampleLedger
        from escape.ledger import EscapeLedger

        sample = AuditSampleLedger(loop._samples_path).read_all()[0]
        labels = await github.get_issue_labels(sample.find_issue)
        assert "audit-refuted" in labels
        assert github._issues[sample.find_issue].state == "closed"
        # A false alarm never fabricates an escape.
        assert EscapeLedger(loop._escape_ledger_path).read_all() == []
