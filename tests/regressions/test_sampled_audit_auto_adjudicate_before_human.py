"""Regression: SampledAuditLoop auto-adjudicates a re-audit disagreement BEFORE
routing it to a human (ADR-0115, receipts #10750 / #10751).

The recurring gap: every disagreement filed a ``hydraflow-find`` issue and then
WAITED for a human to apply ``audit-upheld`` / ``audit-refuted``, even though the
adjudication (fetch diff + claim, decide upheld/refuted) was machine-runnable.
This pins the routing:

  - upheld       → ``audit-upheld`` self-applied → crosses into the escape ledger;
  - refuted      → ``audit-refuted`` self-applied + closed with evidence;
  - inconclusive → left unlabelled for a human (escalation preserved);
  - flag OFF     → no label applied (unchanged, human path).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from audit.models import AUDIT_INPUT_SOURCES, AuditSample
from audit.store import AuditSampleLedger
from dedup_store import DedupStore
from escape.ledger import EscapeLedger
from mockworld.fakes.fake_github import FakeGitHub
from sampled_audit_loop import SampledAuditLoop
from tests.helpers import make_bg_loop_deps


class _FakeAdjudicator:
    def __init__(self, verdict: str) -> None:
        self._verdict = verdict

    async def adjudicate(self, *, prompt: str) -> str:
        _ = prompt
        return f'{{"verdict": "{self._verdict}", "rationale": "test"}}'


def _pending_disagreement(find_issue: int, *, sample_id: str = "55:abc123") -> AuditSample:
    return AuditSample(
        id=sample_id,
        audited_at="2026-07-27T00:00:00+00:00",
        pr_number=55,
        merge_sha="abc123def456",
        blast_radius_class="structural",
        verdict="disagree",
        findings="unchecked index into a possibly-empty list",
        input_sources=AUDIT_INPUT_SOURCES,
        auditor_model="sonnet",
        sample_rate=0.1,
        disposition="pending",
        find_issue=find_issue,
    )


def _build_loop(
    tmp_path: Path,
    github: Any,
    *,
    auto_adjudicate: bool,
    adjudicator: Any = None,
) -> SampledAuditLoop:
    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "repo_root", tmp_path / "repo")
    object.__setattr__(bg.config, "data_root", tmp_path / "data")
    object.__setattr__(bg.config, "sampled_audit_loop_enabled", True)
    object.__setattr__(bg.config, "sampled_audit_reaudit_enabled", True)
    object.__setattr__(
        bg.config, "sampled_audit_auto_adjudicate_enabled", auto_adjudicate
    )
    return SampledAuditLoop(
        config=bg.config,
        pr_manager=github,
        state=MagicMock(),
        dedup=DedupStore("sampled_audit", tmp_path / "dedup.json"),
        deps=bg.loop_deps,
        adjudicator=adjudicator,
    )


class TestSampledAuditAutoAdjudicateBeforeHuman:
    async def test_upheld_self_applies_label_and_crosslinks(
        self, tmp_path: Path
    ) -> None:
        github = FakeGitHub()
        github.add_issue(901, "audit find", "body", labels=["hydraflow-find"])
        loop = _build_loop(
            tmp_path, github, auto_adjudicate=True, adjudicator=_FakeAdjudicator("upheld")
        )
        AuditSampleLedger(loop._samples_path).append(_pending_disagreement(901))

        acted = await loop._auto_adjudicate()
        assert acted == 1
        assert "audit-upheld" in await github.get_issue_labels(901)

        # The existing reconcile then crosses it into the escape ledger — no human.
        reconciled = await loop._reconcile_pending()
        assert reconciled == 1
        escapes = EscapeLedger(loop._escape_ledger_path).read_all()
        assert len(escapes) == 1
        assert escapes[0].detection_source == "sampled-audit"

    async def test_refuted_self_applies_label_and_closes(
        self, tmp_path: Path
    ) -> None:
        github = FakeGitHub()
        github.add_issue(902, "audit find", "body", labels=["hydraflow-find"])
        loop = _build_loop(
            tmp_path,
            github,
            auto_adjudicate=True,
            adjudicator=_FakeAdjudicator("refuted"),
        )
        AuditSampleLedger(loop._samples_path).append(_pending_disagreement(902))

        acted = await loop._auto_adjudicate()
        assert acted == 1
        assert "audit-refuted" in await github.get_issue_labels(902)
        assert github._issues[902].state == "closed"

        # Reconcile records it as a refuted false alarm — NOT an escape.
        await loop._reconcile_pending()
        assert EscapeLedger(loop._escape_ledger_path).read_all() == []

    async def test_inconclusive_leaves_it_for_a_human(self, tmp_path: Path) -> None:
        github = FakeGitHub()
        github.add_issue(903, "audit find", "body", labels=["hydraflow-find"])
        loop = _build_loop(
            tmp_path,
            github,
            auto_adjudicate=True,
            adjudicator=_FakeAdjudicator("inconclusive"),
        )
        AuditSampleLedger(loop._samples_path).append(_pending_disagreement(903))

        acted = await loop._auto_adjudicate()
        assert acted == 0, "inconclusive must not self-apply a disposition"
        labels = await github.get_issue_labels(903)
        assert "audit-upheld" not in labels
        assert "audit-refuted" not in labels
        assert github._issues[903].state == "open"  # still open for a human

    async def test_flag_off_applies_no_label(self, tmp_path: Path) -> None:
        github = FakeGitHub()
        github.add_issue(904, "audit find", "body", labels=["hydraflow-find"])
        loop = _build_loop(
            tmp_path,
            github,
            auto_adjudicate=False,
            adjudicator=_FakeAdjudicator("upheld"),
        )
        AuditSampleLedger(loop._samples_path).append(_pending_disagreement(904))

        acted = await loop._auto_adjudicate()
        assert acted == 0
        assert await github.get_issue_labels(904) == ["hydraflow-find"]

    async def test_adjudicated_once_not_respawned(self, tmp_path: Path) -> None:
        # An inconclusive finding must be adjudicated at most once — the dedup
        # guard stops a re-spawn every tick.
        github = FakeGitHub()
        github.add_issue(905, "audit find", "body", labels=["hydraflow-find"])
        calls = {"n": 0}

        class _Counting:
            async def adjudicate(self, *, prompt: str) -> str:
                _ = prompt
                calls["n"] += 1
                return '{"verdict": "inconclusive", "rationale": "x"}'

        loop = _build_loop(
            tmp_path, github, auto_adjudicate=True, adjudicator=_Counting()
        )
        AuditSampleLedger(loop._samples_path).append(_pending_disagreement(905))

        await loop._auto_adjudicate()
        await loop._auto_adjudicate()
        assert calls["n"] == 1
