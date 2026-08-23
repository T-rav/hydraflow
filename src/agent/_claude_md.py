"""The ``CLAUDE.md`` tamper guard of ``AgentRunner``.

Extracted VERBATIM from ``src/agent.py`` (god-class decomposition,
Refs #11547) as a mixin.

One concern: an agent must not quietly rewrite the instructions it runs under —
snapshot the file before the build, compare after, and revert an unsanctioned
edit.
"""

from __future__ import annotations

import logging
from pathlib import Path

from base_runner import BaseRunner

logger = logging.getLogger("hydraflow.agent")


class AgentClaudeMdGuardMixin(BaseRunner):
    """The ``CLAUDE.md`` tamper guard of ``AgentRunner``.

    Inherits ``BaseRunner``: these slices call ``self._execute`` /
    ``self._build_command`` and one delegates to ``super()._verify_quality``,
    so the base has to sit in the MIXIN's own MRO, not only in
    ``AgentRunner``'s. It also keeps the runner-scoped gates enumerating every
    file that holds a spawn site.
    """

    @staticmethod
    def _snapshot_claude_md(worktree_path: Path) -> str | None:
        """Return the full text of CLAUDE.md before the agent runs, or None if absent."""
        claude_md = worktree_path / "CLAUDE.md"
        if claude_md.is_file():
            try:
                return claude_md.read_text()
            except OSError:
                return None
        return None

    @staticmethod
    def _guard_claude_md(
        worktree_path: Path,
        snapshot: str | None,
        issue_id: int,
    ) -> None:
        """Restore CLAUDE.md if the agent deleted it or removed content.

        Compares the current file against the pre-agent *snapshot*.
        If content was lost (file deleted, or line count shrank), the
        original is restored and a warning is logged.
        """
        if snapshot is None:
            return  # no CLAUDE.md existed before — nothing to protect

        claude_md = worktree_path / "CLAUDE.md"

        # Case 1: file was deleted entirely
        if not claude_md.is_file():
            logger.warning(
                "Issue #%d: agent deleted CLAUDE.md — restoring original",
                issue_id,
            )
            claude_md.write_text(snapshot)
            return

        # Case 2: content was shrunk (overwrite / truncation)
        try:
            current = claude_md.read_text()
        except OSError:
            claude_md.write_text(snapshot)
            return

        original_lines = snapshot.count("\n")
        current_lines = current.count("\n")
        if original_lines > 0 and current_lines < original_lines:
            logger.warning(
                "Issue #%d: agent shrank CLAUDE.md from %d to %d lines — restoring original",
                issue_id,
                original_lines,
                current_lines,
            )
            claude_md.write_text(snapshot)
