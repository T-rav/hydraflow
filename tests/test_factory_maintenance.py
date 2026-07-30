"""Tests for ``factory_maintenance.is_factory_self_maintenance``.

The predicate must recognise the factory's own chore/maintenance work (so the
wiki-ingest paths can skip it) while staying narrow enough that genuine
feat/fix/refactor change — and even a real ``chore(deps)`` bump — is still
treated as product change worth documenting.
"""

from __future__ import annotations

import pytest

from factory_maintenance import is_factory_self_maintenance


class TestBranchSignal:
    @pytest.mark.parametrize(
        "branch",
        [
            "hydraflow/wiki-maint-20260728",
            "arch-regen-auto",
            "ul-proposer/batch-3",
            "ul-evidence/foo",
            "ul-edges/bar",
            "ul-pruner/baz",
            "pricing-refresh-auto",
            "rc/2026-07-28-1200",
        ],
    )
    def test_factory_maintenance_branches_match(self, branch: str) -> None:
        assert is_factory_self_maintenance(branch=branch) is True

    @pytest.mark.parametrize(
        "branch",
        [
            "agent/issue-42",  # normal pipeline branch
            "fix/some-bug",
            "feat/new-thing",
            "refactor/cleanup",
            "chore/deps-bump",  # generic chore branch — real work
            "",
        ],
    )
    def test_non_maintenance_branches_do_not_match(self, branch: str) -> None:
        assert is_factory_self_maintenance(branch=branch) is False


class TestTitleSignal:
    @pytest.mark.parametrize(
        "title",
        [
            "chore(wiki): maintenance 2026-07-28",
            "chore(arch): regenerate architecture knowledge",
            "chore(rc): promotion",
            "feat(ul): term-proposer batch — 3 drafts",
            "CHORE(WIKI): maintenance",  # case-insensitive
            "  feat(ul): whitespace-tolerant",  # leading whitespace tolerated
        ],
    )
    def test_factory_scopes_match(self, title: str) -> None:
        assert is_factory_self_maintenance(title=title) is True

    @pytest.mark.parametrize(
        "title",
        [
            "feat: add the widget",
            "fix: correct the off-by-one",
            "refactor(core): extract helper",
            "chore(deps): bump pydantic to 2.9",  # real dependency work
            "chore: tidy imports",  # generic chore — not factory-internal
            "docs: update README",
            "",
        ],
    )
    def test_genuine_change_titles_do_not_match(self, title: str) -> None:
        assert is_factory_self_maintenance(title=title) is False


class TestLabelSignal:
    def test_arch_regen_label_matches(self) -> None:
        assert is_factory_self_maintenance(labels=["hydraflow-ready", "arch-regen"])

    def test_pricing_refresh_label_matches(self) -> None:
        assert is_factory_self_maintenance(labels=["pricing-refresh"])

    def test_ordinary_labels_do_not_match(self) -> None:
        assert (
            is_factory_self_maintenance(labels=["ready", "bug", "hydraflow-plan"])
            is False
        )


class TestCombinedAndEmpty:
    def test_all_empty_is_false(self) -> None:
        assert is_factory_self_maintenance() is False

    def test_feature_branch_with_maintenance_label_still_matches(self) -> None:
        # Any single signal is sufficient.
        assert is_factory_self_maintenance(
            branch="agent/issue-99", title="fix: real bug", labels=["arch-regen"]
        )

    def test_genuine_item_on_all_three_signals_is_false(self) -> None:
        assert (
            is_factory_self_maintenance(
                branch="agent/issue-99",
                title="feat: ship the thing",
                labels=["ready", "bug"],
            )
            is False
        )
