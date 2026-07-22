"""FakeGitHub mirrors for the label/dispatch reconciliation path (#10260).

Covers ``get_pr_checks`` (now serving seeded ``FakePR.checks``),
``find_open_resolving_pr``, and the ``escalated_with_resolving_pr`` kind in
the fake's ``find_label_drift`` mirror.
"""

from __future__ import annotations

import pytest

from mockworld.fakes import FakeGitHub


@pytest.mark.asyncio
async def test_get_pr_checks_defaults_to_empty() -> None:
    gh = FakeGitHub()
    gh.add_pr(number=100, issue_number=42, branch="hf/issue-42")

    checks = await gh.get_pr_checks(100)

    assert checks == []


@pytest.mark.asyncio
async def test_get_pr_checks_serves_seeded_checks() -> None:
    gh = FakeGitHub()
    gh.add_pr(number=100, issue_number=42, branch="hf/issue-42")
    gh._prs[100].checks = [("Tests", "SUCCESS"), ("Lint", "SUCCESS")]

    checks = await gh.get_pr_checks(100)

    assert checks == [
        {"name": "Tests", "state": "SUCCESS"},
        {"name": "Lint", "state": "SUCCESS"},
    ]


@pytest.mark.asyncio
async def test_get_pr_checks_unknown_pr_returns_empty() -> None:
    gh = FakeGitHub()

    checks = await gh.get_pr_checks(999)

    assert checks == []


class TestFindOpenResolvingPr:
    @pytest.mark.asyncio
    async def test_finds_open_pr_linked_to_issue(self) -> None:
        gh = FakeGitHub()
        gh.add_pr(number=100, issue_number=42, branch="hf/issue-42")

        result = await gh.find_open_resolving_pr(42)

        assert result == 100

    @pytest.mark.asyncio
    async def test_returns_none_when_no_pr_for_issue(self) -> None:
        gh = FakeGitHub()
        gh.add_pr(number=100, issue_number=7, branch="hf/issue-7")

        result = await gh.find_open_resolving_pr(42)

        assert result is None

    @pytest.mark.asyncio
    async def test_ignores_merged_pr(self) -> None:
        gh = FakeGitHub()
        gh.add_pr(number=100, issue_number=42, branch="hf/issue-42", merged=True)

        result = await gh.find_open_resolving_pr(42)

        assert result is None

    @pytest.mark.asyncio
    async def test_ignores_closed_pr(self) -> None:
        gh = FakeGitHub()
        gh.add_pr(number=100, issue_number=42, branch="hf/issue-42")
        gh._prs[100].closed = True

        result = await gh.find_open_resolving_pr(42)

        assert result is None

    @pytest.mark.asyncio
    async def test_ignores_draft_pr(self) -> None:
        """A draft PR is not a reliable "this issue is resolved" signal even
        with green CI — the author explicitly marked it not ready (#10260
        review)."""
        gh = FakeGitHub()
        gh.add_pr(number=100, issue_number=42, branch="hf/issue-42")
        gh._prs[100].draft = True

        result = await gh.find_open_resolving_pr(42)

        assert result is None


class TestFakeFindLabelDriftEscalatedWithResolvingPr:
    @pytest.mark.asyncio
    async def test_detects_escalated_issue_with_green_resolving_pr(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(
            42,
            "stuck",
            "body",
            labels=["hitl-escalation", "diagnose-failed"],
        )
        gh.add_pr(number=100, issue_number=42, branch="hf/issue-42")
        gh._prs[100].checks = [("Tests", "SUCCESS")]

        drift = await gh.find_label_drift()

        assert len(drift) == 1
        assert drift[0].kind == "escalated_with_resolving_pr"
        assert drift[0].issue == 42
        assert drift[0].pr == 100

    @pytest.mark.asyncio
    async def test_not_detected_when_ci_failing(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(42, "stuck", "body", labels=["hitl-escalation"])
        gh.add_pr(number=100, issue_number=42, branch="hf/issue-42")
        gh._prs[100].checks = [("Tests", "FAILURE")]

        drift = await gh.find_label_drift()

        assert drift == []

    @pytest.mark.asyncio
    async def test_not_detected_when_no_checks_seeded(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(42, "stuck", "body", labels=["hitl-escalation"])
        gh.add_pr(number=100, issue_number=42, branch="hf/issue-42")

        drift = await gh.find_label_drift()

        assert drift == []

    @pytest.mark.asyncio
    async def test_not_detected_when_resolving_pr_is_draft(self) -> None:
        """#10260 review: mirrors ``find_open_resolving_pr``'s draft
        exclusion — a draft PR is not a reliable resolved signal even with
        green CI, so the reconciliation loop must not clear escalation
        labels against one."""
        gh = FakeGitHub()
        gh.add_issue(
            42,
            "stuck",
            "body",
            labels=["hitl-escalation", "diagnose-failed"],
        )
        gh.add_pr(number=100, issue_number=42, branch="hf/issue-42")
        gh._prs[100].checks = [("Tests", "SUCCESS")]
        gh._prs[100].draft = True

        drift = await gh.find_label_drift()

        assert drift == []

    @pytest.mark.asyncio
    async def test_not_detected_without_escalation_labels(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(7, "aligned", "body", labels=["hydraflow-review"])
        gh.add_pr(number=70, issue_number=7, branch="hf/issue-7")
        gh.add_pr_label(70, "hydraflow-review")
        gh._prs[70].checks = [("Tests", "SUCCESS")]

        drift = await gh.find_label_drift()

        assert drift == []

    @pytest.mark.asyncio
    async def test_not_detected_for_bare_hitl_escalation_without_diagnose_failed(
        self,
    ) -> None:
        """#10260 review: other loops (corpus_learning_loop,
        trust_fleet_sanity_loop, wiki_rot_detector_loop, ...) file bare
        ``hitl-escalation`` + their own ``-stuck`` label with no pipeline
        label — clearing ``hitl-escalation`` there would orphan the issue.
        Only the diagnostic_loop pairing may be cleared this way."""
        gh = FakeGitHub()
        gh.add_issue(
            42, "stuck", "body", labels=["hitl-escalation", "corpus-learning-stuck"]
        )
        gh.add_pr(number=100, issue_number=42, branch="hf/issue-42")
        gh._prs[100].checks = [("Tests", "SUCCESS")]

        drift = await gh.find_label_drift()

        assert drift == []
