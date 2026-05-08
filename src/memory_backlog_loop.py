"""MemoryBacklogLoop — promote session-memory feedback to the find queue.

ADR-0057. See `docs/superpowers/specs/2026-05-07-tier2-enforcement-batch-design.md` §6
for the design rationale, and `docs/wiki/memory-feedback/README.md` for the
mirror frontmatter schema.

Pattern reference: `src/fake_coverage_auditor_loop.py` (canonical caretaker
loop). Same shape: tick logic in `_do_work`, dedup keys via `DedupStore`
(get → mutate set → set_all), 3-strikes escalation via
`MemoryBacklogStateMixin` attempt counters, ADR-0049 in-body kill-switch
gate.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from memory_backlog_mirror import (
    dedup_key_for,
    pending_entries,
    render_issue_body,
    update_status,
)
from models import WorkCycleResult  # noqa: TCH001

if TYPE_CHECKING:
    from pathlib import Path

    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from memory_backlog_mirror import MirrorEntry
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.memory_backlog_loop")

_MAX_ATTEMPTS = 3
_MIRROR_SUBPATH = ("docs", "wiki", "memory-feedback")
_DEDUP_PREFIX = "memory_backlog:"


class MemoryBacklogLoop(BaseBackgroundLoop):
    """Files hydraflow-find issues for pending memory-feedback entries."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        dedup: DedupStore,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="memory_backlog",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup

    def _get_default_interval(self) -> int:
        return self._config.memory_backlog_interval_seconds

    def _mirror_dir(self) -> Path:
        return self._config.repo_root.joinpath(*_MIRROR_SUBPATH)

    async def _do_work(self) -> WorkCycleResult:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        await self._reconcile_closed_escalations()

        mirror = self._mirror_dir()
        if not mirror.exists():
            return {"status": "no-mirror-dir", "filed": 0, "skipped": 0}

        filed = 0
        skipped = 0
        escalated = 0
        dedup = self._dedup.get()
        for entry in pending_entries(mirror):
            key = dedup_key_for(entry.slug)
            if key in dedup:
                skipped += 1
                continue
            attempts = self._state.inc_memory_backlog_attempts(key)
            try:
                if attempts >= _MAX_ATTEMPTS:
                    await self._file_escalation(entry, attempts)
                    escalated += 1
                else:
                    issue_num = await self._file_backlog_issue(entry)
                    update_status(entry.path, status="issue-open", issue=issue_num)
                    filed += 1
            except Exception:  # noqa: BLE001
                logger.exception("filing memory-backlog issue for %s", entry.slug)
                continue
            dedup.add(key)
            self._dedup.set_all(dedup)

        return {
            "status": "ok",
            "filed": filed,
            "skipped": skipped,
            "escalated": escalated,
        }

    async def _file_backlog_issue(self, entry: MirrorEntry) -> int:
        rel = entry.path.relative_to(self._config.repo_root)
        body = render_issue_body(entry, repo_relative_path=str(rel))
        title = f"Memory backlog: {entry.name}"
        labels = list(self._config.find_label) + list(self._config.memory_backlog_label)
        return await self._pr.create_issue(title, body, labels)

    async def _file_escalation(self, entry: MirrorEntry, attempts: int) -> int:
        title = f"HITL: memory backlog {entry.slug} unresolved after {attempts}"
        body = (
            f"`memory_backlog` has re-filed the `{entry.slug}` entry "
            f"{attempts} times without closure. Human review needed.\n\n"
            f"_Closing this issue clears the dedup key + attempt counter._"
        )
        labels = ["hitl-escalation"] + list(self._config.memory_backlog_stuck_label)
        return await self._pr.create_issue(title, body, labels)

    async def _reconcile_closed_escalations(self) -> None:
        """Clear dedup keys + attempt counters for closed escalations.

        Mirrors `FakeCoverageAuditorLoop._reconcile_closed_escalations`:
        scans `gh issue list --state closed` for memory-backlog-stuck
        escalations the bot filed, then clears the matching dedup key
        and StateTracker attempt counter so the entry can re-file fresh.
        """
        stuck_label = self._config.memory_backlog_stuck_label[0]
        cmd = [
            "gh",
            "issue",
            "list",
            "--repo",
            self._config.repo,
            "--state",
            "closed",
            "--label",
            "hitl-escalation",
            "--label",
            stuck_label,
            "--author",
            "@me",
            "--limit",
            "100",
            "--json",
            "title",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return
        try:
            closed = json.loads(stdout.decode() or "[]")
        except json.JSONDecodeError:
            return
        current = self._dedup.get()
        keep = set(current)
        for issue in closed:
            title = issue.get("title", "")
            for key in list(keep):
                if not key.startswith(_DEDUP_PREFIX):
                    continue
                slug = key.split(":", 1)[1]
                if slug in title:
                    keep.discard(key)
                    self._state.clear_memory_backlog_attempts(key)
        if keep != current:
            self._dedup.set_all(keep)
