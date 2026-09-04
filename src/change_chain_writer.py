"""The ONLY write path for the per-change artifact chain (ADR-0149).

The implementer agent must never author these files. It runs inside a
worktree this module has already populated and committed, so the chain it
would have to forge is a commit behind it and digest-anchored on an
append-only stream it cannot reach. ADR-0149's Divergence section justifies
the chain by "the agent cannot rewrite the CH-1 record"; removing the write
path serves that rationale more directly than the digest does, and leaves
the digest as corroboration rather than the sole defence.

**One authoritative location.** ``docs/changes/`` is written here and
nowhere else. The planner writes ``.hydraflow/plans/`` (a cache) and appends
the CH-1 record (the anchor); neither is the committed chain. There is no
second copy to drift out of sync with this one, and no move between two
places — the bodies travel in the stream and land once, in the worktree.

Materialisation is best-effort by design. A change planned before this
feature existed has no chain record, and a factory that refused to
implement such an issue would stall on its own backlog. A missing chain is
a gate finding, not an implementation failure.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from change_chain import ChainArtifact, ChainRecord, chain_dir
from subprocess_util import run_subprocess_result

if TYPE_CHECKING:
    from config import HydraFlowConfig

logger = logging.getLogger(__name__)

COMMIT_SUBJECT_PREFIX = "chore(chain):"


@dataclass(frozen=True)
class ChainMaterialisation:
    """What :meth:`ChangeChainWriter.materialise` actually put on disk."""

    written: tuple[ChainArtifact, ...]
    committed: bool


@dataclass
class ChangeChainWriter:
    """Writes a change's chain files into its worktree and commits them."""

    config: HydraFlowConfig

    async def materialise(
        self, worktree_path: Path, issue_number: int
    ) -> ChainMaterialisation:
        """Write and commit *issue_number*'s chain inside *worktree_path*."""
        if not self.config.change_chain_enabled:
            return ChainMaterialisation(written=(), committed=False)

        record = self._latest_record(issue_number)
        if record is None:
            logger.info(
                "No chain record for issue #%d — nothing to materialise",
                issue_number,
                extra={"issue": issue_number},
            )
            return ChainMaterialisation(written=(), committed=False)

        written = self._write_files(worktree_path, record)
        committed = await self._commit(worktree_path, issue_number, written)
        return ChainMaterialisation(written=written, committed=committed)

    def _write_files(
        self, worktree_path: Path, record: ChainRecord
    ) -> tuple[ChainArtifact, ...]:
        """Write every rendered body the record carries. Returns what landed."""
        target = chain_dir(worktree_path, record.issue_number)
        target.mkdir(parents=True, exist_ok=True)
        written: list[ChainArtifact] = []
        for artifact in ChainArtifact:
            body = record.rendered.get(artifact)
            if body is None:
                continue
            (target / f"{artifact.value}.md").write_text(body)
            written.append(artifact)
        return tuple(written)

    def _latest_record(self, issue_number: int) -> ChainRecord | None:
        """Return the newest chain record for *issue_number*, or None.

        Newest wins: a re-planned issue appends a second record, and the
        worktree must carry the plan the implementer was actually given.
        """
        path = self.config.change_chain_path
        if not path.exists():
            return None
        newest: ChainRecord | None = None
        try:
            lines = path.read_text().splitlines()
        except OSError:
            logger.warning(
                "Could not read the chain stream for issue #%d",
                issue_number,
                exc_info=True,
                extra={"issue": issue_number},
            )
            return None
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if not isinstance(payload, dict):
                continue
            if payload.get("issue_number") != issue_number:
                continue
            newest = ChainRecord.from_json_dict(payload)
        return newest

    async def _commit(
        self,
        worktree_path: Path,
        issue_number: int,
        written: tuple[ChainArtifact, ...],
    ) -> bool:
        """Commit the chain files. Returns True when a commit was made."""
        if not written:
            return False
        rel = f"docs/changes/issue-{issue_number}"
        add = await run_subprocess_result("git", "add", rel, cwd=worktree_path)
        if add.returncode != 0:
            logger.warning(
                "Could not stage the chain for issue #%d: %s",
                issue_number,
                add.stderr,
                extra={"issue": issue_number},
            )
            return False
        commit = await run_subprocess_result(
            "git",
            "commit",
            "-m",
            f"{COMMIT_SUBJECT_PREFIX} artifact chain for issue #{issue_number}",
            cwd=worktree_path,
        )
        if commit.returncode != 0:
            logger.warning(
                "Could not commit the chain for issue #%d: %s",
                issue_number,
                commit.stderr,
                extra={"issue": issue_number},
            )
            return False
        return True
