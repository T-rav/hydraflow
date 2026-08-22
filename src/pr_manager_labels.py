"""Label add/remove/swap surface of :class:`pr_manager.PRManager`.

Extracted VERBATIM from ``pr_manager.py`` (god-class decomposition, Refs
#11547) as a mixin, same shape as ``pr_manager_promotion.py``. ``PRManager``
inherits :class:`PRManagerLabelsMixin`, so ``PRManager().add_labels`` and
``patch("pr_manager.PRManager.swap_pipeline_labels")`` resolve unchanged.

One cohesive concern: mutating labels on issues and PRs — the write half of
the ADR-0002 label state machine, including the strict variant that refuses
to swallow a failed add and the pipeline-stage swap that notifies the
dashboard listener.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal
from urllib.parse import quote

from pr_manager_common import _is_missing_label_404

if TYPE_CHECKING:
    from pathlib import Path

    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.pr_manager")


class PRManagerLabelsMixin:
    """Label mutation mixed into :class:`pr_manager.PRManager`."""

    # ------------------------------------------------------------------
    # Collaborator seams — attributes and methods provided by PRManager or a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would take precedence over the real
    # implementation whenever the declaring mixin precedes the implementing
    # one in PRManager's MRO.
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _repo: str

    if TYPE_CHECKING:

        def _assert_repo(self) -> None: ...  # provided by PRManager

        async def _run_gh(
            self, *cmd: str, cwd: Path | None = None
        ) -> str: ...  # provided by PRManager

        def _notify_pipeline_label_listener(
            self, issue_number: int, new_label: str
        ) -> None: ...  # provided by PRManager

    async def ensure_labels_exist(self) -> None:
        """Create all HydraFlow lifecycle labels in the repo if they don't exist.

        Delegates to :func:`prep.ensure_labels` which handles creation,
        reporting, and dry-run behaviour.
        """
        self._assert_repo()
        from prep import ensure_labels  # noqa: PLC0415

        result = await ensure_labels(self._config)
        logger.info(result.summary())

    async def _add_labels(
        self, target: Literal["issue", "pr"], number: int, labels: list[str]
    ) -> None:
        """Add *labels* to a GitHub issue or PR."""
        self._assert_repo()
        if self._config.dry_run or not labels:
            return
        for label in labels:
            try:
                await self._run_gh(
                    "gh",
                    "api",
                    f"repos/{self._repo}/issues/{number}/labels",
                    "-X",
                    "POST",
                    "--raw-field",
                    f"labels[]={label}",
                )
            except RuntimeError as exc:
                logger.warning(
                    "Could not add label %r to %s #%d: %s",
                    label,
                    target,
                    number,
                    exc,
                )

    async def _add_labels_strict(
        self, target: Literal["issue", "pr"], number: int, labels: list[str]
    ) -> None:
        """Add *labels* to a GitHub issue or PR — raises on failure.

        Unlike :meth:`_add_labels` this does **not** swallow errors, so
        callers (e.g. :meth:`swap_pipeline_labels`) can abort before
        removing old labels.
        """
        self._assert_repo()
        if self._config.dry_run or not labels:
            return
        for label in labels:
            try:
                await self._run_gh(
                    "gh",
                    "api",
                    f"repos/{self._repo}/issues/{number}/labels",
                    "-X",
                    "POST",
                    "--raw-field",
                    f"labels[]={label}",
                )
            except RuntimeError:
                logger.warning(
                    "Failed to add label %r to %s #%d during swap — "
                    "aborting to prevent orphan",
                    label,
                    target,
                    number,
                )
                raise

    async def add_labels(self, issue_number: int, labels: list[str]) -> None:
        """Add *labels* to a GitHub issue."""
        await self._add_labels("issue", issue_number, labels)

    async def _remove_label(
        self, target: Literal["issue", "pr"], number: int, label: str
    ) -> None:
        """Remove *label* from a GitHub issue or PR."""
        self._assert_repo()
        if self._config.dry_run:
            return
        try:
            encoded_label = quote(label, safe="")
            await self._run_gh(
                "gh",
                "api",
                f"repos/{self._repo}/issues/{number}/labels/{encoded_label}",
                "-X",
                "DELETE",
            )
        except RuntimeError as exc:
            if _is_missing_label_404(exc):
                logger.debug(
                    "Label %r not present on %s #%d; skipping remove",
                    label,
                    target,
                    number,
                )
                return
            logger.warning(
                "Could not remove label %r from %s #%d: %s",
                label,
                target,
                number,
                exc,
            )

    async def remove_label(self, issue_number: int, label: str) -> None:
        """Remove *label* from a GitHub issue."""
        await self._remove_label("issue", issue_number, label)

    async def remove_pr_label(self, pr_number: int, label: str) -> None:
        """Remove *label* from a GitHub pull request."""
        await self._remove_label("pr", pr_number, label)

    async def add_pr_labels(self, pr_number: int, labels: list[str]) -> None:
        """Add *labels* to a GitHub pull request."""
        await self._add_labels("pr", pr_number, labels)

    async def swap_pipeline_labels(
        self,
        issue_number: int,
        new_label: str,
        *,
        pr_number: int | None = None,
    ) -> None:
        """Swap to *new_label*, removing all other pipeline labels.

        Adds the new label **first** so the issue is never left without a
        pipeline label.  If the add fails the old labels remain intact and
        the exception propagates — callers can retry or escalate.
        """
        self._assert_repo()
        # --- add new label first (raises on failure) ---
        await self._add_labels_strict("issue", issue_number, [new_label])
        if pr_number is not None:
            await self._add_labels_strict("pr", pr_number, [new_label])

        # The swap is now real on GitHub (add-first defines the new stage) —
        # push it to the in-memory pipeline BEFORE the best-effort removal
        # fan-out so the dashboard card moves in seconds (#9842).
        self._notify_pipeline_label_listener(issue_number, new_label)

        # --- then remove stale labels (best-effort) ---
        all_labels = self._config.all_pipeline_labels
        for lbl in all_labels:
            if lbl != new_label:
                await self._remove_label("issue", issue_number, lbl)
                if pr_number is not None:
                    await self._remove_label("pr", pr_number, lbl)
