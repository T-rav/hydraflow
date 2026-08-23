"""Label mutation surface of ``FakeGitHub``.

Extracted VERBATIM from ``src/mockworld/fakes/fake_github.py``
(god-class decomposition, Refs #11547) as a mixin. ``FakeGitHub`` inherits it,
so every method here still resolves as an attribute of ``FakeGitHub`` and every
seam that drives the fake through a Port resolves to the same object as before.

The cluster boundary mirrors the real adapter's: this module is the fake's
side of ``pr_manager_labels.PRManagerLabelsMixin``, so the fake and the thing it doubles read alike.

One concern: adding and removing labels on issues and PRs, including the
``swap_pipeline_labels`` stage transition that ADR-0002's label state machine
turns on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._common import FakeIssue, FakePR


class FakeGitHubLabelsMixin:
    """Label mutation surface of ``FakeGitHub``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``FakeGitHub.__init__`` or by
    # a sibling mixin. The method declarations are TYPE_CHECKING-only
    # on purpose: a runtime ``...`` body would win over the
    # real implementation whenever this mixin precedes the
    # implementing one in ``FakeGitHub``'s MRO.
    # ------------------------------------------------------------------
    _issues: dict[int, FakeIssue]
    _prs: dict[int, FakePR]

    if TYPE_CHECKING:

        def _maybe_rate_limit(self) -> None: ...  # provided by _seeding

    async def swap_pipeline_labels(
        self,
        issue_number: int,
        new_label: str,
        *,
        pr_number: int | None = None,
    ) -> None:
        self._maybe_rate_limit()
        _ = pr_number
        if issue_number in self._issues:
            issue = self._issues[issue_number]
            issue.labels = [
                lbl for lbl in issue.labels if not lbl.startswith("hydraflow-")
            ]
            issue.labels.append(new_label)

    async def add_labels(self, issue_number: int, labels: list[str]) -> None:
        self._maybe_rate_limit()
        if issue_number in self._issues:
            for label in labels:
                if label not in self._issues[issue_number].labels:
                    self._issues[issue_number].labels.append(label)

    async def remove_label(self, issue_number: int, label: str) -> None:
        self._maybe_rate_limit()
        if issue_number in self._issues:
            issue = self._issues[issue_number]
            issue.labels = [lbl for lbl in issue.labels if lbl != label]

    async def add_pr_labels(self, pr_number: int, labels: list[str]) -> None:
        """Mirror PRManager.add_pr_labels — append each label idempotently."""
        self._maybe_rate_limit()
        pr = self._prs.get(pr_number)
        if pr is None:
            return
        for label in labels:
            if label not in pr.labels:
                pr.labels.append(label)

    async def remove_pr_label(self, pr_number: int, label: str) -> None:
        """Mirror PRManager.remove_pr_label — drop *label* if present."""
        self._maybe_rate_limit()
        pr = self._prs.get(pr_number)
        if pr is None:
            return
        if label in pr.labels:
            pr.labels.remove(label)

    async def ensure_labels_exist(self) -> None:
        """Idempotently create HydraFlow lifecycle labels (no-op stub).

        Production PRManager pushes label definitions to GitHub via
        ``gh label create``. The seeded FakeGitHub already has whatever
        labels the seed declared, so this is a no-op. Required because
        ``HydraFlowOrchestrator.run()`` calls ``prs.ensure_labels_exist()``
        unconditionally during pipeline boot.
        """
        return None
