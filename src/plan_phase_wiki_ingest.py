"""Plan-phase wiki ingest — per-repo wiki knowledge capture from plan output.

Extracted verbatim from ``plan_phase.py`` (god-file decomposition, #10840):
the self-contained ADR-0032 ingest cluster — LLM-compiler synthesis with
corroboration precompute, the git-backed tracked-store write + commit path,
and the mechanical fallback extraction. ``PlanPhase`` composes
:class:`PlanWikiIngestMixin`; behaviour, method names, and the
``hydraflow.plan_phase`` logger are unchanged.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from repo_wiki import (
    RepoWikiStore,
    WikiEntry,
    classify_topic,
    increment_corroboration,
)
from wiki_maint_queue import enqueue_wiki_ingest

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from wiki_compiler import CorroborationDecision, WikiCompiler  # noqa: TCH004

# Same logger as the host phase — the moved code's log records keep their
# pre-extraction ``hydraflow.plan_phase`` origin.
logger = logging.getLogger("hydraflow.plan_phase")


def _run_fallback_ingest_plan(
    *,
    tracked_store: RepoWikiStore,
    worktree_path: Path,
    repo: str,
    issue_number: int,
    plan_text: str,
    path_prefix: str,
) -> None:
    """Sync wrapper for the fallback plan-ingest path.

    Module-level so it can be dispatched via ``asyncio.to_thread`` without
    binding a bound-method reference to the loop.  See ADR-0001 — the
    sync ``git commit`` call under ``commit_pending_entries`` must not
    run on the event loop.
    """
    from repo_wiki_ingest import ingest_from_plan  # noqa: PLC0415

    count = ingest_from_plan(
        tracked_store, repo, issue_number, plan_text, git_backed=True
    )
    if count:
        tracked_store.commit_pending_entries(
            worktree_path=worktree_path,
            phase="plan",
            issue_number=issue_number,
            path_prefix=path_prefix,
        )


class PlanWikiIngestMixin:
    """Wiki-ingest methods mixed into ``PlanPhase``.

    Attribute declarations below are provided by ``PlanPhase.__init__``
    (the sole concrete host) — same protocol-by-annotation convention as
    the ``state/_*.py`` StateMixins.
    """

    _config: HydraFlowConfig
    _wiki_store: RepoWikiStore | None
    _wiki_compiler: WikiCompiler | None

    _WIKI_INGEST_MAX_CHARS = 40_000

    async def _wiki_ingest_plan(self, issue_number: int, plan_text: str) -> None:
        """Ingest plan knowledge into the per-repo wiki.

        Uses the LLM compiler for synthesis when available, falling back
        to mechanical section extraction.  Skips if already ingested.
        Never raises.

        When ``config.repo_wiki_git_backed`` is True and the issue
        worktree exists, per-entry markdown files are written under the
        worktree's ``repo_wiki/`` directory and committed by
        ``commit_pending_entries`` so the wiki updates ride the issue's
        PR.  Dedup state (``is_ingested`` / ``mark_ingested``) still
        lives on the main host's legacy wiki path regardless — the
        tracked writes are an additional artifact, not a replacement
        for dedup bookkeeping.
        """
        if self._wiki_store is None or not self._config.repo:
            return
        repo = self._config.repo
        if self._wiki_store.is_ingested(repo, issue_number, "plan"):
            return

        tracked_store, worktree_path = self._wiki_tracked_store(issue_number)
        try:
            # Prefer LLM synthesis when compiler is available
            if self._wiki_compiler is not None:
                entries = await self._wiki_compiler.synthesize_ingest(
                    repo,
                    issue_number,
                    "plan",
                    plan_text[: self._WIKI_INGEST_MAX_CHARS],
                )
                if entries:
                    if tracked_store is not None and worktree_path is not None:
                        # Precompute corroboration decisions on the event
                        # loop (async LLM calls) so the sync commit step
                        # can just read them.
                        decisions = await self._precompute_corroboration(
                            tracked_store=tracked_store,
                            repo=repo,
                            entries=entries,
                        )
                        # Offload the sync file + git-subprocess work off
                        # the event loop so the other four concurrent
                        # phase loops (ADR-0001) don't stall on git commit.
                        await asyncio.to_thread(
                            self._wiki_commit_compiler_entries,
                            tracked_store=tracked_store,
                            worktree_path=worktree_path,
                            repo=repo,
                            issue_number=issue_number,
                            phase="plan",
                            entries=entries,
                            decisions=decisions,
                        )
                    else:
                        # No issue worktree (git-backed off, or worktree
                        # gone): the boot store is read-only, so route the
                        # entries through the maintenance queue for the
                        # worktree-isolated PR instead of dirtying repo_root
                        # (#9836).
                        enqueue_wiki_ingest(self._config, repo, entries)
                    self._wiki_store.mark_ingested(repo, issue_number, "plan")
                    return

            # Fallback: mechanical section extraction
            from repo_wiki_ingest import build_plan_entries  # noqa: PLC0415

            if tracked_store is not None and worktree_path is not None:
                # Offload the sync write + commit.
                await asyncio.to_thread(
                    _run_fallback_ingest_plan,
                    tracked_store=tracked_store,
                    worktree_path=worktree_path,
                    repo=repo,
                    issue_number=issue_number,
                    plan_text=plan_text,
                    path_prefix=self._config.repo_wiki_path,
                )
            else:
                enqueue_wiki_ingest(
                    self._config,
                    repo,
                    [e for e, _ in build_plan_entries(issue_number, plan_text)],
                )
            self._wiki_store.mark_ingested(repo, issue_number, "plan")
        except Exception:  # noqa: BLE001
            logger.warning(
                "Wiki ingest failed for plan #%d", issue_number, exc_info=True
            )

    def _wiki_tracked_store(
        self, issue_number: int
    ) -> tuple[RepoWikiStore | None, Path | None]:
        """Build a RepoWikiStore pointed at the issue worktree's tracked
        ``repo_wiki/`` directory, or ``(None, None)`` when git-backed writes
        are disabled / the worktree is missing.
        """
        if not self._config.repo_wiki_git_backed:
            return None, None
        worktree_path = self._config.workspace_path_for_issue(issue_number)
        if not worktree_path.is_dir():
            logger.debug(
                "Wiki git-backed write skipped for #%d: worktree %s missing",
                issue_number,
                worktree_path,
            )
            return None, None
        tracked_root = worktree_path / self._config.repo_wiki_path
        return (
            RepoWikiStore(wiki_root=tracked_root, tracked_root=tracked_root),
            worktree_path,
        )

    async def _precompute_corroboration(
        self,
        *,
        tracked_store: RepoWikiStore,
        repo: str,
        entries: list[WikiEntry],
    ) -> list[CorroborationDecision]:
        from wiki_compiler import CorroborationDecision  # noqa: PLC0415

        """Run ``dedup_or_corroborate`` per entry against existing active
        entries in the same topic. Returns one decision per entry in the
        same order. Bounded per-entry by ``max_candidates_per_entry`` so
        a large topic doesn't fire one LLM call per existing entry.
        """
        decisions: list[CorroborationDecision] = []
        if self._wiki_compiler is None:
            return [CorroborationDecision() for _ in entries]
        max_candidates = 5
        for entry in entries:
            topic = classify_topic(entry)
            topic_dir = tracked_store._tracked_topic_dir(repo, topic)
            existing_pairs: list[tuple[WikiEntry, Path]] = []
            if topic_dir is not None:
                existing_pairs = (
                    tracked_store._load_tracked_topic_entries_with_paths(topic_dir)
                )[:max_candidates]
            try:
                decision = await self._wiki_compiler.dedup_or_corroborate(
                    repo_slug=repo,
                    entry=entry,
                    existing_entries=existing_pairs,
                    topic=topic,
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "corroboration precompute failed for %s/%s",
                    repo,
                    entry.title,
                    exc_info=True,
                )
                decision = CorroborationDecision()
            decisions.append(decision)
        return decisions

    def _wiki_commit_compiler_entries(
        self,
        *,
        tracked_store: RepoWikiStore,
        worktree_path: Path,
        repo: str,
        issue_number: int,
        phase: str,
        entries: list[WikiEntry],
        decisions: list[CorroborationDecision] | None = None,
    ) -> None:
        from wiki_compiler import CorroborationDecision  # noqa: PLC0415

        """Route compiler-synthesized entries through ``write_entry`` then
        commit. Topic classification mirrors ``RepoWikiStore.ingest``.
        Rolls back any files written before a mid-batch failure.

        When ``decisions`` is provided (same length as ``entries``), any
        entry whose decision says ``should_corroborate`` skips the write
        and instead bumps the canonical's counter via
        ``increment_corroboration``. This is the ingest-side of the
        depth-signal system (ADR-0032).
        """
        # Classification uses the module-level helper — same keyword
        # scheme the legacy layout used, so synthesized entries land in
        # the expected topic directory.
        written: list[Path] = []
        if decisions is None or len(decisions) != len(entries):
            decisions = [CorroborationDecision() for _ in entries]
        try:
            any_wrote = False
            for entry, decision in zip(entries, decisions, strict=True):
                if decision.should_corroborate and decision.canonical_path is not None:
                    increment_corroboration(decision.canonical_path)
                    continue
                topic = classify_topic(entry)
                written.append(tracked_store.write_entry(repo, entry, topic=topic))
                any_wrote = True
            tracked_store.append_log(
                repo,
                issue_number,
                {"phase": phase, "action": "ingest", "entries": len(written)},
            )
            # Always commit — a pure corroboration pass (0 writes) still
            # flipped counters, which are tracked in files that need to
            # ride along on the PR.
            _ = any_wrote
            tracked_store.commit_pending_entries(
                worktree_path=worktree_path,
                phase=phase,
                issue_number=issue_number,
                path_prefix=self._config.repo_wiki_path,
            )
        except Exception:
            for p in written:
                try:
                    p.unlink()
                except OSError:
                    logger.warning("wiki ingest rollback: failed to unlink %s", p)
            raise
