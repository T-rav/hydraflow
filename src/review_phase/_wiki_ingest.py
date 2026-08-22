"""Repo-wiki ingest slice of ``ReviewPhase`` (ADR-0032).

Extracted VERBATIM from ``_phase.py`` (god-class decomposition, Refs #11547)
as a mixin — the same shape ``_visual_gate.py`` took in the #10840 pass.
``ReviewPhase`` inherits it, so every method here still resolves as an
attribute of ``ReviewPhase`` and instance/class-level patching in tests still
lands.

One concern: turning a finished review into repo-wiki knowledge — drafting
candidate entries from the review, running the ingest advisor over them,
pre-computing corroboration against existing entries, and committing the
compiler's output.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from repo_wiki import RepoWikiStore, WikiEntry, classify_topic, increment_corroboration
from wiki_corroboration_rank import rank_corroboration_candidates
from wiki_maint_queue import enqueue_wiki_ingest

from ._common import _detect_self_modification_context, _run_fallback_ingest_review

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Literal

    from config import HydraFlowConfig
    from review_advisor import PostVerifyResult, ReviewPlan
    from wiki_compiler import CorroborationDecision, WikiCompiler

logger = logging.getLogger("hydraflow.review_phase")


class WikiIngestMixin:
    """Repo-wiki ingest slice of ``ReviewPhase`` (ADR-0032)."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``ReviewPhase.__init__`` or by a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would win over the real
    # implementation whenever this mixin precedes the implementing one
    # in ``ReviewPhase``'s MRO.
    # ------------------------------------------------------------------
    _WIKI_INGEST_MAX_CHARS: int
    _config: HydraFlowConfig
    _wiki_compiler: WikiCompiler | None
    _wiki_store: RepoWikiStore | None

    if TYPE_CHECKING:

        async def _run_post_verify_for_surface(
            self,
            *,
            surface: str,
            diff: str,
            spec: str | None,
            executor_verdict_summary: str,
            executor_fix_diff: str | None = None,
            pre_flight_plan: ReviewPlan | None = None,
            attempt_number: int = 0,
            issue_number: int,
            log_pr_number: int | None = None,
            lens: Literal["correctness", "security", "spec"] | None = None,
            classification_paths: list[str] | None = None,
        ) -> PostVerifyResult | None: ...  # provided by _advisors

    async def _wiki_ingest_review(
        self, issue_number: int, *, transcript: str, summary: str
    ) -> None:
        """Ingest review knowledge into the per-repo wiki.

        When the LLM compiler is available, passes the full *transcript*
        for richer synthesis.  Falls back to *summary* for mechanical
        extraction.  Skips if this issue+review was already ingested.
        Never raises.

        When ``config.repo_wiki_git_backed`` is True and the issue
        worktree exists, per-entry markdown files are written under the
        worktree's ``repo_wiki/`` directory and committed so the wiki
        updates ride the issue's PR.  Dedup state still lives on the
        main host's legacy wiki path.

        T28: PostVerifyAdvisor (surface=``wiki_ingest``) is consulted
        in advisory mode (``post_verify_authority="advisory"``) before
        content is written. In advisory
        mode the advisor's VETO is downgraded to APPROVE inside
        :class:`PostVerifyAdvisor.run` — disagreements are still logged
        for telemetry/calibration but ingestion proceeds. EXCEPTION:
        T29's self-modification guard upgrades authority to ``veto``
        when the candidate content discusses changes to advisor's own
        implementation files (``src/review_advisor.py``,
        ``src/review_phase.py``); in that path a real VETO blocks
        ingestion.
        """
        if self._wiki_store is None or not self._config.repo:
            return
        repo = self._config.repo
        if self._wiki_store.is_ingested(repo, issue_number, "review"):
            return

        # T28: post-verify advisor in advisory mode. VETO is downgraded
        # to APPROVE unless self-mod guard forces veto authority — then a
        # real VETO short-circuits the ingest entirely.
        if await self._run_wiki_ingest_advisor(
            issue_number=issue_number, transcript=transcript, summary=summary
        ):
            return

        tracked_store, worktree_path = self._wiki_tracked_store(issue_number)
        try:
            # Prefer LLM synthesis from transcript when compiler is available
            if self._wiki_compiler is not None and transcript:
                entries = await self._wiki_compiler.synthesize_ingest(
                    repo,
                    issue_number,
                    "review",
                    transcript[: self._WIKI_INGEST_MAX_CHARS],
                )
                if entries:
                    if tracked_store is not None and worktree_path is not None:
                        decisions = await self._precompute_corroboration(
                            tracked_store=tracked_store,
                            repo=repo,
                            entries=entries,
                        )
                        # Offload sync file + git-subprocess work off the
                        # event loop — ADR-0001 — so other concurrent
                        # phase loops don't stall on ``git commit``.
                        await asyncio.to_thread(
                            self._wiki_commit_compiler_entries,
                            tracked_store=tracked_store,
                            worktree_path=worktree_path,
                            repo=repo,
                            issue_number=issue_number,
                            phase="review",
                            entries=entries,
                            decisions=decisions,
                        )
                    else:
                        # No issue worktree: boot store is read-only, so
                        # route entries through the maintenance queue for
                        # the worktree-isolated PR (#9836).
                        enqueue_wiki_ingest(self._config, repo, entries)
                    self._wiki_store.mark_ingested(repo, issue_number, "review")
                    return

            # Fallback: mechanical extraction from structured summary
            from repo_wiki_ingest import build_review_entries  # noqa: PLC0415

            if tracked_store is not None and worktree_path is not None:
                await asyncio.to_thread(
                    _run_fallback_ingest_review,
                    tracked_store=tracked_store,
                    worktree_path=worktree_path,
                    repo=repo,
                    issue_number=issue_number,
                    summary=summary,
                    path_prefix=self._config.repo_wiki_path,
                )
            else:
                enqueue_wiki_ingest(
                    self._config,
                    repo,
                    [e for e, _ in build_review_entries(issue_number, summary)],
                )
            self._wiki_store.mark_ingested(repo, issue_number, "review")
        except Exception:  # noqa: BLE001
            logger.warning(
                "Wiki ingest failed for review #%d", issue_number, exc_info=True
            )

    async def _run_wiki_ingest_advisor(
        self,
        *,
        issue_number: int,
        transcript: str,
        summary: str,
    ) -> bool:
        """Run :class:`PostVerifyAdvisor` for the ``wiki_ingest`` surface (T28).

        Returns ``True`` when ingestion should be blocked (only ever happens
        when T29's self-modification guard upgrades authority to ``veto`` and
        the advisor returns VETO). Returns ``False`` when ingestion may
        proceed — covering the normal advisory-mode path (VETO is downgraded
        to APPROVE inside :class:`PostVerifyAdvisor.run`), APPROVE verdicts,
        the kill-switch off path, and degraded advisor failures.

        Per spec tiering, ``wiki_ingest`` has ``post_verify_authority="advisory"``
        — so the advisor is consulted purely for
        calibration: disagreements feed
        ``review_advisor_disagreement_total`` (T16.5) and the
        ``review_advisor_disagreement_validated_total`` KPI (T22), and every
        call appends to ``advisor_session.jsonl`` (T12). The advisor's
        opinion does *not* normally block ingestion.

        ``reraise_on_credit_or_bug`` discipline is preserved per
        ``docs/wiki/dark-factory.md`` §2.2 inside
        :meth:`_run_post_verify_for_surface`.
        """
        diff_descriptor = self._build_wiki_ingest_diff_descriptor(
            issue_number=issue_number, transcript=transcript, summary=summary
        )

        pv_result = await self._run_post_verify_for_surface(
            surface="wiki_ingest",
            diff=diff_descriptor,
            spec=summary or None,
            executor_verdict_summary="wiki_ingest_candidate",
            issue_number=issue_number,
        )
        if pv_result is None:
            return False

        # Advisory mode: VETO is downgraded to APPROVE inside advisor.run.
        # A residual VETO here means the self-mod guard upgraded authority
        # to "veto" — block ingestion.
        if pv_result.verdict == "VETO":
            logger.warning(
                "wiki_ingest VETO from advisor for review #%d "
                "(self-modification guard active): %s",
                issue_number,
                pv_result.reasoning,
            )
            return True
        return False

    def _build_wiki_ingest_diff_descriptor(
        self,
        *,
        issue_number: int,
        transcript: str,
        summary: str,
    ) -> str:
        """Render a textual descriptor of the candidate wiki ingest content.

        Wiki ingest has no unified text diff — the advisor's input is a
        synthesized view of what would be written: the review summary and
        a bounded slice of the transcript. The descriptor must be
        non-empty so the advisor has *something* to evaluate, and must
        carry through any discussion of advisor implementation files so
        ``resolve_post_verify_authority``'s self-modification guard can
        detect those references and force veto authority.

        ``resolve_post_verify_authority`` matches *unified-diff header*
        substrings (``diff --git a/<path>`` etc.). Wiki ingest never
        produces those headers naturally, so when the candidate content
        mentions a self-modifying path we synthesize a pseudo-header
        block in the descriptor — that gives the existing self-mod
        detector a unified surface to match against without forking its
        path-matching logic.

        Path list source-of-truth (T30.5 I3): we import
        ``review_advisor.SELF_MODIFYING_PATHS`` to keep the recognized-path
        set aligned with the advisor module; different matchers (unified-
        diff headers vs. content context) consume the same paths.

        T37: detection is context-sensitive. A bare substring mention of an
        advisor source path (e.g., "review found a type-hint gap in
        src/review_advisor.py") no longer synthesizes the pseudo header —
        only modification context (already-formed diff headers, fenced
        diff/patch blocks, or editorial verbs like "modified <path>") does.
        See ``_detect_self_modification_context``.
        """
        from review_advisor import SELF_MODIFYING_PATHS  # noqa: PLC0415

        # Mirror the synthesize_ingest cap so the descriptor reflects
        # exactly the content that would feed the wiki compiler.
        bounded_transcript = (transcript or "")[: self._WIKI_INGEST_MAX_CHARS]
        combined = f"{summary}\n{bounded_transcript}"
        lines = [
            f"Wiki ingest candidate — issue #{issue_number}",
            f"Repo: {self._config.repo or '(unset)'}",
        ]
        # Synthesize unified-diff headers only for self-mod paths that
        # appear in a *modification context* — bare substring mentions
        # (benign prose) do NOT trigger synthesis. Intersect with
        # SELF_MODIFYING_PATHS so the regex remains the gate but the
        # canonical path list still governs which paths are eligible.
        detected = _detect_self_modification_context(combined)
        for path in detected:
            if path in SELF_MODIFYING_PATHS:
                lines.append(f"diff --git a/{path} b/{path}")
        lines.extend(
            [
                "",
                "## Summary",
                summary or "(none)",
            ]
        )
        if bounded_transcript:
            lines.extend(["", "## Transcript (bounded)", bounded_transcript])
        return "\n".join(lines)

    def _wiki_tracked_store(
        self, issue_number: int
    ) -> tuple[RepoWikiStore | None, Path | None]:
        """Build a ``RepoWikiStore`` pointed at the issue worktree's
        tracked ``repo_wiki/`` directory, or ``(None, None)`` when
        git-backed writes are disabled / the worktree is missing.
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
        """Run ``dedup_or_corroborate`` per entry against existing active
        entries in the same topic. Returns one decision per entry in the
        same order. Bounded per-entry by a candidate cap so a large
        topic doesn't fire one LLM call per existing entry — the cap picks
        the entries most similar to the one being ingested, never whichever
        entries happen to sort first by filename (#11606).
        """
        from wiki_compiler import CorroborationDecision  # noqa: PLC0415

        if self._wiki_compiler is None:
            return [CorroborationDecision() for _ in entries]
        max_candidates = 5
        decisions: list[CorroborationDecision] = []
        for entry in entries:
            topic = classify_topic(entry)
            topic_dir = tracked_store._tracked_topic_dir(repo, topic)
            existing_pairs: list[tuple[WikiEntry, Path]] = []
            if topic_dir is not None:
                existing_pairs = rank_corroboration_candidates(
                    entry,
                    tracked_store._load_tracked_topic_entries_with_paths(topic_dir),
                    limit=max_candidates,
                )
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
        """Route compiler-synthesized entries through ``write_entry`` then
        commit.  Rolls back any files written before a mid-batch failure.

        When ``decisions`` is provided (same length as ``entries``),
        entries whose decision says ``should_corroborate`` skip the
        write and instead bump the canonical's counter via
        ``increment_corroboration`` — the ingest side of the
        depth-signal system (ADR-0032).
        """
        from wiki_compiler import CorroborationDecision  # noqa: PLC0415

        written: list[Path] = []
        if decisions is None or len(decisions) != len(entries):
            decisions = [CorroborationDecision() for _ in entries]
        try:
            for entry, decision in zip(entries, decisions, strict=True):
                if decision.should_corroborate and decision.canonical_path is not None:
                    increment_corroboration(decision.canonical_path)
                    continue
                topic = classify_topic(entry)
                written.append(tracked_store.write_entry(repo, entry, topic=topic))
            tracked_store.append_log(
                repo,
                issue_number,
                {"phase": phase, "action": "ingest", "entries": len(written)},
            )
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
