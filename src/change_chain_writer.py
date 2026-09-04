"""The ONLY write path for the per-change artifact chain (ADR-0149).

The implementer agent must never author these files. It runs inside a
worktree this module has already populated and committed, so the chain it
would have to forge is a commit behind it and digest-anchored on an
append-only stream it cannot reach. ADR-0149's Divergence section justifies
the chain by "the agent cannot rewrite the CH-1 record"; removing the write
path serves that rationale more directly than the digest does, and leaves
the digest as corroboration rather than the sole defence.

**One authoritative location.** ``docs/changes/`` is written here and
nowhere else. The planner writes ``.hydraflow/plans/`` (a cache) and the
recorder writes the CH-1 anchor plus the body cache; neither is the
committed chain. There is no second copy of the committed artifact to drift.

**The body cache is not trusted.** Bodies travel through
``config.chain_bodies_dir``, which is ordinary mutable disk state. Every
body is digest-checked against its CH-1 anchor before it is written into
the worktree, so a mutated cache is caught rather than committed.

Materialisation is best-effort by design. A change planned before this
feature existed has no chain record, and a factory that refused to
implement such an issue would stall on its own backlog. A missing chain is
a gate finding, not an implementation failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from change_chain import (
    CHANGES_PREFIX,
    ChainArtifact,
    ChainRecord,
    chain_dir,
    digest,
)
from change_chain_recorder import latest_record
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
    rejected: tuple[ChainArtifact, ...] = ()


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

        record = latest_record(self.config, issue_number)
        if record is None:
            logger.info(
                "No chain record for issue #%d — nothing to materialise",
                issue_number,
                extra={"issue": issue_number},
            )
            return ChainMaterialisation(written=(), committed=False)

        written, rejected = self._write_files(worktree_path, record)
        committed = await self._commit(worktree_path, issue_number, written)
        return ChainMaterialisation(
            written=written, committed=committed, rejected=rejected
        )

    def _write_files(
        self, worktree_path: Path, record: ChainRecord
    ) -> tuple[tuple[ChainArtifact, ...], tuple[ChainArtifact, ...]]:
        """Write every anchored body whose cached bytes match its digest.

        Returns ``(written, rejected)``. A rejected artifact is one whose
        cached body does not hash to the anchored digest — the cache was
        edited after the plan phase recorded it. Refusing to commit it is
        the point: writing it anyway would put a file on the branch that the
        gate is guaranteed to flag, and would let whoever edited the cache
        choose what the agent reads.
        """
        target = chain_dir(worktree_path, record.issue_number)
        source = self.config.chain_bodies_dir / f"issue-{record.issue_number}"
        written: list[ChainArtifact] = []
        rejected: list[ChainArtifact] = []
        for artifact in ChainArtifact:
            anchored = record.digests.get(artifact)
            if anchored is None:
                continue
            body = self._cached_body(source, artifact)
            if body is None:
                rejected.append(artifact)
                logger.warning(
                    "Chain body for issue #%d %s is missing from the cache",
                    record.issue_number,
                    artifact.value,
                    extra={"issue": record.issue_number},
                )
                continue
            if digest(body) != anchored:
                rejected.append(artifact)
                logger.warning(
                    "Chain body for issue #%d %s does not match its anchored "
                    "digest — refusing to commit it",
                    record.issue_number,
                    artifact.value,
                    extra={"issue": record.issue_number},
                )
                continue
            target.mkdir(parents=True, exist_ok=True)
            (target / f"{artifact.value}.md").write_text(body, encoding="utf-8")
            written.append(artifact)
        return tuple(written), tuple(rejected)

    def _cached_body(self, source: Path, artifact: ChainArtifact) -> str | None:
        """Read one cached body as UTF-8, or None when it cannot be read."""
        try:
            return (source / f"{artifact.value}.md").read_text(encoding="utf-8")
        except OSError:
            return None

    async def _commit(
        self,
        worktree_path: Path,
        issue_number: int,
        written: tuple[ChainArtifact, ...],
    ) -> bool:
        """Commit the chain files. Returns True when a commit was made.

        The commit carries an explicit pathspec. A bare ``git commit`` would
        sweep in whatever else was already staged — and this runs on the
        resumed-worktree path too, where a prior interrupted run can have left
        work in the index. That would produce a commit labelled as the
        artifact chain carrying unrelated delivery, which the
        ``docs/changes`` exclusions would then wrongly discount.
        """
        if not written:
            return False
        rel = f"{CHANGES_PREFIX}/issue-{issue_number}"
        add = await run_subprocess_result("git", "add", "--", rel, cwd=worktree_path)
        if add.returncode != 0:
            logger.warning(
                "Could not stage the chain for issue #%d: %s",
                issue_number,
                add.stderr,
                extra={"issue": issue_number},
            )
            return False

        # Already committed is committed. `_setup_worktree_and_branch` calls
        # materialise again on the RESUMED-worktree path, where the files are
        # already tracked at HEAD with identical bytes: nothing stages, `git
        # commit` exits 1 with "nothing to commit", and reporting that as a
        # failure made the caller delete the tracked chain it had committed
        # on the first pass — the agent's `git add -A` then committed the
        # deletions as its own delivery.
        staged = await run_subprocess_result(
            "git", "diff", "--cached", "--quiet", "--", rel, cwd=worktree_path
        )
        if staged.returncode == 0:
            logger.info(
                "Chain for issue #%d is already committed — nothing to do",
                issue_number,
                extra={"issue": issue_number},
            )
            return True

        commit = await run_subprocess_result(
            "git",
            "commit",
            "--only",
            "-m",
            f"{COMMIT_SUBJECT_PREFIX} artifact chain for issue #{issue_number}",
            "--",
            rel,
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
